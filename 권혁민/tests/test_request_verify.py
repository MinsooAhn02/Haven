"""Unit/integration checks using local synthetic fixture server. No AWS network access."""
from __future__ import annotations

from argparse import Namespace
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
from pathlib import Path
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import request_verify as cli
from mock_server import FixtureHandler


@contextmanager
def server(tmp_path: Path):
    class Handler(FixtureHandler):
        waf_log = tmp_path / "synthetic_waf.jsonl"
        app_log = tmp_path / "synthetic_app.jsonl"

    host = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=host.serve_forever, daemon=True)
    t.start()
    try:
        yield host.server_port, Handler.waf_log, Handler.app_log
    finally:
        host.shutdown()
        t.join(timeout=3)
        host.server_close()


def inputs(tmp_path, port, suite_name="cases_local.json", *, max_requests=100, rate=5):
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"approved_origins":[f"http://127.0.0.1:{port}"]}), encoding="utf-8")
    return Namespace(
        target=f"http://127.0.0.1:{port}", allowlist=allow, cases=ROOT/"fixtures"/suite_name,
        fixture_dir=ROOT/"fixtures", output_dir=tmp_path/"run_output", timeout=3,
        max_requests=max_requests, rate=rate, max_duration=60, max_response_bytes=cli.MAX_RESPONSE,
    )


def utc_time():
    return datetime.now(timezone.utc).isoformat()


def test_origins_exact_allowlist_and_public_http_rejected():
    assert cli.canonical_origin("HTTPS://Example.COM") == "https://example.com:443"
    assert cli.canonical_origin("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    for bad in ["http://example.com", "https://example.com/path", "https://u:p@example.com",
                "https://example.com?token=abc", "file:///tmp/abc", "https://example.com\\evil"]:
        with pytest.raises(cli.ConfigError):
            cli.canonical_origin(bad)


def test_path_blocks_origin_changes():
    for bad in ["https://outside.invalid/", "//outside.invalid/a", "\\\\outside.invalid",
                "/\\outside.invalid", "posts/", "/index#fragment", "/a\nHost: outside"]:
        with pytest.raises(cli.ConfigError):
            cli.validate_path(bad)
    assert cli.validate_path("/posts/?page=1") == "/posts/?page=1"
    assert "<redacted>" in cli.safe_path_log("/posts/?page=secret")


def test_fixture_traversal_and_symlink_forbidden(tmp_path):
    base = tmp_path / "fixtures"
    base.mkdir()

    (base / "good.json").write_text("{}", encoding="utf-8")
    assert cli.safe_relative(base, "good.json").name == "good.json"

    (tmp_path / "private.json").write_text("{}", encoding="utf-8")

    # 경로 이동 및 절대 경로 차단 검사
    for ref in ["../private.json", "/etc/passwd", "..\\private.json"]:
        with pytest.raises(cli.ConfigError):
            cli.safe_relative(base, ref)

    # 심볼릭 링크를 이용한 외부 파일 접근 차단 검사
    try:
        (base / "alias.json").symlink_to(tmp_path / "private.json")
    except (OSError, NotImplementedError):
        pass  # Windows에서 권한이 없으면 이 검사만 생략
    else:
        with pytest.raises(cli.ConfigError):
            cli.safe_relative(base, "alias.json")


def test_suite_rejects_undefined_fields_and_duplicate_case():
    sample = cli.load_json(ROOT/"fixtures"/"cases_local.json")
    cli.validate_suite(sample, ROOT/"fixtures")
    sample["cases"][1]["case_id"] = sample["cases"][0]["case_id"]
    with pytest.raises(cli.ConfigError):
        cli.validate_suite(sample, ROOT/"fixtures")


def test_end_to_end_run_pending_then_correlate_pass(tmp_path):
    with server(tmp_path) as (port, waf, app):
        args = inputs(tmp_path, port)
        assert cli.run(args) == 3
        run_json = args.output_dir/"results.json"
        data = cli.load_json(run_json)
        assert data["unexecuted_cases"] == 0
        assert len(data["results"]) == 4
        assert all(x["correlation_status"] == "PENDING_LOG" for x in data["results"])
        assert all(x["waf_verdict"] == "UNKNOWN" for x in data["results"])
        assert data["total_http_requests_including_preparation"] == 4
        assert all("sessionid" not in json.dumps(x) for x in data["results"])
        original = run_json.read_bytes()
        corr = Namespace(run_json=run_json, waf_log=waf, app_log=app, output_dir=tmp_path/"corr")
        assert cli.correlate(corr) == 0
        assert run_json.read_bytes() == original  # don't overwrite run
        output = cli.load_json(corr.output_dir/"correlated_results.json")["results"]
        assert [item["verdict"] for item in output] == ["PASS"] * 4
        assert all(x.get("evidence_kind") == "SYNTHETIC_FIXTURE_NOT_REAL_WAF" for x in output)


def test_app11_serialized_exact_body_sizes(tmp_path):
    with server(tmp_path) as (port, waf, app):
        args = inputs(tmp_path, port, suite_name="cases_body_boundary.json")
        assert cli.run(args) == 3
        raw = cli.load_json(args.output_dir/"results.json")
        assert [x["response_summary"]["request_body_bytes"] for x in raw["results"]] == [8191, 8192, 8193]
        assert [x["http_status"] for x in raw["results"]] == [302, 302, 413]
        assert raw["total_http_requests_including_preparation"] == 4  # 1 CSRF GET + 3 POST
        corr = Namespace(run_json=args.output_dir/"results.json", waf_log=waf, app_log=app, output_dir=tmp_path/"corr")
        assert cli.correlate(corr) == 0


def test_request_cap_records_partial_and_stops(tmp_path):
    with server(tmp_path) as (port, _waf, _app):
        args = inputs(tmp_path, port, max_requests=1)
        assert cli.run(args) == 2
        state = cli.load_json(args.output_dir/"results.json")
        assert len(state["results"]) == 2
        assert state["unexecuted_cases"] == 2
        assert state["total_http_requests_including_preparation"] == 1
        assert state["results"][-1]["transport_status"] == "ERROR"
        assert state["stopped_reason"]


def test_existing_output_directory_cannot_be_overwritten(tmp_path):
    with server(tmp_path) as (port, _waf, _app):
        args = inputs(tmp_path, port)
        args.output_dir.mkdir()
        with pytest.raises(cli.ConfigError):
            cli.run(args)


def test_missing_waf_logs_unresolved_not_pass(tmp_path):
    with server(tmp_path) as (port, _waf, app):
        args = inputs(tmp_path, port)
        assert cli.run(args) == 3
        empty = tmp_path/"missing.jsonl"
        empty.write_text("", encoding="utf-8")
        corr = Namespace(run_json=args.output_dir/"results.json", waf_log=empty, app_log=app,
                         output_dir=tmp_path/"corr")
        assert cli.correlate(corr) == 3
        recs = cli.load_json(corr.output_dir/"correlated_results.json")["results"]
        assert all(item["correlation_status"] == "UNRESOLVED" for item in recs)
        assert all(item["verdict"] == "UNKNOWN" for item in recs)


def test_duplicate_waf_log_is_unresolved(tmp_path):
    with server(tmp_path) as (port, waf, app):
        args = inputs(tmp_path, port)
        assert cli.run(args) == 3
        lines = waf.read_text(encoding="utf-8").splitlines()
        with waf.open("a", encoding="utf-8") as fh:
            fh.write(lines[0] + "\n")
        corr = Namespace(run_json=args.output_dir/"results.json", waf_log=waf, app_log=app,
                         output_dir=tmp_path/"corr")
        assert cli.correlate(corr) == 3
        recs = cli.load_json(corr.output_dir/"correlated_results.json")["results"]
        assert recs[0]["correlation_status"] == "UNRESOLVED"
        assert recs[0]["waf_verdict"] == "UNKNOWN"


def test_preparation_login_is_counted_and_redacted(tmp_path, monkeypatch):
    with server(tmp_path) as (port, waf, app):
        suite = cli.load_json(ROOT/"fixtures"/"cases_local.json")
        suite["cases"] = [dict(suite["cases"][1], auth_role="member_a", expected_app={"http_status":200})]
        suite_file = tmp_path/"auth_cases.json"
        suite_file.write_text(json.dumps(suite), encoding="utf-8")
        args = inputs(tmp_path, port)
        args.cases = suite_file
        monkeypatch.setattr("builtins.input", lambda _prompt: "dummy_user")
        monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: "my_fake_test_password")
        assert cli.run(args) == 3
        text = (args.output_dir/"results.json").read_text(encoding="utf-8")
        data = json.loads(text)
        assert data["total_http_requests_including_preparation"] == 3
        assert len(data["preparation_events"]) == 2
        assert "my_fake_test_password" not in text
        assert "fixture-session" not in text
        assert data["results"][0]["http_status"] == 200


def test_correlate_rejects_empty_run_results(tmp_path):
    run_json = tmp_path / "results.json"
    run_json.write_text(json.dumps({"run_id": "test", "results": []}), encoding="utf-8")
    empty_log = tmp_path / "empty.jsonl"
    empty_log.touch()
    output_dir = tmp_path / "correlated"

    assert cli.main([
        "correlate", "--run-json", str(run_json), "--waf-log", str(empty_log),
        "--app-log", str(empty_log), "--output-dir", str(output_dir),
    ]) == 2
    assert not output_dir.exists()


def test_aws_style_header_correlation():
    event = {"httpRequest":{"headers":[{"name":"x-haven-request-id","value":"case-abc"}]},
             "timestamp": 1790000000000, "action":"ALLOW"}
    assert cli.log_request_id(event) == "case-abc"
    assert cli.log_timestamp(event) is not None


def test_manual_security_case_never_auto_passes_on_http_alone(tmp_path):
    with server(tmp_path) as (port, waf, app):
        original = cli.load_json(ROOT/"fixtures"/"cases_local.json")
        original["cases"] = [dict(original["cases"][0], case_id="SEC-23", verification_mode="manual_required")]
        casefile = tmp_path/"manual.json"
        casefile.write_text(json.dumps(original), encoding="utf-8")
        args = inputs(tmp_path, port)
        args.cases = casefile
        assert cli.run(args) == 3
        corr = Namespace(run_json=args.output_dir/"results.json", waf_log=waf, app_log=app,
                         output_dir=tmp_path/"corr")
        assert cli.correlate(corr) == 3
        row = cli.load_json(corr.output_dir/"correlated_results.json")["results"][0]
        assert row["correlation_status"] == "MATCHED"
        assert row["http_expectation_match"] is True
        assert row["manual_validation"] == "REQUIRED"
        assert row["verdict"] == "UNKNOWN"


def test_waf_expectation_mismatch_is_fail_with_confirmed_logs(tmp_path):
    with server(tmp_path) as (port, waf, app):
        raw = cli.load_json(ROOT/"fixtures"/"cases_local.json")
        raw["cases"] = [dict(raw["cases"][0], expected_waf="BLOCK")]
        casefile = tmp_path/"wrong_waf.json"
        casefile.write_text(json.dumps(raw), encoding="utf-8")
        args = inputs(tmp_path, port)
        args.cases = casefile
        assert cli.run(args) == 3
        corr = Namespace(run_json=args.output_dir/"results.json", waf_log=waf, app_log=app,
                         output_dir=tmp_path/"corr")
        assert cli.correlate(corr) == 1
        row = cli.load_json(corr.output_dir/"correlated_results.json")["results"][0]
        assert row["verdict"] == "FAIL"

