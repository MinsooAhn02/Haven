#!/usr/bin/env python3
"""
run()       → 대상/시험표 검증 → 역할별 세션·CSRF 준비 → 제한된 요청 → JSON/CSV 기록
correlate() → run 결과와 WAF·앱 JSONL 로그를 요청 ID로 결합 → 신뢰도·판정 기록
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
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
import os
import warnings
import requests
import subprocess
from contextvars import ContextVar
from functools import wraps

ROLES = {"anonymous", "member_a", "member_b", "member_c", "operator"}
METHODS = {"GET", "POST"}
WAF_EXPECT = {"ALLOW", "BLOCK", "COUNT", "NOT_APPLICABLE"}
REQ_ID_HEADER = "X-Haven-Request-ID"
RUN_ID_HEADER = "X-Haven-Run-ID"
MAX_RESPONSE = 2 * 1024 * 1024
RESULT_FIELDS = [
    "run_id", "request_id", "trace_id", "case_id", "parent_case_id", "payload_id", "timestamp_utc", "elapsed_ms",
    "auth_role", "category", "method", "path", "expected_app", "expected_waf",
    "http_status", "redirect_target", "response_summary", "app_observed",
    "waf_action", "rule_id", "waf_verdict", "app_validity", "transport_status", "request_attempted",
    "correlation_status", "evidence_path", "execution_stage",
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


def aws_post_marker(run_id: str, case_id: str) -> str:
    """AWS 시험 실행과 생성 케이스를 식별하는 고유 표식."""
    return f"[HAVEN-AWS:{run_id}:{case_id}]"


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


def validate_suite(suite: object, fixtures: Path, *, _cleanup=False):
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
        capture = item.get("capture_post_id", False)

        if type(capture) is not bool:
            raise ConfigError(f"{cid}: capture_post_id 형식 오류")

        post_ref = item.get("post_reference")

        if post_ref is not None:
            allowed_post_path = (
                item["method"] == "GET"
                # 삭제 GET은 확인 화면만 보여 주는 읽기 요청이다.
                and item["path"] in {"/posts/{post_id}/", "/posts/{post_id}/delete/"}
            ) or (
                item["method"] == "POST"
                and re.fullmatch(
                    r"/posts/\{post_id\}/(?:attachments/|delete/|shares/|edit/|shares/\{share_id\}/revoke/)",
                    item["path"],
                ) is not None
            )

            if (
                not isinstance(post_ref, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", post_ref)
                or not allowed_post_path
            ):
                raise ConfigError(f"{cid}: post_reference 설정 오류")

        elif "{post_id}" in item["path"]:
            raise ConfigError(f"{cid}: post_id 참조가 없습니다")
        if "share_recipient_role" in item:
            recipient_role = item["share_recipient_role"]

            if (
                not isinstance(recipient_role, str)
                or recipient_role not in {
                    "member_a", "member_b", "member_c"
                }
                or recipient_role == item["auth_role"]
                or item["method"] != "POST"
                or item["path"] != "/posts/{post_id}/shares/"
                or post_ref is None
                or _cleanup
            ):
                raise ConfigError(
                    f"{cid}: share_recipient_role 설정 오류"
                )

            # 공유 시점에 수신자 계정명을 알려면 수신자가 먼저 로그인해 있어야 한다.
            if not any(
                previous.get("auth_role") == recipient_role
                for previous in cases[:index]
            ):
                raise ConfigError(
                    f"{cid}: 공유 수신자({recipient_role})의 요청이 먼저 필요합니다"
                )
        if "critical" in item and type(item["critical"]) is not bool:
            raise ConfigError(f"{cid}: critical은 bool이어야 합니다")

        if "cleanup_before" in item:
            if type(item["cleanup_before"]) is not bool or _cleanup:
                raise ConfigError(f"{cid}: cleanup_before 설정 오류")
            
        share_ref = item.get("share_reference")
        if share_ref is not None:
            if (not isinstance(share_ref, dict)
                    or not {"post_id", "recipient", "lookup_role"}.issubset(share_ref)
                    or set(share_ref) - {"post_id", "recipient", "lookup_role", "allow_missing"}
                    or type(share_ref["post_id"]) is not int or not 1 <= share_ref["post_id"] <= 2**63 - 1
                    or not isinstance(share_ref["recipient"], str)
                    or share_ref["recipient"] not in {"member_a", "member_b", "member_c"}
                    or not isinstance(share_ref["lookup_role"], str)
                    or share_ref["lookup_role"] not in {"member_a", "member_b", "member_c"}
                    or type(share_ref.get("allow_missing", False)) is not bool):
                raise ConfigError(f"{cid}: share_reference 설정 오류")
            if (item["method"] != "POST"
                    or not re.fullmatch(r"/posts/[1-9]\d*/shares/\{share_id\}/revoke/", item["path"])):
                raise ConfigError(f"{cid}: 동적 공유 ID는 공유 해제 POST 경로에서만 사용할 수 있습니다")
            if share_ref.get("allow_missing") and not _cleanup:
                raise ConfigError(f"{cid}: allow_missing은 cleanup_cases에서만 허용합니다")
        elif (
            "{share_id}" in item["path"]
            and "share_revoke_role" not in item
        ):
            raise ConfigError(
                f"{cid}: 공유 ID 경로에는 공유 대상 참조가 필요합니다"
            )

        lookup_role = item.get("share_lookup_role")

        if lookup_role is not None and (
            "share_revoke_role" not in item
            or not isinstance(lookup_role, str)
            or lookup_role not in {"member_a", "member_b", "member_c"}
            or lookup_role == item.get("share_revoke_role")
        ):
            raise ConfigError(f"{cid}: share_lookup_role 설정 오류")

        if "share_revoke_role" in item:
            revoke_role = item["share_revoke_role"]
            # 공유 ID를 조회할 소유자 역할. 없으면 요청자 본인이 소유자다.
            owner_role = lookup_role or item["auth_role"]

            if (
                not isinstance(revoke_role, str)
                or revoke_role not in {
                    "member_a", "member_b", "member_c"
                }
                or revoke_role == owner_role
                or item["method"] != "POST"
                or item["path"] != (
                    "/posts/{post_id}/shares/{share_id}/revoke/"
                )
                or post_ref is None
                or "share_reference" in item
                or "share_recipient_role" in item
                or _cleanup
            ):
                raise ConfigError(
                    f"{cid}: share_revoke_role 설정 오류"
                )

            # 공유 ID를 찾으려면 소유자와 수신자가 모두 로그인해 있어야 한다.
            earlier_roles = {
                previous.get("auth_role") for previous in cases[:index]
            } | {item["auth_role"]}

            if not {owner_role, revoke_role} <= earlier_roles:
                raise ConfigError(
                    f"{cid}: 공유 해제 전 소유자와 수신자의 요청이 먼저 필요합니다"
                )
        if "after_case" in item and not _cleanup:
            raise ConfigError(f"{cid}: after_case는 cleanup_cases에서만 허용합니다")
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
        if capture and (
            _cleanup
            or item["method"] != "POST"
            or item["path"] != "/posts/new/"
            or item["expected_app"]["http_status"] != 302
        ):
            raise ConfigError(f"{cid}: 게시글 ID 캡처 설정 오류")
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

            if "variants" in payload:
                if _cleanup:
                    raise ConfigError(f"{cid}: cleanup에는 단일 payload가 필요합니다")
                variants = payload["variants"]

                if len(variants) > item["max_requests"]:
                    raise ConfigError(f"{cid}: variants 수가 max_requests를 초과합니다")

                for variant in variants:
                    expanded_id = f"{cid}-{variant['id']}"

                    if len(expanded_id) > 64:
                        raise ConfigError(f"{cid}: 확장된 case_id가 너무 깁니다")

    checkpoints = [
        i for i, case in enumerate(cases)
        if case.get("cleanup_before") is True
    ]
    if len(checkpoints) > 1:
        raise ConfigError("복구 체크포인트는 하나만 지정할 수 있습니다")

    cleanup = suite.get("cleanup_cases", [])
    if not isinstance(cleanup, list) or (_cleanup and cleanup):
        raise ConfigError("cleanup_cases는 중첩되지 않은 목록이어야 합니다")
    if cleanup:
        validate_suite({"schema_version": 1, "suite_id": suite["suite_id"] + "-cleanup",
                        "suite_kind": suite["suite_kind"], "cases": cleanup}, fixtures, _cleanup=True)
        by_id = {case["case_id"]: case for case in cases}
        for case in cleanup:
            source = case.get("after_case")
            if (case["case_id"] in found or not isinstance(source, str) or source not in by_id
                    or case.get("phase") != by_id[source].get("phase")
                    or case["method"] != "POST" or by_id[source]["method"] != "POST"
                    or "checkpoint_before" in case):
                raise ConfigError(f"{case['case_id']}: cleanup after_case/phase/POST 설정 오류")

        if checkpoints:
            positions = {
                case["case_id"]: i
                for i, case in enumerate(cases)
            }
            for cleanup_case in cleanup:
                if positions[cleanup_case["after_case"]] >= checkpoints[0]:
                    raise ConfigError(
                        f"{cleanup_case['case_id']}: 복구 대상은 체크포인트보다 먼저 실행되어야 합니다"
                    )

    if not _cleanup:
        creators = {}
        for case in cases:
            ref = case.get("post_reference")
            if ref is not None:
                source = creators.get(ref)

                if source is None:
                    raise ConfigError(
                        f"{case['case_id']}: 게시글 생성 선행조건 오류"
                    )

                # 소유자가 아닌 계정의 변경 요청은 거부(404)를 확인하는 시험으로만 허용한다.
                if (
                    case["method"] != "GET"
                    and source["auth_role"] != case["auth_role"]
                    and case["expected_app"].get("http_status") != 404
                ):
                    raise ConfigError(
                        f"{case['case_id']}: 게시글 생성 선행조건 오류"
                    )

            if case.get("capture_post_id"):
                creators[case["case_id"]] = case

        for cleanup_case in cleanup:
            ref = cleanup_case.get("post_reference")
            if ref is not None:
                source = creators.get(ref)
                if source is None or source["auth_role"] != cleanup_case["auth_role"]:
                    raise ConfigError(
                        f"{cleanup_case['case_id']}: 복구 게시글 참조 오류"
                    )


def validate_aws_cleanup_suite(suite: dict) -> None:
    """AWS 공유 환경에서 안전하게 정리 가능한 케이스만 허용한다."""
    cases = suite["cases"]
    cleanup_cases = suite.get("cleanup_cases", [])

    creators = {
        case["case_id"]: case
        for case in cases
        if case["method"] == "POST"
        and case["path"] == "/posts/new/"
    }

    allowed_mutations = {
        "/posts/{post_id}/edit/",
        "/posts/{post_id}/shares/",
        "/posts/{post_id}/attachments/",
        "/posts/{post_id}/shares/{share_id}/revoke/",
    }

    for case in cases:
        cid = case["case_id"]

        # 기존 cleanup 실행 구조에서는 중간 복구 이후
        # 생성한 리소스의 마지막 복구가 누락될 수 있다.
        if case.get("cleanup_before") or "checkpoint_before" in case:
            raise ConfigError(
                f"{cid}: AWS 안전 시험에서 수동/중간 체크포인트 금지"
            )

        if case["method"] != "POST":
            continue

        if case["path"] == "/posts/new/":
            if not case.get("capture_post_id"):
                raise ConfigError(
                    f"{cid}: AWS 게시글 생성에는 capture_post_id 필요"
                )
            continue

        # 비로그인 로그인 시도는 데이터를 바꾸지 않는다(로그인 실패 기록만 남는다).
        if case["auth_role"] == "anonymous" and case["path"] == "/accounts/login/":
            continue

        # 소유자가 아닌 계정의 삭제 시도는 거부(404)를 확인하는 시험으로만 허용한다.
        ref = case.get("post_reference")
        is_delete_denial = (
            case["path"] == "/posts/{post_id}/delete/"
            and ref in creators
            and case["auth_role"] != creators[ref]["auth_role"]
            and case["expected_app"].get("http_status") == 404
        )

        # 기존 글의 변경이나 시험 계정 상태 변경을 차단한다.
        if not is_delete_denial and (
            case["path"] not in allowed_mutations
            or ref not in creators
        ):
            raise ConfigError(
                f"{cid}: AWS에서는 시험 중 생성한 게시글만 변경 가능"
            )

    cleanup_counts = {cid: 0 for cid in creators}

    for case in cleanup_cases:
        ref = case.get("post_reference")

        if (
            ref not in creators
            or case["path"] != "/posts/{post_id}/delete/"
            or case.get("after_case") != ref
            or case["auth_role"] != creators[ref]["auth_role"]
        ):
            raise ConfigError(
                f"{case['case_id']}: AWS 복구 대상 설정 오류"
            )

        cleanup_counts[ref] += 1

    for cid, count in cleanup_counts.items():
        if count != 1:
            raise ConfigError(
                f"{cid}: 게시글 생성마다 삭제 복구 케이스가 정확히 1개 필요"
            )


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

    result = {**suite, "cases": selected}
    if "cleanup_cases" in suite:
        result["cleanup_cases"] = [case for case in suite["cleanup_cases"] if case.get("phase") == phase]
    return result


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

    if "variants" in payload:
        if set(payload) != {"variants"}:
            raise ConfigError("다중 payload에는 variants만 허용합니다")

        variants = payload["variants"]
        if not isinstance(variants, list) or not 1 <= len(variants) <= 16:
            raise ConfigError("variants는 1~16개여야 합니다")

        seen = set()

        for variant in variants:
            if not isinstance(variant, dict) or set(variant) != {"id", "payload"}:
                raise ConfigError("variant에는 id와 payload가 필요합니다")

            variant_id = variant["id"]

            if not isinstance(variant_id, str) or not re.fullmatch(r"P\d{2}", variant_id):
                raise ConfigError("variant id는 P01 형식이어야 합니다")

            if variant_id in seen:
                raise ConfigError(f"중복 variant id: {variant_id}")

            seen.add(variant_id)

            item = variant["payload"]

            if not isinstance(item, dict) or "variants" in item:
                raise ConfigError("중첩 variants는 허용하지 않습니다")

            # 기존 단일 payload 검증 로직 재사용
            validate_payload(item, root)

        return

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


def expand_suite_variants(suite: dict, fixtures: Path) -> dict:
    """다중 payload 케이스를 요청별 실행 단위로 확장한다.

    - 기존 단일 payload 케이스는 그대로 유지한다.
    - 다중 payload 케이스는 case_id-P01 형태로 확장한다.
    - 원본 suite와 case 객체는 변경하지 않는다.
    - 네트워크 요청은 수행하지 않는다.
    """
    original_ids = {case["case_id"] for case in suite["cases"]}
    used_ids = set()
    expanded = []

    for case in suite["cases"]:
        ref = case["input_reference"]

        if ref is None:
            payload = None
        else:
            payload = read_payload(fixtures, ref)

        # 기존 단일 payload 또는 GET 케이스
        if payload is None or "variants" not in payload:
            expanded.append(dict(case))
            used_ids.add(case["case_id"])
            continue

        # 다중 payload 케이스
        for variant in payload["variants"]:
            expanded_id = f"{case['case_id']}-{variant['id']}"

            # 기존 케이스 및 확장 케이스와의 ID 충돌 방지
            if expanded_id in original_ids or expanded_id in used_ids:
                raise ConfigError(
                    f"확장 case_id 중복: {expanded_id}"
                )

            child = {
                **case,
                "case_id": expanded_id,
                "parent_case_id": case["case_id"],
                "payload_id": variant["id"],
                "_variant_payload": variant["payload"],
                "max_requests": 1,
            }

            expanded.append(child)
            used_ids.add(expanded_id)

    return {
        **suite,
        "cases": expanded,
    }


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


class ShareHtmlParser(HTMLParser):
    """소유자 공유 목록의 같은 li 안에서 사용자명과 해제 경로를 연결한다."""

    def __init__(self, post_id: int, recipient: str):
        super().__init__(convert_charrefs=True)
        self.post_id = post_id
        self.recipient = recipient
        self.rows = []
        self.open_rows = []
        self.has_share_list = False
        self.nav_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "nav":
            self.nav_depth += 1
            return
        if self.nav_depth:
            return
        attributes = dict(attrs)
        if ((tag == "h2" and attributes.get("id") == "share-list-heading")
                or (tag == "section" and attributes.get("aria-labelledby") == "share-list-heading")):
            self.has_share_list = True
        if tag == "li":
            self.open_rows.append({"names": [], "actions": [], "title": None})
        elif self.open_rows:
            row = self.open_rows[-1]
            if tag == "h3" and "record-title" in (attributes.get("class") or "").split():
                if row["title"] is not None:
                    raise ConfigError("공유 목록의 사용자명 구조가 모호합니다")
                row["title"] = []
            elif tag == "form":
                row["actions"].append(((attributes.get("method") or "get").lower(), attributes.get("action") or ""))

    def handle_data(self, data):
        if self.open_rows and self.open_rows[-1]["title"] is not None:
            self.open_rows[-1]["title"].append(data)

    def handle_endtag(self, tag):
        if tag == "nav":
            if self.nav_depth:
                self.nav_depth -= 1
            return
        if self.nav_depth:
            return
        if not self.open_rows:
            return
        row = self.open_rows[-1]
        if tag == "h3" and row["title"] is not None:
            row["names"].append("".join(row["title"]).strip())
            row["title"] = None
        elif tag == "li":
            self.rows.append(self.open_rows.pop())

    def share_id(self) -> int | None:
        if self.open_rows:
            raise ConfigError("공유 목록 HTML이 완결되지 않았습니다")
        matches = []
        for row in self.rows:
            if self.recipient not in row["names"]:
                continue
            if row["names"] != [self.recipient] or len(row["actions"]) != 1:
                raise ConfigError("공유 대상의 해제 경로가 중복되거나 모호합니다")
            method, action = row["actions"][0]
            pattern = rf"/posts/{self.post_id}/shares/([1-9]\d{{0,18}})/revoke/"
            match = re.fullmatch(pattern, action)
            if method != "post" or match is None:
                raise ConfigError("공유 대상의 해제 경로가 같은 글의 안전한 POST 경로가 아닙니다")
            share_id = int(match.group(1))
            if share_id > 2**63 - 1:
                raise ConfigError("공유 ID가 BigAutoField 범위를 초과합니다")
            matches.append(share_id)
        if len(matches) > 1:
            raise ConfigError("공유 대상 관계가 여러 개여서 ID를 결정할 수 없습니다")
        if not matches and not self.has_share_list:
            raise ConfigError("공유 목록 영역을 확인하지 못해 관계 부재를 판정할 수 없습니다")
        return matches[0] if matches else None


def parse_share_id(html: bytes, post_id: int, recipient: str) -> int | None:
    """제한된 HTML만 메모리에서 검사하며 원문·CSRF 토큰을 기록하지 않는다."""
    if not isinstance(html, bytes) or len(html) > 65536:
        raise ConfigError("공유 목록 HTML의 형식 또는 크기가 잘못되었습니다")
    parser = ShareHtmlParser(post_id, recipient)
    try:
        parser.feed(html.decode("utf-8"))
        parser.close()
    except UnicodeError as exc:
        raise ConfigError("공유 목록이 UTF-8 HTML이 아닙니다") from exc
    return parser.share_id()


class AwsPostListParser(HTMLParser):
    """시험 계정의 게시글 목록에서 제목과 상세 URL을 추출한다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.current = None
        self.in_title = False
        self.title_parts = []
        self.in_page_count = False
        self.page_parts = []
        self.page_count = None
        self.has_list = False
        self.has_empty = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        classes = set((d.get("class") or "").split())

        if tag == "ul" and "record-list" in classes:
            self.has_list = True

        if tag == "section" and "empty-state" in classes:
            self.has_empty = True

        if tag == "li" and "record-row" in classes:
            if self.current is not None:
                raise ConfigError("게시글 목록 구조가 모호합니다")
            self.current = {"title": None, "href": None}

        elif self.current is not None:
            if tag == "h2" and "record-title" in classes:
                if self.in_title or self.current["title"] is not None:
                    raise ConfigError("게시글 제목이 중복되었습니다")
                self.in_title = True
                self.title_parts = []

            elif tag == "a" and "record-link" in classes:
                if self.current["href"] is not None:
                    raise ConfigError("게시글 링크가 중복되었습니다")
                self.current["href"] = d.get("href")

        if tag == "span" and "page-count" in classes:
            self.in_page_count = True
            self.page_parts = []

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if self.in_page_count:
            self.page_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "h2" and self.in_title:
            self.current["title"] = "".join(self.title_parts).strip()
            self.in_title = False

        elif tag == "li" and self.current is not None:
            if self.in_title:
                raise ConfigError("게시글 제목이 완결되지 않았습니다")
            self.rows.append(self.current)
            self.current = None

        elif tag == "span" and self.in_page_count:
            self.page_count = "".join(self.page_parts).strip()
            self.in_page_count = False


