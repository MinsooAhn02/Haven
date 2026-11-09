#!/usr/bin/env python3
"""
run()       → 대상/시험표 검증 → 역할별 세션·CSRF 준비 → 제한된 요청 → JSON/CSV 기록
correlate() → run 결과와 WAF·앱 JSONL 로그를 요청 ID로 결합 → 신뢰도·판정 기록
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import getpass
import hashlib
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit, urlunsplit
import uuid
import socket
import threading

import requests

ROLES = {"anonymous", "member_a", "member_b", "member_c", "operator"}
METHODS = {"GET", "POST"}
WAF_EXPECT = {"ALLOW", "BLOCK", "COUNT", "NOT_APPLICABLE"}
REQ_ID_HEADER = "X-Haven-Request-ID"
RUN_ID_HEADER = "X-Haven-Run-ID"
MAX_RESPONSE = 2 * 1024 * 1024
RESULT_FIELDS = [
    "run_id", "request_id", "trace_id", "case_id", "timestamp_utc", "elapsed_ms",
    "auth_role", "category", "method", "path", "expected_app", "expected_waf",
    "http_status", "redirect_target", "response_summary", "app_observed",
    "waf_action", "rule_id", "waf_verdict", "app_validity", "transport_status",
    "correlation_status", "evidence_path",
]


class ConfigError(Exception):
    """잘못된 실행 설정·파일·입력값을 나타내는 오류."""
    pass


class ExecutionError(Exception):
    """시간·속도 제한 또는 네트워크 실행 단계의 오류."""
    pass


class TooLargeResponse(ExecutionError):
    """수신 응답의 크기 한도 초과."""
    pass


def utc_now() -> str:
    """UTC ISO 타임스탬프를 반환한다. 로컬 시각과 섞이지 않도록 모든 증거에 사용."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_trace_id() -> str:
    """AWS X-Amzn-Trace-Id 형식의 Root 값을 생성한다."""
    epoch_hex = f"{int(time.time()):08x}"
    random_hex = uuid.uuid4().hex[:24]
    return f"Root=1-{epoch_hex}-{random_hex}"