# ---------------------------------------------------------
# 최근 수정사항에 대한 회귀 테스트
# ---------------------------------------------------------

def test_origin_rejects_zero_port():
    """명시적으로 입력한 포트 0은 기본 포트로 변환하지 않고 거부한다."""
    with pytest.raises(cli.ConfigError):
        cli.canonical_origin("https://example.com:0")


def test_missing_fixture_raises_config_error(tmp_path):
    """존재하지 않는 Fixture는 ConfigError로 처리한다."""
    base = tmp_path / "fixtures"
    base.mkdir()

    with pytest.raises(cli.ConfigError):
        cli.safe_relative(base, "nonexistent.json")


def test_path_rejects_whitespace():
    """URL 경로의 공백은 거부하지만 쿼리 문자열의 공백은 허용한다."""
    with pytest.raises(cli.ConfigError):
        cli.validate_path("/posts/1 /")

    assert cli.validate_path("/posts/?q=hello world") == "/posts/?q=hello world"


def test_response_header_case_insensitive():
    """HTTP 응답 헤더 이름과 값의 대소문자 차이를 허용한다."""
    detail = {
        "status": 200,
        "headers": {
            "Content-Type": "application/json"
        }
    }

    expected = {
        "http_status": 200,
        "headers_contain": {
            "content-type": "APPLICATION/JSON"
        }
    }

    assert cli.check_http_expected(detail, expected)


def test_haven_template_schema_and_fixture_references():
    """Haven 시험표의 스키마·ID 중복·입력 fixture 참조를 검증한다."""
    fixture_root = ROOT / "fixtures"
    suite = cli.load_json(fixture_root / "cases_haven_template.json")

    cli.validate_suite(suite, fixture_root)


def test_haven_first_round_contract_routes():
    """Yochan 1회차 앱 계약의 기본 경로와 폼 필드를 확인한다."""
    fixture_root = ROOT / "fixtures"
    suite = cli.load_json(
        fixture_root / "cases_haven_template.json"
    )

    cli.validate_suite(suite, fixture_root)

    cases = {
        case["case_id"]: case
        for case in suite["cases"]
    }

    expected_routes = {
        "APP-01-HEALTHZ-GET": (
            "GET", "/healthz", "anonymous", 200
        ),
        "APP-01-SIGNUP-GET": (
            "GET", "/accounts/signup/", "anonymous", 200
        ),
        "APP-01-LOGIN-GET": (
            "GET", "/accounts/login/", "anonymous", 200
        ),
        "APP-02-OWNER-LIST": (
            "GET", "/posts/", "member_a", 200
        ),
        "APP-02-SHARED-EMPTY": (
            "GET", "/posts/shared/", "member_a", 200
        ),
    }

    for case_id, (method, path, role, status) in expected_routes.items():
        case = cases[case_id]

        assert case["phase"] == 1
        assert case["method"] == method
        assert case["path"] == path
        assert case["auth_role"] == role
        assert case["expected_app"]["http_status"] == status

    # Yochan PostForm 계약: title, body
    payload = cli.load_json(
        fixture_root / "post_valid_record.json"
    )
    assert set(payload["fields"]) == {"title", "body"}
    assert payload["csrf_mode"] == "valid"
    

def test_phase_selection_preserves_order_and_original():
    """선택한 회차만 반환하고, 순서와 원본을 유지한다."""
    suite = {
        "suite_id": "phase-test",
        "cases": [
            {"case_id": "FIRST", "phase": 1},
            {"case_id": "SECOND", "phase": 2},
            {"case_id": "THIRD", "phase": 1},
        ],
    }
    before = json.dumps(suite, sort_keys=True)

    selected = cli.select_phase(suite, 1)

    assert [case["case_id"] for case in selected["cases"]] == [
        "FIRST", "THIRD"
    ]
    assert selected["suite_id"] == "phase-test"
    assert json.dumps(suite, sort_keys=True) == before


def test_phase_omitted_accepts_legacy_suite():
    """phase 없는 기존 로컬 fixture도 옵션 생략 시 사용 가능하다."""
    suite = cli.load_json(ROOT / "fixtures" / "cases_local.json")

    cli.validate_suite(suite, ROOT / "fixtures")
    selected = cli.select_phase(suite, None)

    assert selected == suite


def test_phase_selection_rejects_missing_phase():
    """일부 케이스에 phase가 없으면 조용히 제외하지 않고 거부한다."""
    suite = {
        "cases": [
            {"case_id": "WITH-PHASE", "phase": 1},
            {"case_id": "MISSING-PHASE"},
        ]
    }

    with pytest.raises(cli.ConfigError, match="MISSING-PHASE"):
        cli.select_phase(suite, 1)


def test_phase_selection_rejects_empty_phase():
    """선택 회차에 케이스가 없으면 거부한다."""
    suite = {
        "cases": [
            {"case_id": "ONLY-PHASE-ONE", "phase": 1},
        ]
    }

    with pytest.raises(cli.ConfigError, match="해당하는 케이스가 없습니다"):
        cli.select_phase(suite, 4)


@pytest.mark.parametrize("bad_phase", [0, 5, "1", True, 1.5, None])
def test_suite_rejects_invalid_phase(bad_phase):
    """JSON에 명시한 phase는 1~4 정수만 허용한다."""
    suite = cli.load_json(ROOT / "fixtures" / "cases_local.json")
    suite["cases"][0]["phase"] = bad_phase

    with pytest.raises(cli.ConfigError, match="phase"):
        cli.validate_suite(suite, ROOT / "fixtures")


def test_run_phase_filters_requests_and_records_counts(tmp_path):
    """실제로 선택된 요청만 보내고 결과·로그·개수를 대조한다."""
    with server(tmp_path) as (port, waf, app):
        suite = cli.load_json(ROOT / "fixtures" / "cases_local.json")

        # 기존 로컬 fixture 4개를 1·2회차로 번갈아 배정한다.
        for index, case in enumerate(suite["cases"]):
            case["phase"] = 1 if index % 2 == 0 else 2

        expected_ids = [
            case["case_id"]
            for case in suite["cases"]
            if case["phase"] == 1
        ]

        case_file = tmp_path / "phase_cases.json"
        case_file.write_text(
            json.dumps(suite, ensure_ascii=False),
            encoding="utf-8",
        )

        args = inputs(tmp_path, port)
        args.cases = case_file
        args.phase = 1

        # run 단계는 아직 로그 대조 전이므로 UNKNOWN(3).
        assert cli.run(args) == 3

        result = cli.load_json(args.output_dir / "results.json")
        records = result["results"]

        assert [row["case_id"] for row in records] == expected_ids
        assert result["selected_phase"] == 1
        assert result["total_suite_cases"] == 4
        assert result["selected_cases"] == 2
        assert result["excluded_cases"] == 2
        assert result["unexecuted_cases"] == 0
        assert result["stopped_reason"] is None

        # 로컬 fixture는 인증 준비가 없는 요청이므로 정확히 2회.
        assert result["total_http_requests_including_preparation"] == 2
        assert all(row["transport_status"] == "OK" for row in records)
        assert all(row["http_expectation_match"] is True for row in records)

        # 결과 기록뿐 아니라 서버가 실제로 받은 요청 ID도 확인한다.
        waf_events = cli.log_lines(waf)
        assert [event["request_id"] for event in waf_events] == [
            row["request_id"] for row in records
        ]

        # 로그 대조 후에도 회차 정보가 유지되는지 확인한다.
        corr = Namespace(
            run_json=args.output_dir / "results.json",
            waf_log=waf,
            app_log=app,
            output_dir=tmp_path / "phase_corr",
        )
        assert cli.correlate(corr) == 0

        correlated = cli.load_json(
            corr.output_dir / "correlated_results.json"
        )
        assert correlated["selected_phase"] == 1
        assert correlated["selected_cases"] == 2
        assert correlated["excluded_cases"] == 2
        assert all(
            row["verdict"] == "PASS"
            for row in correlated["results"]
        )


@pytest.mark.parametrize(
    "location, expected_match",
    [
        ("/accounts/login/?next=/posts/", True),
        ("https://haven.example/accounts/login/", True),
        ("https://haven.example:443/accounts/login/", True),
        ("//haven.example/accounts/login/", True),
        ("https://other.example/accounts/login/", False),
        ("//other.example/accounts/login/", False),
        ("///accounts/login/", False),
        (r"/\accounts/login/", False),
        ("https:/accounts/login/", False),
        ("http://haven.example/accounts/login/", False),
        ("https://haven.example:444/accounts/login/", False),
        ("/posts/", False),
        (None, False),
    ],
)
def test_redirect_requires_expected_origin_and_path(location, expected_match):
    detail = {
        "status": 302,
        "location": location,
        "headers": {},
    }
    expected = {
        "http_status": 302,
        "redirect_path": "/accounts/login/",
    }

    assert cli.check_http_expected(
        detail,
        expected,
        target_origin="https://haven.example:443",
    ) is expected_match


@contextmanager
def probe_server(*, redirect_to=None):
    """CLI 동작 관찰용 로컬 서버. 실제 인증·WAF는 구현하지 않는다."""
    received = []
    release_slow = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            received.append({
                "path": self.path,
                "cookie": self.headers.get("Cookie", ""),
            })

            if self.path in {"/slow-stream-200", "/slow-stream-302"}:
                status = 302 if self.path.endswith("302") else 200

                try:
                    self.send_response(status)

                    if status == 302:
                        self.send_header("Location", "/accounts/login/")

                    self.send_header("Content-Length", "12")
                    self.end_headers()

                    for _ in range(12):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.08)

                except OSError:
                    pass

                return

            if self.path == "/stall-body":
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", "12")
                    self.end_headers()
                    self.wfile.flush()

                    # 헤더는 보내지만 본문은 전달하지 않는다.
                    # 클라이언트는 다음 바이트를 기다리게 된다.
                    release_slow.wait(timeout=2)

                except OSError:
                    pass

                return
            
            if self.path == "/slow-302-body":
                self.send_response(302)
                self.send_header("Location", "/accounts/login/")
                self.send_header("Content-Length", "4")
                self.end_headers()
                self.wfile.flush()

                # 헤더 전송 후 본문을 일부러 지연시킨다.
                release_slow.wait(timeout=1)

                try:
                    self.wfile.write(b"slow")
                except OSError:
                    pass
                return

            if self.path == "/slow":
                release_slow.wait(timeout=5)

            status = 302 if self.path == "/redirect" else 200
            body = b"probe"

            try:
                self.send_response(status)
                if status == 302:
                    self.send_header("Location", redirect_to)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                # timeout으로 클라이언트가 먼저 연결을 끊은 경우.
                pass

    host = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=host.serve_forever, daemon=True)
    thread.start()

    try:
        yield host.server_port, received
    finally:
        release_slow.set()
        host.shutdown()
        thread.join(timeout=3)
        host.server_close()