def parse_aws_post_page(html: bytes, expected_page: int):
    """게시글 목록 HTML을 검증하고 (제목, ID), 전체 페이지 수를 반환한다."""
    if not isinstance(html, bytes) or len(html) > 65536:
        raise ConfigError("게시글 목록 HTML 크기 또는 형식 오류")

    parser = AwsPostListParser()

    try:
        parser.feed(html.decode("utf-8"))
        parser.close()
    except UnicodeError as exc:
        raise ConfigError("게시글 목록 UTF-8 오류") from exc

    if parser.current is not None or parser.in_title:
        raise ConfigError("게시글 목록 HTML이 완결되지 않았습니다")

    if parser.has_empty and not parser.has_list:
        return [], 1

    if not parser.has_list or parser.page_count is None:
        raise ConfigError("게시글 목록 또는 페이지 정보를 확인하지 못했습니다")

    match = re.fullmatch(
        r"(\d+)\s*/\s*(\d+)\s*페이지",
        parser.page_count,
    )

    if match is None:
        raise ConfigError("페이지 번호 형식 오류")

    current_page, total_pages = map(int, match.groups())

    if current_page != expected_page or total_pages < current_page:
        raise ConfigError("게시글 목록 페이지 번호 불일치")

    rows = []

    for row in parser.rows:
        match = re.fullmatch(
            r"/posts/([1-9]\d{0,18})/",
            row["href"] or "",
        )

        if row["title"] is None or match is None:
            raise ConfigError("게시글 제목 또는 상세 경로 오류")

        post_id = int(match.group(1))

        if post_id > 2**63 - 1:
            raise ConfigError("게시글 ID 범위 초과")

        rows.append((row["title"], post_id))

    return rows, total_pages


def find_aws_post_by_marker(
    session, target, budget, run_id, marker
) -> int | None:
    """시험 계정이 소유한 게시글에서 고유 표식과 일치하는 ID를 찾는다."""

    found_ids = []

    # 전용 시험 계정의 목록만 조회한다.
    # 최대 25페이지까지만 허용하고, 초과하면 임의로 판단하지 않는다.
    for page in range(1, 26):
        path = "/posts/" if page == 1 else f"/posts/?page={page}"

        detail, html = bounded_send(
            session,
            "GET",
            target,
            path,
            budget,
            str(uuid.uuid4()),
            headers={RUN_ID_HEADER: run_id},
            trace_id=new_trace_id(),
            max_response_bytes=65536,
            capture_html=True,
        )

        if detail["status"] != 200 or html is None:
            raise ExecutionError(
                "AWS 시험 게시글 목록 조회 실패"
            )

        rows, total_pages = parse_aws_post_page(html, page)

        for title, post_id in rows:
            if title.startswith(marker + " "):
                found_ids.append(post_id)

        if page >= total_pages:
            break
    else:
        raise ExecutionError(
            "게시글 목록이 25페이지를 초과하여 자동 식별을 중단합니다"
        )

    if len(found_ids) > 1:
        raise ExecutionError(
            "동일 실행 표식의 게시글이 여러 개입니다. 수동 확인 필요"
        )

    return found_ids[0] if found_ids else None


