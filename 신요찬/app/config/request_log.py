"""요청 단위 구조화 로그 (명세 3.1 "구조화 앱 로그", 앱계약.md 7장, D5).

요청 하나당 JSON 한 줄을 로거 `haven.request`로 남긴다(서버에서는 표준 출력 → journald).
권혁민 요청 재현 CLI(`request_verify.py correlate`)가 이 로그를 WAF 로그·실행 결과와 대조한다.

필드
  ts                UTC ISO 시각(밀리초)
  request_id        서버가 만든 UUID. 응답 헤더 X-Request-ID로도 돌려준다
  trace_id          X-Amzn-Trace-Id의 Root(`1-<8 hex>-<24 hex>`). CLI가 보내고 AWS에서는 ALB가 붙인다
  client_request_id X-Haven-Request-ID (CLI 요청 ID, 예전 방식 대조용)
  run_id            X-Haven-Run-ID (CLI 실행 ID)
  method, path      요청 메서드, 경로(쿼리 문자열 제외, 200자까지)
  view              URL 이름(예: posts:edit). 없는 주소는 null
  action            login_success / login_failure / logout / csrf_failure / body_too_large / 그 외 view 이름
  actor_id          로그인 사용자 id, 비로그인은 null
  resource_id       대상 식별자(예: post:1, post:1/attachment:3, user:5). 경로 변수에서만 만든다
  status            응답 코드
  result            ok(2xx·3xx) / invalid(400) / denied(401·403·404·405·413) / error(5xx)
  elapsed_ms        처리 시간

남기지 않는 것: 비밀번호, 세션·CSRF 토큰, 쿠키, 쿼리 문자열, 글 본문, 파일 이름·내용, 입력한 아이디.
요청 헤더 값은 정해진 형식에 맞을 때만 남기고, 아니면 null로 둔다(로그 위조·주입 방지).
"""
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from django.urls import Resolver404, resolve

logger = logging.getLogger("haven.request")

TRACE_ROOT_RE = re.compile(r"1-[0-9a-f]{8}-[0-9a-f]{24}")
CLIENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
SKIP_PATHS = frozenset({"/healthz"})  # ALB 상태 검사는 몇 초마다 와서 남기지 않는다
RESOURCE_KEYS = (("pk", None), ("attachment_id", "attachment"), ("share_id", "share"))
REASON_ATTR = "haven_log_action"  # 다른 미들웨어·view가 거부 이유를 표시할 때 쓰는 request 속성


def mark(request, action):
    """거부 이유 등 action을 표시한다(예: body_too_large, csrf_failure)."""
    setattr(request, REASON_ATTR, action)


def trace_root(header_value):
    """X-Amzn-Trace-Id에서 Root만 꺼낸다. 형식이 다르거나 Root가 둘 이상이면 None."""
    if not header_value or len(header_value) > 256:
        return None
    roots = []
    for part in header_value.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name.strip().lower() == "root":
            value = value.strip().lower()
            if not TRACE_ROOT_RE.fullmatch(value):
                return None
            roots.append(value)
    return roots[0] if len(roots) == 1 else None


def client_id(header_value):
    if header_value and CLIENT_ID_RE.fullmatch(header_value):
        return header_value
    return None


def result_of(status):
    if status >= 500:
        return "error"
    if status == 400:
        return "invalid"
    if status >= 400:
        return "denied"
    return "ok"


class RequestLogMiddleware:
    """가장 바깥에 두어 413·CSRF 403·500을 포함한 최종 응답을 기록한다."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info in SKIP_PATHS:
            return self.get_response(request)
        started = time.monotonic()
        request.haven_request_id = uuid.uuid4().hex
        response = self.get_response(request)
        try:
            response["X-Request-ID"] = request.haven_request_id
            logger.info(json.dumps(self._event(request, response, started), ensure_ascii=False, separators=(",", ":")))
        except Exception:  # 로그 실패가 응답을 망가뜨리지 않게 한다
            logging.getLogger("haven.request.errors").exception("request log failed")
        return response

    def _event(self, request, response, started):
        match = self._match(request)
        view = match.view_name if match else None
        user = getattr(request, "user", None)
        actor_id = user.pk if user is not None and user.is_authenticated else None
        status = response.status_code
        meta = request.META
        return {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "request_id": request.haven_request_id,
            "trace_id": trace_root(meta.get("HTTP_X_AMZN_TRACE_ID")),
            "client_request_id": client_id(meta.get("HTTP_X_HAVEN_REQUEST_ID")),
            "run_id": client_id(meta.get("HTTP_X_HAVEN_RUN_ID")),
            "method": request.method,
            "path": request.path[:200],
            "view": view,
            "action": self._action(request, view, status),
            "actor_id": actor_id,
            "resource_id": self._resource(match),
            "status": status,
            "result": result_of(status),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        }

    @staticmethod
    def _match(request):
        try:
            return resolve(request.path_info)
        except Resolver404:
            return None

    @staticmethod
    def _action(request, view, status):
        marked = getattr(request, REASON_ATTR, None)
        if marked:
            return marked
        if view == "accounts:login" and request.method == "POST":
            return "login_success" if status == 302 else "login_failure"
        if view == "accounts:logout" and request.method == "POST" and status == 302:
            return "logout"
        return view

    @staticmethod
    def _resource(match):
        if match is None:
            return None
        kwargs = match.kwargs
        if "pk" not in kwargs:
            return None
        base = "user" if (match.namespace == "adminpanel") else "post"
        parts = []
        for key, label in RESOURCE_KEYS:
            if key in kwargs:
                parts.append(f"{label or base}:{int(kwargs[key])}")
        return "/".join(parts) or None


def csrf_failure(request, reason=""):
    """CSRF 실패를 로그 action에 표시하고 Django 기본 화면(403_csrf.html)을 그대로 쓴다."""
    from django.views.csrf import csrf_failure as django_csrf_failure

    mark(request, "csrf_failure")
    return django_csrf_failure(request, reason=reason)