def probe_inputs(tmp_path, port, paths, roles=None):
    """기존 로컬 케이스 형식을 재사용해 임시 시험표를 만든다."""
    args = inputs(tmp_path, port)
    suite = cli.load_json(ROOT / "fixtures" / "cases_local.json")
    template = suite["cases"][0]
    roles = roles or ["anonymous"] * len(paths)

    suite["cases"] = [
        {
            **template,
            "case_id": f"PROBE-{index}",
            "method": "GET",
            "path": path,
            "auth_role": role,
            "input_reference": None,
            "expected_app": {
                "http_status": 302 if path == "/redirect" else 200
            },
            "expected_waf": "NOT_APPLICABLE",
            "verification_mode": "http_only",
        }
        for index, (path, role) in enumerate(zip(paths, roles))
    ]

    args.cases = tmp_path / "probe_cases.json"
    args.cases.write_text(
        json.dumps(suite, ensure_ascii=False),
        encoding="utf-8",
    )
    return args


def test_probe_sessions_are_isolated(tmp_path, monkeypatch):
    """역할별 쿠키가 실제 전송에서도 분리되는지 확인한다."""
    prepared_roles = []

    def fake_login(session, target, budget, role, *args, **kwargs):
        prepared_roles.append(role)
        session.cookies.set(
            "sessionid",
            f"dummy-{role}",
            domain="127.0.0.1",
            path="/",
        )

    monkeypatch.setattr(cli, "prep_login", fake_login)

    with probe_server() as (port, received):
        args = probe_inputs(
            tmp_path,
            port,
            ["/healthz"] * 4,
            ["member_a", "member_b", "anonymous", "member_a"],
        )

        assert cli.run(args) == 3

        assert prepared_roles == ["member_a", "member_b"]
        assert [item["cookie"] for item in received] == [
            "sessionid=dummy-member_a",
            "sessionid=dummy-member_b",
            "",
            "sessionid=dummy-member_a",
        ]


def test_probe_rate_limits_send_intervals(tmp_path, monkeypatch):
    """rate=1일 때 실제 HTTP 전송 시작 간격을 확인한다."""
    send_times = []
    original_send = cli.requests.Session.send

    def observed_send(session, request, **kwargs):
        send_times.append(time.monotonic())
        return original_send(session, request, **kwargs)

    monkeypatch.setattr(cli.requests.Session, "send", observed_send)

    with probe_server() as (port, received):
        args = probe_inputs(tmp_path, port, ["/healthz"] * 3)
        args.rate = 1

        assert cli.run(args) == 3
        assert len(received) == 3
        assert len(send_times) == 3

        intervals = [
            later - earlier
            for earlier, later in zip(send_times, send_times[1:])
        ]

        # 실행 시계·스케줄링 차이를 고려한 20ms 허용 오차.
        assert all(interval >= 0.98 for interval in intervals), intervals


def test_probe_timeout_preserves_partial_results(tmp_path):
    """응답 헤더 지연 시 timeout 오류와 미실행 케이스를 기록한다."""
    with probe_server() as (port, received):
        args = probe_inputs(tmp_path, port, ["/slow", "/healthz"])
        args.timeout = 0.2

        assert cli.run(args) == 2

        result = cli.load_json(args.output_dir / "results.json")

        assert [item["path"] for item in received] == ["/slow"]
        assert result["total_http_requests_including_preparation"] == 1
        assert result["unexecuted_cases"] == 1
        assert result["stopped_reason"]
        assert len(result["results"]) == 1

        row = result["results"][0]
        assert row["transport_status"] == "ERROR"
        assert row["verdict"] == "ERROR"
        assert "ReadTimeout" in row["response_summary"]["error"]


def test_probe_unapproved_origin_sends_nothing(tmp_path, monkeypatch):
    """미승인 target은 HTTP 전송 함수 호출 전 거부한다."""
    attempted_urls = []
    original_send = cli.requests.Session.send

    def observed_send(session, request, **kwargs):
        attempted_urls.append(request.url)
        return original_send(session, request, **kwargs)

    monkeypatch.setattr(cli.requests.Session, "send", observed_send)

    with probe_server() as (approved_port, approved_received):
        with probe_server() as (other_port, other_received):
            args = probe_inputs(tmp_path, approved_port, ["/healthz"])

            # allowlist는 첫 번째 서버만 허용한 상태로 유지.
            args.target = f"http://127.0.0.1:{other_port}"

            with pytest.raises(cli.ConfigError, match="allowlist"):
                cli.run(args)

            assert attempted_urls == []
            assert approved_received == []
            assert other_received == []
            assert not args.output_dir.exists()


@pytest.mark.parametrize("location, matched", [
    ("/accounts/login/?token=private-value", True),
    ("///accounts/login/?token=private-value", False),
])
def test_probe_checks_raw_location_and_redacts_output(tmp_path, location, matched):
    with probe_server(redirect_to=location) as (port, _):
        args = probe_inputs(tmp_path, port, ["/redirect"])
        suite = cli.load_json(args.cases)
        suite["cases"][0]["expected_app"]["redirect_path"] = "/accounts/login/"
        args.cases.write_text(json.dumps(suite), encoding="utf-8")

        assert cli.run(args) == 3
        result_text = (args.output_dir / "results.json").read_text(encoding="utf-8")
        record = json.loads(result_text)["results"][0]
        assert record["http_expectation_match"] is matched
        assert record["redirect_target"] == "/accounts/login/?token=<redacted>"
        assert "private-value" not in result_text


def test_probe_external_redirect_is_not_followed(tmp_path, monkeypatch):
    """허용 서버가 다른 origin으로 유도해도 후속 요청은 보내지 않는다."""
    attempted_urls = []
    original_send = cli.requests.Session.send

    def observed_send(session, request, **kwargs):
        attempted_urls.append(request.url)
        return original_send(session, request, **kwargs)

    monkeypatch.setattr(cli.requests.Session, "send", observed_send)

    with probe_server() as (other_port, other_received):
        destination = f"http://127.0.0.1:{other_port}/healthz"

        with probe_server(redirect_to=destination) as (port, received):
            args = probe_inputs(tmp_path, port, ["/redirect"])

            assert cli.run(args) == 3

            assert attempted_urls == [
                f"http://127.0.0.1:{port}/redirect"
            ]
            assert len(received) == 1
            assert other_received == []

            result = cli.load_json(args.output_dir / "results.json")
            assert result["total_http_requests_including_preparation"] == 1
            assert result["results"][0]["http_status"] == 302
            assert result["results"][0]["redirect_target"] == destination


def test_probe_slow_redirect_body_is_not_read(tmp_path):
    """302 응답의 본문이 지연돼도 상태와 Location으로 판정한다."""

    with probe_server() as (port, received):
        args = probe_inputs(
            tmp_path,
            port,
            ["/slow-302-body", "/healthz"],
        )
        args.timeout = 0.15

        suite = cli.load_json(args.cases)
        suite["cases"][0]["expected_app"] = {
            "http_status": 302,
            "redirect_path": "/accounts/login/",
        }
        args.cases.write_text(
            json.dumps(suite),
            encoding="utf-8",
        )

        # run은 로그 대조 전이므로 UNKNOWN(3)이 정상.
        assert cli.run(args) == 3

        result = cli.load_json(args.output_dir / "results.json")

        assert result["unexecuted_cases"] == 0
        assert len(received) == 2
        assert all(
            row["transport_status"] == "OK"
            for row in result["results"]
        )

        redirect = result["results"][0]
        assert redirect["http_status"] == 302
        assert redirect["http_expectation_match"] is True
        assert redirect["response_summary"]["body_bytes"] is None
        assert redirect["response_summary"]["sha256"] is None


@pytest.mark.parametrize(
    "path",
    ["/slow-stream-200", "/slow-stream-302"]
)
def test_streaming_body_respects_global_deadline(tmp_path, path):
    """느린 응답에서도 전체 실행 제한을 지키고 부분 결과를 보존한다."""

    with probe_server() as (port, received):
        args = probe_inputs(
            tmp_path,
            port,
            [path, "/healthz"]
        )

        args.timeout = 0.2
        args.max_duration = 0.25

        suite = cli.load_json(args.cases)

        suite["cases"][0]["expected_app"] = {
            "http_status": 302 if path.endswith("302") else 200,
            "body_bytes": 12,
        }

        args.cases.write_text(
            json.dumps(suite),
            encoding="utf-8"
        )

        started = time.monotonic()
        assert cli.run(args) == 2
        elapsed = time.monotonic() - started

        result = cli.load_json(
            args.output_dir / "results.json"
        )

        # 실행 제한 0.25초 + 테스트 환경 허용 오차
        assert elapsed < 0.60

        # 첫 요청만 전송되어야 한다.
        assert [row["path"] for row in received] == [path]

        # 부분 결과 보존
        assert result["total_http_requests_including_preparation"] == 1
        assert result["unexecuted_cases"] == 1
        assert len(result["results"]) == 1

        row = result["results"][0]

        assert row["transport_status"] == "ERROR"
        assert row["verdict"] == "ERROR"
        assert result["stopped_reason"]


@pytest.mark.parametrize(
    "origin_mode, expected_origin",
    [
        (None, "https://haven.example"),
        ("same", "https://haven.example"),
        ("absent", None),
        ("foreign", "https://attacker.invalid"),
    ],
)
def test_prepare_case_post_origin_modes(
    tmp_path, origin_mode, expected_origin
):
    """정상·생략·외부 Origin 시험을 구분한다."""
    payload = {
        "csrf_mode": "valid",
        "fields": {
            "title": "Origin test",
            "body": "Safe test content",
        },
    }

    if origin_mode is not None:
        payload["origin_mode"] = origin_mode

    payload_file = tmp_path / "origin_payload.json"
    payload_file.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    cli.validate_payload(payload, tmp_path)

    case = {
        "method": "POST",
        "path": "/posts/new/",
        "input_reference": payload_file.name,
    }

    budget = cli.RequestBudget(
        Namespace(
            max_requests=10,
            rate=5,
            timeout=3,
            max_duration=60,
        )
    )

    with cli.new_session() as session:
        session.cookies.set("csrftoken", "unit-csrf-token")

        fields, headers, file_info = cli.prepare_case_request(
            session,
            case,
            tmp_path,
            "https://haven.example:443",
            budget,
            "test-run",
            [],
            cli.MAX_RESPONSE,
        )

    assert headers.get("Origin") == expected_origin
    assert headers["X-CSRFToken"] == "unit-csrf-token"
    assert fields["csrfmiddlewaretoken"] == "unit-csrf-token"
    assert file_info is None