class AdminAccountHtmlParser(HTMLParser):
    """계정 목록에서 사용자명, 상태, 변경 경로, 페이지를 읽는다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.capture = None
        self.parts = []
        self.page_parts = None
        self.pages = []
        self.has_list = False
        self.has_empty = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "h2" and attrs.get("id") == "accounts-heading":
            self.has_list = True

        if (
            tag == "section"
            and "empty-state" in (attrs.get("class") or "").split()
        ):
            self.has_empty = True

        if tag == "span" and attrs.get("aria-current") == "page":
            if self.page_parts is not None:
                raise ConfigError("계정 목록 페이지 구조 오류")
            self.page_parts = []

        if tag == "tr":
            if self.row is not None:
                raise ConfigError("계정 목록 행 중첩 오류")
            self.row = {
                "names": [],
                "cells": [],
                "actions": [],
                "next_states": [],
            }

        elif self.row is not None:
            if tag == "th" and attrs.get("scope") == "row":
                self.capture = "names"
                self.parts = []
            elif tag == "td":
                self.capture = "cells"
                self.parts = []
            elif tag == "form":
                self.row["actions"].append((
                    attrs.get("method", "get").lower(),
                    attrs.get("action", ""),
                ))
            elif tag == "input" and attrs.get("name") == "is_active":
                self.row["next_states"].append(attrs.get("value"))

    def handle_data(self, data):
        if self.capture is not None:
            self.parts.append(data)
        if self.page_parts is not None:
            self.page_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "span" and self.page_parts is not None:
            self.pages.append("".join(self.page_parts).strip())
            self.page_parts = None

        if self.row is None:
            return

        if (
            (tag == "th" and self.capture == "names")
            or (tag == "td" and self.capture == "cells")
        ):
            self.row[self.capture].append(
                "".join(self.parts).strip()
            )
            self.capture = None
            self.parts = []

        elif tag == "tr":
            if self.capture is not None:
                raise ConfigError("계정 목록 셀이 완결되지 않았습니다")

            # 표 머리글 행은 제외한다.
            if self.row["names"]:
                self.rows.append(self.row)
            elif self.row["cells"] or self.row["actions"]:
                raise ConfigError("사용자명을 확인할 수 없는 계정 행입니다")

            self.row = None


def parse_admin_account_page(html, expected_page):
    """계정 목록 한 페이지를 (계정 목록, 전체 페이지 수)로 반환한다."""
    if (
        not isinstance(html, bytes)
        or len(html) > 65536
        or type(expected_page) is not int
        or expected_page < 1
    ):
        raise ConfigError("계정 목록 입력 형식 오류")

    parser = AdminAccountHtmlParser()

    try:
        parser.feed(html.decode("utf-8"))
        parser.close()
    except UnicodeError as exc:
        raise ConfigError("계정 목록 UTF-8 오류") from exc

    if (
        parser.row is not None
        or parser.capture is not None
        or parser.page_parts is not None
        or len(parser.pages) != 1
    ):
        raise ConfigError("계정 목록 HTML 구조 오류")

    match = re.fullmatch(
        r"(\d+)\s*/\s*(\d+)\s*페이지",
        parser.pages[0],
    )
    if match is None:
        raise ConfigError("계정 목록 페이지 형식 오류")

    current_page, total_pages = map(int, match.groups())

    if current_page != expected_page or total_pages < current_page:
        raise ConfigError("계정 목록 페이지 번호 불일치")

    if not parser.rows:
        if not parser.has_empty:
            raise ConfigError("빈 계정 목록을 확인하지 못했습니다")
        return [], total_pages

    if not parser.has_list or parser.has_empty:
        raise ConfigError("계정 목록 영역이 없거나 모호합니다")

    accounts = []
    seen_names = set()
    seen_ids = set()

    for row in parser.rows:
        if (
            len(row["names"]) != 1
            or not row["names"][0]
            or len(row["cells"]) != 4
            or len(row["actions"]) != 1
            or len(row["next_states"]) != 1
        ):
            raise ConfigError("계정 행의 필수 정보가 없거나 중복되었습니다")

        username = row["names"][0]
        status = row["cells"][0]
        method, action = row["actions"][0]

        match = re.fullmatch(
            r"/admin/accounts/([1-9]\d{0,18})/status/",
            action,
        )
        if method != "post" or match is None:
            raise ConfigError("계정 상태 변경 경로 오류")

        account_id = int(match.group(1))
        if account_id > 2**63 - 1:
            raise ConfigError("계정 ID 범위 초과")

        if status not in {"활성", "비활성"}:
            raise ConfigError("계정 활성 상태를 확인하지 못했습니다")

        is_active = status == "활성"
        expected_next = "false" if is_active else "true"

        if row["next_states"][0] != expected_next:
            raise ConfigError("계정 상태 표시와 변경 값이 모순됩니다")

        if username in seen_names or account_id in seen_ids:
            raise ConfigError("계정 목록에 중복된 계정이 있습니다")

        seen_names.add(username)
        seen_ids.add(account_id)
        accounts.append({
            "username": username,
            "account_id": account_id,
            "is_active": is_active,
        })

    return accounts, total_pages


def find_admin_account(
    session, target, budget, run_id,
    username, prep_events, max_response_bytes,
):
    """관리자 세션으로 전체 목록을 확인해 계정명과 정확히 일치하는 계정을 찾는다."""
    if (
        not isinstance(username, str)
        or not username
        or username.strip() != username
    ):
        raise ConfigError("조회할 계정명 형식 오류")

    found = None
    expected_total = None
    seen_names = set()
    seen_ids = set()

    for page in range(1, 26):
        path = (
            "/admin/accounts/"
            if page == 1
            else f"/admin/accounts/?page={page}"
        )
        request_id = str(uuid.uuid4())
        trace_id = new_trace_id()

        detail, html = bounded_send(
            session,
            "GET",
            target,
            path,
            budget,
            request_id,
            headers={RUN_ID_HEADER: run_id},
            trace_id=trace_id,
            max_response_bytes=min(max_response_bytes, 65536),
            capture_html=True,
        )

        prep_events.append({
            "stage": "admin_account_lookup",
            "page": page,
            "http_status": detail["status"],
            "request_id": request_id,
            "trace_id": trace_id,
        })

        if detail["status"] != 200 or html is None:
            raise ExecutionError(
                "관리자 계정 목록 조회 실패"
            )

        accounts, total_pages = parse_admin_account_page(
            html, page
        )

        if total_pages > 25:
            raise ExecutionError(
                "계정 목록이 25페이지를 초과합니다"
            )

        if expected_total is None:
            expected_total = total_pages
        elif total_pages != expected_total:
            raise ExecutionError(
                "조회 중 계정 목록 페이지 수가 변경되었습니다"
            )

        for account in accounts:
            name = account["username"]
            account_id = account["account_id"]

            if name in seen_names or account_id in seen_ids:
                raise ExecutionError(
                    "페이지 간 계정 중복으로 조회 결과를 확정할 수 없습니다"
                )

            seen_names.add(name)
            seen_ids.add(account_id)

            # 부분 일치나 역할명 추측을 사용하지 않는다.
            if name == username:
                found = dict(account)

        if page == total_pages:
            break

    if found is None:
        raise ExecutionError(
            "관리자 목록에서 시험 계정을 찾지 못했습니다"
        )

    return found


class RequestBudget:
    """로그인/CSRF 준비 포함 전체 요청 수·속도·시간 예산 관리."""
    def __init__(self, args):
        """CLI 한도 옵션을 복사하고 실행 시작 시각 기록."""
        self.maximum = args.max_requests
        self.rate = args.rate
        self.duration = args.max_duration
        self.timeout = args.timeout
        self.count = 0
        self.responses_received = 0
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
                 max_response_bytes=MAX_RESPONSE, read_redirect_body=False, trace_id=None, on_send=None,
                 capture_html=False) -> tuple[dict, bytes | None]:
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
            budget.responses_received += 1
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

                    # 로그인/공유 ID 조회 HTML만 제한된 크기로 메모리에 보관한다.
                    if capture_html and total > 65536:
                        raise TooLargeResponse("공유 목록 HTML이 65536바이트를 초과합니다")
                    if (capture_html or path == "/accounts/login/") and total <= 65536:
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


_MEMBER_PASSWORDS = ContextVar("haven_member_passwords", default=None)


def member_password_scope(func):
    """실행마다 별도의 비밀번호 보관 영역을 만들고 종료 시 비운다."""
    @wraps(func)
    def wrapped(*args, **kwargs):
        cache = {}
        token = _MEMBER_PASSWORDS.set(cache)
        try:
            return func(*args, **kwargs)
        finally:
            cache.clear()
            _MEMBER_PASSWORDS.reset(token)

    return wrapped


def aws_member_password():
    """AWS 테스트 회원 세 계정의 공통 비밀번호를 한 번 입력받는다."""
    cache = _MEMBER_PASSWORDS.get()

    if cache is not None and "password" in cache:
        return cache["password"]

    try:
        password = getpass.getpass(
            "AWS member_a/member_b/member_c 공통 비밀번호: "
        )
    except EOFError as exc:
        raise ExecutionError(
            "공통 비밀번호 입력을 받을 수 없습니다"
        ) from exc

    if not password:
        raise ExecutionError("공통 비밀번호가 비어 있습니다")

    if cache is not None:
        cache["password"] = password

    return password


def prep_login(s: requests.Session, target: str, budget: RequestBudget, role: str,
               run_id: str, prep_events: list, max_response_bytes: int) -> None:
    """역할별 시험 계정으로 로그인한다. 비밀번호는 대화형 입력하고 기록 금지."""
    # 재로그인 실패 시 이전 인증 정보가 남지 않도록 제거한다.
    s.__dict__.pop("_haven_username", None)
    local_test_account = (
        target == "http://127.0.0.1:8000"
        and role in {"member_a", "member_b", "member_c", "operator"}
    )
    seed_password = (
        os.environ.get("HAVEN_SEED_PASSWORD")
        if local_test_account else None
    )

    if (
        target == canonical_origin("https://orchestration-haven.cloud")
        and role in {"member_a", "member_b", "member_c"}
    ):
        username = role
        password = aws_member_password()
        print(f"[인증 준비] {role}: 고정 시험 계정 로그인")
    elif seed_password:
        username = role
        password = seed_password
        print(f"[인증 준비] {role}: 로컬 시험 계정 자동 로그인")
    else:
        print(f"[인증 준비] {role}: 계정 정보를 입력하세요")

        try:
            username = input(f"  {role} 사용자 이름: ").strip()
        except EOFError as exc:
            raise ExecutionError("사용자 이름 입력을 받을 수 없습니다") from exc

        if not username:
            raise ExecutionError("사용자 이름이 비어 있습니다")

        try:
            password = getpass.getpass(f"  {role} 비밀번호: ")
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

    # 성공한 로그인에 사용한 계정명만 메모리에 유지한다.
    # 공유 대상 및 시험 계정 식별에 사용하며 비밀번호는 저장하지 않는다.
    s._haven_username = username


def resolve_share_id(case: dict, sessions: dict, prepped: dict, target: str,
                     budget: RequestBudget, run_id: str, prep_events: list,
                     max_response_bytes: int) -> int | None:
    """현재 소유자 목록에서 관계 ID를 얻는다. 거부 시험의 B/C 세션은 변경하지 않는다."""
    reference = case["share_reference"]
    role = reference["lookup_role"]
    if role not in sessions:
        sessions[role] = new_session()
    owner_session = sessions[role]
    if not prepped.get(role):
        prep_login(owner_session, target, budget, role, run_id, prep_events, max_response_bytes)
        prepped[role] = True
    rid = str(uuid.uuid4())
    detail, html = bounded_send(
        owner_session, "GET", target, f"/posts/{reference['post_id']}/shares/", budget, rid,
        headers={RUN_ID_HEADER: run_id}, max_response_bytes=min(max_response_bytes, 65536),
        capture_html=True,
    )
    prep_events.append({"request_id": rid, "stage": "share_lookup", "http_status": detail["status"],
                        "post_id": reference["post_id"], "lookup_role": role})
    if detail["status"] != 200 or html is None:
        raise ExecutionError("소유자의 공유 목록을 HTTP 200 HTML로 확인하지 못했습니다")
    share_id = parse_share_id(html, reference["post_id"], reference["recipient"])
    if share_id is None and not reference.get("allow_missing", False):
        raise ExecutionError("공유 대상 관계가 없어 해제 경로를 결정할 수 없습니다")
    return share_id


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


def bind_share_recipient(case, fields, sessions, prepped):
    """공유 대상 역할을 로그인에 성공한 실제 계정명으로 변환한다."""
    role = case.get("share_recipient_role")

    if role is None:
        return fields

    recipient_session = sessions.get(role)
    owner_session = sessions.get(case["auth_role"])

    recipient = getattr(
        recipient_session, "_haven_username", None
    )
    owner = getattr(
        owner_session, "_haven_username", None
    )

    if (
        not prepped.get(role)
        or not prepped.get(case["auth_role"])
        or not isinstance(recipient, str)
        or not recipient.strip()
        or not isinstance(owner, str)
        or not owner.strip()
    ):
        raise ExecutionError(
            "공유 전 소유자와 수신자 로그인이 필요합니다"
        )

    if recipient == owner:
        raise ExecutionError(
            "소유자와 공유 수신자가 동일한 계정입니다"
        )

    if not isinstance(fields, dict):
        raise ConfigError("공유 요청 fields 형식 오류")

    resolved = dict(fields)
    resolved["username"] = recipient
    return resolved


def resolve_created_share_id(
    post_id, owner_role, recipient_role,
    sessions, prepped, target, budget,
    run_id, prep_events, max_response_bytes,
    *, allow_missing=False,
):
    """실제로 생성한 게시글에서 로그인한 수신자의 공유 ID를 찾는다."""
    if type(allow_missing) is not bool:
        raise ConfigError("allow_missing은 bool이어야 합니다")

    if type(post_id) is not int or not 1 <= post_id <= 2**63 - 1:
        raise ConfigError("공유 조회 게시글 ID 오류")

    member_roles = {"member_a", "member_b", "member_c"}

    if (
        not isinstance(owner_role, str)
        or owner_role not in member_roles
        or not isinstance(recipient_role, str)
        or recipient_role not in member_roles
        or owner_role == recipient_role
    ):
        raise ConfigError("공유 조회 계정 역할 오류")

    # 로그인 완료 여부, 실제 계정명, 동일 계정 여부를 함께 확인한다.
    fields = bind_share_recipient(
        {
            "auth_role": owner_role,
            "share_recipient_role": recipient_role,
        },
        {},
        sessions,
        prepped,
    )

    # 기존 조회 함수를 재사용하되 실제 게시글 ID와 계정명을 전달한다.
    lookup_case = {
        "share_reference": {
            "post_id": post_id,
            "recipient": fields["username"],
            "lookup_role": owner_role,
            "allow_missing": allow_missing,
        }
    }

    return resolve_share_id(
        lookup_case,
        sessions,
        prepped,
        target,
        budget,
        run_id,
        prep_events,
        max_response_bytes,
    )


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

    # 다중 페이로드로 확장된 케이스는 선택된 payload를 사용한다.
    # 기존 단일 페이로드 케이스는 input_reference 파일을 그대로 읽는다.
    if "_variant_payload" in case:
        payload = case["_variant_payload"]
    else:
        payload = read_payload(fixture_root, case["input_reference"])

    fields = dict(payload.get("fields", {}))

    # AWS에서 생성하는 시험용 게시글에 실행 고유 표식 추가.
    if (
        target == canonical_origin("https://orchestration-haven.cloud")
        and case.get("capture_post_id")
        and case["path"] == "/posts/new/"
    ):
        marker = aws_post_marker(run_id, case["case_id"])
        title = fields.get("title")

        if not isinstance(title, str) or not title.strip():
            raise ConfigError(
                "AWS 시험용 게시글에는 유효한 제목이 필요합니다"
            )

        new_title = f"{marker} {title}"

        if len(new_title) > 200:
            raise ConfigError(
                "AWS 시험용 게시글 제목이 200자를 초과합니다"
            )

        fields["title"] = new_title

    # AWS에서 시험 게시글을 수정할 때도 생성 표식을 제목 앞에 유지한다.
    # 표식이 사라지면 정리 단계가 이 게시글을 찾지 못한다.
    if (
        target == canonical_origin("https://orchestration-haven.cloud")
        and case.get("post_reference")
        and re.fullmatch(r"/posts/[1-9]\d*/edit/", case["path"])
        and "title" in fields
    ):
        marker = aws_post_marker(run_id, case["post_reference"])
        title = fields["title"]

        if not isinstance(title, str):
            raise ConfigError("AWS 시험 게시글 수정 제목 형식 오류")

        new_title = f"{marker} {title}"

        if len(new_title) > 200:
            raise ConfigError(
                "AWS 시험용 게시글 제목이 200자를 초과합니다"
            )

        fields["title"] = new_title

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


def extract_created_post_id(location: str | None, target: str) -> int:
    """신규 글 생성 응답의 Location에서 게시글 ID를 안전하게 추출한다."""
    path = same_origin_redirect_path(location, target)

    match = re.fullmatch(r"/posts/([1-9]\d{0,18})/", path or "")
    if match is None:
        raise ExecutionError("신규 글 생성 Location에서 게시글 ID를 확인하지 못했습니다")

    post_id = int(match.group(1))
    if post_id > 2**63 - 1:
        raise ExecutionError("게시글 ID가 허용 범위를 초과했습니다")

    return post_id


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
        parent_case_id=case.get("parent_case_id"), payload_id=case.get("payload_id"),
        timestamp_utc=utc_now(), elapsed_ms=None, auth_role=case["auth_role"],
        category=case["category"], method=case["method"], path=safe_path_log(case["path"]),
        expected_app=case["expected_app"], expected_waf=case["expected_waf"],
        http_status=None, redirect_target=None, response_summary=None, app_observed=None,
        waf_action=None, rule_id=None, waf_verdict="UNKNOWN", app_validity="UNKNOWN",
        transport_status="PENDING", request_attempted=False, correlation_status="PENDING_LOG", evidence_path=None,
        http_expectation_match=None, verdict="UNKNOWN",
        verification_mode=case.get("verification_mode", "manual_required"),
        manual_validation="REQUIRED" if case.get("verification_mode", "manual_required") == "manual_required" else "NOT_REQUIRED",
        execution_stage="test",
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
        w = csv.DictWriter(
            fh,
            fieldnames=RESULT_FIELDS + ["count_rule_ids", "http_expectation_match", "verdict"],
            extrasaction="ignore",
        )
        w.writeheader()
        for record in (
            records
            + state.get("cleanup_results", [])
            + state.get("cleanup_verification_results", [])
        ):
            row = {**record}
            row["expected_app"] = json.dumps(row["expected_app"], ensure_ascii=False)
            row["response_summary"] = json.dumps(row["response_summary"], ensure_ascii=False)
            # WAF Count 매칭 규칙은 상관분석 뒤에만 있으므로, 없으면 빈 칸으로 둔다.
            row["count_rule_ids"] = ";".join(row.get("count_rule_ids") or [])
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


def build_aws_recovery_plan(state: dict, suite: dict) -> list[dict]:
    """중단된 AWS 시험 결과에서 안전한 게시글 복구 계획을 만든다."""
    target = canonical_origin("https://orchestration-haven.cloud")

    if (
        not isinstance(state, dict)
        or state.get("schema_version") != 1
        or state.get("source") != "live_http_run"
        or state.get("target_origin") != target
        or state.get("suite_id") != suite.get("suite_id")
    ):
        raise ConfigError("AWS 복구 결과 파일의 출처가 올바르지 않습니다")

    run_id = state.get("run_id")

    try:
        if not isinstance(run_id, str):
            raise ValueError("run_id")
        if str(uuid.UUID(run_id)) != run_id:
            raise ValueError("run_id")
    except ValueError as exc:
        raise ConfigError("AWS 복구 run_id 형식 오류") from exc

    validate_aws_cleanup_suite(suite)

    if state.get("cleanup_complete") is True:
        return []

    creators = {
        case["case_id"]: case
        for case in suite["cases"]
        if case.get("capture_post_id")
    }

    cleanup_by_source = {
        case["post_reference"]: case
        for case in suite.get("cleanup_cases", [])
    }

    results = state.get("results")

    if not isinstance(results, list):
        raise ConfigError("복구 결과에 results 목록이 없습니다")

    completed = set()

    for record in state.get("cleanup_results", []):
        verification = (
            (record.get("response_summary") or {})
            .get("verification", {})
        )

        if (
            record.get("http_expectation_match") is True
            and verification.get("post_inaccessible") is True
        ):
            completed.add(record.get("after_case"))

    plan = []
    seen = set()

    for record in results:
        cid = record.get("case_id")

        if cid not in creators:
            continue

        if cid in seen:
            raise ConfigError("복구 대상 생성 케이스가 중복되었습니다")
        seen.add(cid)

        marker = record.get("post_marker")

        if marker is None:
            if record.get("request_attempted"):
                raise ConfigError(
                    f"{cid}: 전송된 게시글의 복구 표식이 없습니다"
                )
            continue

        if marker != aws_post_marker(run_id, cid):
            raise ConfigError(
                f"{cid}: 실행 ID와 게시글 표식이 일치하지 않습니다"
            )

        post_id = record.get("created_post_id")

        if post_id is not None and (
            type(post_id) is not int
            or not 1 <= post_id <= 2**63 - 1
        ):
            raise ConfigError(f"{cid}: 저장된 게시글 ID 오류")

        if cid in completed:
            continue

        plan.append({
            "case_id": cid,
            "auth_role": creators[cid]["auth_role"],
            "marker": marker,
            "saved_post_id": post_id,
            "cleanup_case_id": cleanup_by_source[cid]["case_id"],
        })

    return plan


def cleanup_post_shares(
    session, post_id, target, budget, run_id,
    prep_events, max_response_bytes, events,
):
    """표식 검증이 끝난 시험 게시글의 남은 공유를 해제한다."""

    def read_share_ids():
        request_id = str(uuid.uuid4())
        trace_id = new_trace_id()
        path = f"/posts/{post_id}/shares/"

        detail, html = bounded_send(
            session,
            "GET",
            target,
            path,
            budget,
            request_id,
            headers={RUN_ID_HEADER: run_id},
            trace_id=trace_id,
            max_response_bytes=min(max_response_bytes, 65536),
            capture_html=True,
        )

        events.append({
            "stage": "cleanup_share_lookup",
            "path": path,
            "http_status": detail["status"],
            "request_id": request_id,
            "trace_id": trace_id,
        })

        if detail["status"] != 200 or html is None:
            raise ExecutionError("복구용 공유 목록 조회 실패")

        if not isinstance(html, bytes) or len(html) > 65536:
            raise ConfigError("복구용 공유 목록 크기 또는 형식 오류")

        parser = ShareHtmlParser(post_id, "")

        try:
            parser.feed(html.decode("utf-8"))
            parser.close()
        except UnicodeError as exc:
            raise ConfigError("복구용 공유 목록 UTF-8 오류") from exc

        if not parser.has_share_list or parser.open_rows:
            raise ConfigError("복구용 공유 목록 구조를 확인하지 못했습니다")

        share_ids = []

        for row in parser.rows:
            if len(row["names"]) != 1 or not row["names"][0]:
                raise ConfigError("복구용 공유 대상 식별 오류")

            # 기존 파서로 같은 게시글의 POST 해제 경로인지 검증한다.
            share_id = parse_share_id(
                html, post_id, row["names"][0]
            )

            if share_id is None or share_id in share_ids:
                raise ConfigError("복구용 공유 ID가 없거나 중복되었습니다")

            share_ids.append(share_id)

        return share_ids

    share_ids = read_share_ids()

    # 이미 해제된 상태라면 추가 POST 없이 완료한다.
    if not share_ids:
        return 0

    for share_id in share_ids:
        path = f"/posts/{post_id}/shares/{share_id}/revoke/"
        csrf = csrf_for_post(
            session,
            target,
            budget,
            prep_events,
            max_response_bytes,
            "valid",
            run_id,
        )
        request_id = str(uuid.uuid4())
        trace_id = new_trace_id()

        detail, _ = bounded_send(
            session,
            "POST",
            target,
            path,
            budget,
            request_id,
            fields={"csrfmiddlewaretoken": csrf},
            headers={
                RUN_ID_HEADER: run_id,
                "Origin": serialize_origin_header(target),
                "X-CSRFToken": csrf,
            },
            trace_id=trace_id,
            max_response_bytes=max_response_bytes,
        )

        events.append({
            "stage": "cleanup_share_revoke",
            "path": path,
            "http_status": detail["status"],
            "request_id": request_id,
            "trace_id": trace_id,
        })

        if detail["status"] != 302:
            raise ExecutionError("복구용 공유 해제 HTTP 기대값 불일치")

    # 302 응답만으로 완료하지 않고 실제 목록에서 사라졌는지 확인한다.
    if read_share_ids():
        raise ExecutionError("복구 후에도 공유 관계가 남아 있습니다")

    return len(share_ids)


def execute_cleanup(cases: list, attempted: set[str], sessions: dict, prepped: dict,
                    target: str, budget: RequestBudget, run_id: str, prep_events: list,
                    fixture_root: Path, max_response_bytes: int, results: list, created_post_ids: dict | None = None) -> bool:
    """시도한 변경의 복구만 같은 전역 예산 안에서 수행한다. 한 복구 오류가 다른 복구를 막지 않는다."""
    complete = True
    created_post_ids = created_post_ids or {}
    for source in cases:
        case = dict(source)
        record = base_record(run_id, case)
        record.update(execution_stage="cleanup", after_case=case["after_case"])
        if case["after_case"] not in attempted:
            record.update(transport_status="SKIPPED", skip_reason="trigger_not_attempted")
            results.append(record)
            continue
        try:
            role = case["auth_role"]
            if role not in sessions:
                sessions[role] = new_session()
            session = sessions[role]
            if role != "anonymous" and not prepped.get(role):
                prep_login(session, target, budget, role, run_id, prep_events, max_response_bytes)
                prepped[role] = True
            
            if "post_reference" in case:
                ref = case["post_reference"]
                post_id = created_post_ids.get(ref)

                is_aws_post_cleanup = (
                    target == canonical_origin(
                        "https://orchestration-haven.cloud"
                    )
                    and case["path"] == "/posts/{post_id}/delete/"
                )

                if is_aws_post_cleanup:
                    # 이번 실행에서 생성한 게시글만 찾는다.
                    marker = aws_post_marker(run_id, ref)

                    found_id = find_aws_post_by_marker(
                        session,
                        target,
                        budget,
                        run_id,
                        marker,
                    )

                    if found_id is None:
                        raise ExecutionError(
                            "고유 표식의 게시글을 찾지 못했습니다. "
                            "삭제 여부를 별도로 확인해야 합니다"
                        )

                    # 응답에서 얻은 ID와 목록에서 찾은 ID가
                    # 다르면 다른 게시글을 삭제하지 않도록 중단한다.
                    if post_id is not None and post_id != found_id:
                        raise ExecutionError(
                            "생성 응답 ID와 고유 표식 조회 ID가 "
                            "일치하지 않아 복구를 중단합니다"
                        )

                    post_id = found_id

                    record["verified_post_id"] = post_id
                    record["verified_post_marker"] = marker

                    record["share_cleanup_events"] = []
                    record["revoked_share_count"] = cleanup_post_shares(
                        session,
                        post_id,
                        target,
                        budget,
                        run_id,
                        prep_events,
                        max_response_bytes,
                        record["share_cleanup_events"],
                    )
                    record["shares_absent_verified"] = True

                elif post_id is None:
                    raise ExecutionError(
                        "복구 대상 게시글 ID를 확인하지 못했습니다"
                    )

                case["path"] = case["path"].replace(
                    "{post_id}", str(post_id)
                )
                record["path"] = safe_path_log(case["path"])

            if "share_reference" in case:
                share_id = resolve_share_id(case, sessions, prepped, target, budget,
                                            run_id, prep_events, max_response_bytes)
                if share_id is None:
                    record.update(transport_status="SKIPPED", skip_reason="share_not_present")
                    results.append(record)
                    continue
                case["path"] = case["path"].replace("{share_id}", str(share_id))
                record["path"] = safe_path_log(case["path"])
            fields, headers, file_info = prepare_case_request(
                session, case, fixture_root, target, budget, run_id, prep_events, max_response_bytes)
            detail, _ = bounded_send(
                session, case["method"], target, case["path"], budget, record["request_id"],
                fields=fields, file_info=file_info, headers=headers, trace_id=record["trace_id"],
                max_response_bytes=max_response_bytes,
                on_send=lambda timestamp: record.update(timestamp_utc=timestamp, request_attempted=True))
            record.update(http_status=detail["status"], elapsed_ms=detail["elapsed_ms"],
                          redirect_target=safe_location(detail["location"]), request_attempted=True,
                          response_summary={"request_body_bytes": detail["request_body_bytes"],
                                            "body_bytes": detail["body_bytes"], "sha256": detail["sha256"],
                                            "headers": detail["headers"]}, transport_status="OK",
                          http_expectation_match=check_http_expected(detail, case["expected_app"], target_origin=target))
            
            if not record["http_expectation_match"]:
                complete = False

            # AWS에서 이번 실행이 생성한 게시글을 삭제한 경우,
            # 삭제 후 다시 조회하여 접근 차단 여부를 확인한다.
            elif (
                target == canonical_origin("https://orchestration-haven.cloud")
                and case.get("post_reference")
                and case["path"] == f"/posts/{post_id}/delete/"
            ):
                verify_path = f"/posts/{post_id}/"
                verify_request_id = str(uuid.uuid4())
                verify_trace_id = new_trace_id()
                verify_timing = {"timestamp_utc": None}

                verify_detail, _ = bounded_send(
                    session,
                    "GET",
                    target,
                    verify_path,
                    budget,
                    verify_request_id,
                    headers={RUN_ID_HEADER: run_id},
                    trace_id=verify_trace_id,
                    max_response_bytes=max_response_bytes,
                    on_send=lambda timestamp: verify_timing.update(timestamp_utc=timestamp),
                )

                inaccessible = verify_detail["status"] == 404

                record["response_summary"]["verification"] = {
                    "path": verify_path,
                    "http_status": verify_detail["status"],
                    "request_id": verify_request_id,
                    "trace_id": verify_trace_id,
                    "post_inaccessible": inaccessible,
                    "verification_level": "HTTP_ONLY",
                    "db_cleanup_verified": False,
                    "file_cleanup_verified": False,
                    "method": "GET",
                    "timestamp_utc": verify_timing["timestamp_utc"],
                }

                if not inaccessible:
                    complete = False

        except (ExecutionError, ConfigError, KeyboardInterrupt) as exc:
            record.update(transport_status="ERROR", verdict="ERROR",
                          response_summary={"error": "KeyboardInterrupt" if isinstance(exc, KeyboardInterrupt) else str(exc)})
            complete = False
        results.append(record)
        print(f"복구 {case['case_id']}: HTTP {record['http_status']} / {record['transport_status']}", file=sys.stderr)
    return complete


@contextmanager
def temporary_seed_password(enabled: bool, target: str):
    """명시적 로컬 시험 옵션에서만 공통 비밀번호를 받아 종료 시 환경을 복원한다."""
    if not enabled:
        yield
        return
    if target != "http://127.0.0.1:8000":
        raise ConfigError("--prompt-seed-password는 http://127.0.0.1:8000에서만 사용할 수 있습니다")
    previous = os.environ.get("HAVEN_SEED_PASSWORD")
    try:
        if not previous:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                try:
                    password = getpass.getpass("로컬 시험 계정 4개의 공통 비밀번호: ")
                except (EOFError, getpass.GetPassWarning) as exc:
                    raise ExecutionError("비밀번호를 가려서 입력할 수 있는 CMD 터미널이 필요합니다") from exc
            if not password:
                raise ExecutionError("시험 계정 비밀번호가 비어 있습니다")
            os.environ["HAVEN_SEED_PASSWORD"] = password
        yield
    finally:
        if previous is None:
            os.environ.pop("HAVEN_SEED_PASSWORD", None)
        else:
            os.environ["HAVEN_SEED_PASSWORD"] = previous


def print_run_summary(state: dict) -> None:
    """본 시험과 정리 결과를 구분해 출력한다. 실제 입력값은 포함하지 않는다."""
    records = state["results"]
    cleanup = state.get("cleanup_results", [])
    summary = {key: state.get(key) for key in (
        "selected_cases", "execution_cases", "test_http_requests", "preparation_http_requests",
        "cleanup_http_requests", "total_http_requests_including_preparation", "http_responses_received",
        "unexecuted_cases", "cleanup_complete", "stopped_reason",
    )}
    summary.update(
        recorded_results=len(records),
        http_expectation_matches=sum(row.get("http_expectation_match") is True for row in records),
        http_expectation_mismatches=sum(row.get("http_expectation_match") is False for row in records),
        cleanup_results=len(cleanup),
        cleanup_http_matches=sum(row.get("http_expectation_match") is True for row in cleanup),
        cleanup_http_mismatches=sum(row.get("http_expectation_match") is False for row in cleanup),
        cleanup_errors=sum(row.get("transport_status") == "ERROR" for row in cleanup),
        cleanup_skipped=sum(row.get("transport_status") == "SKIPPED" for row in cleanup),
    )
    for verdict in ("PASS", "FAIL", "UNKNOWN", "ERROR"):
        summary[verdict] = sum(row.get("verdict") == verdict for row in records)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


@member_password_scope
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
    prompt_seed = getattr(args, "prompt_seed_password", False)
    if prompt_seed and target != "http://127.0.0.1:8000":
        raise ConfigError("--prompt-seed-password는 http://127.0.0.1:8000에서만 사용할 수 있습니다")
    root = args.fixture_dir.resolve(strict=True)
    suite = load_json(args.cases)
    validate_suite(suite, root)

    total_cases = len(suite["cases"])
    phase = getattr(args, "phase", None)

    # 먼저 회차를 선택한다.
    suite = select_phase(suite, phase)

    if (any("checkpoint_before" in case for case in suite["cases"]) and not getattr(args, "manual_checkpoints", False)):
        raise ConfigError("수동 체크포인트 시험에는 --manual-checkpoints 옵션이 필요합니다")

    validate_selected_checkpoint_sequence(suite)

    # 기존 논리적 시험 케이스 수를 보존한다.
    selected_cases = len(suite["cases"])

    # 다중 payload를 실제 요청 단위로 확장한다.
    # 실행 전에 모든 확장을 끝내므로 ID 충돌도 전송 전에 발견된다.
    suite = expand_suite_variants(suite, root)

    cleanup_cases = suite.get("cleanup_cases", [])
    if {case["case_id"] for case in suite["cases"]} & {case["case_id"] for case in cleanup_cases}:
        raise ConfigError("확장된 시험 ID와 cleanup ID가 충돌합니다")

    # Haven AWS 공유 환경은 실행 전에 복구 가능성을 검증한다.
    if target == canonical_origin("https://orchestration-haven.cloud"):
        validate_aws_cleanup_suite(suite)

    execution_cases = len(suite["cases"])

    phase_label = "전체" if phase is None else f"{phase}회차"
    print(
        f"대상={target}  suite={suite['suite_id']}  "
        f"회차={phase_label}  선택={selected_cases}/{total_cases}  "
        f"요청단위={execution_cases}  "
        f"timeout={args.timeout}s  요청≤{args.max_requests}  "
        f"초당≤{args.rate}  시간≤{args.max_duration}s",
        file=sys.stderr,
    )
    if args.output_dir.exists():
        raise ConfigError("출력 폴더가 이미 있습니다. 새 경로를 지정하세요")
    if getattr(args, "dry_run", False):
        all_cases = suite["cases"] + cleanup_cases
        roles = {case["auth_role"] for case in all_cases} - {"anonymous"}
        roles.update(case["share_reference"]["lookup_role"] for case in all_cases if "share_reference" in case)
        print(json.dumps({
            "target": target, "suite_id": suite["suite_id"], "selected_phase": phase,
            "total_suite_cases": total_cases, "selected_cases": selected_cases,
            "execution_cases": execution_cases, "cleanup_cases": len(cleanup_cases),
            "authenticated_roles": sorted(roles), "minimum_login_requests": 2 * len(roles),
            "minimum_http_requests_excluding_extra_preparation_and_cleanup": execution_cases + 2 * len(roles),
            "share_lookup_case_count": sum(
                "share_reference" in case
                or "share_revoke_role" in case
                for case in all_cases
            ),
            "request_budget": args.max_requests, "max_duration_seconds": args.max_duration,
            "output_dir": str(args.output_dir),
            "count_note": "실행 전 하한이며 실제 요청 수가 아닙니다. 추가 CSRF·공유 ID 조회·조건부 복구도 같은 예산에 포함합니다.",
        }, ensure_ascii=False, indent=2))
        print("DRY RUN: HTTP·DB 작업·비밀번호 입력·출력 폴더 생성은 수행하지 않았습니다.")
        return 0
    with temporary_seed_password(prompt_seed, target):
        return _execute_run(args, target, root, suite, total_cases, selected_cases)


@member_password_scope
def recover(args) -> int:
    """중단된 AWS 시험의 복구 계획 확인 또는 실제 재복구."""
    if args.dry_run == args.apply:
        raise ConfigError("--dry-run 또는 --apply 중 하나만 선택하세요")

    target = canonical_origin(args.target)
    aws_target = canonical_origin(
        "https://orchestration-haven.cloud"
    )

    if target != aws_target:
        raise ConfigError("재복구는 Haven AWS 대상만 지원합니다")

    allow = load_json(args.allowlist)
    if (
        not isinstance(allow, dict)
        or not isinstance(allow.get("approved_origins"), list)
    ):
        raise ConfigError("allowlist 형식 오류")

    approved = {
        canonical_origin(origin)
        for origin in allow["approved_origins"]
    }

    if target not in approved:
        raise ConfigError("재복구 대상이 allowlist에 없습니다")

    root = args.fixture_dir.resolve(strict=True)
    suite = load_json(args.cases)
    state = load_json(args.run_json)

    validate_suite(suite, root)

    phase = state.get("selected_phase")
    suite = select_phase(suite, phase)
    suite = expand_suite_variants(suite, root)

    plan = build_aws_recovery_plan(state, suite)

    print(json.dumps({
        "run_id": state["run_id"],
        "target": target,
        "recovery_count": len(plan),
        "required_roles": sorted({
            item["auth_role"] for item in plan
        }),
        "recovery_plan": plan,
    }, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("DRY RUN: 로그인·삭제 요청을 전송하지 않았습니다.")
        return 0

    if not plan:
        print("재복구 계획에 남은 게시글이 없습니다.")
        return 0

    if args.output_dir is None:
        raise ConfigError("--apply에는 --output-dir이 필요합니다")

    if args.output_dir.exists():
        raise ConfigError("복구 결과 폴더가 이미 존재합니다")

    validate_limits(args)

    if any(
        item["auth_role"] not in {
            "member_a", "member_b", "member_c"
        }
        for item in plan
    ):
        raise ConfigError("지원하지 않는 복구 계정 역할입니다")

    cleanup_map = {
        case["case_id"]: case
        for case in suite.get("cleanup_cases", [])
    }

    selected_cleanup = [
        cleanup_map[item["cleanup_case_id"]]
        for item in plan
    ]

    attempted = {
        item["case_id"]
        for item in plan
    }

    created_post_ids = {
        item["case_id"]: item["saved_post_id"]
        for item in plan
        if item["saved_post_id"] is not None
    }

    args.output_dir.mkdir(parents=True, exist_ok=False)

    budget = RequestBudget(args)
    sessions = {}
    prepped = {}
    prep_events = []
    cleanup_results = []

    recovery_state = {
        "schema_version": 1,
        "source": "aws_recovery",
        "source_run_json": str(args.run_json),
        "run_id": state["run_id"],
        "target_origin": target,
        "started_utc": utc_now(),
        "cleanup_complete": False,
        "cleanup_results": cleanup_results,
        "preparation_events": prep_events,
        "recovery_count": len(plan),
    }

    recovery_state["cleanup_verification_level"] = "HTTP_ONLY"
    recovery_state["db_cleanup_verified"] = False
    recovery_state["file_cleanup_verified"] = False

    try:
        recovery_state["cleanup_complete"] = execute_cleanup(
            cases=selected_cleanup,
            attempted=attempted,
            sessions=sessions,
            prepped=prepped,
            target=target,
            budget=budget,
            run_id=state["run_id"],
            prep_events=prep_events,
            fixture_root=root,
            max_response_bytes=args.max_response_bytes,
            results=cleanup_results,
            created_post_ids=created_post_ids,
        )
    finally:
        for session in sessions.values():
            session.close()

        recovery_state["ended_utc"] = utc_now()
        recovery_state["total_http_requests_including_preparation"] = (
            budget.count
        )
        recovery_state["http_responses_received"] = (
            budget.responses_received
        )

        save_results(
            args.output_dir,
            recovery_state,
            [],
        )

    print(
        f"복구 결과: {args.output_dir / 'results.json'}"
    )

    return 0 if recovery_state["cleanup_complete"] else 2


def _execute_run(args, target: str, root: Path, suite: dict, total_cases: int, selected_cases: int) -> int:
    """검증과 선택적 인증 정보 준비가 끝난 뒤 기존 실행 루프를 수행한다."""
    phase = getattr(args, "phase", None)
    execution_cases = len(suite["cases"])
    cleanup_cases = suite.get("cleanup_cases", [])
    args.output_dir.mkdir(parents=True, exist_ok=False)
    # 2) 실행 단위 ID와 전역 요청 예산을 생성한다.
    
    run_id = str(uuid.uuid4())

    # AWS 공유 환경에서는 복구에 필요한 요청 수를 미리 예약한다.
    aws_mode = target == canonical_origin(
        "https://orchestration-haven.cloud"
    )

    cleanup_reserve = (
        max(8, len(cleanup_cases) * 3 + 5)
        if aws_mode and cleanup_cases
        else 0
    )

    if cleanup_reserve >= args.max_requests:
        raise ConfigError(
            "AWS 복구용 요청을 예약할 수 없습니다. "
            "--max-requests 값을 늘려주세요."
        )

    main_args = argparse.Namespace(**vars(args))
    main_args.max_requests = args.max_requests - cleanup_reserve

    budget = RequestBudget(main_args)
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
        selected_cases=selected_cases,
        execution_cases=execution_cases,
        excluded_cases=total_cases - selected_cases,
        cleanup_results=[], cleanup_complete=None, cleanup_http_requests=0,
        test_http_requests=0, preparation_http_requests=0, http_responses_received=0,
    )

    if aws_mode:
        state["cleanup_verification_level"] = "HTTP_ONLY"
        state["db_cleanup_verified"] = False
        state["file_cleanup_verified"] = False

    records = []
    attempted = set()
    created_post_ids = {}
    failed = False
    
    cleanup_done = False
    cleanup_http_requests = 0
    cleanup_http_responses = 0

    def perform_cleanup_once():
        nonlocal cleanup_done, cleanup_http_requests, cleanup_http_responses

        if cleanup_done:
            return

        # 로컬 시험은 기존 예산을 그대로 사용한다.
        # AWS 시험은 예약한 요청 수와 독립된 실행 시간을 사용한다.
        active_budget = budget

        if aws_mode and cleanup_cases:
            cleanup_args = argparse.Namespace(**vars(args))
            cleanup_args.max_requests = cleanup_reserve
            cleanup_args.max_duration = 300
            cleanup_args.rate = min(args.rate, 1.0)

            # 복구 시작 시점부터 시간을 계산한다.
            active_budget = RequestBudget(cleanup_args)

        started = active_budget.count
        responses_started = active_budget.responses_received

        try:
            state["cleanup_complete"] = execute_cleanup(
                cleanup_cases,
                attempted,
                sessions,
                prepped,
                target,
                active_budget,
                run_id,
                prep_events,
                root,
                args.max_response_bytes,
                state["cleanup_results"],
                created_post_ids=created_post_ids,
            )
        finally:
            cleanup_http_requests += active_budget.count - started
            cleanup_http_responses += (
                active_budget.responses_received - responses_started
            )
            state["cleanup_http_requests"] = cleanup_http_requests
            cleanup_done = True

    try:
        for source_case in suite["cases"]:
            if source_case.get("cleanup_before") is True:
                perform_cleanup_once()

                if not state["cleanup_complete"]:
                    failed = True
                    state["stopped_reason"] = (
                        f"cleanup before {source_case['case_id']} incomplete"
                    )
                    break

            case = dict(source_case)
            record = base_record(run_id, case)
            role = case["auth_role"]
            try:
                if "post_reference" in case:
                    ref = case["post_reference"]
                    post_id = created_post_ids.get(ref)

                    if post_id is None:
                        raise ExecutionError(
                            f"{case['case_id']}: 선행 게시글 ID를 찾을 수 없습니다"
                        )

                    case["path"] = case["path"].replace(
                        "{post_id}", str(post_id)
                    )
                    record["path"] = safe_path_log(case["path"])
                # 역할별 세션을 유지하되, 익명 로그인 POST는
                # 케이스마다 독립된 세션을 사용한다.
                isolate_login = (
                    role == "anonymous"
                    and case["method"] == "POST"
                    and case["path"] == "/accounts/login/"
                )

                if isolate_login:
                    session_key = (role, case["case_id"])
                else:
                    session_key = role

                if session_key not in sessions:
                    sessions[session_key] = new_session()

                sess = sessions[session_key]

                if role != "anonymous" and not prepped.get(role):
                    prep_login(
                        sess,
                        target,
                        budget,
                        role,
                        run_id,
                        prep_events,
                        args.max_response_bytes
                    )
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

                if "share_revoke_role" in case:
                    resolved_post_id = created_post_ids.get(
                        case["post_reference"]
                    )

                    share_id = resolve_created_share_id(
                        resolved_post_id,
                        case.get("share_lookup_role", role),
                        case["share_revoke_role"],
                        sessions,
                        prepped,
                        target,
                        budget,
                        run_id,
                        prep_events,
                        args.max_response_bytes,
                    )

                    case["path"] = case["path"].replace(
                        "{share_id}", str(share_id)
                    )
                    record["path"] = safe_path_log(case["path"])
                    record["resolved_share_id"] = share_id

                if "share_reference" in case:
                    share_id = resolve_share_id(case, sessions, prepped, target, budget,
                                                run_id, prep_events, args.max_response_bytes)
                    case["path"] = case["path"].replace("{share_id}", str(share_id))
                    record["path"] = safe_path_log(case["path"])

                # 인가/CSRF 준비와 HTTP 전송을 분리해 run()의 흐름을 단순하게 유지한다.
                fields, headers, file_info = prepare_case_request(
                    sess, case, root, target, budget, run_id, prep_events, args.max_response_bytes
                )

                fields = bind_share_recipient(
                    case, fields, sessions, prepped
                )

                # AWS 게시글 생성 전 복구 식별자를 디스크에 기록.
                if aws_mode and case.get("capture_post_id"):
                    marker = aws_post_marker(
                        run_id, case["case_id"]
                    )

                    record["post_marker"] = marker

                    state["pending_post_creation"] = {
                        "case_id": case["case_id"],
                        "auth_role": role,
                        "marker": marker,
                    }

                    save_results(
                        args.output_dir,
                        state,
                        records + [record],
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
                        timestamp_utc=timestamp, request_attempted=True
                    ),
                )
                
                record.update(http_status=detail["status"], elapsed_ms=detail["elapsed_ms"],
                              redirect_target=safe_location(detail["location"]),
                              response_summary={"request_body_bytes": detail["request_body_bytes"], "body_bytes": detail["body_bytes"], "sha256": detail["sha256"],
                                                "headers": detail["headers"]}, transport_status="OK", request_attempted=True,
                              http_expectation_match=check_http_expected(detail, case["expected_app"], target_origin=target))

                if case.get("capture_post_id"):
                    if not check_http_expected(
                        detail, case["expected_app"], target_origin=target
                    ):
                        raise ExecutionError("게시글 생성 HTTP 기대값 불일치")

                    post_id = extract_created_post_id(
                        detail["location"], target
                    )

                    if post_id in created_post_ids.values():
                        raise ExecutionError("중복된 생성 게시글 ID입니다")

                    created_post_ids[case["case_id"]] = post_id

                    if aws_mode:
                        state["pending_post_creation"] = None
                        record["created_post_id"] = post_id
                
                # No WAF/app log evidence in run: do not invent a pass based on HTTP 403.
                record["verdict"] = "UNKNOWN"
                if case.get("critical") and not record["http_expectation_match"]:
                    failed = True
            except (ExecutionError, ConfigError, KeyboardInterrupt) as exc:
                record.update(
                    transport_status="ERROR",
                    verdict="ERROR",
                )

                if record.get("response_summary") is None:
                    record["response_summary"] = {}

                record["response_summary"]["error"] = (
                    "KeyboardInterrupt"
                    if isinstance(exc, KeyboardInterrupt)
                    else str(exc)
                )
                failed = True
            # 4) 성공/실패마다 즉시 기록: 중단돼도 부분 증거를 보존한다.
            records.append(record)
            if record["request_attempted"]:
                attempted.add(case.get("parent_case_id", case["case_id"]))
            state["test_http_requests"] = sum(row["request_attempted"] for row in records)
            state["preparation_http_requests"] = (
                budget.count
                - state["test_http_requests"]
                - (0 if aws_mode else cleanup_http_requests)
            )
            state["http_responses_received"] = (
                budget.responses_received
                + (cleanup_http_responses if aws_mode else 0)
            )
            state["unexecuted_cases"] = len(suite["cases"]) - len(records)
            state["total_http_requests_including_preparation"] = (
                budget.count
                + (cleanup_http_requests if aws_mode else 0)
            )
            state["ended_utc"] = utc_now()
            if failed:
                state["stopped_reason"] = f"case {case['case_id']}: " + record["response_summary"].get("error", "핵심 선행조건 HTTP 기대값 불일치")
            save_results(args.output_dir, state, records)
            print(f"{case['case_id']}: HTTP {record['http_status']} / {record['transport_status']} / "
                  f"상관 상태={record['correlation_status']}", file=sys.stderr)
            if failed:
                break
    finally:
        try:
            perform_cleanup_once()
        finally:
            for s in sessions.values():
                s.close()

            state["cleanup_http_requests"] = cleanup_http_requests
            state["test_http_requests"] = sum(
                row["request_attempted"] for row in records
            )
            state["preparation_http_requests"] = (
                budget.count
                - state["test_http_requests"]
                - (0 if aws_mode else cleanup_http_requests)
            )
            state["http_responses_received"] = (
                budget.responses_received
                + (cleanup_http_responses if aws_mode else 0)
            )
            state["total_http_requests_including_preparation"] = (
                budget.count
                + (cleanup_http_requests if aws_mode else 0)
            )
            state["ended_utc"] = utc_now()
            state["unexecuted_cases"] = (
                len(suite["cases"]) - len(records)
            )
            save_results(args.output_dir, state, records)
    print(f"run 결과: {args.output_dir / 'results.json'}", file=sys.stderr)
    print_run_summary(state)
    return get_exit_code(records, incomplete=failed or len(records) != len(suite["cases"]) or not state["cleanup_complete"])


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
    """시간대가 명시된 시각 또는 epoch만 UTC로 정규화한다."""
    val = event.get("timestamp_utc")
    if val is None:
        val = event.get("ts")
    if val is None:
        val = event.get("timestamp")

    try:
        if isinstance(val, bool):
            return None

        if isinstance(val, (int, float)):
            if val > 10**11:
                val /= 1000
            return datetime.fromtimestamp(val, timezone.utc)

        if isinstance(val, str):
            parsed = datetime.fromisoformat(
                val.replace("Z", "+00:00")
            )
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return None
            return parsed.astimezone(timezone.utc)

    except (ValueError, TypeError, OverflowError, OSError):
        return None

    return None


def plausible_event(event: dict, row: dict, origin: str) -> bool:
    """실행 ID·대상·시간(±120초)이 같은 증거인지 점검."""
    if event.get("run_id") not in {None, row["run_id"]}:
        return False
    if event.get("target_origin") not in {None, origin}:
        return False
    t1 = log_timestamp(event)
    t2 = log_timestamp({
        "timestamp_utc": row.get("timestamp_utc")
    })

    return (
        t1 is not None
        and t2 is not None
        and abs((t1 - t2).total_seconds()) <= 120
    )


def correlation_cleanup_records(state):
    """정리 기록을 검증하고 원래 순서를 유지한다."""
    rows = state.get("cleanup_results", [])

    if not isinstance(rows, list) or any(
        not isinstance(row, dict) for row in rows
    ):
        raise ConfigError("정리 결과 목록 형식 오류")

    return rows


def correlation_verification_records(state):
    """삭제 후 확인 GET을 독립적인 상관분석 기록으로 만든다."""
    records = []

    for parent in correlation_cleanup_records(state):
        summary = parent.get("response_summary") or {}
        verification = summary.get("verification")

        if verification is None:
            continue
        if not isinstance(verification, dict):
            raise ConfigError("삭제 후 확인 기록 형식 오류")

        post_id = parent.get("verified_post_id")
        if (
            type(post_id) is not int
            or not 1 <= post_id <= 2**63 - 1
            or parent.get("method") != "POST"
            or parent.get("path") != f"/posts/{post_id}/delete/"
            or verification.get("path") != f"/posts/{post_id}/"
            or verification.get("method", "GET") != "GET"
        ):
            raise ConfigError("삭제 요청과 확인 요청의 대상 불일치")

        status = verification.get("http_status")
        request_id = verification.get("request_id")
        trace_id = verification.get("trace_id")

        if (
            type(status) is not int
            or not 100 <= status <= 599
            or not isinstance(request_id, str)
            or not request_id.strip()
            or extract_trace_root(trace_id) is None
        ):
            raise ConfigError("삭제 후 확인 요청의 응답·식별자 오류")

        row = base_record(parent["run_id"], {
            "case_id": parent["case_id"] + "-VERIFY",
            "category": "cleanup_verification",
            "method": "GET",
            "path": verification["path"],
            "auth_role": parent["auth_role"],
            "expected_app": {"http_status": 404},
            "expected_waf": "ALLOW",
            "verification_mode": "http_only",
        })

        row.update(
            parent_case_id=parent["case_id"],
            execution_stage="cleanup_verification",
            request_id=request_id,
            trace_id=trace_id,
            # 과거 기록에 없는 시각을 생성하거나 추정하지 않는다.
            timestamp_utc=verification.get("timestamp_utc"),
            http_status=status,
            transport_status="OK",
            request_attempted=True,
            http_expectation_match=(status == 404),
            response_summary={
                "verification_level": "HTTP_ONLY",
                "db_cleanup_verified": False,
                "file_cleanup_verified": False,
            },
            verdict="UNKNOWN",
        )
        records.append(row)

    return records


def correlate(args) -> int:
    """실행 결과와 WAF·앱 로그를 Trace Root 기준으로 연결하고 검증한다."""
    state = load_json(args.run_json)
    if not isinstance(state, dict) or not isinstance(state.get("results"), list) or not state.get("run_id"):
        raise ConfigError("올바른 run results JSON이 아닙니다")
    if not state["results"]:
        raise ConfigError("대조할 run 결과가 비어 있습니다")
    cleanup_sources = correlation_cleanup_records(state)
    verification_sources = correlation_verification_records(state)
    test_count = len(state["results"])
    cleanup_count = len(cleanup_sources)
    # 로그는 별도 로컬 파일을 읽으며 인터넷에서 직접 수집하지 않는다.
    waf = log_lines(args.waf_log)
    app = log_lines(args.app_log)
    if args.output_dir.exists():
        raise ConfigError("correlate 출력 폴더가 이미 있습니다")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    records = []
    origin = state.get("target_origin", "")
    for src in (state["results"] + cleanup_sources + verification_sources):
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
    cleanup_end = test_count + cleanup_count
    test_records = records[:test_count]
    cleanup_records = records[test_count:cleanup_end]
    verification_records = records[cleanup_end:]

    out = {
        k: v
        for k, v in state.items()
        if k not in {
            "results",
            "preparation_events",
            "cleanup_results",
            "cleanup_verification_results",
        }
    }
    out["cleanup_results"] = cleanup_records
    out["cleanup_verification_results"] = verification_records
    out["source"] = "correlated_from_local_logs"
    out["correlated_utc"] = utc_now()
    out["source_run_json"] = args.run_json.name

    save_results(
        args.output_dir,
        out,
        test_records,
        correlation=True,
    )

    # 실행되지 않은 정리는 판정 대상에서 제외한다.
    # 실제 정리 오류·로그 부족·불일치는 종료 코드에 반영한다.
    verdict_records = test_records + [
        row for row in cleanup_records
        if row.get("transport_status") != "SKIPPED"
    ] + verification_records
    code = get_exit_code(
        verdict_records,
        incomplete=(
            bool(state.get("stopped_reason"))
            or bool(state.get("unexecuted_cases"))
            or state.get("cleanup_complete") is False
        ),
    )

    print(
        f"correlate 결과: "
        f"{args.output_dir / 'correlated_results.json'} "
        f"(종료 코드 {code})",
        file=sys.stderr,
    )
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


def get_aws_identity(profile: str, region: str = "ap-northeast-2") -> dict:
    """AWS CLI 프로필로 현재 인증된 계정과 사용자·역할을 확인한다."""
    if (
        not isinstance(profile, str)
        or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", profile)
    ):
        raise ConfigError("AWS 프로필명 형식 오류")

    if (
        not isinstance(region, str)
        or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", region)
    ):
        raise ConfigError("AWS 리전 형식 오류")

    command = [
        "aws",
        "sts",
        "get-caller-identity",
        "--profile", profile,
        "--region", region,
        "--output", "json",
        "--no-cli-pager",
        "--no-cli-auto-prompt",
    ]

    try:
        result = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExecutionError(
            "AWS CLI를 찾을 수 없습니다. 설치와 PATH를 확인하세요"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ExecutionError(
            "AWS 인증 확인 시간이 초과되었습니다"
        ) from exc
    except OSError as exc:
        raise ExecutionError(
            "AWS CLI 프로세스를 실행하지 못했습니다"
        ) from exc

    if result.returncode != 0:
        # 원본 stderr를 결과 파일이나 예외 메시지에 그대로 넣지 않는다.
        raise ExecutionError(
            f"AWS 인증 확인 실패 (종료 코드 {result.returncode}). "
            f"터미널에서 aws sts get-caller-identity "
            f"--profile {profile} --region {region}로 원인을 확인하세요"
        )

    try:
        identity = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ExecutionError(
            "AWS 인증 응답이 올바른 JSON이 아닙니다"
        ) from exc

    if not isinstance(identity, dict):
        raise ExecutionError("AWS 인증 응답 형식 오류")

    account = identity.get("Account")
    arn = identity.get("Arn")
    user_id = identity.get("UserId")

    if (
        not isinstance(account, str)
        or not re.fullmatch(r"\d{12}", account)
        or not isinstance(arn, str)
        or not isinstance(user_id, str)
        or not user_id.strip()
    ):
        raise ExecutionError("AWS 인증 응답의 필수 정보가 잘못되었습니다")

    arn_parts = arn.split(":", 5)
    if (
        len(arn_parts) != 6
        or arn_parts[0] != "arn"
        or arn_parts[1] not in {"aws", "aws-cn", "aws-us-gov"}
        or arn_parts[2] not in {"iam", "sts"}
        or arn_parts[4] != account
        or not arn_parts[5]
    ):
        raise ExecutionError("AWS 인증 응답의 ARN과 계정이 일치하지 않습니다")

    return {
        "profile": profile,
        "region": region,
        "account_id": account,
        "arn": arn,
        "user_id": user_id,
    }


def cloudwatch_window_from_run(state, *, padding_seconds=120):
    """실행 시작·종료 시각을 CloudWatch 조회용 epoch 밀리초로 변환한다."""
    if not isinstance(state, dict):
        raise ConfigError("실행 결과 형식 오류")

    if (
        type(padding_seconds) is not int
        or not 0 <= padding_seconds <= 300
    ):
        raise ConfigError("로그 조회 여유 시간은 0~300초 정수여야 합니다")

    def parse_time(field):
        value = state.get(field)

        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"실행 결과에 {field} 시각이 없습니다")

        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timezone missing")

            return parsed.astimezone(timezone.utc)
        except (ValueError, OverflowError) as exc:
            raise ConfigError(
                f"{field}는 시간대가 포함된 ISO 시각이어야 합니다"
            ) from exc

    started = parse_time("started_utc")
    ended = parse_time("ended_utc")

    if ended < started:
        raise ConfigError("실행 종료 시각이 시작 시각보다 빠릅니다")

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def epoch_ms(value):
        delta = value - epoch
        return (
            delta.days * 86400000
            + delta.seconds * 1000
            + delta.microseconds // 1000
        )

    started_ms = epoch_ms(started)
    ended_ms = epoch_ms(ended)

    if started_ms < 0:
        raise ConfigError("실행 시각은 Unix epoch 이후여야 합니다")

    padding_ms = padding_seconds * 1000
    start_ms = max(0, started_ms - padding_ms)

    # 종료 시각이 속한 밀리초까지 조회 범위에 포함한다.
    end_ms = ended_ms + padding_ms + 1

    if end_ms - start_ms > 60 * 60 * 1000:
        raise ConfigError(
            "여유 시간을 포함한 로그 조회 범위가 1시간을 초과합니다"
        )

    return {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "padding_seconds": padding_seconds,
    }


def fetch_cloudwatch_page(
    profile, region, log_group,
    start_ms, end_ms, *, next_token=None,
):
    """지정한 시간 범위의 CloudWatch 로그 한 페이지를 가져온다."""
    if (
        not isinstance(profile, str)
        or not re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", profile
        )
        or not isinstance(region, str)
        or not re.fullmatch(
            r"[a-z]{2}(?:-[a-z]+)+-\d+", region
        )
    ):
        raise ConfigError("AWS 프로필명 또는 리전 형식 오류")

    if (
        not isinstance(log_group, str)
        or log_group not in {
            "aws-waf-logs-haven", "/haven/web"
        }
    ):
        raise ConfigError("허용되지 않은 로그 그룹입니다")

    if (
        type(start_ms) is not int
        or type(end_ms) is not int
        or start_ms < 0
        or end_ms <= start_ms
        or end_ms - start_ms > 60 * 60 * 1000
    ):
        raise ConfigError(
            "로그 조회 범위는 밀리초 정수이며 1시간 이하여야 합니다"
        )

    if next_token is not None and (
        not isinstance(next_token, str)
        or not next_token
    ):
        raise ConfigError("CloudWatch 다음 페이지 토큰 형식 오류")

    request = {
        "logGroupName": log_group,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 1000,
    }
    if next_token is not None:
        request["nextToken"] = next_token

    command = [
        "aws",
        "logs",
        "filter-log-events",
        "--cli-input-json", json.dumps(request),
        "--profile", profile,
        "--region", region,
        "--no-paginate",
        "--output", "json",
        "--no-cli-pager",
        "--no-cli-auto-prompt",
    ]

    try:
        result = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=60,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExecutionError("AWS CLI를 찾을 수 없습니다") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExecutionError("CloudWatch 로그 조회 시간 초과") from exc
    except UnicodeError as exc:
        raise ExecutionError("CloudWatch 응답 인코딩 오류") from exc
    except OSError as exc:
        raise ExecutionError("AWS CLI 실행 실패") from exc

    if result.returncode != 0:
        raise ExecutionError(
            f"CloudWatch 로그 조회 실패 "
            f"(종료 코드 {result.returncode}, 그룹 {log_group})"
        )

    try:
        page = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ExecutionError("CloudWatch 응답 JSON 오류") from exc

    if (
        not isinstance(page, dict)
        or not isinstance(page.get("events"), list)
    ):
        raise ExecutionError("CloudWatch 이벤트 목록 형식 오류")

    token = page.get("nextToken")
    if token is not None and (
        not isinstance(token, str) or not token
    ):
        raise ExecutionError("CloudWatch 응답 토큰 형식 오류")

    for event in page["events"]:
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("eventId"), str)
            or not event["eventId"]
            or not isinstance(event.get("logStreamName"), str)
            or not event["logStreamName"]
            or type(event.get("timestamp")) is not int
            or event["timestamp"] < 0
            or not isinstance(event.get("message"), str)
        ):
            raise ExecutionError("CloudWatch 이벤트 필수 정보 오류")

    return {
        "events": page["events"],
        "next_token": token,
    }


def collect_cloudwatch_events(
    profile, region, log_group, start_ms, end_ms,
    *, max_pages=20, max_events=10000,
):
    """마지막 페이지까지 조회하고 이벤트 ID 기준으로 중복을 제거한다."""
    if (
        type(max_pages) is not int
        or not 1 <= max_pages <= 100
        or type(max_events) is not int
        or not 1 <= max_events <= 100000
    ):
        raise ConfigError("CloudWatch 수집 한도 설정 오류")

    next_token = None
    seen_tokens = set()
    unique_events = {}

    for page_number in range(1, max_pages + 1):
        page = fetch_cloudwatch_page(
            profile,
            region,
            log_group,
            start_ms,
            end_ms,
            next_token=next_token,
        )

        for event in page["events"]:
            # 스트림이 다른 이벤트를 잘못 합치지 않는다.
            key = (event["logStreamName"], event["eventId"])

            if key in unique_events:
                if unique_events[key] != event:
                    raise ExecutionError(
                        "동일 CloudWatch 이벤트 ID의 내용이 충돌합니다"
                    )
                continue

            if len(unique_events) >= max_events:
                raise ExecutionError(
                    "CloudWatch 이벤트 수집 한도를 초과했습니다"
                )

            unique_events[key] = dict(event)

        next_token = page["next_token"]

        # 이벤트가 0건이어도 종료 여부는 토큰으로 판단한다.
        if next_token is None:
            events = sorted(
                unique_events.values(),
                key=lambda event: (
                    event["timestamp"],
                    event["logStreamName"],
                    event["eventId"],
                ),
            )
            return {
                "events": events,
                "pages_fetched": page_number,
                "event_count": len(events),
                "pagination_complete": True,
            }

        if next_token in seen_tokens:
            raise ExecutionError(
                "CloudWatch 다음 페이지 토큰이 반복되었습니다"
            )

        seen_tokens.add(next_token)

    raise ExecutionError(
        "CloudWatch 페이지 수집 한도를 초과했습니다. "
        "조회 시간 범위를 줄이거나 수집 한도를 조정하세요"
    )


def check_aws_account(args) -> int:
    """AWS 프로필의 인증 계정이 예상한 프로젝트 계정인지 확인한다."""
    expected_account = args.expected_account

    if (
        not isinstance(expected_account, str)
        or not re.fullmatch(r"\d{12}", expected_account)
    ):
        raise ConfigError("예상 AWS 계정 ID는 12자리 숫자여야 합니다")

    identity = get_aws_identity(
        args.profile,
        args.region,
    )

    if identity["account_id"] != expected_account:
        raise ExecutionError(
            "AWS 계정 불일치: "
            f"예상={expected_account}, "
            f"실제={identity['account_id']}"
        )

    print(json.dumps({
        "source": "aws_identity_check",
        "checked_utc": utc_now(),
        "account_match": True,
        **identity,
    }, ensure_ascii=False, indent=2))

    return 0


def inspect_accounts(args) -> int:
    """관리자 로그인 후 지정한 시험 계정의 ID와 활성 상태를 조회한다."""
    validate_limits(args)
    target = canonical_origin(args.target)

    if target != canonical_origin(
        "https://orchestration-haven.cloud"
    ):
        raise ConfigError(
            "inspect-accounts는 Haven AWS 대상만 지원합니다"
        )

    allow = load_json(args.allowlist)
    if (
        not isinstance(allow, dict)
        or not isinstance(allow.get("approved_origins"), list)
    ):
        raise ConfigError("allowlist 형식 오류")

    approved = {
        canonical_origin(origin)
        for origin in allow["approved_origins"]
    }
    if target not in approved:
        raise ConfigError("대상 origin이 allowlist에 없습니다")

    usernames = args.username
    if (
        not usernames
        or any(
            not isinstance(name, str)
            or not name
            or name.strip() != name
            for name in usernames
        )
        or len(set(usernames)) != len(usernames)
    ):
        raise ConfigError("조회 계정명이 비어 있거나 중복되었습니다")

    run_id = str(uuid.uuid4())
    budget = RequestBudget(args)
    prep_events = []
    accounts = []

    with new_session() as session:
        # 일반 시험 계정과 별도로 관리자 계정 정보를 입력받는다.
        prep_login(
            session,
            target,
            budget,
            "operator",
            run_id,
            prep_events,
            args.max_response_bytes,
        )

        for username in usernames:
            account = find_admin_account(
                session,
                target,
                budget,
                run_id,
                username,
                prep_events,
                args.max_response_bytes,
            )

            if any(
                previous["account_id"] == account["account_id"]
                for previous in accounts
            ):
                raise ExecutionError(
                    "서로 다른 계정명이 같은 ID로 조회되었습니다"
                )

            accounts.append(account)

    print(json.dumps({
        "source": "aws_account_inspection",
        "run_id": run_id,
        "target_origin": target,
        "inspected_utc": utc_now(),
        "accounts": accounts,
        "account_state_changed": False,
        "total_http_requests": budget.count,
    }, ensure_ascii=False, indent=2))

    return 0


def parse_cloudwatch_message(raw, *, allow_app_prefix=False):
    """순수 JSON 또는 확인된 앱 스트림의 Gunicorn JSON을 해석한다."""
    message = raw["message"]

    try:
        return json.loads(message)
    except ValueError:
        if not allow_app_prefix:
            raise

    stream = raw.get("logStreamName")
    if (
        not isinstance(stream, str)
        or re.fullmatch(r"i-[0-9a-f]+/app", stream) is None
    ):
        raise ValueError("지원하지 않는 앱 로그 스트림")

    match = re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T"
        r"\d{2}:\d{2}:\d{2}(?:\.\d+)?"
        r"(?:Z|[+-]\d{2}:\d{2}) "
        r"[A-Za-z0-9_.-]+ gunicorn\[[0-9]+\]: "
        r"(?P<payload>\{[^\r\n]*\})[ \t]*",
        message,
    )
    if match is None:
        raise ValueError("지원하지 않는 앱 로그 접두사")

    return json.loads(match.group("payload"))


def select_cloudwatch_run_logs(raw_events, state, *, allow_app_prefix=False):
    """CloudWatch message를 해석하고 이번 시험의 Trace Root로 선별한다."""
    if (
        not isinstance(raw_events, list)
        or not isinstance(state, dict)
        or not isinstance(state.get("results"), list)
        or not state["results"]
    ):
        raise ConfigError("로그 선별 입력 형식 오류")

    expected_roots = set()
    cleanup_rows = correlation_cleanup_records(state)
    verification_rows = correlation_verification_records(state)

    for row in state["results"] + cleanup_rows + verification_rows:
        if not isinstance(row, dict):
            raise ConfigError("실행 결과의 요청 기록 형식 오류")

        root = extract_trace_root(row.get("trace_id"))
        if root is None:
            raise ConfigError(
                "실행 결과에 유효한 Trace ID가 없는 요청이 있습니다"
            )

        if root in expected_roots:
            raise ConfigError("실행 결과의 Trace ID가 중복되었습니다")

        expected_roots.add(root)

    selected = []
    counts = {
        "raw_events": len(raw_events),
        "non_json": 0,
        "non_object": 0,
        "missing_trace": 0,
        "other_trace": 0,
        "selected": 0,
    }

    for raw in raw_events:
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("message"), str)
        ):
            raise ConfigError("CloudWatch 원본 이벤트 형식 오류")

        try:
            event = parse_cloudwatch_message(
                raw,
                allow_app_prefix=allow_app_prefix,
            )
        except ValueError:
            # 지원하지 않는 텍스트 형식은 판정 근거로 사용하지 않는다.
            counts["non_json"] += 1
            continue

        if not isinstance(event, dict):
            counts["non_object"] += 1
            continue

        root = log_trace_root(event)

        if root is None:
            counts["missing_trace"] += 1
            continue

        if root not in expected_roots:
            counts["other_trace"] += 1
            continue

        # run_id·시각·HTTP 상태의 충돌은 correlate에서 판정한다.
        # 여기서 정상값으로 덮어쓰거나 충돌 로그를 제거하지 않는다.
        selected.append(event)
        counts["selected"] += 1

    return {
        "events": selected,
        "counts": counts,
    }


def load_cloudwatch_collection(run_json, logs_dir):
    """실행 결과와 수집 명세를 대조하고 원본 로그 두 개를 읽는다."""
    state = load_json(run_json)

    if (
        not isinstance(state, dict)
        or state.get("source") != "live_http_run"
        or state.get("target_origin") != canonical_origin(
            "https://orchestration-haven.cloud"
        )
        or not isinstance(state.get("results"), list)
        or not state["results"]
    ):
        raise ConfigError("AWS 시험의 원본 results.json이 필요합니다")

    run_id = state.get("run_id")
    try:
        if not isinstance(run_id, str):
            raise ValueError("run_id")
        if str(uuid.UUID(run_id)) != run_id:
            raise ValueError("run_id")
    except ValueError as exc:
        raise ConfigError("실행 결과의 run_id 형식 오류") from exc

    manifest = load_json(
        safe_relative(logs_dir, "collection_manifest.json")
    )

    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("source") != "cloudwatch_log_collection"
    ):
        raise ConfigError("CloudWatch 수집 명세 형식 오류")

    if manifest.get("run_id") != run_id:
        raise ConfigError("실행 결과와 수집 로그의 run_id 불일치")

    if (
        manifest.get("collection_complete") is not True
        or manifest.get("error_type") is not None
    ):
        raise ConfigError("완료되지 않은 로그 수집 결과입니다")

    account_id = manifest.get("account_id")
    if (
        not isinstance(account_id, str)
        or not re.fullmatch(r"[0-9]{12}", account_id)
    ):
        raise ConfigError("수집 명세의 AWS 계정 ID 형식 오류")

    window = manifest.get("window")
    if not isinstance(window, dict):
        raise ConfigError("수집 명세의 조회 시간 범위가 없습니다")

    expected_window = cloudwatch_window_from_run(
        state,
        padding_seconds=window.get("padding_seconds"),
    )
    if window != expected_window:
        raise ConfigError("실행 결과와 로그 조회 시간 범위 불일치")

    groups = manifest.get("groups")
    if not isinstance(groups, list) or len(groups) != 2:
        raise ConfigError("WAF와 앱 로그 수집 정보가 모두 필요합니다")

    expected_files = {
        "aws-waf-logs-haven": "waf_events.jsonl",
        "/haven/web": "app_events.jsonl",
    }
    raw_logs = {}

    for group in groups:
        if not isinstance(group, dict):
            raise ConfigError("로그 그룹 명세 형식 오류")

        name = group.get("log_group")

        if (
            not isinstance(name, str)
            or name not in expected_files
            or name in raw_logs
            or group.get("file") != expected_files[name]
            or group.get("pagination_complete") is not True
            or type(group.get("pages_fetched")) is not int
            or not 1 <= group["pages_fetched"] <= 100
            or type(group.get("event_count")) is not int
            or not 0 <= group["event_count"] <= 100000
        ):
            raise ConfigError("로그 그룹·파일·수집 건수 설정 오류")

        path = safe_relative(logs_dir, expected_files[name])
        events = log_lines(path)

        if len(events) != group["event_count"]:
            raise ConfigError("수집 명세와 로그 파일의 이벤트 건수 불일치")

        raw_logs[name] = events

    return {
        "state": state,
        "manifest": manifest,
        "waf_events": raw_logs["aws-waf-logs-haven"],
        "app_events": raw_logs["/haven/web"],
    }


def collect_logs(args) -> int:
    """AWS 실행 결과의 시간 범위에 해당하는 WAF·앱 로그를 수집한다."""
    if not re.fullmatch(r"[0-9]{12}", args.expected_account):
        raise ConfigError("예상 AWS 계정 ID는 12자리 숫자여야 합니다")

    state = load_json(args.run_json)

    if (
        not isinstance(state, dict)
        or state.get("source") != "live_http_run"
        or state.get("target_origin") != canonical_origin(
            "https://orchestration-haven.cloud"
        )
        or not isinstance(state.get("results"), list)
        or not state["results"]
    ):
        raise ConfigError("AWS 시험의 원본 results.json이 필요합니다")

    run_id = state.get("run_id")
    try:
        if not isinstance(run_id, str):
            raise ValueError("run_id")
        if str(uuid.UUID(run_id)) != run_id:
            raise ValueError("run_id")
    except ValueError as exc:
        raise ConfigError("실행 결과의 run_id 형식 오류") from exc

    window = cloudwatch_window_from_run(
        state,
        padding_seconds=args.padding_seconds,
    )

    if args.output_dir.exists():
        raise ConfigError("로그 출력 폴더가 이미 존재합니다")

    identity = get_aws_identity(args.profile, args.region)
    if identity["account_id"] != args.expected_account:
        raise ExecutionError(
            "AWS 계정 불일치: "
            f"예상={args.expected_account}, "
            f"실제={identity['account_id']}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "schema_version": 1,
        "source": "cloudwatch_log_collection",
        "run_id": run_id,
        "source_run_json": str(args.run_json.resolve()),
        "profile": args.profile,
        "region": args.region,
        "account_id": identity["account_id"],
        "started_utc": utc_now(),
        "window": window,
        "groups": [],
        "collection_complete": False,
        "error_type": None,
    }

    def write_manifest():
        temporary = args.output_dir / "collection_manifest.json.tmp"
        destination = args.output_dir / "collection_manifest.json"

        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)

    try:
        write_manifest()

        for group, filename in (
            ("aws-waf-logs-haven", "waf_events.jsonl"),
            ("/haven/web", "app_events.jsonl"),
        ):
            collected = collect_cloudwatch_events(
                args.profile,
                args.region,
                group,
                window["start_ms"],
                window["end_ms"],
            )

            destination = args.output_dir / filename
            temporary = args.output_dir / (filename + ".tmp")

            with temporary.open(
                "w", encoding="utf-8", newline="\n"
            ) as output:
                for event in collected["events"]:
                    output.write(
                        json.dumps(event, ensure_ascii=False) + "\n"
                    )

            temporary.replace(destination)

            manifest["groups"].append({
                "log_group": group,
                "file": filename,
                "event_count": collected["event_count"],
                "pages_fetched": collected["pages_fetched"],
                "pagination_complete": collected["pagination_complete"],
            })
            write_manifest()

        manifest["collection_complete"] = True

    except (
        ConfigError, ExecutionError, OSError, KeyboardInterrupt
    ) as exc:
        manifest["error_type"] = type(exc).__name__
        raise

    finally:
        manifest["ended_utc"] = utc_now()
        write_manifest()

    print(json.dumps({
        "run_id": run_id,
        "collection_complete": True,
        "groups": manifest["groups"],
        "manifest": str(
            args.output_dir / "collection_manifest.json"
        ),
    }, ensure_ascii=False, indent=2))

    return 0


def correlate_cloudwatch(args) -> int:
    """수집한 CloudWatch 로그를 검증·선별하고 기존 상관분석을 실행한다."""
    if not re.fullmatch(r"[0-9]{12}", args.expected_account):
        raise ConfigError("예상 AWS 계정 ID는 12자리 숫자여야 합니다")

    if args.output_dir.exists():
        raise ConfigError("상관분석 출력 폴더가 이미 존재합니다")

    loaded = load_cloudwatch_collection(
        args.run_json, args.logs_dir
    )
    manifest = loaded["manifest"]

    if manifest["account_id"] != args.expected_account:
        raise ConfigError("수집 로그의 AWS 계정이 예상 계정과 다릅니다")

    selected = {
        "waf": select_cloudwatch_run_logs(
            loaded["waf_events"], loaded["state"]
        ),
        "app": select_cloudwatch_run_logs(
            loaded["app_events"],
            loaded["state"],
            allow_app_prefix=True,
        ),
    }

    args.output_dir.mkdir(parents=True, exist_ok=False)

    for kind in ("waf", "app"):
        path = args.output_dir / f"{kind}_selected.jsonl"
        with path.open(
            "w", encoding="utf-8", newline="\n"
        ) as output:
            for event in selected[kind]["events"]:
                output.write(
                    json.dumps(event, ensure_ascii=False) + "\n"
                )

    selection_report = {
        "schema_version": 1,
        "source": "cloudwatch_log_selection",
        "run_id": loaded["state"]["run_id"],
        "account_id": manifest["account_id"],
        "source_run_json": str(args.run_json.resolve()),
        "source_collection_manifest": str(
            (args.logs_dir / "collection_manifest.json").resolve()
        ),
        "selected_utc": utc_now(),
        "waf": selected["waf"]["counts"],
        "app": selected["app"]["counts"],
    }

    (args.output_dir / "selection_summary.json").write_text(
        json.dumps(
            selection_report, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )

    # PASS/FAIL/UNKNOWN 판정과 종료 코드는 기존 함수를 그대로 사용한다.
    return correlate(argparse.Namespace(
        run_json=args.run_json,
        waf_log=args.output_dir / "waf_selected.jsonl",
        app_log=args.output_dir / "app_selected.jsonl",
        output_dir=args.output_dir / "correlated",
    ))


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
    r.add_argument("--dry-run", action="store_true", help="입력·출력 폴더 생성·HTTP 없이 선택한 시험 계획만 검증")
    r.add_argument("--prompt-seed-password", action="store_true", help="로컬 127.0.0.1:8000 시험 계정의 공통 비밀번호를 한 번 가려서 입력")
    
    rec = commands.add_parser(
        "recover",
        help="중단된 AWS 시험의 재복구 계획 확인 및 실행"
    )
    rec.add_argument("--run-json", required=True, type=Path)
    rec.add_argument("--target", required=True)
    rec.add_argument("--allowlist", required=True, type=Path)
    rec.add_argument("--cases", required=True, type=Path)
    rec.add_argument(
        "--fixture-dir", type=Path, default=Path("fixtures")
    )
    rec.add_argument("--output-dir", type=Path)

    mode = rec.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")

    rec.add_argument("--timeout", type=float, default=10)
    rec.add_argument("--max-requests", type=int, default=100)
    rec.add_argument("--rate", type=float, default=1)
    rec.add_argument("--max-duration", type=float, default=300)
    rec.add_argument(
        "--max-response-bytes",
        type=int,
        default=MAX_RESPONSE,
    )

    c = commands.add_parser("correlate", help="기존 run 결과에 로컬 JSONL WAF/앱 로그를 연결")
    c.add_argument("--run-json", required=True, type=Path)
    c.add_argument("--waf-log", required=True, type=Path)
    c.add_argument("--app-log", required=True, type=Path)
    c.add_argument("--output-dir", required=True, type=Path)

    inspect = commands.add_parser(
        "inspect-accounts",
        help="관리자 로그인 후 시험 계정 ID와 활성 상태 조회",
    )
    inspect.add_argument("--target", required=True)
    inspect.add_argument(
        "--allowlist", required=True, type=Path
    )
    inspect.add_argument(
        "--username",
        action="append",
        required=True,
        help="조회할 실제 계정명. 여러 계정은 옵션을 반복 지정",
    )
    inspect.add_argument("--timeout", type=float, default=10)
    inspect.add_argument("--max-requests", type=int, default=100)
    inspect.add_argument("--rate", type=float, default=1)
    inspect.add_argument("--max-duration", type=float, default=300)
    inspect.add_argument(
        "--max-response-bytes",
        type=int,
        default=MAX_RESPONSE,
    )

    aws_check = commands.add_parser(
        "aws-check",
        help="AWS 프로필 인증 및 프로젝트 계정 일치 확인",
    )
    aws_check.add_argument("--profile", required=True)
    aws_check.add_argument(
        "--region", default="ap-northeast-2"
    )
    aws_check.add_argument(
        "--expected-account",
        required=True,
        help="사용하려는 프로젝트 AWS 계정의 12자리 ID",
    )

    collect = commands.add_parser(
        "collect-logs",
        help="AWS 시험 결과의 시간 범위로 CloudWatch 로그 수집",
    )
    collect.add_argument(
        "--run-json", required=True, type=Path
    )
    collect.add_argument("--profile", required=True)
    collect.add_argument(
        "--region", default="ap-northeast-2"
    )
    collect.add_argument(
        "--expected-account", required=True
    )
    collect.add_argument(
        "--output-dir", required=True, type=Path
    )
    collect.add_argument(
        "--padding-seconds", type=int, default=120
    )

    cw = commands.add_parser(
        "correlate-cloudwatch",
        help="수집한 CloudWatch 로그를 선별하여 상관분석",
    )
    cw.add_argument(
        "--run-json", required=True, type=Path
    )
    cw.add_argument(
        "--logs-dir", required=True, type=Path
    )
    cw.add_argument(
        "--expected-account", required=True
    )
    cw.add_argument(
        "--output-dir", required=True, type=Path
    )

    return parser


def main(argv=None) -> int:
    """파싱·예외 처리 후 종료 코드를 운영체제에 반환."""
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run(args)
        if args.command == "recover":
            return recover(args)
        if args.command == "inspect-accounts":
            return inspect_accounts(args)
        if args.command == "aws-check":
            return check_aws_account(args)
        if args.command == "collect-logs":
            return collect_logs(args)
        if args.command == "correlate-cloudwatch":
            return correlate_cloudwatch(args)
        return correlate(args)
    except KeyboardInterrupt:
        print("중단됨: 사용자가 Ctrl+C를 눌렀습니다", file=sys.stderr)
        return 2
    except (ConfigError, ExecutionError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
