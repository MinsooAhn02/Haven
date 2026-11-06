#!/usr/bin/env python3
"""Haven: approved, bounded HTTP request replay and evidence correlation.

Only runs declared cases on an exactly allowlisted origin; no attack generation.
See README_CLI.md for the fixture JSON schema and expected log formats.
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

import requests

ROLES = {"anonymous", "member_a", "member_b", "member_c", "operator"}           # user 역할
METHODS = {"GET", "POST"}                                                       # HTTP 메서드
WAF_EXPECT = {"ALLOW", "BLOCK", "COUNT", "NOT_APPLICABLE"}                      # WAF 예상 동작
REQ_ID_HEADER = "X-Haven-Request-ID"
RUN_ID_HEADER = "X-Haven-Run-ID"
MAX_RESPONSE = 2 * 1024 * 1024                                                  # 응답 최대 크기 2MiB
RESULT_FIELDS = [                                                               # csv 기록 필드
    "run_id", "request_id", "case_id", "timestamp_utc", "elapsed_ms",
    "auth_role", "category", "method", "path", "expected_app", "expected_waf",
    "http_status", "redirect_target", "response_summary", "app_observed",
    "waf_action", "rule_id", "waf_verdict", "app_validity", "transport_status",
    "correlation_status", "evidence_path",
]

# 설정 및 실행 오류 처리
# --------------------------------------------
class ConfigError(Exception):
    pass

class ExecutionError(Exception):
    pass

class TooLargeResponse(ExecutionError):
    pass
# --------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ConfigError(f"JSON 파일을 읽을 수 없습니다: {path.name} ({type(exc).__name__})") from exc


def safe_relative(base: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or "\\" in rel:
        raise ConfigError("fixture 파일 경로는 내부 상대 경로여야 합니다")
    # Reject traversal even if the file has not yet been created.
    if any(part in {"..", ""} for part in Path(rel).parts):
        raise ConfigError("fixture 경로에 상위 폴더 이동이 있습니다")
    root = base.resolve(strict=True)
    candidate = (root / rel).resolve(strict=True)
    if not candidate.is_file() or not candidate.is_relative_to(root):
        raise ConfigError("허용된 fixture 경로 밖이거나 파일이 없습니다")
    return candidate


def canonical_origin(value: str) -> str:
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


def validate_path(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        raise ConfigError("케이스 path는 / 로 시작하는 같은 origin의 상대 경로여야 합니다")
    if re.search(r"[\x00-\x1f\x7f\\#]", path) or len(path) > 4096:
        raise ConfigError("path에 금지된 문자가 있습니다")
    p = urlsplit(path)
    if p.scheme or p.netloc or not p.path.startswith("/"):
        raise ConfigError("origin을 바꾸는 path는 허용하지 않습니다")
    return path


def safe_path_log(path: str) -> str:
    p = urlsplit(path)
    if not p.query:
        return p.path
    keys = [part.split("=", 1)[0][:64] for part in p.query.split("&")][:32]
    return p.path + "?" + "&".join(f"{key}=<redacted>" for key in keys)


def safe_location(raw: str | None) -> str | None:
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
    for name, maximum in (("timeout", 30), ("max_requests", 1000), ("rate", 5),
                          ("max_duration", 900), ("max_response_bytes", MAX_RESPONSE)):
        value = getattr(args, name)
        if not 0 < value <= maximum:
            raise ConfigError(f"{name}은 0 초과, {maximum} 이하여야 합니다")


def validate_suite(suite: object, fixtures: Path):
    if not isinstance(suite, dict) or suite.get("schema_version") != 1 or not isinstance(suite.get("suite_id"), str):
        raise ConfigError("suite에는 schema_version=1 및 suite_id가 필요합니다")
    if not suite["suite_id"].strip() or suite.get("suite_kind") not in {"regression", "confirmation"}:
        raise ConfigError("suite_id / suite_kind가 잘못되었습니다")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ConfigError("cases는 비어 있지 않은 목록이어야 합니다")
    found = set()
    for item in cases:
        required = {"case_id", "category", "method", "path", "auth_role", "input_reference",
                    "expected_app", "expected_waf", "max_requests", "note"}
        if not isinstance(item, dict) or not required.issubset(item):
            raise ConfigError("케이스에 필수 필드가 부족합니다")
        cid = item["case_id"]
        if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", cid) or cid in found:
            raise ConfigError("case_id가 중복되었거나 유효하지 않습니다")
        found.add(cid)
        if item["method"] not in METHODS or item["auth_role"] not in ROLES:
            raise ConfigError(f"{cid}: method/auth_role 오류")
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


def validate_payload(payload: object, root: Path):
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
    if payload.get("origin_mode", "absent") not in {"absent", "same", "foreign"}:
        raise ConfigError("origin_mode 오류 (absent/same/foreign)")
    if "pad_form_body_to" in payload:
        n = payload["pad_form_body_to"]
        if type(n) is not int or not 1 <= n <= 8193 or "file" in payload or "body" not in fields:
            raise ConfigError("pad_form_body_to는 비-multipart 글 body 필드와 함께 1~8193만 가능합니다")
    if set(payload) - {"fields", "file", "csrf_mode", "origin_mode", "pad_form_body_to"}:
        raise ConfigError("지원하지 않는 payload 필드가 있습니다")


def read_payload(root: Path, ref: str) -> dict:
    return load_json(safe_relative(root, ref))


class CsrfHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.value = None

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            d = dict(attrs)
            if d.get("name") == "csrfmiddlewaretoken" and d.get("value"):
                self.value = d["value"]


class RequestBudget:
    def __init__(self, args):
        self.maximum = args.max_requests
        self.rate = args.rate
        self.duration = args.max_duration
        self.timeout = args.timeout
        self.count = 0
        self.started = time.monotonic()
        self.last_request = None

    def begin(self):
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


def new_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # avoid implicit .netrc / environment proxy credentials
    return s


def bounded_send(s: requests.Session, method: str, target: str, path: str, budget: RequestBudget,
                 request_id: str, *, fields=None, file_info=None, headers=None,
                 max_response_bytes=MAX_RESPONSE) -> tuple[dict, bytes | None]:
    url = target + validate_path(path)
    h = {REQ_ID_HEADER: request_id}
    if headers:
        h.update(headers)
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
        with s.send(prepared, allow_redirects=False, timeout=timeout, stream=True, verify=True) as resp:
            total = 0
            digest = hashlib.sha256()
            chunks = []
            content_length = resp.headers.get("Content-Length")
            if content_length and content_length.isdecimal() and int(content_length) > max_response_bytes:
                raise TooLargeResponse("응답 Content-Length가 허용 크기를 초과합니다")
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if time.monotonic() - budget.started > budget.duration:
                    raise ExecutionError("응답을 읽는 중 전체 실행 시간 한도를 초과했습니다")
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_response_bytes:
                    raise TooLargeResponse("실제 응답이 허용 크기를 초과합니다")
                digest.update(chunk)
                # Capture only preparation HTML (never persist); all other content is discarded.
                if path == "/accounts/login/" and total <= 65536:
                    chunks.append(chunk)
            safe_headers = {key: resp.headers[key] for key in (
                "Content-Type", "Content-Disposition", "X-Content-Type-Options", "Cache-Control"
            ) if key in resp.headers}
            detail = {
                "status": resp.status_code, "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
                "location": safe_location(resp.headers.get("Location")), "body_bytes": total,
                "sha256": digest.hexdigest(), "headers": safe_headers,
                "request_body_bytes": len(prepared.body or b"") if isinstance(prepared.body, (str, bytes)) else None,
            }
            return detail, b"".join(chunks) if chunks else None
    except (requests.RequestException, OSError) as exc:
        raise ExecutionError(f"HTTP 요청 실패: {type(exc).__name__}") from exc
    finally:
        if opened is not None:
            opened.close()


def get_csrf_token(s: requests.Session) -> str | None:
    return s.cookies.get("csrftoken")


def prep_login(s: requests.Session, target: str, budget: RequestBudget, role: str,
               run_id: str, prep_events: list, max_response_bytes: int) -> None:
    print(f"[인증 준비] {role}: 가상 시험 계정 정보를 대화형으로 입력하세요", file=sys.stderr)
    username = input(f"  {role} 사용자 이름: ").strip()
    if not username:
        raise ExecutionError("사용자 이름이 비어 있습니다")
    password = getpass.getpass(f"  {role} 비밀번호(화면 미표시): ")
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
    detail, _ = bounded_send(s, "POST", target, "/accounts/login/", budget, rid,
                            fields={"username": username, "password": password, "csrfmiddlewaretoken": csrf},
                            headers={"X-CSRFToken": csrf, RUN_ID_HEADER: run_id}, max_response_bytes=max_response_bytes)
    prep_events.append({"request_id": rid, "stage": "login_submit", "http_status": detail["status"]})
    # No redirect follow. Login POST success is expected to redirect away from login.
    if detail["status"] != 302 or not s.cookies.get("sessionid") or (detail["location"] or "").startswith("/accounts/login/"):
        raise ExecutionError("로그인 인증 준비 실패 (상태/세션 확인)")


def csrf_for_post(s: requests.Session, target: str, budget: RequestBudget,
                  prep_events: list, max_response_bytes: int, mode: str, run_id: str):
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


def check_http_expected(detail: dict, expected: dict) -> bool:
    ok = detail["status"] == expected["http_status"]
    if "redirect_path" in expected:
        # If a local redirect contains a next query, compare only the path.
        ok = ok and urlsplit(detail["location"] or "").path == expected["redirect_path"]
    if "body_bytes" in expected:
        ok = ok and detail["body_bytes"] == expected["body_bytes"]
    if "sha256" in expected:
        ok = ok and detail["sha256"] == expected["sha256"]
    for header, needle in expected.get("headers_contain", {}).items():
        ok = ok and needle.lower() in detail["headers"].get(header, "").lower()
    return bool(ok)


def base_record(run_id: str, case: dict) -> dict:
    return dict(
        run_id=run_id, request_id=str(uuid.uuid4()), case_id=case["case_id"],
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
    if incomplete or any(r["transport_status"] == "ERROR" for r in records):
        return 2
    if any(r["verdict"] == "UNKNOWN" for r in records):
        return 3
    if any(r["verdict"] == "FAIL" for r in records):
        return 1
    return 0


def run(args) -> int:
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
    print(f"대상={target}  suite={suite['suite_id']}  사례={len(suite['cases'])}  ",
          f"timeout={args.timeout}s  요청≤{args.max_requests}  초당≤{args.rate}  시간≤{args.max_duration}s",
          file=sys.stderr)
    if args.output_dir.exists():
        raise ConfigError("출력 폴더가 이미 있습니다. 새 경로를 지정하세요")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    run_id = str(uuid.uuid4())
    budget = RequestBudget(args)
    sessions = {}
    prepped = {}
    prep_events = []
    state = {"schema_version": 1, "run_id": run_id, "suite_id": suite["suite_id"],
             "suite_kind": suite["suite_kind"], "target_origin": target, "started_utc": utc_now(),
             "source": "live_http_run", "stopped_reason": None, "unexecuted_cases": len(suite["cases"]),
             "total_http_requests_including_preparation": 0, "preparation_events": prep_events}
    records = []
    failed = False
    try:
        for case in suite["cases"]:
            record = base_record(run_id, case)
            role = case["auth_role"]
            try:
                if role not in sessions:
                    sessions[role] = new_session()
                sess = sessions[role]
                if role != "anonymous" and not prepped.get(role):
                    prep_login(sess, target, budget, role, run_id, prep_events, args.max_response_bytes)
                    prepped[role] = True
                payload = read_payload(root, case["input_reference"]) if case["input_reference"] else {}
                fields = dict(payload.get("fields", {}))
                headers = {RUN_ID_HEADER: run_id}
                file_info = None
                if case["method"] == "POST":
                    csrf = csrf_for_post(sess, target, budget, prep_events, args.max_response_bytes,
                                         payload.get("csrf_mode", "valid"), run_id)
                    if csrf:
                        fields["csrfmiddlewaretoken"] = csrf
                        headers["X-CSRFToken"] = csrf
                    if payload.get("origin_mode") == "same":
                        headers["Origin"] = target
                    elif payload.get("origin_mode") == "foreign":
                        headers["Origin"] = "https://attacker.invalid"
                    if "pad_form_body_to" in payload:
                        size = payload["pad_form_body_to"]
                        # requests uses application/x-www-form-urlencoded for fields-only POST.
                        body = requests.Request("POST", target + case["path"], data=fields).prepare().body
                        current = len(body.encode("utf-8") if isinstance(body, str) else body)
                        if current > size:
                            raise ExecutionError(f"요청 기본 body 크기 {current}가 목표 {size}바이트보다 큽니다")
                        fields["body"] += "A" * (size - current)
                    if "file" in payload:
                        spec = payload["file"]
                        file_info = {"path": safe_relative(root, spec["local_fixture_path"]),
                                     "filename": spec["filename"], "content_type": spec["content_type"]}
                detail, _ = bounded_send(sess, case["method"], target, case["path"], budget,
                                         record["request_id"], fields=fields if case["method"] == "POST" else None,
                                         file_info=file_info, headers=headers,
                                         max_response_bytes=args.max_response_bytes)
                record.update(http_status=detail["status"], elapsed_ms=detail["elapsed_ms"],
                              redirect_target=detail["location"],
                              response_summary={"request_body_bytes": detail["request_body_bytes"], "body_bytes": detail["body_bytes"], "sha256": detail["sha256"],
                                                "headers": detail["headers"]}, transport_status="OK",
                              http_expectation_match=check_http_expected(detail, case["expected_app"]))
                # No WAF/app log evidence in run: do not invent a pass based on HTTP 403.
                record["verdict"] = "UNKNOWN"
            except (ExecutionError, ConfigError, KeyboardInterrupt) as exc:
                record.update(transport_status="ERROR", verdict="ERROR",
                              response_summary={"error": ("KeyboardInterrupt" if isinstance(exc, KeyboardInterrupt)
                                                          else str(exc))})
                failed = True
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
    if isinstance(event.get("request_id"), str):
        return event["request_id"]
    req = event.get("httpRequest", {})
    if not isinstance(req, dict):
        return None
    for header in req.get("headers", []):
        if isinstance(header, dict) and str(header.get("name", "")).lower() == REQ_ID_HEADER.lower():
            return header.get("value")
    return None


def log_timestamp(event: dict) -> datetime | None:
    val = event.get("timestamp_utc", event.get("timestamp"))
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
    state = load_json(args.run_json)
    if not isinstance(state, dict) or not isinstance(state.get("results"), list) or not state.get("run_id"):
        raise ConfigError("올바른 run results JSON이 아닙니다")
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
        waf_events = [e for e in waf if log_request_id(e) == row["request_id"]]
        app_events = [e for e in app if log_request_id(e) == row["request_id"]]
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
            counts = [x.get("ruleId") for x in e.get("nonTerminatingMatchingRules", []) if isinstance(x, dict) and x.get("action") == "COUNT"]
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
            row["app_validity"] = "MATCH" if (app_status == row["expected_app"]["http_status"] and row["http_expectation_match"]) else "MISMATCH"
        elif row["waf_verdict"] == "BLOCK":
            row["app_observed"] = False
            row["app_validity"] = "NOT_APPLICABLE"
        else:
            row["app_validity"] = "UNKNOWN"
        evidence_ok = not conflict and ((valid_waf or not needs_waf) and (valid_app or row["waf_verdict"] == "BLOCK"))
        waf_match = True
        if needs_waf:
            expected = row["expected_waf"]
            if expected == "COUNT":
                waf_match = bool(counts) or action == "COUNT"
            else:
                waf_match = row["waf_verdict"] == expected
        if not evidence_ok:
            row["correlation_status"] = "UNRESOLVED"
            row["verdict"] = "UNKNOWN"
            if conflict:
                row["waf_verdict"] = "UNKNOWN"
                row["app_validity"] = "UNKNOWN"
        else:
            row["correlation_status"] = "MATCHED"
            if not waf_match or row["http_expectation_match"] is False or row["app_validity"] == "MISMATCH":
                row["verdict"] = "FAIL"
            elif row["app_validity"] in {"MATCH", "NOT_APPLICABLE"}:
                row["verdict"] = ("PASS" if row.get("verification_mode") == "http_only" else "UNKNOWN")
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


def create_parser():
    parser = argparse.ArgumentParser(description="Haven 승인된 요청 재현 / WAF·앱 로그 대조 CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    r = commands.add_parser("run", help="승인된 HTTP 케이스를 순차 실행")
    r.add_argument("--target", required=True)
    r.add_argument("--allowlist", required=True, type=Path)
    r.add_argument("--cases", required=True, type=Path)
    r.add_argument("--fixture-dir", type=Path, default=Path("fixtures"))
    r.add_argument("--output-dir", required=True, type=Path)
    r.add_argument("--timeout", type=float, default=10)
    r.add_argument("--max-requests", type=int, default=100)
    r.add_argument("--rate", type=float, default=1)
    r.add_argument("--max-duration", type=float, default=300)
    r.add_argument("--max-response-bytes", type=int, default=MAX_RESPONSE)
    c = commands.add_parser("correlate", help="기존 run 결과에 로컬 JSONL WAF/앱 로그를 연결")
    c.add_argument("--run-json", required=True, type=Path)
    c.add_argument("--waf-log", required=True, type=Path)
    c.add_argument("--app-log", required=True, type=Path)
    c.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv=None) -> int:
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