def test_login_prep_sends_same_origin(monkeypatch):
    """로그인 준비 POST에 정상 Origin과 CSRF 토큰을 포함한다."""
    requests_seen = []

    def fake_bounded_send(
        session, method, target, path, budget, request_id, **kwargs
    ):
        requests_seen.append({
            "method": method,
            "path": path,
            "headers": kwargs.get("headers", {}),
            "fields": kwargs.get("fields"),
        })

        if method == "GET":
            html = (
                b'<input name="csrfmiddlewaretoken" '
                b'value="unit-csrf-token">'
            )
            return {"status": 200}, html

        session.cookies.set("sessionid", "unit-session")
        return {
            "status": 302,
            "location": "/posts/",
        }, None

    monkeypatch.setattr(cli, "bounded_send", fake_bounded_send)
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: "member_a",
    )
    monkeypatch.setattr(
        cli.getpass,
        "getpass",
        lambda _prompt: "unit-password",
    )

    budget = cli.RequestBudget(
        Namespace(
            max_requests=10,
            rate=5,
            timeout=3,
            max_duration=60,
        )
    )

    with cli.new_session() as session:
        cli.prep_login(
            session,
            "https://haven.example:443",
            budget,
            "member_a",
            "test-run",
            [],
            cli.MAX_RESPONSE,
        )

    assert len(requests_seen) == 2

    login_post = requests_seen[1]

    assert login_post["method"] == "POST"
    assert login_post["path"] == "/accounts/login/"
    assert login_post["headers"]["Origin"] == (
        "https://haven.example"
    )
    assert login_post["headers"]["X-CSRFToken"] == (
        "unit-csrf-token"
    )
    assert login_post["fields"]["csrfmiddlewaretoken"] == (
        "unit-csrf-token"
    )


@pytest.mark.parametrize(
    "case_id, method, path, role, status",
    [
        (
            "SH-01-B-SHARED-BEFORE",
            "GET", "/posts/shared/", "member_b", 200
        ),
        (
            "SH-01-C-SHARED-BEFORE",
            "GET", "/posts/shared/", "member_c", 200
        ),
        (
            "SH-01-B-DETAIL-BEFORE",
            "GET", "/posts/1/", "member_b", 404
        ),
        (
            "SH-07-ANON-SHARED-GET",
            "GET", "/posts/shared/", "anonymous", 302
        ),
    ],
)
def test_phase2_share_contract(
    case_id, method, path, role, status
):
    """2회차 공유 전 접근 통제 fixture 계약을 확인한다."""
    fixture_root = ROOT / "fixtures"
    suite = cli.load_json(
        fixture_root / "cases_haven_template.json"
    )

    cli.validate_suite(suite, fixture_root)

    cases = {
        case["case_id"]: case
        for case in suite["cases"]
    }

    case = cases[case_id]

    assert case["phase"] == 2
    assert case["method"] == method
    assert case["path"] == path
    assert case["auth_role"] == role
    assert case["expected_app"]["http_status"] == status
    assert case["expected_waf"] == "NOT_APPLICABLE"
    assert case["verification_mode"] == "manual_required"

    if case_id == "SH-07-ANON-SHARED-GET":
        assert case["expected_app"]["redirect_path"] == (
            "/accounts/login/"
        )

@pytest.mark.parametrize(
    "case_id, role, method, path, status",
    [
        ("SH-01-B-SHARED-LIST",
         "member_b", "GET", "/posts/shared/", 200),
        ("SH-01-B-DETAIL-ALLOWED",
         "member_b", "GET", "/posts/1/", 200),
        ("SH-01-C-DETAIL-DENIED",
         "member_c", "GET", "/posts/1/", 404),
        ("SH-02-B-EDIT-GET-DENIED",
         "member_b", "GET", "/posts/1/edit/", 404),
        ("SH-02-B-EDIT-POST-DENIED",
         "member_b", "POST", "/posts/1/edit/", 404),
        ("SH-02-B-DELETE-POST-DENIED",
         "member_b", "POST", "/posts/1/delete/", 404),
        ("SH-02-B-SHARES-GET-DENIED",
         "member_b", "GET", "/posts/1/shares/", 404),
        ("SH-02-B-DELETE-GET-DENIED",
        "member_b", "GET", "/posts/1/delete/", 404),
        ("SH-02-B-SHARES-POST-DENIED",
        "member_b", "POST", "/posts/1/shares/", 404),
    ],
)
def test_phase2_shared_readonly_fixture(
    case_id, role, method, path, status
):
    """공유 후 읽기 허용·변경 거부 fixture를 검증한다."""
    fixture_root = ROOT / "fixtures"

    suite = cli.load_json(
        fixture_root / "cases_share_granted.json"
    )
    cli.validate_suite(suite, fixture_root)

    cases = {
        item["case_id"]: item
        for item in suite["cases"]
    }

    case = cases[case_id]

    assert case["phase"] == 2
    assert case["auth_role"] == role
    assert case["method"] == method
    assert case["path"] == path
    assert case["expected_app"]["http_status"] == status
    assert case["expected_waf"] == "NOT_APPLICABLE"
    assert case["verification_mode"] == "manual_required"


@pytest.mark.parametrize(
    "case_id, role, path, status",
    [
        ("SH-03-A-DETAIL-AFTER",
         "member_a", "/posts/1/", 200),
        ("SH-03-B-SHARED-LIST-AFTER",
         "member_b", "/posts/shared/", 200),
        ("SH-03-B-DETAIL-AFTER",
         "member_b", "/posts/1/", 404),
        ("SH-03-C-DETAIL-AFTER",
         "member_c", "/posts/1/", 404),
    ],
)
def test_phase2_share_revoked_fixture(
    case_id, role, path, status
):
    """공유 해제 이후의 접근 권한 fixture를 검증한다."""
    fixture_root = ROOT / "fixtures"

    suite = cli.load_json(
        fixture_root / "cases_share_revoked.json"
    )
    cli.validate_suite(suite, fixture_root)

    cases = {
        item["case_id"]: item
        for item in suite["cases"]
    }

    case = cases[case_id]

    assert case["phase"] == 2
    assert case["auth_role"] == role
    assert case["method"] == "GET"
    assert case["path"] == path
    assert case["input_reference"] is None
    assert case["expected_app"]["http_status"] == status
    assert case["expected_waf"] == "NOT_APPLICABLE"
    assert case["verification_mode"] == "manual_required"


def test_phase2_share_revoke_changes_access():
    """공유 해제 전후 B의 조회 권한 변화와 A의 소유권 유지를 확인한다."""
    fixture_root = ROOT / "fixtures"

    granted = cli.load_json(
        fixture_root / "cases_share_granted.json"
    )
    revoked = cli.load_json(
        fixture_root / "cases_share_revoked.json"
    )

    cli.validate_suite(granted, fixture_root)
    cli.validate_suite(revoked, fixture_root)

    before = {
        case["case_id"]: case
        for case in granted["cases"]
    }
    after = {
        case["case_id"]: case
        for case in revoked["cases"]
    }

    b_before = before["SH-01-B-DETAIL-ALLOWED"]
    b_after = after["SH-03-B-DETAIL-AFTER"]
    a_after = after["SH-03-A-DETAIL-AFTER"]

    assert b_before["path"] == b_after["path"]
    assert b_before["auth_role"] == b_after["auth_role"]

    # 공유 중에는 B가 읽을 수 있다.
    assert b_before["expected_app"]["http_status"] == 200

    # 공유 해제 후에는 B가 더 이상 읽을 수 없다.
    assert b_after["expected_app"]["http_status"] == 404

    # 공유 해제가 소유자 A의 조회 권한을 없애면 안 된다.
    assert a_after["expected_app"]["http_status"] == 200


@pytest.mark.parametrize(
    "case_id, role, path, status",
    [
        (
            "SH-06-A-INACTIVE-B-SHARED-LIST",
            "member_b", "/posts/shared/", 200
        ),
        (
            "SH-06-A-INACTIVE-B-DETAIL",
            "member_b", "/posts/1/", 404
        ),
        (
            "SH-06-A-INACTIVE-C-DETAIL",
            "member_c", "/posts/1/", 404
        ),
    ],
)
def test_phase2_owner_inactive_fixture(
    case_id, role, path, status
):
    """소유자 비활성화 이후의 접근 통제 fixture를 검증한다."""
    fixture_root = ROOT / "fixtures"

    suite = cli.load_json(
        fixture_root / "cases_owner_inactive.json"
    )
    cli.validate_suite(suite, fixture_root)

    cases = {
        item["case_id"]: item
        for item in suite["cases"]
    }

    case = cases[case_id]

    assert case["phase"] == 2
    assert case["method"] == "GET"
    assert case["path"] == path
    assert case["auth_role"] == role
    assert case["input_reference"] is None
    assert case["expected_app"]["http_status"] == status
    assert case["expected_waf"] == "NOT_APPLICABLE"
    assert case["verification_mode"] == "manual_required"


def test_phase2_owner_inactive_blocks_shared_access():
    """소유자 비활성화 전후 공유 대상의 조회 기대값을 비교한다."""
    fixture_root = ROOT / "fixtures"

    granted = cli.load_json(
        fixture_root / "cases_share_granted.json"
    )
    inactive = cli.load_json(
        fixture_root / "cases_owner_inactive.json"
    )

    cli.validate_suite(granted, fixture_root)
    cli.validate_suite(inactive, fixture_root)

    granted_cases = {
        case["case_id"]: case
        for case in granted["cases"]
    }
    inactive_cases = {
        case["case_id"]: case
        for case in inactive["cases"]
    }

    before = granted_cases["SH-01-B-DETAIL-ALLOWED"]
    after = inactive_cases["SH-06-A-INACTIVE-B-DETAIL"]

    assert before["path"] == after["path"] == "/posts/1/"
    assert before["auth_role"] == after["auth_role"] == "member_b"

    # A가 활성일 때 B에게 공유된 P1은 조회 가능.
    assert before["expected_app"]["http_status"] == 200

    # A가 비활성화되면 B의 조회도 차단.
    assert after["expected_app"]["http_status"] == 404


@pytest.mark.parametrize(
    "case_id, path, status",
    [
        ("SH-06-B-ACTIVE-BASELINE", "/posts/1/", 200),
        ("SH-06-B-INACTIVE-DETAIL", "/posts/1/", 302),
        ("SH-06-B-INACTIVE-SHARED-LIST", "/posts/shared/", 302),
    ],
)
def test_phase2_member_inactive_contract(case_id, path, status):
    fixture_root = ROOT / "fixtures"
    suite = cli.load_json(
        fixture_root / "cases_member_inactive.json"
    )
    cli.validate_suite(suite, fixture_root)

    cases = {c["case_id"]: c for c in suite["cases"]}
    case = cases[case_id]

    assert case["phase"] == 2
    assert case["method"] == "GET"
    assert case["auth_role"] == "member_b"
    assert case["path"] == path
    assert case["expected_app"]["http_status"] == status
    assert case["verification_mode"] == "manual_required"

    if status == 302:
        assert case["expected_app"]["redirect_path"] == (
            "/accounts/login/"
        )

    if case_id == "SH-06-B-INACTIVE-DETAIL":
        assert case["checkpoint_before"] == "deactivate_member_b"