def load_json(path: Path):
    """UTF-8 JSON을 읽는다. 파일/형식 오류는 CLI 설정 오류로 통일."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ConfigError(f"JSON 파일을 읽을 수 없습니다: {path.name} ({type(exc).__name__})") from exc


def safe_relative(base: Path, rel: str) -> Path:
    """상대 fixture 경로만 허용한다. .., 절대경로, 루트 밖 심볼릭 링크를 거부."""
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or "\\" in rel:
        raise ConfigError("fixture 파일 경로는 내부 상대 경로여야 합니다")
    # Reject traversal even if the file has not yet been created.
    if any(part in {"..", ""} for part in Path(rel).parts):
        raise ConfigError("fixture 경로에 상위 폴더 이동이 있습니다")
    try:
        root = base.resolve(strict=True)
        candidate = (root / rel).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ConfigError("fixture 경로가 존재하지 않거나 확인할 수 없습니다") from exc

    if not candidate.is_file() or not candidate.is_relative_to(root):
        raise ConfigError("허용된 fixture 경로 밖이거나 파일이 없습니다")
    return candidate


def canonical_origin(value: str) -> str:
    """주소를 scheme://host:port 형태로 정규화하고 승인 불가 HTTP를 거절."""
    if not isinstance(value, str) or not value or value.strip() != value or re.search(r"[\x00-\x20\\]", value):
        raise ConfigError("origin에 잘못된 문자가 있습니다")
    try:
        p = urlsplit(value)
        if p.scheme not in {"http", "https"} or not p.hostname or p.username is not None or p.password is not None:
            raise ValueError("scheme/host/credential")
        if p.path not in {"", "/"} or p.query or p.fragment:
            raise ValueError("origin에 경로/쿼리가 있습니다")
        if p.hostname.endswith(".") or "%" in p.hostname:
            raise ValueError("host 형식")
        port = p.port if p.port is not None else (443 if p.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError("port")
        host = p.hostname.lower()
        # HTTPS is required except for explicitly allowlisted local loopback HTTP.
        if p.scheme == "http":
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = host == "localhost"
            if not loopback:
                raise ValueError("HTTP는 로컬 loopback에서만 허용합니다")
        display_host = f"[{host}]" if ":" in host else host
        return f"{p.scheme}://{display_host}:{port}"
    except ValueError as exc:
        raise ConfigError(f"유효하지 않은 origin: {exc}") from exc


def serialize_origin_header(origin: str) -> str:
    """HTTP Origin 헤더용 직렬화. 기본 포트는 생략한다."""
    normalized = canonical_origin(origin)
    parsed = urlsplit(normalized)

    host = parsed.hostname
    display_host = f"[{host}]" if ":" in host else host

    default_port = 443 if parsed.scheme == "https" else 80

    port_suffix = (
        "" if parsed.port == default_port
        else f":{parsed.port}"
    )

    return f"{parsed.scheme}://{display_host}{port_suffix}"


def validate_path(path: str) -> str:
    """현재 origin 안에서만 사용할 수 있는 안전한 상대 URL 경로인지 검사."""
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise ConfigError("케이스 path는 / 로 시작하는 같은 origin의 상대 경로여야 합니다")
    if re.search(r"[\x00-\x1f\x7f\\#]", path) or len(path) > 4096:
        raise ConfigError("path에 금지된 문자가 있습니다")
    p = urlsplit(path)
    if p.scheme or p.netloc or not p.path.startswith("/"):
        raise ConfigError("origin을 바꾸는 path는 허용하지 않습니다")
    if any(ch.isspace() for ch in p.path):
        raise ConfigError("URL 경로에 공백을 사용할 수 없습니다")
    return path


def safe_path_log(path: str) -> str:
    """query의 값만 가려 기록한다. 원본 query는 출력에 남기지 않는다."""
    p = urlsplit(path)
    if not p.query:
        return p.path
    keys = [part.split("=", 1)[0][:64] for part in p.query.split("&")][:32]
    return p.path + "?" + "&".join(f"{key}=<redacted>" for key in keys)


def safe_location(raw: str | None) -> str | None:
    """HTTP Location 헤더에서 토큰성 query 값·자격증명을 제거."""
    if not raw:
        return None
    try:
        p = urlsplit(raw)
        if p.username or p.password:
            return "<redacted-location>"
        # Redact query values and fragments, keep redirect destination evidence.
        if p.scheme or p.netloc:
            origin = urlunsplit((p.scheme, p.netloc, "", "", ""))
            return origin + safe_path_log((p.path or "/") + ("?" + p.query if p.query else ""))
        return safe_path_log((p.path or "/") + ("?" + p.query if p.query else ""))
    except ValueError:
        return "<invalid-location>"


def validate_limits(args):
    """요청 수/초당 속도/timeout/전체 실행시간/응답 크기의 상한 검사."""
    for name, maximum in (("timeout", 30), ("max_requests", 1000), ("rate", 5),
                          ("max_duration", 900), ("max_response_bytes", MAX_RESPONSE)):
        value = getattr(args, name)
        if not 0 < value <= maximum:
            raise ConfigError(f"{name}은 0 초과, {maximum} 이하여야 합니다")


def validate_suite(suite: object, fixtures: Path):
    """케이스의 공통 스키마 및 fixture 참조를 전송 전에 검증."""
    if not isinstance(suite, dict) or suite.get("schema_version") != 1 or not isinstance(suite.get("suite_id"), str):
        raise ConfigError("suite에는 schema_version=1 및 suite_id가 필요합니다")
    if not suite["suite_id"].strip() or suite.get("suite_kind") not in {"regression", "confirmation"}:
        raise ConfigError("suite_id / suite_kind가 잘못되었습니다")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ConfigError("cases는 비어 있지 않은 목록이어야 합니다")
    found = set()
    for index, item in enumerate(cases):
        required = {"case_id", "category", "method", "path", "auth_role", "input_reference",
                    "expected_app", "expected_waf", "max_requests", "note"}
        if not isinstance(item, dict) or not required.issubset(item):
            raise ConfigError("케이스에 필수 필드가 부족합니다")
        cid = item["case_id"]
        if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", cid) or cid in found:
            raise ConfigError("case_id가 중복되었거나 유효하지 않습니다")
        found.add(cid)
        if "phase" in item:
            if type(item["phase"]) is not int or item["phase"] not in {1, 2, 3, 4}:
                raise ConfigError(f"{cid}: phase는 1~4 정수여야 합니다")
        if item["method"] not in METHODS or item["auth_role"] not in ROLES:
            raise ConfigError(f"{cid}: method/auth_role 오류")
        if "checkpoint_before" in item:
            if (
                item["checkpoint_before"] != "deactivate_member_b"
                or item["auth_role"] != "member_b"
            ):
                raise ConfigError(
                    f"{cid}: checkpoint_before 설정 오류"
                )

            if not any(
                previous.get("auth_role") == "member_b"
                for previous in cases[:index]
            ):
                raise ConfigError(
                    f"{cid}: B 세션 기준 요청이 먼저 필요합니다"
                )
        validate_path(item["path"])
        if not isinstance(item["category"], str) or not item["category"].strip() or not isinstance(item["note"], str):
            raise ConfigError(f"{cid}: category/note 오류")
        if type(item["max_requests"]) is not int or item["max_requests"] < 1 or item["max_requests"] > 1000:
            raise ConfigError(f"{cid}: max_requests 오류")
        if item["expected_waf"] not in WAF_EXPECT:
            raise ConfigError(f"{cid}: expected_waf는 {sorted(WAF_EXPECT)} 중 하나여야 합니다")
        if item.get("verification_mode", "manual_required") not in {"manual_required", "http_only"}:
            raise ConfigError(f"{cid}: verification_mode는 manual_required 또는 http_only여야 합니다")
        expected = item["expected_app"]
        if not isinstance(expected, dict) or "http_status" not in expected:
            raise ConfigError(f"{cid}: expected_app.http_status가 필요합니다")
        status = expected["http_status"]
        if not (isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599):
            raise ConfigError(f"{cid}: http_status는 100~599 정수여야 합니다")
        if "redirect_path" in expected:
            validate_path(expected["redirect_path"])
        if "sha256" in expected and (not isinstance(expected["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", expected["sha256"])):
            raise ConfigError(f"{cid}: sha256 형식 오류")
        if "body_bytes" in expected and (type(expected["body_bytes"]) is not int or not 0 <= expected["body_bytes"] <= MAX_RESPONSE):
            raise ConfigError(f"{cid}: body_bytes 형식 오류")
        if "headers_contain" in expected and (not isinstance(expected["headers_contain"], dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in expected["headers_contain"].items())):
            raise ConfigError(f"{cid}: headers_contain 형식 오류")
        ref = item["input_reference"]
        if item["method"] == "GET" and ref is not None:
            raise ConfigError(f"{cid}: GET은 payload fixture를 사용하지 않습니다")
        if item["method"] == "POST" and ref is None:
            raise ConfigError(f"{cid}: POST는 payload fixture가 필요합니다")
        if ref is not None:
            payload = load_json(safe_relative(fixtures, ref))
            validate_payload(payload, fixtures)


def select_phase(suite: dict, phase: int | None) -> dict:
    """선택한 회차만 원래 순서대로 반환한다. 원본 suite는 변경하지 않는다."""
    if phase is None:
        return suite

    if type(phase) is not int or phase not in {1, 2, 3, 4}:
        raise ConfigError("phase는 1~4 정수여야 합니다")

    missing = [case["case_id"] for case in suite["cases"] if "phase" not in case]
    if missing:
        raise ConfigError("--phase 사용 시 모든 케이스에 phase가 필요합니다: " + ", ".join(missing))

    selected = [case for case in suite["cases"] if case["phase"] == phase]
    if not selected:
        raise ConfigError(f"{phase}회차에 해당하는 케이스가 없습니다")

    return {**suite, "cases": selected}


def validate_selected_checkpoint_sequence(suite: dict) -> None:
    """실제로 선택된 케이스에 체크포인트 선행 조건이 있는지 확인한다."""

    cases = suite["cases"]

    for index, case in enumerate(cases):
        if case.get("checkpoint_before") != "deactivate_member_b":
            continue

        baseline_found = any(
            previous["auth_role"] == "member_b"
            and previous["method"] == "GET"
            and previous["path"] == case["path"]
            and previous["expected_app"]["http_status"] == 200
            and "checkpoint_before" not in previous
            for previous in cases[:index]
        )

        if not baseline_found:
            raise ConfigError(f"{case['case_id']}: 선택된 회차에 동일 기록을 조회하는 B의 활성 상태 기준 요청(HTTP 200)이 없습니다")


def validate_payload(payload: object, root: Path):
    """POST payload의 지원 필드, 파일명, content type, 크기 등을 검사."""
    if not isinstance(payload, dict) or payload.get("csrf_mode", "valid") not in {"valid", "missing", "invalid"}:
        raise ConfigError("payload csrf_mode가 잘못되었습니다")
    fields = payload.get("fields", {})
    if not isinstance(fields, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in fields.items()):
        raise ConfigError("fields는 문자열 키/값 객체여야 합니다")
    if "csrfmiddlewaretoken" in fields or len(fields) > 40 or any(len(k) > 100 for k in fields):
        raise ConfigError("토큰은 fixture에 저장하지 않으며 fields 항목 수/길이를 제한합니다")
    if "file" in payload:
        item = payload["file"]
        if not isinstance(item, dict) or set(item) != {"field_name", "local_fixture_path", "filename", "content_type"}:
            raise ConfigError("file 필드 형식 오류")
        if item["field_name"] != "attachment" or not all(isinstance(v, str) for v in item.values()):
            raise ConfigError("multipart file 필드 형식 오류")
        file_path = safe_relative(root, item["local_fixture_path"])
        if file_path.stat().st_size > MAX_RESPONSE + 1:
            raise ConfigError("시험용 파일이 단일 파일 상한을 초과합니다")
        if len(item["filename"]) > 255 or len(item["content_type"]) > 128:
            raise ConfigError("파일명 또는 MIME이 너무 깁니다")
    if payload.get("origin_mode", "same") not in {"absent", "same", "foreign"}:
        raise ConfigError("origin_mode 오류 (absent/same/foreign)")
    if "pad_form_body_to" in payload:
        n = payload["pad_form_body_to"]
        if type(n) is not int or not 1 <= n <= 8193 or "file" in payload or "body" not in fields:
            raise ConfigError("pad_form_body_to는 비-multipart 글 body 필드와 함께 1~8193만 가능합니다")
    if set(payload) - {"fields", "file", "csrf_mode", "origin_mode", "pad_form_body_to"}:
        raise ConfigError("지원하지 않는 payload 필드가 있습니다")


def read_payload(root: Path, ref: str) -> dict:
    """검증된 fixture 루트에서 입력 JSON을 읽는다."""
    return load_json(safe_relative(root, ref))


class CsrfHtmlParser(HTMLParser):
    """로그인 페이지 HTML에서 csrfmiddlewaretoken hidden input만 찾는다."""
    def __init__(self):
        super().__init__()
        self.value = None

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            d = dict(attrs)
            if d.get("name") == "csrfmiddlewaretoken" and d.get("value"):
                self.value = d["value"]


class RequestBudget:
    """로그인/CSRF 준비 포함 전체 요청 수·속도·시간 예산 관리."""
    def __init__(self, args):
        """CLI 한도 옵션을 복사하고 실행 시작 시각 기록."""
        self.maximum = args.max_requests
        self.rate = args.rate
        self.duration = args.max_duration
        self.timeout = args.timeout
        self.count = 0
        self.started = time.monotonic()
        self.last_request = None

    def begin(self):
        """요청 1건의 예산을 선점한 뒤 허용 timeout을 반환."""
        if self.count >= self.maximum:
            raise ExecutionError("요청 수 한도 도달")
        elapsed = time.monotonic() - self.started
        if elapsed >= self.duration:
            raise ExecutionError("전체 실행 시간 한도 도달")
        if self.last_request is not None:
            waiting = 1.0 / self.rate - (time.monotonic() - self.last_request)
            if waiting > 0:
                if elapsed + waiting >= self.duration:
                    raise ExecutionError("속도 대기 중 전체 시간 한도 도달")
                time.sleep(waiting)
        remaining = self.duration - (time.monotonic() - self.started)
        if remaining <= 0:
            raise ExecutionError("전체 실행 시간 한도 도달")
        self.count += 1
        self.last_request = time.monotonic()
        return max(0.001, min(self.timeout, remaining))


class NoRedirectBodySession(requests.Session):
    """리다이렉트를 따르지 않을 때 requests의 불필요한 본문 소비를 방지한다."""

    def resolve_redirects(self, resp, req, **kwargs):
        if kwargs.get("yield_requests", False):
            # allow_redirects=False인 경우 다음 요청도 생성하지 않는다.
            return iter(())

        return super().resolve_redirects(resp, req, **kwargs)


def new_session() -> requests.Session:
    """역할 간 쿠키 분리. 환경 proxy/.netrc의 암묵적 인증도 사용하지 않음."""
    s = NoRedirectBodySession()
    s.trust_env = False  # avoid implicit .netrc / environment proxy credentials
    return s


def bounded_send(s: requests.Session, method: str, target: str, path: str, budget: RequestBudget,
                 request_id: str, *, fields=None, file_info=None, headers=None,
                 max_response_bytes=MAX_RESPONSE, read_redirect_body=False, trace_id=None, on_send=None) -> tuple[dict, bytes | None]:
    """HTTP를 최대 1회 전송한다. 리다이렉트 미추적·TLS 확인·응답 상한 적용."""
    url = target + validate_path(path)
    h = {REQ_ID_HEADER: request_id}
    if headers:
        h.update(headers)
    if trace_id is not None:
        h["X-Amzn-Trace-Id"] = trace_id
    opened = None
    try:
        if file_info:
            opened = open(file_info["path"], "rb")
            files = {"attachment": (file_info["filename"], opened, file_info["content_type"])}
        else:
            files = None
        req = requests.Request(method, url, headers=h, data=fields if fields is not None else None, files=files)
        prepared = s.prepare_request(req)
        if canonical_origin(urlunsplit((urlsplit(prepared.url).scheme, urlsplit(prepared.url).netloc, "", "", ""))) != target:
            raise ConfigError("요청 준비 과정에서 origin이 바뀌었습니다")
        timeout = budget.begin()
        start = time.monotonic()

        # 속도 제한 대기가 끝난 후 실제 HTTP 전송 직전 시각 기록
        if on_send is not None:
            on_send(utc_now())

        with s.send(prepared, allow_redirects=False, timeout=timeout, stream=True, verify=True) as resp:
            total = 0
            digest = hashlib.sha256()
            chunks = []
            content_length = resp.headers.get("Content-Length")
            if content_length and content_length.isdecimal() and int(content_length) > max_response_bytes:
                raise TooLargeResponse("응답 Content-Length가 허용 크기를 초과합니다")
            
            # 리다이렉트 본문에 대한 검증 요구가 없으면 본문을 수신하지 않는다.
            if 300 <= resp.status_code < 400 and not read_redirect_body:
                if time.monotonic() - budget.started >= budget.duration:
                    raise ExecutionError("응답 헤더 수신 중 전체 실행 시간 한도를 초과했습니다")

                request_body = prepared.body
                if isinstance(request_body, bytes):
                    request_body_bytes = len(request_body)
                elif isinstance(request_body, str):
                    request_body_bytes = len(request_body.encode("utf-8"))
                else:
                    request_body_bytes = None

                safe_headers = {
                    key: resp.headers[key]
                    for key in (
                        "Content-Type",
                        "Content-Disposition",
                        "X-Content-Type-Options",
                        "Cache-Control",
                        "X-Request-ID",
                    )
                    if key in resp.headers
                }

                return {
                    "status": resp.status_code,
                    "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
                    "location": resp.headers.get("Location"),
                    "body_bytes": None,
                    "sha256": None,
                    "headers": safe_headers,
                    "request_body_bytes": request_body_bytes,
                }, None
            
            # 전체 실행 제한 시간을 절대 deadline으로 계산한다.
            deadline = budget.started + budget.duration
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                raise ExecutionError(
                    "응답을 읽는 중 전체 실행 시간 한도를 초과했습니다"
                )

            deadline_expired = threading.Event()

            def interrupt_stream():
                # 제한 시간에 도달하면 진행 중인 소켓 수신을 중단한다.
                deadline_expired.set()
                try:
                    resp.raw._fp.fp.raw._sock.shutdown(socket.SHUT_RDWR)
                except (AttributeError, OSError):
                    pass

            watchdog = threading.Timer(remaining, interrupt_stream)
            watchdog.daemon = True
            watchdog.start()

            try:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if time.monotonic() >= deadline:
                        raise ExecutionError(
                            "응답을 읽는 중 전체 실행 시간 한도를 초과했습니다"
                        )

                    if not chunk:
                        continue

                    total += len(chunk)

                    if total > max_response_bytes:
                        raise TooLargeResponse(
                            "실제 응답이 허용 크기를 초과합니다"
                        )

                    digest.update(chunk)

                    # 로그인 준비 HTML만 메모리에 보관한다.
                    if path == "/accounts/login/" and total <= 65536:
                        chunks.append(chunk)

                if deadline_expired.is_set() or time.monotonic() >= deadline:
                    raise ExecutionError(
                        "응답을 읽는 중 전체 실행 시간 한도를 초과했습니다"
                    )

            except (requests.RequestException, OSError) as exc:
                if deadline_expired.is_set() or time.monotonic() >= deadline:
                    raise ExecutionError(
                        "응답을 읽는 중 전체 실행 시간 한도를 초과했습니다"
                    ) from exc
                raise

            finally:
                watchdog.cancel()
                watchdog.join()
            safe_headers = {key: resp.headers[key] for key in (
                "Content-Type", "Content-Disposition", "X-Content-Type-Options", "Cache-Control", "X-Request-ID"
            ) if key in resp.headers}

            request_body = prepared.body

            if isinstance(request_body, bytes):
                request_body_bytes = len(request_body)
            elif isinstance(request_body, str):
                request_body_bytes = len(request_body.encode("utf-8"))
            else:
                request_body_bytes = None

            detail = {
                "status": resp.status_code, "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
                "location": resp.headers.get("Location"), "body_bytes": total,
                "sha256": digest.hexdigest(), "headers": safe_headers,
                "request_body_bytes": request_body_bytes,
            }
            return detail, b"".join(chunks) if chunks else None
    except (requests.RequestException, OSError) as exc:
        raise ExecutionError(f"HTTP 요청 실패: {type(exc).__name__}") from exc
    finally:
        if opened is not None:
            opened.close()


def get_csrf_token(s: requests.Session) -> str | None:
    """현재 역할 session의 CSRF 쿠키를 읽는다. 결과 파일에는 저장하지 않음."""
    return s.cookies.get("csrftoken")


def prep_login(s: requests.Session, target: str, budget: RequestBudget, role: str,
               run_id: str, prep_events: list, max_response_bytes: int) -> None:
    """역할별 시험 계정으로 로그인한다. 비밀번호는 대화형 입력하고 기록 금지."""
    print(f"[인증 준비] {role}: 가상 시험 계정 정보를 대화형으로 입력하세요", file=sys.stderr)
    try:
        username = input(f"  {role} 사용자 이름: ").strip()
    except EOFError as exc:
        raise ExecutionError("사용자 이름 입력을 받을 수 없습니다") from exc
    if not username:
        raise ExecutionError("사용자 이름이 비어 있습니다")
    try:
        password = getpass.getpass(f"  {role} 비밀번호(화면 미표시): ")
    except EOFError as exc:
        raise ExecutionError("비밀번호 입력을 받을 수 없습니다") from exc
    if not password:
        raise ExecutionError("비밀번호가 비어 있습니다")
    rid = str(uuid.uuid4())
    detail, html = bounded_send(s, "GET", target, "/accounts/login/", budget, rid,
                                headers={RUN_ID_HEADER: run_id}, max_response_bytes=min(max_response_bytes, 65536))
    prep_events.append({"request_id": rid, "stage": "login_form", "http_status": detail["status"]})
    if detail["status"] != 200:
        raise ExecutionError("로그인 폼 준비 실패")
    parser = CsrfHtmlParser()
    if html:
        parser.feed(html.decode("utf-8", errors="replace"))
    csrf = parser.value or get_csrf_token(s)
    if not csrf:
        raise ExecutionError("CSRF 토큰 준비 실패")
    rid = str(uuid.uuid4())
    detail, _ = bounded_send(
        s, "POST", target, "/accounts/login/", budget, rid,
        fields={
            "username": username,
            "password": password,
            "csrfmiddlewaretoken": csrf,
        },
        headers={
            "Origin": serialize_origin_header(target),
            "X-CSRFToken": csrf,
            RUN_ID_HEADER: run_id,
        },
        max_response_bytes=max_response_bytes,
    )
    prep_events.append({"request_id": rid, "stage": "login_submit", "http_status": detail["status"]})
    # No redirect follow. Login POST success is expected to redirect away from login.
    login_redirect = same_origin_redirect_path(detail["location"], target)
    if detail["status"] != 302 or not s.cookies.get("sessionid") or not login_redirect or login_redirect.startswith("/accounts/login/"):
        raise ExecutionError("로그인 인증 준비 실패 (상태/세션 확인)")


def csrf_for_post(s: requests.Session, target: str, budget: RequestBudget,
                  prep_events: list, max_response_bytes: int, mode: str, run_id: str):
    """POST에 쓰일 CSRF 토큰을 얻는다. missing/invalid 시험은 의도적 예외."""
    if mode == "missing":
        return None
    if mode == "invalid":
        return "invalid-token-for-negative-test"
    csrf = get_csrf_token(s)
    if not csrf:
        rid = str(uuid.uuid4())
        detail, html = bounded_send(s, "GET", target, "/accounts/login/", budget, rid,
                                    headers={RUN_ID_HEADER: run_id}, max_response_bytes=min(max_response_bytes, 65536))
        prep_events.append({"request_id": rid, "stage": "csrf_form", "http_status": detail["status"]})
        parser = CsrfHtmlParser()
        if html:
            parser.feed(html.decode("utf-8", errors="replace"))
        csrf = parser.value or get_csrf_token(s)
    if not csrf:
        raise ExecutionError("CSRF 토큰 준비 실패")
    return csrf



def prepare_case_request(s: requests.Session, case: dict, fixture_root: Path, target: str,
                         budget: RequestBudget, run_id: str, prep_events: list,
                         max_response_bytes: int):
    """시험 케이스의 POST 데이터를 구성한다. 네트워크 전송은 bounded_send가 담당.

    반환값: (fields 또는 None, headers, file_info 또는 None)
    GET 요청은 payload를 읽지 않는다. POST는 사용자의 기존 session에서 CSRF를 가져오며,
    로그인/CSRF 준비 요청까지 RequestBudget에 포함한다.
    """
    headers = {RUN_ID_HEADER: run_id}
    if case["method"] == "GET":
        return None, headers, None

    payload = read_payload(fixture_root, case["input_reference"])
    fields = dict(payload.get("fields", {}))
    csrf = csrf_for_post(s, target, budget, prep_events, max_response_bytes,
                         payload.get("csrf_mode", "valid"), run_id)
    if csrf:
        fields["csrfmiddlewaretoken"] = csrf
        headers["X-CSRFToken"] = csrf

    # Origin 공격은 '목적지' 변경이 아니라 헤더만 변경한다.
    origin_mode = payload.get("origin_mode", "same")
    if origin_mode == "same":
        headers["Origin"] = serialize_origin_header(target)
    elif origin_mode == "foreign":
        headers["Origin"] = "https://attacker.invalid"

    # 테스트의 실제 form-urlencoded 직렬화 크기를 정확하게 맞춘다.
    if "pad_form_body_to" in payload:
        target_size = payload["pad_form_body_to"]
        serialized = requests.Request("POST", target + case["path"], data=fields).prepare().body
        current_size = len(serialized.encode("utf-8") if isinstance(serialized, str) else serialized)
        if current_size > target_size:
            raise ExecutionError(f"요청 기본 body 크기 {current_size}가 목표 {target_size}바이트보다 큽니다")
        fields["body"] += "A" * (target_size - current_size)

    file_info = None
    if "file" in payload:
        spec = payload["file"]
        file_info = {
            "path": safe_relative(fixture_root, spec["local_fixture_path"]),
            "filename": spec["filename"],
            "content_type": spec["content_type"],
        }
    return fields, headers, file_info


def same_origin_redirect_path(location: str | None, target_origin: str | None) -> str | None:
    """원본 Location이 같은 origin을 가리키면 목적지 경로를 반환."""
    if not location or location.startswith("///") or re.search(r"[\x00-\x20\x7f\\]", location):
        return None
    try:
        destination = urlsplit(location)
        if not destination.scheme and not destination.netloc:
            return validate_path(destination.path)
        if target_origin is None:
            return None
        origin = urlunsplit((destination.scheme or urlsplit(target_origin).scheme, destination.netloc, "", "", ""))
        if canonical_origin(origin) == canonical_origin(target_origin):
            return destination.path or "/"
    except (ValueError, ConfigError):
        return None
    return None


def check_http_expected(detail: dict, expected: dict, *, target_origin: str | None = None) -> bool:
    """응답 코드·리다이렉트·길이·해시·헤더의 명시적 기대값을 비교."""
    ok = detail["status"] == expected["http_status"]
    if "redirect_path" in expected:
        ok = ok and same_origin_redirect_path(detail.get("location"), target_origin) == expected["redirect_path"]
    if "body_bytes" in expected:
        ok = ok and detail["body_bytes"] == expected["body_bytes"]
    if "sha256" in expected:
        ok = ok and detail["sha256"] == expected["sha256"]

    headers_ci = {
        name.lower(): value
        for name, value in detail["headers"].items()
    }

    # 기대한 헤더 값이 실제 응답에 포함되어 있는지 확인
    for header, needle in expected.get("headers_contain", {}).items():
        actual = headers_ci.get(header.lower(), "")
        ok = ok and needle.lower() in actual.lower()
    return bool(ok)


def base_record(run_id: str, case: dict) -> dict:
    """요청 1건에 대한 결과 기본 필드를 만든다. 최초 판정은 UNKNOWN."""
    return dict(
        run_id=run_id, request_id=str(uuid.uuid4()), trace_id=new_trace_id(), case_id=case["case_id"],
        timestamp_utc=utc_now(), elapsed_ms=None, auth_role=case["auth_role"],
        category=case["category"], method=case["method"], path=safe_path_log(case["path"]),
        expected_app=case["expected_app"], expected_waf=case["expected_waf"],
        http_status=None, redirect_target=None, response_summary=None, app_observed=None,
        waf_action=None, rule_id=None, waf_verdict="UNKNOWN", app_validity="UNKNOWN",
        transport_status="PENDING", correlation_status="PENDING_LOG", evidence_path=None,
        http_expectation_match=None, verdict="UNKNOWN",
        verification_mode=case.get("verification_mode", "manual_required"),
        manual_validation="REQUIRED" if case.get("verification_mode", "manual_required") == "manual_required" else "NOT_REQUIRED",
    )


def save_results(outdir: Path, state: dict, records: list, *, correlation=False) -> None:
    """JSON 상세와 CSV 요약을 작성한다. 원본 run 결과는 correlate가 수정하지 않음."""
    jsonpath = outdir / ("correlated_results.json" if correlation else "results.json")
    csvpath = outdir / ("correlated_summary.csv" if correlation else "summary.csv")
    state["results"] = records
    # Atomic replace only inside the new output directory owned by this run.
    temp = jsonpath.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    temp.replace(jsonpath)
    with csvpath.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=RESULT_FIELDS + ["http_expectation_match", "verdict"], extrasaction="ignore")
        w.writeheader()
        for record in records:
            row = {**record}
            row["expected_app"] = json.dumps(row["expected_app"], ensure_ascii=False)
            row["response_summary"] = json.dumps(row["response_summary"], ensure_ascii=False)
            w.writerow(row)


def get_exit_code(records: list, *, incomplete: bool) -> int:
    """종료 코드 우선순위: ERROR(2) > UNKNOWN(3) > FAIL(1) > PASS(0)."""
    if incomplete or any(r["transport_status"] == "ERROR" for r in records):
        return 2
    if any(r["verdict"] == "UNKNOWN" for r in records):
        return 3
    if any(r["verdict"] == "FAIL" for r in records):
        return 1
    return 0


def run(args) -> int:
    """승인한 대상의 고정 케이스를 순차 실행한다. HTTP 결과만으로 보안 PASS 금지."""
    # 1) 실행 전 검증: 대상이 allowlist와 정확히 일치해야 전송 가능.
    validate_limits(args)
    target = canonical_origin(args.target)
    allow = load_json(args.allowlist)
    if not isinstance(allow, dict) or not isinstance(allow.get("approved_origins"), list):
        raise ConfigError('allowlist 형식은 {"approved_origins":["https://..."]} 입니다')
    approved = {canonical_origin(x) for x in allow["approved_origins"]}
    if target not in approved:
        raise ConfigError("대상 origin이 정확한 allowlist에 없습니다")
    root = args.fixture_dir.resolve(strict=True)
    suite = load_json(args.cases)
    validate_suite(suite, root)

    total_cases = len(suite["cases"])
    phase = getattr(args, "phase", None)
    suite = select_phase(suite, phase)
    if any("checkpoint_before" in case for case in suite["cases"]) and not getattr(args, "manual_checkpoints", False):
        raise ConfigError("수동 체크포인트 시험에는 --manual-checkpoints 옵션이 필요합니다")
    validate_selected_checkpoint_sequence(suite)
    phase_label = "전체" if phase is None else f"{phase}회차"
    print(
        f"대상={target}  suite={suite['suite_id']}  "
        f"회차={phase_label}  선택={len(suite['cases'])}/{total_cases}  "
        f"timeout={args.timeout}s  요청≤{args.max_requests}  "
        f"초당≤{args.rate}  시간≤{args.max_duration}s",
        file=sys.stderr,
    )
    if args.output_dir.exists():
        raise ConfigError("출력 폴더가 이미 있습니다. 새 경로를 지정하세요")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    # 2) 실행 단위 ID와 전역 요청 예산을 생성한다.
    run_id = str(uuid.uuid4())
    budget = RequestBudget(args)
    sessions = {}
    prepped = {}
    prep_events = []
    state = {"schema_version": 1, "run_id": run_id, "suite_id": suite["suite_id"],
             "suite_kind": suite["suite_kind"], "target_origin": target, "started_utc": utc_now(),
             "source": "live_http_run", "stopped_reason": None, "unexecuted_cases": len(suite["cases"]),
             "total_http_requests_including_preparation": 0, "preparation_events": prep_events}
    state.update(
        selected_phase=phase,
        total_suite_cases=total_cases,
        selected_cases=len(suite["cases"]),
        excluded_cases=total_cases - len(suite["cases"]),
    )
    records = []
    failed = False
    try:
        for case in suite["cases"]:
            record = base_record(run_id, case)
            role = case["auth_role"]
            try:
                # 3) 사용자 역할별 Session 분리 (A 쿠키를 C가 재사용하지 않도록).
                if role not in sessions:
                    sessions[role] = new_session()
                sess = sessions[role]
                if role != "anonymous" and not prepped.get(role):
                    prep_login(sess, target, budget, role, run_id, prep_events, args.max_response_bytes)
                    prepped[role] = True
                
                if case.get("checkpoint_before") == "deactivate_member_b":
                    baseline_ok = any(
                        previous["auth_role"] == "member_b"
                        and previous["method"] == "GET"
                        and previous["path"] == safe_path_log(case["path"])
                        and previous["expected_app"]["http_status"] == 200
                        and previous["http_status"] == 200
                        and previous["http_expectation_match"] is True
                        and previous["transport_status"] == "OK"
                        for previous in records
                    )

                    if not baseline_ok:
                        raise ExecutionError("B의 활성 상태 기준 요청이 HTTP 200으로 확인되지 않아 비활성화 체크포인트를 중단합니다")
                    
                    print("\n[수동 체크포인트] B 계정 비활성화", file=sys.stderr)
                    print("1. 별도 관리자 화면에서 member_b를 비활성화하세요.", file=sys.stderr)
                    print("2. member_a와 P1 및 공유 관계는 유지하세요.", file=sys.stderr)
                    print("3. 이 CLI는 B의 기존 세션을 유지합니다.", file=sys.stderr)

                    try:
                        confirmation = input("비활성화 확인 후 DEACTIVATED 입력: ").strip()
                    except EOFError as exc:
                        raise ExecutionError("수동 확인 입력을 받을 수 없습니다") from exc

                    if confirmation != "DEACTIVATED":
                        raise ExecutionError("계정 비활성화 확인이 완료되지 않았습니다")

                    prep_events.append({
                        "stage": "manual_checkpoint",
                        "case_id": case["case_id"],
                        "action": "deactivate_member_b_confirmed",
                        "timestamp_utc": utc_now(),
                    })

                # 인가/CSRF 준비와 HTTP 전송을 분리해 run()의 흐름을 단순하게 유지한다.
                fields, headers, file_info = prepare_case_request(
                    sess, case, root, target, budget, run_id, prep_events, args.max_response_bytes
                )
                detail, _ = bounded_send(
                    sess, case["method"], target, case["path"], budget, record["request_id"],
                    fields=fields, file_info=file_info, headers=headers,
                    trace_id=record["trace_id"],
                    max_response_bytes=args.max_response_bytes,
                    read_redirect_body=any(
                        key in case["expected_app"]
                        for key in ("body_bytes", "sha256")
                    ),
                    on_send=lambda timestamp: record.update(
                        timestamp_utc=timestamp
                    ),
                )
                record.update(http_status=detail["status"], elapsed_ms=detail["elapsed_ms"],
                              redirect_target=safe_location(detail["location"]),
                              response_summary={"request_body_bytes": detail["request_body_bytes"], "body_bytes": detail["body_bytes"], "sha256": detail["sha256"],
                                                "headers": detail["headers"]}, transport_status="OK",
                              http_expectation_match=check_http_expected(detail, case["expected_app"], target_origin=target))
                # No WAF/app log evidence in run: do not invent a pass based on HTTP 403.
                record["verdict"] = "UNKNOWN"
            except (ExecutionError, ConfigError, KeyboardInterrupt) as exc:
                record.update(transport_status="ERROR", verdict="ERROR",
                              response_summary={"error": ("KeyboardInterrupt" if isinstance(exc, KeyboardInterrupt)
                                                          else str(exc))})
                failed = True
            # 4) 성공/실패마다 즉시 기록: 중단돼도 부분 증거를 보존한다.
            records.append(record)
            state["unexecuted_cases"] = len(suite["cases"]) - len(records)
            state["total_http_requests_including_preparation"] = budget.count
            state["ended_utc"] = utc_now()
            if failed:
                state["stopped_reason"] = f"case {case['case_id']}: " + record["response_summary"]["error"]
            save_results(args.output_dir, state, records)
            print(f"{case['case_id']}: HTTP {record['http_status']} / {record['transport_status']} / "
                  f"상관 상태={record['correlation_status']}", file=sys.stderr)
            if failed:
                break
    finally:
        for s in sessions.values():
            s.close()
        state["total_http_requests_including_preparation"] = budget.count
        state["ended_utc"] = utc_now()
        state["unexecuted_cases"] = len(suite["cases"]) - len(records)
        if not records or failed:
            save_results(args.output_dir, state, records)
    print(f"run 결과: {args.output_dir / 'results.json'}", file=sys.stderr)
    return get_exit_code(records, incomplete=failed or len(records) != len(suite["cases"]))


def log_lines(path: Path) -> list[dict]:
    """JSONL WAF/애플리케이션 로그를 읽는다. 한 줄에 JSON 객체 하나."""
    results = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError(f"line {i}")
                results.append(item)
        return results
    except (OSError, ValueError, UnicodeError) as exc:
        raise ConfigError(f"로그를 읽거나 해석할 수 없습니다: {path.name} ({type(exc).__name__})") from exc


def log_request_id(event: dict) -> str | None:
    """CLI 요청 ID를 추출한다. 앱·WAF·기존 로그 형식을 지원."""

    # Django 앱 로그: 서버 자체 ID와 CLI 요청 ID를 구분한다.
    client_id = event.get("client_request_id")
    if isinstance(client_id, str) and client_id.strip():
        return client_id

    # 기존 앱 로그 및 로컬 synthetic fixture 호환성 유지.
    request_id = event.get("request_id")
    if isinstance(request_id, str) and request_id.strip():
        return request_id

    # AWS WAF 원본 로그: HTTP 요청 헤더에서 추출.
    req = event.get("httpRequest", {})
    if not isinstance(req, dict):
        return None

    headers = req.get("headers", [])
    if not isinstance(headers, list):
        return None

    for header in headers:
        if not isinstance(header, dict):
            continue

        name = str(header.get("name", "")).lower()
        value = header.get("value")

        if (name == REQ_ID_HEADER.lower() and isinstance(value, str) and value.strip()):
            return value

    return None


TRACE_ROOT_RE = re.compile(
    r"1-[0-9a-f]{8}-[0-9a-f]{24}",
    re.IGNORECASE,
)


def extract_trace_root(value: object) -> str | None:
    """AWS Trace ID에서 Root 값만 정규화해 추출한다."""
    if not isinstance(value, str):
        return None

    parts = [part.strip() for part in value.split(";")]
    roots = []

    for part in parts:
        if "=" in part:
            name, candidate = part.split("=", 1)

            if name.strip().lower() == "root":
                candidate = candidate.strip()

                if not TRACE_ROOT_RE.fullmatch(candidate):
                    return None

                roots.append(candidate.lower())

        elif len(parts) == 1 and TRACE_ROOT_RE.fullmatch(part):
            roots.append(part.lower())

    # Root가 없거나 여러 개면 임의로 선택하지 않는다.
    return roots[0] if len(roots) == 1 else None


def log_trace_root(event: dict) -> str | None:
    """Django 앱 로그 또는 AWS WAF 로그에서 Trace Root를 추출한다."""
    roots = []

    # Django 앱: request_id에 Trace ID가 기록될 수 있다.
    for field in ("trace_id", "request_id"):
        root = extract_trace_root(event.get(field))
        if root is not None:
            roots.append(root)

    # AWS WAF: httpRequest.headers에서 원본 요청 헤더를 찾는다.
    request = event.get("httpRequest", {})
    if isinstance(request, dict):
        headers = request.get("headers", [])

        if isinstance(headers, list):
            for header in headers:
                if not isinstance(header, dict):
                    continue

                if str(header.get("name", "")).lower() != "x-amzn-trace-id":
                    continue

                root = extract_trace_root(header.get("value"))
                if root is None:
                    return None

                roots.append(root)

    if not roots or len(set(roots)) != 1:
        return None

    return roots[0]


def event_matches_run(event: dict, row: dict) -> bool:
    """로그와 CLI 결과의 요청 식별자가 일치하는지 확인한다."""

    # 과거 결과 파일: trace_id 필드 자체가 없었던 버전.
    if "trace_id" not in row:
        return log_request_id(event) == row.get("request_id")

    expected_root = extract_trace_root(row["trace_id"])

    # Trace ID가 잘못된 실행 결과는 기존 ID로 대체하지 않는다.
    if expected_root is None:
        return False

    actual_root = log_trace_root(event)

    if actual_root is not None:
        return actual_root == expected_root

    # 기존 로컬 mock 로그만 레거시 ID 비교를 허용한다.
    if event.get("synthetic_fixture") is True:
        return log_request_id(event) == row.get("request_id")

    # 실제 로그에 Trace Root가 없으면 연결하지 않는다.
    return False


def log_timestamp(event: dict) -> datetime | None:
    """ISO UTC 또는 AWS 밀리초 epoch를 UTC datetime으로 정규화."""
    val = event.get("timestamp_utc")
    if val is None:
        val = event.get("ts")
    if val is None:
        val = event.get("timestamp")
    if isinstance(val, (float, int)):
        if val > 10**11:  # AWS WAF epoch millis
            val /= 1000
        return datetime.fromtimestamp(val, timezone.utc)
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def plausible_event(event: dict, row: dict, origin: str) -> bool:
    """실행 ID·대상·시간(±120초)이 같은 증거인지 점검."""
    if event.get("run_id") not in {None, row["run_id"]}:
        return False
    if event.get("target_origin") not in {None, origin}:
        return False
    t1 = log_timestamp(event)
    try:
        t2 = datetime.fromisoformat(row["timestamp_utc"])
    except (ValueError, TypeError):
        return False
    return t1 is not None and abs((t1 - t2).total_seconds()) <= 120


def correlate(args) -> int:
    """실행 결과와 WAF·앱 로그를 Trace Root 기준으로 연결하고 검증한다."""
    state = load_json(args.run_json)
    if not isinstance(state, dict) or not isinstance(state.get("results"), list) or not state.get("run_id"):
        raise ConfigError("올바른 run results JSON이 아닙니다")
    if not state["results"]:
        raise ConfigError("대조할 run 결과가 비어 있습니다")
    # 로그는 별도 로컬 파일을 읽으며 인터넷에서 직접 수집하지 않는다.
    waf = log_lines(args.waf_log)
    app = log_lines(args.app_log)
    if args.output_dir.exists():
        raise ConfigError("correlate 출력 폴더가 이미 있습니다")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    records = []
    origin = state.get("target_origin", "")
    for src in state["results"]:
        row = dict(src)
        if row.get("transport_status") != "OK":
            records.append(row)
            continue
        # request_id가 일치해도 시각·run_id가 충돌하면 신뢰할 수 없다.
        waf_events = [event for event in waf if event_matches_run(event, row)]
        app_events = [event for event in app if event_matches_run(event, row)]
        valid_waf = len(waf_events) == 1 and plausible_event(waf_events[0], row, origin)
        valid_app = len(app_events) == 1 and plausible_event(app_events[0], row, origin)
        needs_waf = row["expected_waf"] != "NOT_APPLICABLE"
        # Duplicated or conflicting evidence must never be treated as a match.
        if len(waf_events) > 1 or len(app_events) > 1 or (waf_events and not valid_waf) or (app_events and not valid_app):
            row.update(waf_verdict="UNKNOWN", app_validity="UNKNOWN",
                       correlation_status="UNRESOLVED", verdict="UNKNOWN")
            records.append(row)
            continue
        action = "UNKNOWN"
        counts = []
        if valid_waf:
            e = waf_events[0]
            if e.get("synthetic_fixture") is True:
                row["evidence_kind"] = "SYNTHETIC_FIXTURE_NOT_REAL_WAF"
            action = str(e.get("action", e.get("waf_action", "UNKNOWN"))).upper()
            counts = extract_count_rule_ids(e)
            row["rule_id"] = e.get("terminatingRuleId", e.get("rule_id"))
            row["waf_action"] = action
            row["count_rule_ids"] = counts
            row["waf_verdict"] = "BLOCK" if action == "BLOCK" else ("ALLOW" if action in {"ALLOW", "COUNT"} else "UNKNOWN")
        # If WAF logs explicitly BLOCK, an app log for the *same request* is conflicting evidence.
        conflict = row["waf_verdict"] == "BLOCK" and bool(app_events)
        app_status = None
        if valid_app:
            ev = app_events[0]
            if ev.get("synthetic_fixture") is True:
                row["evidence_kind"] = "SYNTHETIC_FIXTURE_NOT_REAL_WAF"

            app_status = ev.get("http_status", ev.get("status"))
            row["app_observed"] = True

            row["app_validity"] = (
                "MATCH"
                if (
                    app_status == row["expected_app"]["http_status"]
                    and row["http_expectation_match"]
                )
                else "MISMATCH"
            )

        else:
            # 앱 로그가 확인되지 않은 경우
            row["app_observed"] = False

            if (
                row["waf_verdict"] == "BLOCK"
                and row["expected_waf"] == "BLOCK"
            ):
                # 명시적인 WAF 차단 시험에서는 앱 미도달이 정상
                row["app_validity"] = "NOT_APPLICABLE"
            else:
                # 앱 검증이 필요한 시험에서 로그가 없으면 미확정
                row["app_validity"] = "UNKNOWN"
        # 정상 HTTP 코드보다 WAF/앱 증거의 일관성을 먼저 확인한다.
        # 앱 로그 생략은 명시적인 WAF BLOCK 시험에서만 허용한다.
        expected_block = row["expected_waf"] == "BLOCK"
        actual_block = row["waf_verdict"] == "BLOCK"

        app_evidence_ok = valid_app or (expected_block and actual_block)

        evidence_ok = (
            not conflict
            and (valid_waf or not needs_waf)
            and app_evidence_ok
        )
        waf_match = True
        if needs_waf:
            expected = row["expected_waf"]
            if expected == "COUNT":
                waf_match = (
                    row["waf_verdict"] == "ALLOW"
                    and (bool(counts) or action == "COUNT")
                )
            else:
                waf_match = row["waf_verdict"] == expected
        
        # 유효한 WAF 로그에서 기대 동작과의 불일치가
        # 확정되었다면 앱 로그가 없어도 FAIL로 판정한다.
        confirmed_waf_mismatch = (
            valid_waf
            and needs_waf
            and row["waf_verdict"] in {"ALLOW", "BLOCK"}
            and not waf_match
            and not conflict
        )

        if confirmed_waf_mismatch:
            # WAF 불일치는 확정되었지만,
            # 앱 로그가 없으면 전체 상관분석은 미해결 상태다.
            row["correlation_status"] = (
                "MATCHED" if valid_app else "UNRESOLVED"
            )
            row["verdict"] = "FAIL"

        elif not evidence_ok:
            row["correlation_status"] = "UNRESOLVED"
            row["verdict"] = "UNKNOWN"

            if conflict:
                row["waf_verdict"] = "UNKNOWN"
                row["app_validity"] = "UNKNOWN"

        else:
            row["correlation_status"] = "MATCHED"

            if (
                not waf_match
                or row["http_expectation_match"] is False
                or row["app_validity"] == "MISMATCH"
            ):
                row["verdict"] = "FAIL"

            elif row["app_validity"] in {
                "MATCH", "NOT_APPLICABLE"
            }:
                row["verdict"] = (
                    "PASS"
                    if row.get("verification_mode") == "http_only"
                    else "UNKNOWN"
                )

            else:
                row["verdict"] = "UNKNOWN"

        records.append(row)
    out = {k: v for k, v in state.items() if k not in {"results", "preparation_events"}}
    out["source"] = "correlated_from_local_logs"
    out["correlated_utc"] = utc_now()
    out["source_run_json"] = args.run_json.name
    save_results(args.output_dir, out, records, correlation=True)
    code = get_exit_code(records, incomplete=bool(state.get("stopped_reason")) or bool(state.get("unexecuted_cases")))
    print(f"correlate 결과: {args.output_dir / 'correlated_results.json'} (종료 코드 {code})", file=sys.stderr)
    return code


def extract_count_rule_ids(event: dict) -> list[str]:
    """AWS WAF 최상위·규칙 그룹 내부의 Count 매칭을 수집한다."""
    counts = []

    def collect(rules, group_id=None):
        if not isinstance(rules, list):
            return

        for rule in rules:
            if not isinstance(rule, dict):
                continue

            if rule.get("action") != "COUNT":
                continue

            rule_id = rule.get("ruleId")
            if not isinstance(rule_id, str) or not rule_id:
                continue

            if group_id:
                counts.append(f"{group_id}::{rule_id}")
            else:
                counts.append(rule_id)

    # 1. Web ACL 최상위 Count
    collect(event.get("nonTerminatingMatchingRules"))

    # 2. 규칙 그룹 내부 Count
    groups = event.get("ruleGroupList")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue

            group_id = group.get("ruleGroupId")
            if not isinstance(group_id, str) or not group_id:
                continue

            collect(
                group.get("nonTerminatingMatchingRules"),
                group_id
            )

            # 3. 기존 excludedRules Count 로그 호환
            excluded = group.get("excludedRules")
            if isinstance(excluded, list):
                for rule in excluded:
                    if not isinstance(rule, dict):
                        continue

                    rule_id = rule.get("ruleId")
                    if isinstance(rule_id, str) and rule_id:
                        counts.append(f"{group_id}::{rule_id}")

    # 중복 제거, 발견 순서 유지
    return list(dict.fromkeys(counts))


def create_parser():
    """명령행 인터페이스 run / correlate 옵션 정의."""
    parser = argparse.ArgumentParser(description="Haven 승인된 요청 재현 / WAF·앱 로그 대조 CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    r = commands.add_parser("run", help="승인된 HTTP 케이스를 순차 실행")
    r.add_argument("--target", required=True)
    r.add_argument("--allowlist", required=True, type=Path)
    r.add_argument("--cases", required=True, type=Path)
    r.add_argument("--phase", type=int, choices=[1, 2, 3, 4], default=None, help="지정한 회차의 케이스만 실행 (생략 시 전체)")
    r.add_argument("--fixture-dir", type=Path, default=Path("fixtures"))
    r.add_argument("--output-dir", required=True, type=Path)
    r.add_argument("--timeout", type=float, default=10)
    r.add_argument("--max-requests", type=int, default=100)
    r.add_argument("--rate", type=float, default=1)
    r.add_argument("--max-duration", type=float, default=300)
    r.add_argument("--max-response-bytes", type=int, default=MAX_RESPONSE)
    r.add_argument("--manual-checkpoints", action="store_true", help="계정 상태 변경 등 수동 체크포인트 허용")
    c = commands.add_parser("correlate", help="기존 run 결과에 로컬 JSONL WAF/앱 로그를 연결")
    c.add_argument("--run-json", required=True, type=Path)
    c.add_argument("--waf-log", required=True, type=Path)
    c.add_argument("--app-log", required=True, type=Path)
    c.add_argument("--output-dir", required=True, type=Path)

    return parser


def main(argv=None) -> int:
    """파싱·예외 처리 후 종료 코드를 운영체제에 반환."""
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        return run(args) if args.command == "run" else correlate(args)
    except KeyboardInterrupt:
        print("중단됨: 사용자가 Ctrl+C를 눌렀습니다", file=sys.stderr)
        return 2
    except (ConfigError, ExecutionError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