def test_manual_checkpoint_reuses_member_b_session(
    tmp_path, monkeypatch
):
    """모의 응답에서 B 세션 유지·재로그인 방지를 검증한다."""
    args = inputs(tmp_path, 8765)
    args.cases = ROOT / "fixtures" / "cases_member_inactive.json"
    args.manual_checkpoints = True

    login_calls = []
    requests_seen = []
    inactive = {"value": False}

    def fake_login(session, target, budget, role, *a, **kw):
        login_calls.append(role)
        session.cookies.set("sessionid", "unit-b-session")

    def fake_send(
        session, method, target, path, budget, request_id, **kw
    ):
        requests_seen.append({
            "session_id": id(session),
            "cookie": session.cookies.get("sessionid"),
            "inactive": inactive["value"],
            "path": path,
        })

        status = 302 if inactive["value"] else 200

        return {
            "status": status,
            "elapsed_ms": 0.1,
            "location": (
                "/accounts/login/?next=" + path
                if status == 302 else None
            ),
            "body_bytes": 0,
            "sha256": None,
            "headers": {},
            "request_body_bytes": None,
        }, None

    def confirm_deactivation(prompt):
        assert "DEACTIVATED" in prompt
        inactive["value"] = True
        return "DEACTIVATED"

    monkeypatch.setattr(cli, "prep_login", fake_login)
    monkeypatch.setattr(cli, "bounded_send", fake_send)
    monkeypatch.setattr(
        "builtins.input", confirm_deactivation
    )

    assert cli.run(args) == 3  # 로그 대조 전이므로 UNKNOWN

    assert login_calls == ["member_b"]
    assert len(requests_seen) == 3

    # 세 요청 모두 동일한 메모리 세션과 쿠키 사용.
    assert len({
        request["session_id"] for request in requests_seen
    }) == 1
    assert all(
        request["cookie"] == "unit-b-session"
        for request in requests_seen
    )

    assert [r["inactive"] for r in requests_seen] == [
        False, True, True
    ]

    result = cli.load_json(
        args.output_dir / "results.json"
    )

    assert [
        r["http_status"] for r in result["results"]
    ] == [200, 302, 302]
    assert all(
        r["http_expectation_match"] is True
        for r in result["results"]
    )

    assert any(
        event["stage"] == "manual_checkpoint"
        for event in result["preparation_events"]
    )


def test_manual_checkpoint_requires_opt_in(tmp_path):
    """허용 옵션 없이 수동 체크포인트 실행을 시작하지 않는다."""
    args = inputs(tmp_path, 8765)
    args.cases = ROOT / "fixtures" / "cases_member_inactive.json"
    args.manual_checkpoints = False

    with pytest.raises(
        cli.ConfigError,
        match="--manual-checkpoints",
    ):
        cli.run(args)

    assert not args.output_dir.exists()


@pytest.mark.parametrize(
    "event, expected_id",
    [
        (
            {
                "request_id": "server-id",
                "client_request_id": "cli-id",
            },
            "cli-id",
        ),
        (
            {
                "request_id": "legacy-id",
            },
            "legacy-id",
        ),
        (
            {
                "httpRequest": {
                    "headers": [
                        {
                            "name": "x-haven-request-id",
                            "value": "waf-cli-id",
                        }
                    ]
                }
            },
            "waf-cli-id",
        ),
        (
            {
                "request_id": "server-id",
                "client_request_id": "",
            },
            "server-id",
        ),
        (
            {},
            None,
        ),
    ],
)
def test_log_request_id_compatibility(event, expected_id):
    """앱·WAF·기존 로그 형식의 요청 ID 추출을 검증한다."""
    assert cli.log_request_id(event) == expected_id


def test_trace_id_format():
    """생성한 Trace ID가 AWS Root 형식을 만족하는지 확인한다."""
    import re

    trace_id = cli.new_trace_id()

    assert re.fullmatch(
        r"Root=1-[0-9a-f]{8}-[0-9a-f]{24}",
        trace_id,
    )


def test_bounded_send_trace_id_header(monkeypatch):
    """실제 로컬 HTTP 요청에 Trace ID가 포함되는지 확인한다."""
    observed = []
    original_send = cli.requests.Session.send

    def capture_send(session, request, **kwargs):
        observed.append(
            request.headers.get("X-Amzn-Trace-Id")
        )
        return original_send(session, request, **kwargs)

    monkeypatch.setattr(
        cli.requests.Session, "send", capture_send
    )

    with probe_server() as (port, _received):
        target = f"http://127.0.0.1:{port}"
        trace_id = cli.new_trace_id()

        budget = cli.RequestBudget(
            Namespace(
                max_requests=5,
                rate=5,
                timeout=3,
                max_duration=30,
            )
        )

        with cli.new_session() as session:
            detail, _ = cli.bounded_send(
                session,
                "GET",
                target,
                "/healthz",
                budget,
                "test-request-id",
                trace_id=trace_id,
            )

        assert detail["status"] == 200
        assert observed == [trace_id]


@pytest.mark.parametrize(
    "value, expected",
    [
        (
            "Root=1-67891233-abcdef012345678912345678",
            "1-67891233-abcdef012345678912345678",
        ),
        (
            "Self=1-67891233-111111111111111111111111;"
            "Root=1-67891233-abcdef012345678912345678",
            "1-67891233-abcdef012345678912345678",
        ),
        (
            "1-67891233-abcdef012345678912345678",
            "1-67891233-abcdef012345678912345678",
        ),
        (
            "Root=invalid",
            None,
        ),
        (
            "Root=1-67891233-abcdef012345678912345678;"
            "Root=1-67891233-abcdef012345678912345678",
            None,
        ),
        (
            None,
            None,
        ),
    ],
)
def test_extract_trace_root(value, expected):
    """Trace Root 정규화 및 잘못된 형식 거부."""
    assert cli.extract_trace_root(value) == expected


@pytest.mark.parametrize(
    "scenario, expected_code",
    [
        ("matched", 0),
        ("mismatched", 3),
        ("missing", 3),
        ("duplicate", 3),
    ],
)
def test_real_trace_root_correlation(
    tmp_path, scenario, expected_code
):
    """Trace Root 일치·불일치·누락·중복을 검증한다."""

    now = datetime.now(timezone.utc)

    case = {
        "case_id": "TRACE-TEST",
        "category": "authorization",
        "method": "GET",
        "path": "/healthz",
        "auth_role": "anonymous",
        "expected_app": {"http_status": 200},
        "expected_waf": "ALLOW",
        "verification_mode": "http_only",
    }

    row = cli.base_record("trace-test-run", case)
    row.update(
        transport_status="OK",
        http_status=200,
        http_expectation_match=True,
    )

    run_json = tmp_path / "results.json"
    run_json.write_text(
        json.dumps({
            "run_id": "trace-test-run",
            "target_origin": "https://haven.example:443",
            "results": [row],
        }),
        encoding="utf-8",
    )

    waf_event = {
        "timestamp": int(now.timestamp() * 1000),
        "action": "ALLOW",
        "httpRequest": {
            "headers": [
                {
                    "name": "X-Amzn-Trace-Id",
                    "value": row["trace_id"],
                }
            ],
        },
    }

    app_event = {
        "ts": now.isoformat(),
        "request_id": (
            "Self=1-67891233-111111111111111111111111;"
            + row["trace_id"]
        ),
        "status": 200,
    }

    waf_events = [waf_event]

    if scenario == "mismatched":
        app_event["request_id"] = (
            "Root=1-67891233-000000000000000000000000"
        )

    elif scenario == "missing":
        # 기존 CLI ID가 있어도 실제 로그는 Root 없이 연결 금지.
        waf_event["httpRequest"]["headers"] = []
        waf_event["request_id"] = row["request_id"]
        app_event["request_id"] = row["request_id"]

    elif scenario == "duplicate":
        waf_events.append(dict(waf_event))

    waf_path = tmp_path / "waf.jsonl"
    app_path = tmp_path / "app.jsonl"

    waf_path.write_text(
        "".join(json.dumps(e) + "\n" for e in waf_events),
        encoding="utf-8",
    )
    app_path.write_text(
        json.dumps(app_event) + "\n",
        encoding="utf-8",
    )

    args = Namespace(
        run_json=run_json,
        waf_log=waf_path,
        app_log=app_path,
        output_dir=tmp_path / "correlated",
    )

    assert cli.correlate(args) == expected_code

    result = cli.load_json(
        args.output_dir / "correlated_results.json"
    )["results"][0]

    if scenario == "matched":
        assert result["correlation_status"] == "MATCHED"
        assert result["verdict"] == "PASS"
    else:
        assert result["correlation_status"] == "UNRESOLVED"
        assert result["verdict"] == "UNKNOWN"


@pytest.mark.parametrize(
    "invalid_condition",
    ["filtered_baseline", "wrong_path", "wrong_status"],
)
def test_selected_checkpoint_rejects_invalid_baseline(
    invalid_condition,
):
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_member_inactive.json"
    )

    baseline = suite["cases"][0]

    if invalid_condition == "filtered_baseline":
        baseline["phase"] = 1
    elif invalid_condition == "wrong_path":
        baseline["path"] = "/posts/2/"
    elif invalid_condition == "wrong_status":
        baseline["expected_app"]["http_status"] = 404

    selected = cli.select_phase(suite, 2)

    with pytest.raises(cli.ConfigError, match="기준 요청"):
        cli.validate_selected_checkpoint_sequence(selected)


def test_filtered_checkpoint_blocks_before_execution(
    tmp_path, monkeypatch
):
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_member_inactive.json"
    )
    suite["cases"][0]["phase"] = 1

    case_path = tmp_path / "filtered_cases.json"
    case_path.write_text(
        json.dumps(suite, ensure_ascii=False),
        encoding="utf-8",
    )

    args = inputs(tmp_path, 8765)
    args.cases = case_path
    args.phase = 2
    args.manual_checkpoints = True

    def fail_if_sent(*args, **kwargs):
        pytest.fail("사전 검증 실패 시 HTTP 전송 금지")

    monkeypatch.setattr(cli, "bounded_send", fail_if_sent)

    with pytest.raises(cli.ConfigError, match="기준 요청"):
        cli.run(args)

    assert not args.output_dir.exists()


def test_failed_baseline_prevents_manual_checkpoint(
    tmp_path, monkeypatch
):
    args = inputs(tmp_path, 8765)
    args.cases = (
        ROOT / "fixtures" / "cases_member_inactive.json"
    )
    args.manual_checkpoints = True

    sent_paths = []

    def fake_login(session, target, budget, role, *a, **kw):
        session.cookies.set("sessionid", "test-session")

    def fake_send(
        session, method, target, path, budget, request_id, **kw
    ):
        sent_paths.append(path)

        return {
            "status": 404,
            "elapsed_ms": 0.1,
            "location": None,
            "body_bytes": 0,
            "sha256": None,
            "headers": {},
            "request_body_bytes": None,
        }, None

    def forbid_checkpoint(prompt):
        pytest.fail("기준 요청 실패 후 체크포인트 실행 금지")

    monkeypatch.setattr(cli, "prep_login", fake_login)
    monkeypatch.setattr(cli, "bounded_send", fake_send)
    monkeypatch.setattr(
        "builtins.input", forbid_checkpoint
    )

    assert cli.run(args) == 2

    # 첫 번째 기준 요청만 전송되어야 한다.
    assert sent_paths == ["/posts/1/"]

    result = cli.load_json(
        args.output_dir / "results.json"
    )

    records = result["results"]

    assert len(records) == 2
    assert records[0]["http_status"] == 404
    assert records[0]["http_expectation_match"] is False

    # 체크포인트 시작 전에 중단된 기록.
    assert records[1]["transport_status"] == "ERROR"
    assert result["unexecuted_cases"] == 1

    assert not any(
        event["stage"] == "manual_checkpoint"
        for event in result["preparation_events"]
    )


@pytest.mark.parametrize(
    "case_id, role, path, expected_status",
    [
        (
            "APP-07-MEMBER-ADMIN-GET",
            "member_a",
            "/admin/accounts/",
            403,
        ),
        (
            "APP-07-MEMBER-EVENTS-GET",
            "member_b",
            "/admin/account-events/",
            403,
        ),
        (
            "APP-09-OPERATOR-ADMIN-GET",
            "operator",
            "/admin/accounts/",
            200,
        ),
        (
            "SH-07-OPERATOR-P1-DENIED",
            "operator",
            "/posts/1/",
            404,
        ),
    ],
)
def test_phase2_admin_access_contract(
    case_id, role, path, expected_status
):
    """2회차 관리자 접근 통제 fixture 계약 검증."""

    fixture_root = ROOT / "fixtures"
    suite = cli.load_json(
        fixture_root / "cases_haven_template.json"
    )

    cli.validate_suite(suite, fixture_root)

    cases = {
        case["case_id"]: case
        for case in suite["cases"]
    }

    case = cases[case_id]

    assert case["phase"] == 2
    assert case["auth_role"] == role
    assert case["method"] == "GET"
    assert case["path"] == path
    assert case["input_reference"] is None
    assert case["expected_app"]["http_status"] == expected_status
    assert case["expected_waf"] == "NOT_APPLICABLE"
    assert case["verification_mode"] == "manual_required"


@pytest.mark.parametrize(
    "case_id, role, method, status",
    [
        ("SH-04-A-SHARES-GET-BASELINE",
         "member_a", "GET", 200),
        ("SH-02-C-SHARES-GET-DENIED",
         "member_c", "GET", 404),
        ("SH-02-C-SHARES-POST-DENIED",
         "member_c", "POST", 404),
        ("SH-07-ANON-SHARES-GET",
         "anonymous", "GET", 302),
    ],
)
def test_phase2_share_management_access(
    case_id, role, method, status
):
    """공유 관리 엔드포인트의 역할별 시험 계약."""

    fixture_root = ROOT / "fixtures"
    suite = cli.load_json(
        fixture_root / "cases_share_granted.json"
    )

    cli.validate_suite(suite, fixture_root)

    cases = {
        item["case_id"]: item
        for item in suite["cases"]
    }

    case = cases[case_id]

    assert case["phase"] == 2
    assert case["path"] == "/posts/1/shares/"
    assert case["auth_role"] == role
    assert case["method"] == method
    assert case["expected_app"]["http_status"] == status
    assert case["expected_waf"] == "NOT_APPLICABLE"
    assert case["verification_mode"] == "manual_required"

    if method == "POST":
        assert case["input_reference"] == "post_empty_valid.json"
    else:
        assert case["input_reference"] is None

    if role == "anonymous":
        assert case["expected_app"]["redirect_path"] == (
            "/accounts/login/"
        )


def test_share_management_baseline_precedes_denials():
    """소유자 정상 대조군을 거부 시험보다 먼저 배치한다."""

    suite = cli.load_json(
        ROOT / "fixtures" / "cases_share_granted.json"
    )

    positions = {
        item["case_id"]: index
        for index, item in enumerate(suite["cases"])
    }

    baseline = positions["SH-04-A-SHARES-GET-BASELINE"]

    for case_id in (
        "SH-02-B-SHARES-GET-DENIED",
        "SH-02-B-SHARES-POST-DENIED",
        "SH-02-C-SHARES-GET-DENIED",
        "SH-02-C-SHARES-POST-DENIED",
    ):
        assert baseline < positions[case_id]


@pytest.mark.parametrize(
    "option, invalid_value",
    [
        ("timeout", 0),
        ("timeout", 31),
        ("max_requests", 0),
        ("max_requests", 1001),
        ("rate", 0),
        ("rate", 6),
        ("max_duration", 0),
        ("max_duration", 901),
        ("max_response_bytes", 0),
        ("max_response_bytes", cli.MAX_RESPONSE + 1),
    ],
)
def test_invalid_limits_block_before_network(
    tmp_path, monkeypatch, option, invalid_value
):
    """잘못된 한도는 HTTP 전송 및 출력 폴더 생성 전 거부."""

    args = inputs(tmp_path, 8765)
    setattr(args, option, invalid_value)

    def forbidden_send(*args, **kwargs):
        pytest.fail("잘못된 제한값으로 HTTP 전송 시도")

    monkeypatch.setattr(cli, "bounded_send", forbidden_send)

    with pytest.raises(cli.ConfigError, match=option):
        cli.run(args)

    assert not args.output_dir.exists()


def test_duration_limit_preserves_partial_results(
    tmp_path, monkeypatch
):
    """첫 요청 후 시간 한도를 초과하면 다음 요청을 보내지 않는다."""

    original_begin = cli.RequestBudget.begin

    def expire_before_second_request(self):
        if self.count == 1:
            self.started -= self.duration + 1

        return original_begin(self)

    monkeypatch.setattr(
        cli.RequestBudget,
        "begin",
        expire_before_second_request,
    )

    with probe_server() as (port, received):
        args = probe_inputs(
            tmp_path,
            port,
            ["/healthz"] * 3,
        )

        assert cli.run(args) == 2

        result = cli.load_json(
            args.output_dir / "results.json"
        )

        assert len(received) == 1
        assert result["total_http_requests_including_preparation"] == 1
        assert result["unexecuted_cases"] == 1
        assert len(result["results"]) == 2

        assert result["results"][0]["transport_status"] == "OK"
        assert result["results"][1]["transport_status"] == "ERROR"
        assert "전체 실행 시간 한도" in result["stopped_reason"]


@pytest.mark.parametrize(
    "include_content_length",
    [True, False],
)
def test_response_size_limit_stops_remaining_requests(
    tmp_path, monkeypatch, include_content_length
):
    """선언된 크기 또는 실제 수신 크기가 한도를 넘으면 중단."""

    sent = []

    def fake_send(session, request, **kwargs):
        sent.append(request.url)

        response = cli.requests.Response()
        response.status_code = 200
        response.url = request.url
        response._content = b"X" * 20
        response._content_consumed = True

        if include_content_length:
            response.headers["Content-Length"] = "20"

        return response

    monkeypatch.setattr(
        cli.NoRedirectBodySession,
        "send",
        fake_send,
    )

    args = probe_inputs(
        tmp_path,
        8765,
        ["/healthz"] * 2,
    )
    args.max_response_bytes = 8

    assert cli.run(args) == 2

    result = cli.load_json(
        args.output_dir / "results.json"
    )

    assert len(sent) == 1
    assert result["total_http_requests_including_preparation"] == 1
    assert result["unexecuted_cases"] == 1
    assert len(result["results"]) == 1
    assert result["results"][0]["transport_status"] == "ERROR"
    assert result["results"][0]["verdict"] == "ERROR"

    error = result["results"][0]["response_summary"]["error"]

    if include_content_length:
        assert "Content-Length" in error
    else:
        assert "실제 응답" in error


def test_login_preparation_respects_request_limit(
    tmp_path, monkeypatch
):
    """로그인 준비 GET도 전체 요청 수에 포함한다."""

    with server(tmp_path) as (port, waf, _app):
        suite = cli.load_json(
            ROOT / "fixtures" / "cases_local.json"
        )
        suite["cases"] = [
            {
                **suite["cases"][1],
                "auth_role": "member_a",
                "expected_app": {"http_status": 200},
            }
        ]

        case_file = tmp_path / "login_limit.json"
        case_file.write_text(
            json.dumps(suite),
            encoding="utf-8",
        )

        args = inputs(
            tmp_path,
            port,
            max_requests=1,
        )
        args.cases = case_file

        monkeypatch.setattr(
            "builtins.input",
            lambda prompt: "member_a",
        )
        monkeypatch.setattr(
            cli.getpass,
            "getpass",
            lambda prompt: "test-secret-password",
        )

        assert cli.run(args) == 2

        result_path = args.output_dir / "results.json"
        result = cli.load_json(result_path)

        assert result["total_http_requests_including_preparation"] == 1
        assert len(result["preparation_events"]) == 1
        assert result["preparation_events"][0]["stage"] == "login_form"
        assert result["results"][0]["transport_status"] == "ERROR"
        assert "요청 수 한도" in result["stopped_reason"]

        assert len(waf.read_text(encoding="utf-8").splitlines()) == 1

        assert "test-secret-password" not in result_path.read_text(
            encoding="utf-8"
        )


def test_csrf_preparation_respects_request_limit(tmp_path):
    """CSRF 준비 GET 이후 예산이 없으면 변경 POST를 전송하지 않는다."""

    with server(tmp_path) as (port, waf, _app):
        suite = cli.load_json(
            ROOT / "fixtures" / "cases_local.json"
        )

        suite["cases"] = [
            {
                **suite["cases"][0],
                "case_id": "LIMIT-CSRF-PREPARATION",
                "category": "csrf",
                "method": "POST",
                "path": "/posts/new/",
                "auth_role": "anonymous",
                "input_reference": "post_valid_record.json",
                "expected_app": {"http_status": 302},
            }
        ]

        case_file = tmp_path / "csrf_limit.json"
        case_file.write_text(
            json.dumps(suite),
            encoding="utf-8",
        )

        args = inputs(
            tmp_path,
            port,
            max_requests=1,
        )
        args.cases = case_file

        assert cli.run(args) == 2

        result = cli.load_json(
            args.output_dir / "results.json"
        )

        assert result["total_http_requests_including_preparation"] == 1
        assert len(result["preparation_events"]) == 1
        assert result["preparation_events"][0]["stage"] == "csrf_form"
        assert result["results"][0]["transport_status"] == "ERROR"
        assert "요청 수 한도" in result["stopped_reason"]

        # 실제 변경 POST는 전송되지 않아야 한다.
        assert len(waf.read_text(encoding="utf-8").splitlines()) == 1


def test_output_write_failure_returns_exit_code_2(
    tmp_path, monkeypatch
):
    """결과 기록 실패를 성공으로 처리하지 않는다."""

    def fail_save(*args, **kwargs):
        raise OSError("simulated output write failure")

    monkeypatch.setattr(cli, "save_results", fail_save)

    with probe_server() as (port, received):
        args = probe_inputs(
            tmp_path,
            port,
            ["/healthz"] * 2,
        )

        exit_code = cli.main([
            "run",
            "--target", args.target,
            "--allowlist", str(args.allowlist),
            "--cases", str(args.cases),
            "--fixture-dir", str(args.fixture_dir),
            "--output-dir", str(args.output_dir),
            "--rate", "5",
        ])

        assert exit_code == 2
        assert len(received) == 1

        assert not (
            args.output_dir / "results.json"
        ).exists()


@pytest.mark.parametrize(
    "origin, expected",
    [
        ("https://haven.example", "https://haven.example"),
        ("https://haven.example:443", "https://haven.example"),
        ("https://haven.example:8443", "https://haven.example:8443"),
        ("http://127.0.0.1:80", "http://127.0.0.1"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("http://[::1]:8000", "http://[::1]:8000"),
    ],
)
def test_serialize_origin_header(origin, expected):
    """기본 포트는 생략하고 비기본 포트는 유지한다."""
    assert cli.serialize_origin_header(origin) == expected


@pytest.mark.parametrize(
    "expected_waf, mode, expected_code, expected_verdict",
    [
        ("NOT_APPLICABLE", "http_only", 3, "UNKNOWN"),
        ("ALLOW", "http_only", 1, "FAIL"),
        ("COUNT", "http_only", 1, "FAIL"),
        ("BLOCK", "http_only", 0, "PASS"),
        ("BLOCK", "manual_required", 3, "UNKNOWN"),
    ],
)
def test_waf_block_requires_explicit_block_expectation(
    tmp_path, expected_waf, mode, expected_code, expected_verdict
):
    """예상하지 않은 WAF 차단이 앱 검증 PASS로 이어지지 않는다."""

    case = {
        "case_id": "WAF-BLOCK-TEST",
        "category": "SEC",
        "method": "POST",
        "path": "/posts/new/",
        "auth_role": "member_a",
        "expected_app": {"http_status": 403},
        "expected_waf": expected_waf,
        "verification_mode": mode,
    }

    row = cli.base_record("unit-run", case)
    row.update(
        transport_status="OK",
        http_status=403,
        http_expectation_match=True,
    )

    origin = "https://haven.example:443"

    run_file = tmp_path / "results.json"
    run_file.write_text(
        json.dumps({
            "run_id": "unit-run",
            "target_origin": origin,
            "results": [row],
            "unexecuted_cases": 0,
            "stopped_reason": None,
        }),
        encoding="utf-8",
    )

    waf_event = {
        "run_id": "unit-run",
        "target_origin": origin,
        "timestamp_utc": row["timestamp_utc"],
        "trace_id": row["trace_id"],
        "action": "BLOCK",
        "terminatingRuleId": "block-rule",
        "nonTerminatingMatchingRules": [
            {"ruleId": "count-rule", "action": "COUNT"}
        ],
    }

    waf_file = tmp_path / "waf.jsonl"
    waf_file.write_text(
        json.dumps(waf_event) + "\n",
        encoding="utf-8",
    )

    app_file = tmp_path / "app.jsonl"
    app_file.write_text("", encoding="utf-8")

    args = Namespace(
        run_json=run_file,
        waf_log=waf_file,
        app_log=app_file,
        output_dir=tmp_path / "correlated",
    )

    assert cli.correlate(args) == expected_code

    result = cli.load_json(
        args.output_dir / "correlated_results.json"
    )["results"][0]

    assert result["verdict"] == expected_verdict
    assert result["app_observed"] is False

    if expected_waf == "BLOCK":
        assert result["app_validity"] == "NOT_APPLICABLE"
    else:
        assert result["app_validity"] == "UNKNOWN"
        assert result["correlation_status"] == "UNRESOLVED"

    if expected_waf in {"ALLOW", "COUNT"}:
        assert result["waf_verdict"] == "BLOCK"
        assert result["correlation_status"] == "UNRESOLVED"
        assert result["app_observed"] is False


@pytest.mark.parametrize(
    "event, expected",
    [
        # 최상위 Count
        (
            {
                "nonTerminatingMatchingRules": [
                    {"ruleId": "TOP_COUNT", "action": "COUNT"}
                ]
            },
            ["TOP_COUNT"]
        ),

        # 규칙 그룹 내부 Count
        (
            {
                "ruleGroupList": [
                    {
                        "ruleGroupId": "GROUP_A",
                        "nonTerminatingMatchingRules": [
                            {"ruleId": "SQLi_BODY", "action": "COUNT"}
                        ]
                    }
                ]
            },
            ["GROUP_A::SQLi_BODY"]
        ),

        # 여러 그룹에 같은 이름의 규칙
        (
            {
                "ruleGroupList": [
                    {
                        "ruleGroupId": "GROUP_A",
                        "nonTerminatingMatchingRules": [
                            {"ruleId": "RULE_1", "action": "COUNT"}
                        ]
                    },
                    {
                        "ruleGroupId": "GROUP_B",
                        "nonTerminatingMatchingRules": [
                            {"ruleId": "RULE_1", "action": "COUNT"}
                        ]
                    }
                ]
            },
            ["GROUP_A::RULE_1", "GROUP_B::RULE_1"]
        ),

        # excludedRules 형식
        (
            {
                "ruleGroupList": [
                    {
                        "ruleGroupId": "GROUP_A",
                        "excludedRules": [
                            {
                                "ruleId": "LEGACY_RULE",
                                "exclusionType": "EXCLUDED_AS_COUNT"
                            }
                        ]
                    }
                ]
            },
            ["GROUP_A::LEGACY_RULE"]
        ),

        # Count가 아닌 CAPTCHA는 제외
        (
            {
                "nonTerminatingMatchingRules": [
                    {"ruleId": "CAPTCHA_RULE", "action": "CAPTCHA"}
                ]
            },
            []
        ),

        # AWS 로그의 null 필드 대응
        (
            {
                "nonTerminatingMatchingRules": None,
                "ruleGroupList": [
                    {
                        "ruleGroupId": "GROUP_A",
                        "nonTerminatingMatchingRules": None,
                        "excludedRules": None
                    }
                ]
            },
            []
        ),
    ],
)
def test_extract_count_rule_ids(event, expected):
    """AWS WAF Count 규칙을 최상위·그룹 내부에서 추출한다."""
    assert cli.extract_count_rule_ids(event) == expected


def test_correlate_group_count_allows_valid_app(tmp_path):
    """그룹 내부 Count + WAF ALLOW + 앱 정상 도달을 PASS로 판정한다."""

    case = {
        "case_id": "GROUP-COUNT-TEST",
        "category": "SEC",
        "method": "GET",
        "path": "/posts/",
        "auth_role": "member_a",
        "expected_app": {"http_status": 200},
        "expected_waf": "COUNT",
        "verification_mode": "http_only",
    }

    row = cli.base_record("unit-run", case)
    row.update(
        transport_status="OK",
        http_status=200,
        http_expectation_match=True,
    )

    origin = "https://haven.example:443"

    run_file = tmp_path / "results.json"
    run_file.write_text(
        json.dumps({
            "run_id": "unit-run",
            "target_origin": origin,
            "results": [row],
            "unexecuted_cases": 0,
            "stopped_reason": None,
        }),
        encoding="utf-8",
    )

    waf_event = {
        "run_id": "unit-run",
        "target_origin": origin,
        "timestamp_utc": row["timestamp_utc"],
        "trace_id": row["trace_id"],
        "action": "ALLOW",
        "ruleGroupList": [
            {
                "ruleGroupId": "SQLi_GROUP",
                "nonTerminatingMatchingRules": [
                    {"ruleId": "SQLi_BODY", "action": "COUNT"}
                ]
            }
        ],
    }

    app_event = {
        "run_id": "unit-run",
        "target_origin": origin,
        "timestamp_utc": row["timestamp_utc"],
        "trace_id": row["trace_id"],
        "http_status": 200,
    }

    waf_file = tmp_path / "waf.jsonl"
    waf_file.write_text(
        json.dumps(waf_event) + "\n",
        encoding="utf-8",
    )

    app_file = tmp_path / "app.jsonl"
    app_file.write_text(
        json.dumps(app_event) + "\n",
        encoding="utf-8",
    )

    args = Namespace(
        run_json=run_file,
        waf_log=waf_file,
        app_log=app_file,
        output_dir=tmp_path / "correlated",
    )

    assert cli.correlate(args) == 0

    result = cli.load_json(
        args.output_dir / "correlated_results.json"
    )["results"][0]

    assert result["count_rule_ids"] == [
        "SQLi_GROUP::SQLi_BODY"
    ]
    assert result["waf_verdict"] == "ALLOW"
    assert result["app_validity"] == "MATCH"
    assert result["verdict"] == "PASS"


def test_request_timestamp_uses_send_time_after_login_delay(
    tmp_path, monkeypatch
):
    """로그인 준비가 120초 넘게 걸려도 실제 전송 시각으로 로그를 대조한다."""

    clock = {
        "now": datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)
    }

    # 테스트용 UTC 시계
    monkeypatch.setattr(
        cli,
        "utc_now",
        lambda: clock["now"].isoformat(timespec="milliseconds")
    )

    def fake_login(*args, **kwargs):
        # 실제로 130초 기다리지 않고 시계만 이동
        clock["now"] += timedelta(seconds=130)

    monkeypatch.setattr(cli, "prep_login", fake_login)

    with probe_server() as (port, received):
        args = probe_inputs(
            tmp_path,
            port,
            ["/healthz"],
            ["member_a"]
        )

        assert cli.run(args) == 3

        result = cli.load_json(
            args.output_dir / "results.json"
        )

        row = result["results"][0]

        # 실제 HTTP 요청은 정상 전송
        assert row["transport_status"] == "OK"
        assert len(received) == 1

        # 로그인 준비 후 실제 전송 시각 기록
        expected_time = clock["now"].isoformat(
            timespec="milliseconds"
        )
        assert row["timestamp_utc"] == expected_time

        origin = cli.canonical_origin(args.target)

        # 실제 전송 시각에 기록된 로그는 정상 연결
        event = {
            "run_id": row["run_id"],
            "target_origin": origin,
            "timestamp_utc": expected_time,
        }

        assert cli.plausible_event(event, row, origin)

        # 로그인 준비 이전의 오래된 로그는 거부
        old_event = {
            **event,
            "timestamp_utc": (
                clock["now"] - timedelta(seconds=130)
            ).isoformat(timespec="milliseconds"),
        }

        assert not cli.plausible_event(
            old_event, row, origin
        )


@pytest.mark.parametrize("stage", ["username", "password"])
def test_login_input_eof_records_error(
    tmp_path, monkeypatch, capsys, stage
):
    """로그인 입력 EOF를 ERROR로 기록하고 후속 요청을 중단한다."""

    def raise_eof(_prompt):
        raise EOFError

    if stage == "username":
        monkeypatch.setattr("builtins.input", raise_eof)

    else:
        monkeypatch.setattr(
            "builtins.input",
            lambda _prompt: "test-user"
        )
        monkeypatch.setattr(
            cli.getpass, "getpass", raise_eof
        )

    with probe_server() as (port, received):
        args = probe_inputs(
            tmp_path,
            port,
            ["/healthz", "/healthz"],
            ["member_a", "anonymous"],
        )

        assert cli.run(args) == 2

        result = cli.load_json(
            args.output_dir / "results.json"
        )

        # 로그인 실패 후 실제 HTTP 요청이 발생하지 않아야 한다.
        assert received == []
        assert result["total_http_requests_including_preparation"] == 0

        # 실패한 첫 번째 케이스와 미실행 케이스를 구분한다.
        assert len(result["results"]) == 1
        assert result["unexecuted_cases"] == 1

        row = result["results"][0]

        assert row["transport_status"] == "ERROR"
        assert row["verdict"] == "ERROR"
        assert row["response_summary"]["error"]
        assert result["stopped_reason"]

        # 처리되지 않은 예외의 traceback이 출력되면 안 된다.
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err        


def test_login_eof_preserves_previous_results(
    tmp_path, monkeypatch
):
    """앞선 요청 결과를 유지하고 다음 역할의 로그인 EOF에서 중단한다."""

    original_login = cli.prep_login

    def fake_login(
        session, target, budget, role,
        run_id, prep_events, max_response_bytes
    ):
        if role == "member_a":
            # 첫 역할은 인증이 완료된 상황으로 가정한다.
            session.cookies.set(
                "sessionid",
                "test-member-a",
                domain="127.0.0.1",
                path="/",
            )
            return

        return original_login(
            session, target, budget, role,
            run_id, prep_events, max_response_bytes
        )

    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr(cli, "prep_login", fake_login)
    monkeypatch.setattr("builtins.input", raise_eof)

    with probe_server() as (port, received):
        args = probe_inputs(
            tmp_path,
            port,
            ["/healthz", "/healthz", "/healthz"],
            ["member_a", "member_b", "anonymous"],
        )

        assert cli.run(args) == 2

        result = cli.load_json(
            args.output_dir / "results.json"
        )

        # 첫 번째 요청만 정상 전송한다.
        assert len(received) == 1

        # 두 번째 케이스에서 중단된다.
        assert len(result["results"]) == 2
        assert result["unexecuted_cases"] == 1

        first = result["results"][0]
        second = result["results"][1]

        # 기존 성공 기록 유지
        assert first["transport_status"] == "OK"
        assert first["http_status"] == 200

        # 두 번째 로그인 EOF 기록
        assert second["transport_status"] == "ERROR"
        assert second["verdict"] == "ERROR"

        # 세 번째 요청은 실행하지 않는다.
        assert result["total_http_requests_including_preparation"] == 1
        assert result["stopped_reason"]


def test_stalled_body_deadline_preempts_read_timeout(tmp_path):
    """본문 수신이 멈춘 경우 전체 제한 시간이 우선 적용된다."""

    with probe_server() as (port, received):
        args = probe_inputs(
            tmp_path,
            port,
            ["/stall-body", "/healthz"],
        )

        # 개별 timeout 설정은 1.5초지만,
        # 실제 요청 timeout은 남은 전체 실행 예산으로 축소된다.
        args.timeout = 1.5
        args.max_duration = 0.25

        started = time.monotonic()
        assert cli.run(args) == 2
        elapsed = time.monotonic() - started

        result = cli.load_json(
            args.output_dir / "results.json"
        )

        # 개별 read timeout(1.5초)보다 먼저 중단돼야 한다.
        assert elapsed < 0.9

        # 첫 번째 요청 외에는 전송하지 않아야 한다.
        assert [row["path"] for row in received] == [
            "/stall-body"
        ]

        assert result["total_http_requests_including_preparation"] == 1
        assert result["unexecuted_cases"] == 1
        assert len(result["results"]) == 1

        row = result["results"][0]

        assert row["transport_status"] == "ERROR"
        assert row["verdict"] == "ERROR"
        assert "전체 실행 시간 한도" in result["stopped_reason"]


def test_multi_payload_validation(tmp_path):
    valid = {
        "variants": [
            {
                "id": "P01",
                "payload": {
                    "csrf_mode": "valid",
                    "fields": {
                        "username": "'",
                        "password": "dummy-only-not-real"
                    }
                }
            },
            {
                "id": "P02",
                "payload": {
                    "csrf_mode": "valid",
                    "fields": {
                        "username": "' OR '1'='1' -- ",
                        "password": "dummy-only-not-real"
                    }
                }
            }
        ]
    }

    # 정상적인 다중 페이로드
    cli.validate_payload(valid, tmp_path)

    invalid_samples = [
        {"variants": []},
        {
            "variants": [
                {"id": "P01", "payload": {}},
                {"id": "P01", "payload": {}}
            ]
        },
        {
            "variants": [
                {"id": "P01", "payload": {"fields": {"username": 123}}}
            ]
        },
        {
            "variants": [
                {"id": "P01", "payload": {"variants": []}}
            ]
        }
    ]

    for sample in invalid_samples:
        with pytest.raises(cli.ConfigError):
            cli.validate_payload(sample, tmp_path)



def test_multi_payload_expansion(tmp_path):
    payload = {
        "variants": [
            {
                "id": "P01",
                "payload": {
                    "csrf_mode": "valid",
                    "fields": {
                        "username": "'",
                        "password": "dummy"
                    }
                }
            },
            {
                "id": "P02",
                "payload": {
                    "csrf_mode": "valid",
                    "fields": {
                        "username": "' OR '1'='1' -- ",
                        "password": "dummy"
                    }
                }
            }
        ]
    }

    (tmp_path / "variants.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    case = {
        "case_id": "SEC-01",
        "phase": 2,
        "category": "injection",
        "method": "POST",
        "path": "/accounts/login/",
        "auth_role": "anonymous",
        "input_reference": "variants.json",
        "expected_app": {"http_status": 400},
        "expected_waf": "NOT_APPLICABLE",
        "max_requests": 2,
        "note": "다중 SQLi 테스트"
    }

    legacy = {
        **case,
        "case_id": "APP-04-ANON-GET",
        "method": "GET",
        "path": "/posts/",
        "input_reference": None,
        "max_requests": 1
    }

    suite = {
        "schema_version": 1,
        "suite_id": "multi-payload-test",
        "suite_kind": "regression",
        "cases": [case, legacy]
    }

    cli.validate_suite(suite, tmp_path)

    expanded = cli.expand_suite_variants(suite, tmp_path)

    assert len(expanded["cases"]) == 3

    assert [
        c["case_id"] for c in expanded["cases"]
    ] == [
        "SEC-01-P01",
        "SEC-01-P02",
        "APP-04-ANON-GET"
    ]

    first, second, unchanged = expanded["cases"]

    assert first["parent_case_id"] == "SEC-01"
    assert first["payload_id"] == "P01"
    assert second["payload_id"] == "P02"

    assert first["_variant_payload"]["fields"]["username"] == "'"
    assert second["_variant_payload"]["fields"]["username"] == "' OR '1'='1' -- "

    assert first["max_requests"] == 1
    assert second["max_requests"] == 1

    # 기존 단일 케이스는 변경하지 않는다.
    assert unchanged == legacy

    # 원본 suite 역시 변경되지 않는다.
    assert len(suite["cases"]) == 2
    assert suite["cases"][0]["case_id"] == "SEC-01"
    assert "_variant_payload" not in suite["cases"][0]

    # 확장 ID가 기존 case_id와 충돌하면 거부한다.
    collision_suite = {
        **suite,
        "cases": [
            case,
            {**legacy, "case_id": "SEC-01-P01"}
        ]
    }

    with pytest.raises(cli.ConfigError):
        cli.expand_suite_variants(collision_suite, tmp_path)


def test_multi_payload_http_execution(tmp_path, monkeypatch):
    from urllib.parse import parse_qs

    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()

    variants = {
        "variants": [
            {
                "id": "P01",
                "payload": {
                    "csrf_mode": "valid",
                    "fields": {
                        "username": "'",
                        "password": "dummy-test-only"
                    }
                }
            },
            {
                "id": "P02",
                "payload": {
                    "csrf_mode": "valid",
                    "fields": {
                        "username": "' OR '1'='1' -- ",
                        "password": "dummy-test-only"
                    }
                }
            }
        ]
    }

    (fixture_dir / "variants.json").write_text(
        json.dumps(variants),
        encoding="utf-8"
    )

    suite = {
        "schema_version": 1,
        "suite_id": "multi-payload-http-test",
        "suite_kind": "regression",
        "cases": [
            {
                "case_id": "SEC-01",
                "phase": 2,
                "category": "injection",
                "method": "POST",
                "path": "/accounts/login/",
                "auth_role": "anonymous",
                "input_reference": "variants.json",
                # Mock 서버는 유효 CSRF 로그인 POST에 302를 반환한다.
                "expected_app": {"http_status": 302},
                "expected_waf": "NOT_APPLICABLE",
                "max_requests": 2,
                "verification_mode": "manual_required",
                "note": "다중 payload 전송 기능 시험"
            }
        ]
    }

    suite_file = tmp_path / "suite.json"
    suite_file.write_text(
        json.dumps(suite),
        encoding="utf-8"
    )

    observed = []
    original_send = cli.requests.Session.send

    def capture_send(session, prepared, **kwargs):
        if (
            prepared.method == "POST"
            and prepared.path_url == "/accounts/login/"
        ):
            body = prepared.body
            if isinstance(body, bytes):
                body = body.decode("utf-8")

            fields = parse_qs(body)
            observed.append(fields["username"][0])

        return original_send(session, prepared, **kwargs)

    monkeypatch.setattr(
        cli.requests.Session,
        "send",
        capture_send
    )

    with server(tmp_path) as (port, waf, app):
        args = inputs(tmp_path, port)
        args.cases = suite_file
        args.fixture_dir = fixture_dir

        # 로그 검증 전이므로 UNKNOWN(3)이 정상이다.
        assert cli.run(args) == 3

        result_path = args.output_dir / "results.json"
        result = cli.load_json(result_path)
        records = result["results"]

        # 두 페이로드가 실제로 각각 전송됐는지 확인한다.
        assert observed == [
            "'",
            "' OR '1'='1' -- "
        ]

        assert len(records) == 2
        assert [r["case_id"] for r in records] == [
            "SEC-01-P01",
            "SEC-01-P02"
        ]

        assert [r["payload_id"] for r in records] == [
            "P01", "P02"
        ]

        assert all(
            r["parent_case_id"] == "SEC-01"
            for r in records
        )

        # 두 요청의 식별자는 서로 달라야 한다.
        assert len({r["request_id"] for r in records}) == 2
        assert len({r["trace_id"] for r in records}) == 2

        assert result["selected_cases"] == 1
        assert result["execution_cases"] == 2
        assert result["unexecuted_cases"] == 0

        # CSRF 준비 GET 1건 + POST 2건
        assert result["total_http_requests_including_preparation"] == 3

        # 결과 파일에 원본 payload와 비밀번호를 저장하지 않는다.
        raw = result_path.read_text(encoding="utf-8")
        assert "_variant_payload" not in raw
        assert "dummy-test-only" not in raw

        # CSV에도 페이로드 식별자가 있어야 한다.
        csv_header = (
            args.output_dir / "summary.csv"
        ).read_text(encoding="utf-8-sig").splitlines()[0]

        assert "parent_case_id" in csv_header
        assert "payload_id" in csv_header

        # 로그 상관분석에서 확장 요청을 개별적으로 연결한다.
        corr_args = Namespace(
            run_json=result_path,
            waf_log=waf,
            app_log=app,
            output_dir=tmp_path / "correlated"
        )

        # manual_required이므로 로그 연결 후에도 최종 판정은 UNKNOWN.
        assert cli.correlate(corr_args) == 3

        correlated = cli.load_json(
            corr_args.output_dir / "correlated_results.json"
        )["results"]

        assert len(correlated) == 2
        assert all(
            r["correlation_status"] == "MATCHED"
            for r in correlated
        )
        assert all(
            r["verdict"] == "UNKNOWN"
            for r in correlated
        )
