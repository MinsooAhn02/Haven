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
    observed_cookies = []
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
            observed_cookies.append(prepared.headers.get("Cookie", ""))

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

        # 이전 로그인 시도에서 발급된 세션 쿠키가
        # 다음 로그인 페이로드에 전달되면 안 된다.
        assert len(observed_cookies) == 2

        assert all(
            "sessionid=fixture-session" not in cookie
            for cookie in observed_cookies
        )

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

        # 익명 로그인 variant별 CSRF 준비 GET 2건 + POST 2건
        assert result["total_http_requests_including_preparation"] == 4

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


@pytest.mark.parametrize(
    "suite_path",
    sorted((ROOT / "fixtures").glob("cases_*.json")),
    ids=lambda path: path.name
)
def test_all_case_fixtures_validate(suite_path):
    """모든 시험 suite의 형식과 다중 payload 확장을 검증한다."""

    fixture_root = ROOT / "fixtures"

    # 1. JSON 파일 로드
    suite = cli.load_json(suite_path)

    # 2. Suite 및 참조 payload 유효성 검사
    cli.validate_suite(suite, fixture_root)

    # 3. 다중 payload 확장 검사
    expanded = cli.expand_suite_variants(
        suite,
        fixture_root
    )

    original_cases = suite["cases"]
    expanded_cases = expanded["cases"]

    # 4. 확장 후 케이스가 누락되지 않았는지 확인
    assert len(expanded_cases) >= len(original_cases)

    # 5. 모든 실행 case_id가 고유해야 한다.
    case_ids = [case["case_id"] for case in expanded_cases]

    assert len(case_ids) == len(set(case_ids))

    # 6. 다중 payload의 식별 정보 확인
    for case in expanded_cases:
        if "parent_case_id" in case:
            assert case["payload_id"].startswith("P")
            assert case["max_requests"] == 1
            assert "_variant_payload" in case

# Phase-two orchestration checks use in-memory transports only.

def phase2_make_case(case_id="SH-TEST", *, method="GET", path="/posts/1/",
              role="member_a", status=200, **extra):
    case = {
        "case_id": case_id,
        "phase": 2,
        "category": "sharing",
        "method": method,
        "path": path,
        "auth_role": role,
        "input_reference": "post_empty_valid.json" if method == "POST" else None,
        "expected_app": {"http_status": status},
        "expected_waf": "NOT_APPLICABLE",
        "max_requests": 1,
        "verification_mode": "manual_required",
        "note": "Synthetic orchestration test; not a Django integration result",
    }
    case.update(extra)
    return case


def phase2_make_suite(cases, **extra):
    return {
        "schema_version": 1,
        "suite_id": "phase2-synthetic-orchestration",
        "suite_kind": "regression",
        "cases": cases,
        **extra,
    }


def phase2_make_args(tmp_path, suite, *, maximum=100):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps({"approved_origins": ["http://127.0.0.1:8765"]}),
        encoding="utf-8",
    )
    suite_file = tmp_path / "suite.json"
    suite_file.write_text(json.dumps(suite), encoding="utf-8")
    return Namespace(
        target="http://127.0.0.1:8765", allowlist=allowlist,
        cases=suite_file, fixture_dir=ROOT / "fixtures",
        output_dir=tmp_path / "results", phase=2,
        timeout=3, max_requests=maximum, rate=5,
        max_duration=60, max_response_bytes=cli.MAX_RESPONSE,
        manual_checkpoints=False,
    )


def phase2_detail(status=200, location=None):
    return {
        "status": status, "location": location, "elapsed_ms": 0.1,
        "body_bytes": 0, "sha256": None, "headers": {},
        "request_body_bytes": None,
    }


def phase2_share_row(post_id=1, share_id=81, recipient="member_b", *, action=None):
    action = action if action is not None else f"/posts/{post_id}/shares/{share_id}/revoke/"
    return (
        '<li class="record-row"><div>'
        f'<h3 class="record-title">{recipient}</h3>'
        '</div><form method="post" '
        f'action="{action}"><button>Revoke</button></form></li>'
    )


def phase2_share_html(*rows):
    return (
        '<html><section aria-labelledby="share-list-heading">'
        '<h2 id="share-list-heading">Current shares</h2>'
        '<ul class="record-list">' + "".join(rows) + '</ul></section></html>'
    ).encode()


def phase2_reference(post_id=1, recipient="member_b", **extra):
    return {
        "post_id": post_id,
        "recipient": recipient,
        "lookup_role": "member_a",
        **extra,
    }


class Phase2MemoryResponse:
    """Minimal requests response; no sockets, server threads, or DB access."""

    status_code = 200
    headers = {}

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        for index in range(0, len(self.body), 8):
            yield self.body[index:index + 8]


def phase2_command_arguments(args):
    return [
        "run", "--target", args.target,
        "--allowlist", str(args.allowlist), "--cases", str(args.cases),
        "--phase", "2", "--fixture-dir", str(args.fixture_dir),
        "--output-dir", str(args.output_dir),
        "--max-requests", str(args.max_requests),
        "--max-duration", str(args.max_duration), "--rate", str(args.rate),
        "--timeout", str(args.timeout),
    ]


def phase2_local_auth_args(tmp_path, *, roles=("member_a", "member_b", "member_c", "operator")):
    cases = [phase2_make_case(f"LOCAL-{role.upper()}", role=role) for role in roles]
    args = phase2_make_args(tmp_path, phase2_make_suite(cases))
    args.target = "http://127.0.0.1:8000"
    args.allowlist.write_text(json.dumps({"approved_origins": [args.target]}), encoding="utf-8")
    return args


class TestPhase2Integration:
    """Keep network blocking local to these tests; legacy fake servers still work."""

    @pytest.fixture(autouse=True)
    def prohibit_real_requests(self, monkeypatch):
        def prohibited(*args, **kwargs):
            raise AssertionError("This test must not send a real HTTP request")

        monkeypatch.setattr(cli.requests.Session, "send", prohibited)
        monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    @pytest.mark.parametrize("role", ["member_a", "member_b", "member_c", "operator"])
    def test_local_seed_authentication_covers_all_four_roles(self, monkeypatch, capsys, role):
        """The common local password avoids prompts without mixing role sessions."""
        secret = "synthetic-secret-not-a-real-password"
        monkeypatch.setenv("HAVEN_SEED_PASSWORD", secret)
        monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("Unexpected username prompt"))
        monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: pytest.fail("Unexpected password prompt"))
        login_fields = []

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            assert target == "http://127.0.0.1:8000"
            if method == "GET":
                session.cookies.set("csrftoken", "test-csrf")
                return phase2_detail(), b'<input name="csrfmiddlewaretoken" value="test-csrf">'
            login_fields.append(kwargs["fields"])
            session.cookies.set("sessionid", "synthetic-session")
            return phase2_detail(302, "/posts/"), None

        monkeypatch.setattr(cli, "bounded_send", fake_send)
        budget = cli.RequestBudget(Namespace(max_requests=10, rate=5, timeout=3, max_duration=60))
        events = []
        with cli.new_session() as session:
            cli.prep_login(session, "http://127.0.0.1:8000", budget, role, "unit-run", events, cli.MAX_RESPONSE)
        assert login_fields[0]["username"] == role
        assert login_fields[0]["password"] == secret
        assert secret not in json.dumps(events)
        assert secret not in capsys.readouterr().out

    @pytest.mark.parametrize("target", ["http://localhost:8000", "http://127.0.0.1:8765", "https://haven.example:443"])
    def test_seed_password_does_not_expand_to_other_origins(self, monkeypatch, target):
        monkeypatch.setenv("HAVEN_SEED_PASSWORD", "must-not-be-used")
        prompts = []
        monkeypatch.setattr("builtins.input", lambda prompt: prompts.append("username") or "member_a")
        monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: prompts.append("password") or "interactive-test-secret")
        fields_seen = []

        def fake_send(session, method, origin, path, budget, request_id, **kwargs):
            if method == "GET":
                return phase2_detail(), b'<input name="csrfmiddlewaretoken" value="test-csrf">'
            fields_seen.append(kwargs["fields"])
            session.cookies.set("sessionid", "synthetic-session")
            return phase2_detail(302, "/posts/"), None

        monkeypatch.setattr(cli, "bounded_send", fake_send)
        budget = cli.RequestBudget(Namespace(max_requests=10, rate=5, timeout=3, max_duration=60))
        with cli.new_session() as session:
            cli.prep_login(session, target, budget, "member_a", "unit-run", [], cli.MAX_RESPONSE)
        assert prompts == ["username", "password"]
        assert fields_seen[0]["password"] == "interactive-test-secret"

    def test_share_id_is_matched_to_exact_recipient_in_the_same_row(self):
        html = phase2_share_html(
            phase2_share_row(1, 17, "member_b_extra"),
            phase2_share_row(1, 23, "member_c"),
            phase2_share_row(1, 81, "member_b"),
        )
        assert cli.parse_share_id(html, 1, "member_b") == 81
        assert cli.parse_share_id(html, 1, "not-present") is None

    def test_ambiguous_share_rows_are_rejected(self):
        html = phase2_share_html(phase2_share_row(1, 81), phase2_share_row(1, 82))
        with pytest.raises(cli.ConfigError):
            cli.parse_share_id(html, 1, "member_b")

    @pytest.mark.parametrize("html", [
        b'<h2 id="share-list-heading">Current shares</h2>',
        b'<section aria-labelledby="share-list-heading"></section>',
    ])
    def test_missing_share_is_confirmed_only_in_a_recognized_share_list(self, html):
        assert cli.parse_share_id(html, 1, "member_b") is None

    @pytest.mark.parametrize("html", [
        b"",
        b"<html><body>Unrelated page</body></html>",
        b'<html><form action="/accounts/login/">Login</form></html>',
        b'<html><ul class="record-list"></ul></html>',
    ])
    def test_arbitrary_success_html_cannot_prove_that_a_share_is_absent(self, html):
        with pytest.raises(cli.ConfigError):
            cli.parse_share_id(html, 1, "member_b")

    def test_matching_share_row_remains_usable_without_the_empty_list_marker(self):
        assert cli.parse_share_id(phase2_share_row(1, 81).encode(), 1, "member_b") == 81

    @pytest.mark.parametrize("share_id", ["9" * 20, str(2**63), "9" * 5000])
    def test_share_ids_outside_bigint_range_are_rejected_without_large_int_conversion(self, share_id):
        with pytest.raises(cli.ConfigError):
            cli.parse_share_id(phase2_share_html(phase2_share_row(1, share_id)), 1, "member_b")

    def test_largest_valid_bigint_share_id_is_supported(self):
        largest = 2**63 - 1
        assert cli.parse_share_id(phase2_share_html(phase2_share_row(1, largest)), 1, "member_b") == largest

    @pytest.mark.parametrize("action", [
        "https://outside.invalid/posts/1/shares/81/revoke/",
        "//outside.invalid/posts/1/shares/81/revoke/",
        "/posts/2/shares/81/revoke/",
        "/posts/1/shares/0/revoke/",
        "/posts/1/shares/81/revoke/?unexpected=1",
        "/posts/1/shares/81/revoke/#fragment",
    ])
    def test_share_parser_rejects_untrusted_or_wrong_post_actions(self, action):
        with pytest.raises(cli.ConfigError):
            cli.parse_share_id(phase2_share_html(phase2_share_row(action=action)), 1, "member_b")

    @pytest.mark.parametrize("change", [
        {"post_id": 0}, {"post_id": True}, {"post_id": "1"},
        {"recipient": "anonymous"}, {"lookup_role": "anonymous"},
        {"allow_missing": "yes"}, {"unexpected": "field"},
    ])
    def test_invalid_share_metadata_fails_before_execution(self, change):
        case = phase2_make_case(method="POST", path="/posts/1/shares/{share_id}/revoke/", status=302,
                         share_reference=phase2_reference(**change))
        with pytest.raises(cli.ConfigError):
            cli.validate_suite(phase2_make_suite([case]), ROOT / "fixtures")

    def test_share_placeholder_requires_a_lookup_specification(self):
        case = phase2_make_case(method="POST", path="/posts/1/shares/{share_id}/revoke/", status=302)
        with pytest.raises(cli.ConfigError):
            cli.validate_suite(phase2_make_suite([case]), ROOT / "fixtures")

    def test_share_lookup_uses_owner_session_and_counts_preparation(self, monkeypatch):
        case = phase2_make_case(method="POST", path="/posts/1/shares/{share_id}/revoke/", role="member_b", status=404,
                         share_reference=phase2_reference())
        sessions, prepped, events, seen = {}, {}, [], []
        budget = cli.RequestBudget(Namespace(max_requests=10, rate=5, timeout=3, max_duration=60))

        def fake_login(session, target, budget, role, *args):
            assert role == "member_a"
            budget.begin()
            budget.begin()
            session.cookies.set("role", role)

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            budget.begin()
            seen.append((session.cookies.get("role"), method, path, kwargs))
            return phase2_detail(), phase2_share_html(phase2_share_row(1, 81))

        monkeypatch.setattr(cli, "prep_login", fake_login)
        monkeypatch.setattr(cli, "bounded_send", fake_send)
        try:
            assert cli.resolve_share_id(case, sessions, prepped, "http://127.0.0.1:8765", budget, "unit-run", events, cli.MAX_RESPONSE) == 81
        finally:
            for session in sessions.values():
                session.close()
        assert seen[0][:3] == ("member_a", "GET", "/posts/1/shares/")
        assert seen[0][3]["capture_html"] is True
        assert budget.count == 3
        assert prepped["member_a"] is True
        assert any(event["stage"] == "share_lookup" for event in events)

    @pytest.mark.parametrize("status", [302, 403, 404, 500])
    def test_failed_share_lookup_never_treats_a_redirect_or_error_as_a_match(self, monkeypatch, status):
        case = phase2_make_case(method="POST", path="/posts/1/shares/{share_id}/revoke/", status=302,
                         share_reference=phase2_reference())
        owner = cli.new_session()
        monkeypatch.setattr(cli, "bounded_send", lambda *args, **kwargs: (phase2_detail(status), phase2_share_html(phase2_share_row())))
        budget = cli.RequestBudget(Namespace(max_requests=10, rate=5, timeout=3, max_duration=60))
        try:
            with pytest.raises(cli.ExecutionError):
                cli.resolve_share_id(case, {"member_a": owner}, {"member_a": True}, "http://127.0.0.1:8765", budget, "unit-run", [], cli.MAX_RESPONSE)
        finally:
            owner.close()

    def test_share_discovery_html_is_returned_without_a_login_route(self, monkeypatch):
        body = phase2_share_html(phase2_share_row())
        monkeypatch.setattr(cli.requests.Session, "send", lambda *args, **kwargs: Phase2MemoryResponse(body))
        budget = cli.RequestBudget(Namespace(max_requests=10, rate=5, timeout=3, max_duration=60))
        with cli.new_session() as session:
            observed, html = cli.bounded_send(
                session, "GET", "http://127.0.0.1:8765", "/posts/1/shares/", budget,
                "unit-request", capture_html=True, max_response_bytes=4096,
            )
        assert html == body
        assert observed["body_bytes"] == len(body)
        assert budget.count == 1

    def test_chunked_share_discovery_still_obeys_response_limit(self, monkeypatch):
        monkeypatch.setattr(cli.requests.Session, "send", lambda *args, **kwargs: Phase2MemoryResponse(b"X" * 33))
        budget = cli.RequestBudget(Namespace(max_requests=10, rate=5, timeout=3, max_duration=60))
        with cli.new_session() as session:
            with pytest.raises(cli.TooLargeResponse):
                cli.bounded_send(
                    session, "GET", "http://127.0.0.1:8765", "/posts/1/shares/", budget,
                    "unit-request", capture_html=True, max_response_bytes=32,
                )
        assert budget.count == 1

    def test_missing_share_stops_before_sending_a_revoke(self, tmp_path, monkeypatch):
        case = phase2_make_case(method="POST", path="/posts/1/shares/{share_id}/revoke/", status=302,
                         share_reference=phase2_reference())
        args = phase2_make_args(tmp_path, phase2_make_suite([case]))
        seen = []
        monkeypatch.setattr(cli, "prep_login", lambda *args: None)

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            budget.begin()
            seen.append((method, path))
            assert method == "GET"
            return phase2_detail(), phase2_share_html()

        monkeypatch.setattr(cli, "bounded_send", fake_send)
        assert cli.run(args) == 2
        result = cli.load_json(args.output_dir / "results.json")
        assert seen == [("GET", "/posts/1/shares/")]
        assert result["results"][0]["transport_status"] == "ERROR"
        assert result["results"][0]["http_status"] is None

    def test_dynamic_revoke_uses_actual_id_not_sequence_one(self, tmp_path, monkeypatch):
        case = phase2_make_case(method="POST", path="/posts/1/shares/{share_id}/revoke/", status=302,
                         share_reference=phase2_reference())
        args = phase2_make_args(tmp_path, phase2_make_suite([case]))
        seen = []

        def fake_login(session, *args):
            session.cookies.set("csrftoken", "synthetic-csrf")

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            budget.begin()
            seen.append((method, path))
            if method == "GET":
                return phase2_detail(), phase2_share_html(phase2_share_row(1, 81))
            assert path == "/posts/1/shares/81/revoke/"
            return phase2_detail(302, "/posts/1/shares/"), None

        monkeypatch.setattr(cli, "prep_login", fake_login)
        monkeypatch.setattr(cli, "bounded_send", fake_send)
        assert cli.run(args) == 3
        result = cli.load_json(args.output_dir / "results.json")
        assert seen == [("GET", "/posts/1/shares/"), ("POST", "/posts/1/shares/81/revoke/")]
        assert result["results"][0]["path"] == "/posts/1/shares/81/revoke/"
        assert result["results"][0]["http_expectation_match"] is True
        assert result["total_http_requests_including_preparation"] == 2

    def test_cross_post_check_uses_the_other_posts_existing_share(self, tmp_path, monkeypatch):
        case = phase2_make_case(method="POST", path="/posts/1/shares/{share_id}/revoke/", status=404,
                         share_reference=phase2_reference(2, "member_c"))
        args = phase2_make_args(tmp_path, phase2_make_suite([case]))
        seen = []
        monkeypatch.setattr(cli, "prep_login", lambda session, *args: session.cookies.set("csrftoken", "synthetic-csrf"))

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            budget.begin()
            seen.append((method, path))
            if method == "GET":
                assert path == "/posts/2/shares/"
                return phase2_detail(), phase2_share_html(phase2_share_row(2, 92, "member_c"))
            assert path == "/posts/1/shares/92/revoke/"
            return phase2_detail(404), None

        monkeypatch.setattr(cli, "bounded_send", fake_send)
        assert cli.run(args) == 3
        assert seen == [("GET", "/posts/2/shares/"), ("POST", "/posts/1/shares/92/revoke/")]

    def test_critical_mismatch_stops_dependants_but_attempts_registered_cleanup(self, tmp_path, monkeypatch):
        mutation = phase2_make_case("DISABLE-B", method="POST", path="/admin/accounts/2/status/", role="operator", status=302, critical=True)
        mutation["input_reference"] = "basic_status_disable.json"
        dependent = phase2_make_case("B-INACTIVE", role="member_b", status=302)
        restore = phase2_make_case("RESTORE-B", method="POST", path="/admin/accounts/2/status/", role="operator", status=302, after_case="DISABLE-B")
        restore["input_reference"] = "basic_status_enable.json"
        args = phase2_make_args(tmp_path, phase2_make_suite([mutation, dependent], cleanup_cases=[restore]))
        sent_states = []
        monkeypatch.setattr(cli, "prep_login", lambda session, *args: session.cookies.set("csrftoken", "synthetic-csrf"))

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            budget.begin()
            sent_states.append(kwargs["fields"]["is_active"])
            return phase2_detail(500 if len(sent_states) == 1 else 302), None

        monkeypatch.setattr(cli, "bounded_send", fake_send)
        assert cli.run(args) == 2
        result = cli.load_json(args.output_dir / "results.json")
        assert sent_states == ["false", "true"]
        assert result["unexecuted_cases"] == 1
        assert result["results"][0]["http_status"] == 500
        assert result["results"][0]["transport_status"] == "OK"
        assert result["results"][0]["http_expectation_match"] is False
        assert result["cleanup_complete"] is True
        assert len(result["cleanup_results"]) == 1
        assert result["cleanup_http_requests"] == 1
        assert result["total_http_requests_including_preparation"] == 2

    def test_cleanup_for_unattempted_mutations_is_not_sent(self, tmp_path, monkeypatch):
        prerequisite = phase2_make_case("PREREQUISITE", critical=True)
        mutation = phase2_make_case("DISABLE-B", method="POST", path="/admin/accounts/2/status/", role="operator", status=302)
        mutation["input_reference"] = "basic_status_disable.json"
        restore = phase2_make_case("RESTORE-B", method="POST", path="/admin/accounts/2/status/", role="operator", status=302, after_case="DISABLE-B")
        restore["input_reference"] = "basic_status_enable.json"
        args = phase2_make_args(tmp_path, phase2_make_suite([prerequisite, mutation], cleanup_cases=[restore]))
        seen = []
        monkeypatch.setattr(cli, "prep_login", lambda *args: None)

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            budget.begin()
            seen.append((method, path))
            return phase2_detail(404), None

        monkeypatch.setattr(cli, "bounded_send", fake_send)
        assert cli.run(args) == 2
        assert seen == [("GET", "/posts/1/")]
        result = cli.load_json(args.output_dir / "results.json")
        assert result["cleanup_http_requests"] == 0
        assert result["cleanup_complete"] is True

    def test_budget_exhaustion_does_not_hide_unfinished_cleanup(self, tmp_path, monkeypatch):
        mutation = phase2_make_case("DISABLE-B", method="POST", path="/admin/accounts/2/status/", role="operator", status=302)
        mutation["input_reference"] = "basic_status_disable.json"
        restore = phase2_make_case("RESTORE-B", method="POST", path="/admin/accounts/2/status/", role="operator", status=302, after_case="DISABLE-B")
        restore["input_reference"] = "basic_status_enable.json"
        args = phase2_make_args(tmp_path, phase2_make_suite([mutation], cleanup_cases=[restore]), maximum=1)
        seen = []
        monkeypatch.setattr(cli, "prep_login", lambda session, *args: session.cookies.set("csrftoken", "synthetic-csrf"))

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            budget.begin()
            seen.append(path)
            return phase2_detail(302), None

        monkeypatch.setattr(cli, "bounded_send", fake_send)
        assert cli.run(args) == 2
        result = cli.load_json(args.output_dir / "results.json")
        assert seen == ["/admin/accounts/2/status/"]
        assert result["total_http_requests_including_preparation"] == 1
        assert result["cleanup_complete"] is False
        assert result["cleanup_results"][0]["transport_status"] == "ERROR"

    def test_absent_share_cleanup_is_explicitly_skipped_without_a_post(self, tmp_path, monkeypatch):
        mutation = phase2_make_case("GRANT-B", method="POST", path="/posts/1/shares/", status=302)
        mutation["input_reference"] = "basic_share_grant.json"
        cleanup = phase2_make_case("CLEANUP-B", method="POST", path="/posts/1/shares/{share_id}/revoke/", status=302,
                            after_case="GRANT-B", share_reference=phase2_reference(allow_missing=True))
        args = phase2_make_args(tmp_path, phase2_make_suite([mutation], cleanup_cases=[cleanup]))
        seen = []
        monkeypatch.setattr(cli, "prep_login", lambda session, *args: session.cookies.set("csrftoken", "synthetic-csrf"))

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            budget.begin()
            seen.append((method, path))
            return (phase2_detail(302), None) if method == "POST" else (phase2_detail(), phase2_share_html())

        monkeypatch.setattr(cli, "bounded_send", fake_send)
        assert cli.run(args) == 3
        result = cli.load_json(args.output_dir / "results.json")
        assert seen == [("POST", "/posts/1/shares/"), ("GET", "/posts/1/shares/")]
        assert result["cleanup_complete"] is True
        assert result["cleanup_results"][0]["transport_status"] == "SKIPPED"
        assert result["cleanup_http_requests"] == 1

    @pytest.mark.parametrize("unexpected_html", [b"", b"<html><body>Login page, HTTP 200</body></html>"])
    def test_unrecognized_cleanup_html_is_incomplete_instead_of_successfully_skipped(self, tmp_path, monkeypatch, unexpected_html):
        mutation = phase2_make_case("GRANT-B", method="POST", path="/posts/1/shares/", status=302)
        mutation["input_reference"] = "basic_share_grant.json"
        cleanup = phase2_make_case("CLEANUP-B", method="POST", path="/posts/1/shares/{share_id}/revoke/", status=302,
                            after_case="GRANT-B", share_reference=phase2_reference(allow_missing=True))
        args = phase2_make_args(tmp_path, phase2_make_suite([mutation], cleanup_cases=[cleanup]))
        seen = []
        monkeypatch.setattr(cli, "prep_login", lambda session, *args: session.cookies.set("csrftoken", "synthetic-csrf"))

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            budget.begin()
            seen.append((method, path))
            return (phase2_detail(302), None) if method == "POST" else (phase2_detail(), unexpected_html)

        monkeypatch.setattr(cli, "bounded_send", fake_send)
        assert cli.run(args) == 2
        result = cli.load_json(args.output_dir / "results.json")
        assert seen == [("POST", "/posts/1/shares/"), ("GET", "/posts/1/shares/")]
        assert result["cleanup_complete"] is False
        assert result["cleanup_results"][0]["transport_status"] == "ERROR"
        assert result["cleanup_results"][0].get("skip_reason") != "share_not_present"
        assert result["cleanup_http_requests"] == 1

    def test_phase2_command_dry_run_never_prompts_sends_or_creates_output(self, tmp_path, monkeypatch, capsys):
        output_dir = tmp_path / "not-created"
        monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: pytest.fail("Dry run requested a password"))
        monkeypatch.setattr(cli, "prep_login", lambda *args: pytest.fail("Dry run attempted login preparation"))
        args = Namespace(
            target="http://127.0.0.1:8000",
            allowlist=ROOT / "fixtures" / "allowlist_local.json",
            cases=ROOT / "fixtures" / "cases_haven_template.json",
            fixture_dir=ROOT / "fixtures", output_dir=output_dir,
            max_requests=300, max_duration=600, rate=1, timeout=10,
        )
        assert cli.main(phase2_command_arguments(args) + ["--dry-run", "--prompt-seed-password"]) == 0
        assert not output_dir.exists()
        output = capsys.readouterr().out
        assert '"selected_phase": 2' in output
        assert "DRY RUN" in output

    @pytest.mark.parametrize("previous", [None, "", "inherited-synthetic-password"])
    def test_phase2_command_reuses_or_masks_password_and_restores_environment(self, tmp_path, monkeypatch, capsys, previous):
        if previous is None:
            monkeypatch.delenv("HAVEN_SEED_PASSWORD", raising=False)
        else:
            monkeypatch.setenv("HAVEN_SEED_PASSWORD", previous)
        entered = "new-synthetic-password"
        prompted = []
        monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: prompted.append(prompt) or entered)
        args = phase2_local_auth_args(tmp_path)
        seen = []

        def fake_login(session, target, budget, role, *remaining):
            seen.append((role, cli.os.environ.get("HAVEN_SEED_PASSWORD")))
            session.cookies.set("csrftoken", "synthetic-csrf")

        def fake_send(session, method, target, path, budget, request_id, **kwargs):
            budget.begin()
            if kwargs.get("on_send"):
                kwargs["on_send"](cli.utc_now())
            return phase2_detail(), None

        monkeypatch.setattr(cli, "prep_login", fake_login)
        monkeypatch.setattr(cli, "bounded_send", fake_send)
        assert cli.main(phase2_command_arguments(args) + ["--prompt-seed-password"]) == 3
        assert seen == [(role, previous or entered) for role in ("member_a", "member_b", "member_c", "operator")]
        assert bool(prompted) is (not bool(previous))
        assert cli.os.environ.get("HAVEN_SEED_PASSWORD") == previous
        raw_result = (args.output_dir / "results.json").read_text(encoding="utf-8")
        assert entered not in raw_result
        assert "inherited-synthetic-password" not in raw_result
        result = json.loads(raw_result)
        assert result["execution_cases"] == 4
        assert result["unexecuted_cases"] == 0
        output = capsys.readouterr().out
        assert entered not in output
        assert "inherited-synthetic-password" not in output

    @pytest.mark.parametrize("error", [cli.ExecutionError("synthetic failure"), KeyboardInterrupt()])
    def test_phase2_command_restores_password_even_when_execution_fails(self, tmp_path, monkeypatch, error):
        monkeypatch.delenv("HAVEN_SEED_PASSWORD", raising=False)
        monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "synthetic-only-password")
        args = phase2_local_auth_args(tmp_path, roles=("member_a",))

        def fake_login(*arguments):
            assert cli.os.environ["HAVEN_SEED_PASSWORD"] == "synthetic-only-password"
            raise error

        monkeypatch.setattr(cli, "prep_login", fake_login)
        assert cli.main(phase2_command_arguments(args) + ["--prompt-seed-password"]) == 2
        assert "HAVEN_SEED_PASSWORD" not in cli.os.environ

    def test_phase2_command_refuses_an_echoing_password_fallback(self, tmp_path, monkeypatch):
        import warnings

        monkeypatch.delenv("HAVEN_SEED_PASSWORD", raising=False)
        args = phase2_local_auth_args(tmp_path, roles=("member_a",))
        monkeypatch.setattr(cli, "prep_login", lambda *args: pytest.fail("An unmasked password must not start login preparation"))

        def echoing_prompt(prompt):
            warnings.warn("Synthetic terminal cannot mask input", cli.getpass.GetPassWarning)
            pytest.fail("The echoing fallback was allowed to continue")

        monkeypatch.setattr(cli.getpass, "getpass", echoing_prompt)
        assert cli.main(phase2_command_arguments(args) + ["--prompt-seed-password"]) == 2
        assert "HAVEN_SEED_PASSWORD" not in cli.os.environ
        assert not args.output_dir.exists()

    @pytest.mark.parametrize("target", ["http://localhost:8000", "http://127.0.0.1:8765"])
    def test_common_password_prompt_is_rejected_for_other_origins(self, tmp_path, monkeypatch, target):
        args = phase2_local_auth_args(tmp_path, roles=("member_a",))
        args.target = target
        args.allowlist.write_text(json.dumps({"approved_origins": [target]}), encoding="utf-8")
        monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: pytest.fail("Unexpected password prompt"))
        monkeypatch.setattr(cli, "prep_login", lambda *args: pytest.fail("Unexpected login preparation"))
        assert cli.main(phase2_command_arguments(args) + ["--prompt-seed-password"]) == 2
        assert not args.output_dir.exists()

    def test_cleanup_runs_before_delete_and_logout(
        self, tmp_path, monkeypatch
    ):
        grant = phase2_make_case(
            "GRANT",
            method="POST",
            path="/posts/1/shares/",
            status=302,
        )
        grant["input_reference"] = "basic_share_grant.json"

        delete = phase2_make_case(
            "DELETE",
            method="POST",
            path="/posts/1/delete/",
            status=302,
            cleanup_before=True,
        )

        logout = phase2_make_case(
            "LOGOUT",
            method="POST",
            path="/accounts/logout/",
            status=302,
        )

        cleanup = phase2_make_case(
            "CLEANUP-GRANT",
            method="POST",
            path="/posts/1/shares/{share_id}/revoke/",
            status=302,
            after_case="GRANT",
            share_reference=phase2_reference(
                allow_missing=True
            ),
        )

        args = phase2_make_args(
            tmp_path,
            phase2_make_suite(
                [grant, delete, logout],
                cleanup_cases=[cleanup],
            ),
        )

        seen = []

        def fake_login(session, *args):
            session.cookies.set("csrftoken", "test-csrf")

        def fake_send(
            session, method, target, path,
            budget, request_id, **kwargs
        ):
            budget.begin()
            seen.append((method, path))

            if method == "GET" and path == "/posts/1/shares/":
                return (
                    phase2_detail(200),
                    phase2_share_html(
                        phase2_share_row(1, 77, "member_b")
                    ),
                )

            return phase2_detail(302), None

        monkeypatch.setattr(cli, "prep_login", fake_login)
        monkeypatch.setattr(cli, "bounded_send", fake_send)

        assert cli.run(args) == 3

        result = cli.load_json(
            args.output_dir / "results.json"
        )

        assert seen == [
            ("POST", "/posts/1/shares/"),
            ("GET", "/posts/1/shares/"),
            ("POST", "/posts/1/shares/77/revoke/"),
            ("POST", "/posts/1/delete/"),
            ("POST", "/accounts/logout/"),
        ]

        assert result["cleanup_complete"] is True
        assert result["cleanup_http_requests"] == 2
        assert result["preparation_http_requests"] == 0
        assert result["test_http_requests"] == 3


@pytest.mark.parametrize("location", [
    "https://attacker.invalid/posts/10/",
    "//attacker.invalid/posts/10/",
    "///attacker.invalid/posts/10/",
])
def test_created_post_id_rejects_external_location(location):
    with pytest.raises(cli.ExecutionError):
        cli.extract_created_post_id(
            location,
            "http://127.0.0.1:8765",
        )


def test_failed_checkpoint_cleanup_stops_remaining_cases(
    tmp_path, monkeypatch
):
    mutation = phase2_make_case(
        "MUTATE",
        method="POST",
        path="/admin/accounts/2/status/",
        role="operator",
        status=302,
    )

    restore = phase2_make_case(
        "RESTORE",
        method="POST",
        path="/admin/accounts/2/status/",
        role="operator",
        status=302,
        after_case="MUTATE",
    )

    delete = phase2_make_case(
        "DELETE",
        method="POST",
        path="/posts/1/delete/",
        status=302,
        cleanup_before=True,
    )

    logout = phase2_make_case(
        "LOGOUT",
        method="POST",
        path="/accounts/logout/",
        status=302,
    )

    args = phase2_make_args(
        tmp_path,
        phase2_make_suite(
            [mutation, delete, logout],
            cleanup_cases=[restore],
        ),
    )

    sent = []

    monkeypatch.setattr(
        cli,
        "prep_login",
        lambda session, *args: session.cookies.set(
            "csrftoken", "test-csrf"
        ),
    )

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        budget.begin()
        sent.append(path)

        # 두 번째 요청인 복구 요청을 실패시킨다.
        status = 500 if len(sent) == 2 else 302
        return phase2_detail(status), None

    monkeypatch.setattr(cli, "bounded_send", fake_send)

    assert cli.run(args) == 2

    result = cli.load_json(
        args.output_dir / "results.json"
    )

    assert result["cleanup_complete"] is False
    assert result["unexecuted_cases"] == 2

    # DELETE와 LOGOUT은 실행하면 안 된다.
    assert sent == [
        "/admin/accounts/2/status/",
        "/admin/accounts/2/status/",
    ]


# M2: post_reference는 허용된 경로에서만 사용
@pytest.mark.parametrize("path", [
    "/posts/{post_id}/",
    "/posts/{post_id}/attachments/extra/",
])
def test_post_reference_rejects_unsupported_paths(path):
    create = phase2_make_case(
        "CREATE",
        method="POST",
        path="/posts/new/",
        status=302,
        capture_post_id=True,
    )
    use = phase2_make_case(
        "USE",
        method="POST",
        path=path,
        status=302,
        post_reference="CREATE",
    )

    with pytest.raises(cli.ConfigError):
        cli.validate_suite(
            phase2_make_suite([create, use]),
            ROOT / "fixtures",
        )


# M3: 게시글 ID 캡처는 POST /posts/new/ + 302만 허용
@pytest.mark.parametrize("method,path,status", [
    ("GET", "/posts/new/", 302),
    ("POST", "/posts/1/", 302),
    ("POST", "/posts/new/", 200),
])
def test_capture_post_id_rejects_invalid_config(
    method, path, status
):
    case = phase2_make_case(
        "CREATE",
        method=method,
        path=path,
        status=status,
        capture_post_id=True,
    )

    with pytest.raises(cli.ConfigError):
        cli.validate_suite(
            phase2_make_suite([case]),
            ROOT / "fixtures",
        )


# M4: 서로 다른 생성 요청이 동일한 게시글 ID를 반환하면 중단
def test_duplicate_created_post_id_stops_run(
    tmp_path, monkeypatch
):
    cases = [
        phase2_make_case(
            name,
            method="POST",
            path="/posts/new/",
            status=302,
            capture_post_id=True,
        )
        for name in ("CREATE-A", "CREATE-B")
    ]
    cases.append(phase2_make_case("AFTER"))

    args = phase2_make_args(
        tmp_path, phase2_make_suite(cases)
    )
    sent = []

    monkeypatch.setattr(
        cli, "prep_login",
        lambda session, *args: session.cookies.set(
            "csrftoken", "test-csrf"
        ),
    )

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        budget.begin()
        sent.append(path)
        return phase2_detail(
            302, "/posts/42/"
        ), None

    monkeypatch.setattr(cli, "bounded_send", fake_send)

    assert cli.run(args) == 2

    result = cli.load_json(
        args.output_dir / "results.json"
    )
    assert len(sent) == 2
    assert result["unexecuted_cases"] == 1
    assert result["results"][1]["transport_status"] == "ERROR"
    assert "중복" in result["results"][1]["response_summary"]["error"]


# M5: 게시글 생성 HTTP 기대값 불일치 시 후속 요청 중단
def test_capture_post_id_mismatch_stops_run(
    tmp_path, monkeypatch
):
    create = phase2_make_case(
        "CREATE",
        method="POST",
        path="/posts/new/",
        status=302,
        capture_post_id=True,
    )
    dependent = phase2_make_case(
        "DEPENDENT",
        method="POST",
        path="/posts/{post_id}/attachments/",
        status=302,
        post_reference="CREATE",
    )

    args = phase2_make_args(
        tmp_path,
        phase2_make_suite([create, dependent]),
    )
    sent = []

    monkeypatch.setattr(
        cli, "prep_login",
        lambda session, *args: session.cookies.set(
            "csrftoken", "test-csrf"
        ),
    )

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        budget.begin()
        sent.append(path)
        return phase2_detail(
            400, "/posts/42/"
        ), None

    monkeypatch.setattr(cli, "bounded_send", fake_send)

    assert cli.run(args) == 2

    result = cli.load_json(
        args.output_dir / "results.json"
    )
    assert sent == ["/posts/new/"]
    assert result["unexecuted_cases"] == 1
    assert result["results"][0]["transport_status"] == "ERROR"
    assert "기대값 불일치" in result["results"][0]["response_summary"]["error"]

    row = result["results"][0]
    assert row["http_status"] == 400
    assert row["elapsed_ms"] == 0.1
    assert row["http_expectation_match"] is False
    assert row["response_summary"]["body_bytes"] == 0
    assert "headers" in row["response_summary"]


# M6: 복구 체크포인트는 하나만 허용
def test_rejects_multiple_cleanup_checkpoints():
    cases = [
        phase2_make_case(
            "CHECKPOINT-1", cleanup_before=True
        ),
        phase2_make_case(
            "CHECKPOINT-2", cleanup_before=True
        ),
    ]

    with pytest.raises(
        cli.ConfigError, match="복구 체크포인트"
    ):
        cli.validate_suite(
            phase2_make_suite(cases),
            ROOT / "fixtures",
        )


# M7: 체크포인트 뒤에 있는 변경 요청을 복구 대상으로 지정 불가
def test_rejects_cleanup_after_checkpoint():
    checkpoint = phase2_make_case(
        "CHECKPOINT",
        cleanup_before=True,
    )
    mutation = phase2_make_case(
        "MUTATE",
        method="POST",
        path="/posts/1/shares/",
        status=302,
    )
    cleanup = phase2_make_case(
        "RESTORE",
        method="POST",
        path="/posts/1/shares/",
        status=302,
        after_case="MUTATE",
    )

    suite = phase2_make_suite(
        [checkpoint, mutation],
        cleanup_cases=[cleanup],
    )

    with pytest.raises(
        cli.ConfigError, match="체크포인트보다 먼저"
    ):
        cli.validate_suite(
            suite,
            ROOT / "fixtures",
        )


@pytest.mark.parametrize("value", [
    True,
    False,
    float("inf"),
    float("-inf"),
    float("nan"),
    10**100,
    "2026-11-11T12:00:00",
    "not-a-time",
])
def test_invalid_log_timestamp_is_unresolved(value):
    assert cli.log_timestamp({"timestamp": value}) is None


def test_log_timestamp_normalizes_explicit_timezone():
    actual = cli.log_timestamp({
        "ts": "2026-11-11T21:00:00+09:00"
    })
    assert actual == datetime(
        2026, 11, 11, 12, 0, tzinfo=timezone.utc
    )


def test_plausible_event_rejects_naive_run_timestamp():
    row = {
        "run_id": "time-test",
        "timestamp_utc": "2026-11-11T12:00:00",
    }
    event = {
        "timestamp_utc": "2026-11-11T12:00:00+00:00"
    }

    assert cli.plausible_event(
        event, row, "https://haven.example:443"
    ) is False


@pytest.mark.parametrize("expected", [
    None,
    {},
    [],
    {"http_status": "302"},
])
def test_capture_rejects_malformed_expected_app(expected):
    case = phase2_make_case(
        "CREATE",
        method="POST",
        path="/posts/new/",
        status=302,
        capture_post_id=True,
    )
    case["expected_app"] = expected

    with pytest.raises(cli.ConfigError):
        cli.validate_suite(
            phase2_make_suite([case]),
            ROOT / "fixtures",
        )


def test_aws_cleanup_suite_valid():
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )

    cli.validate_aws_cleanup_suite(suite)


def test_aws_cleanup_suite_rejects_missing_cleanup():
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )

    suite["cleanup_cases"] = []

    with pytest.raises(cli.ConfigError):
        cli.validate_aws_cleanup_suite(suite)


def test_aws_cleanup_suite_rejects_fixed_post_mutation():
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )

    suite["cases"][1]["path"] = "/posts/1/attachments/"

    with pytest.raises(cli.ConfigError):
        cli.validate_aws_cleanup_suite(suite)


@pytest.mark.parametrize(
    "get_status, expected_complete",
    [
        (404, True),
        (200, False),
    ],
)
def test_aws_cleanup_verifies_post_inaccessible(
    monkeypatch, get_status, expected_complete
):
    # 공유 정리 자체는 별도 테스트에서 검증한다.
    monkeypatch.setattr(
        cli,
        "cleanup_post_shares",
        lambda *args, **kwargs: 0,
    )
    
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )
    cleanup_case = suite["cleanup_cases"][0]

    budget = cli.RequestBudget(
        Namespace(
            max_requests=10,
            rate=5,
            max_duration=60,
            timeout=3,
        )
    )

    session = cli.new_session()
    session.cookies.set("csrftoken", "synthetic-csrf")

    sent = []

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        budget.begin()
        sent.append((method, path))

        status = 302 if method == "POST" else get_status

        return phase2_detail(status), None

    
    monkeypatch.setattr(cli, "bounded_send", fake_send)

    # 6-3단계에서 추가한 게시글 표식 조회를 모의 처리한다.
    # 이번 테스트는 삭제 후 404 검증이 목적이므로
    # 표식 조회는 정상적으로 ID 17을 반환하도록 설정한다.
    def fake_lookup(session, target, budget, run_id, marker):
        assert marker == cli.aws_post_marker(
            run_id, "AWS-SETUP-A-POST"
        )
        return 17

    monkeypatch.setattr(
        cli, "find_aws_post_by_marker", fake_lookup
    )

    results = []

    complete = cli.execute_cleanup(
        cases=[cleanup_case],
        attempted={"AWS-SETUP-A-POST"},
        sessions={"member_a": session},
        prepped={"member_a": True},
        target=cli.canonical_origin(
            "https://orchestration-haven.cloud"
        ),
        budget=budget,
        run_id="synthetic-test-run",
        prep_events=[],
        fixture_root=ROOT / "fixtures",
        max_response_bytes=cli.MAX_RESPONSE,
        results=results,
        created_post_ids={"AWS-SETUP-A-POST": 17},
    )

    assert complete is expected_complete

    assert sent == [
        ("POST", "/posts/17/delete/"),
        ("GET", "/posts/17/"),
    ]

    verification = results[0]["response_summary"]["verification"]

    assert verification["http_status"] == get_status
    assert verification["post_inaccessible"] is expected_complete

    session.close()


def test_aws_post_creation_adds_unique_marker(monkeypatch):
    monkeypatch.setattr(
        cli, "csrf_for_post",
        lambda *args, **kwargs: "test-csrf"
    )

    case = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )["cases"][0]

    run_id = "11111111-2222-4333-8444-555555555555"

    with cli.new_session() as session:
        fields, headers, file_info = cli.prepare_case_request(
            session,
            case,
            ROOT / "fixtures",
            cli.canonical_origin(
                "https://orchestration-haven.cloud"
            ),
            None,
            run_id,
            [],
            cli.MAX_RESPONSE,
        )

    marker = cli.aws_post_marker(
        run_id, "AWS-SETUP-A-POST"
    )

    assert fields["title"].startswith(marker + " ")
    assert len(fields["title"]) <= 200
    assert fields["body"]
    assert file_info is None


def test_aws_post_parser_finds_actual_id():
    html = """
    <ul class="record-list">
      <li class="record-row">
        <h2 class="record-title">[HAVEN-AWS:test:CREATE] Test</h2>
        <a class="record-link" href="/posts/57/">Open</a>
      </li>
    </ul>
    <span class="page-count">1 / 1 페이지</span>
    """.encode("utf-8")

    rows, pages = cli.parse_aws_post_page(html, 1)

    assert rows == [
        ("[HAVEN-AWS:test:CREATE] Test", 57)
    ]
    assert pages == 1


def test_aws_post_parser_rejects_invalid_link():
    html = """
    <ul class="record-list">
      <li class="record-row">
        <h2 class="record-title">Test</h2>
        <a class="record-link" href="https://evil.invalid/">Open</a>
      </li>
    </ul>
    <span class="page-count">1 / 1 페이지</span>
    """.encode("utf-8")

    with pytest.raises(cli.ConfigError):
        cli.parse_aws_post_page(html, 1)


def test_aws_post_parser_rejects_wrong_page():
    html = """
    <ul class="record-list"></ul>
    <span class="page-count">2 / 3 페이지</span>
    """.encode("utf-8")

    with pytest.raises(cli.ConfigError):
        cli.parse_aws_post_page(html, 1)


@pytest.mark.parametrize(
    "saved_id, expected_complete",
    [
        (None, True),
        (57, True),
        (58, False),
    ],
)
def test_aws_cleanup_recovers_post_by_marker(
    monkeypatch, saved_id, expected_complete
):
    # 공유 정리 자체는 별도 테스트에서 검증한다.
    monkeypatch.setattr(
        cli,
        "cleanup_post_shares",
        lambda *args, **kwargs: 0,
    )
    
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )
    cleanup_case = suite["cleanup_cases"][0]

    budget = cli.RequestBudget(
        Namespace(
            max_requests=20,
            rate=5,
            max_duration=60,
            timeout=3,
        )
    )

    sent = []

    def fake_lookup(
        session, target, budget, run_id, marker
    ):
        budget.begin()
        assert marker == cli.aws_post_marker(
            run_id, "AWS-SETUP-A-POST"
        )
        return 57

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        budget.begin()
        sent.append((method, path))

        status = 302 if method == "POST" else 404
        return phase2_detail(status), None

    monkeypatch.setattr(
        cli, "find_aws_post_by_marker", fake_lookup
    )
    monkeypatch.setattr(
        cli, "bounded_send", fake_send
    )
    monkeypatch.setattr(
        cli, "csrf_for_post",
        lambda *args, **kwargs: "synthetic-csrf"
    )

    created_ids = (
        {}
        if saved_id is None
        else {"AWS-SETUP-A-POST": saved_id}
    )

    results = []

    with cli.new_session() as session:
        complete = cli.execute_cleanup(
            cases=[cleanup_case],
            attempted={"AWS-SETUP-A-POST"},
            sessions={"member_a": session},
            prepped={"member_a": True},
            target=cli.canonical_origin(
                "https://orchestration-haven.cloud"
            ),
            budget=budget,
            run_id="synthetic-test-run",
            prep_events=[],
            fixture_root=ROOT / "fixtures",
            max_response_bytes=cli.MAX_RESPONSE,
            results=results,
            created_post_ids=created_ids,
        )

    assert complete is expected_complete

    if expected_complete:
        assert sent == [
            ("POST", "/posts/57/delete/"),
            ("GET", "/posts/57/"),
        ]
        assert results[0]["verified_post_id"] == 57
    else:
        assert sent == []
        assert results[0]["transport_status"] == "ERROR"


def test_aws_recovery_plan_preserves_real_post_id():
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )

    run_id = "11111111-2222-4333-8444-555555555555"

    state = {
        "schema_version": 1,
        "source": "live_http_run",
        "target_origin": cli.canonical_origin(
            "https://orchestration-haven.cloud"
        ),
        "suite_id": suite["suite_id"],
        "run_id": run_id,
        "cleanup_complete": False,
        "cleanup_results": [],
        "results": [
            {
                "case_id": "AWS-SETUP-A-POST",
                "post_marker": cli.aws_post_marker(
                    run_id, "AWS-SETUP-A-POST"
                ),
                "created_post_id": 57,
                "request_attempted": True,
            }
        ],
    }

    plan = cli.build_aws_recovery_plan(state, suite)

    assert len(plan) == 1
    assert plan[0]["saved_post_id"] == 57
    assert plan[0]["auth_role"] == "member_a"


def test_aws_recovery_plan_rejects_wrong_marker():
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )

    state = {
        "schema_version": 1,
        "source": "live_http_run",
        "target_origin": cli.canonical_origin(
            "https://orchestration-haven.cloud"
        ),
        "suite_id": suite["suite_id"],
        "run_id": "11111111-2222-4333-8444-555555555555",
        "cleanup_complete": False,
        "cleanup_results": [],
        "results": [
            {
                "case_id": "AWS-SETUP-A-POST",
                "post_marker": "[HAVEN-AWS:wrong:CREATE]",
                "request_attempted": True,
            }
        ],
    }

    with pytest.raises(cli.ConfigError):
        cli.build_aws_recovery_plan(state, suite)


def test_aws_recover_dry_run_no_network(
    tmp_path, monkeypatch, capsys
):
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )
    run_id = "11111111-2222-4333-8444-555555555555"

    state = {
        "schema_version": 1,
        "source": "live_http_run",
        "target_origin": cli.canonical_origin(
            "https://orchestration-haven.cloud"
        ),
        "suite_id": suite["suite_id"],
        "selected_phase": None,
        "run_id": run_id,
        "cleanup_complete": False,
        "cleanup_results": [],
        "results": [{
            "case_id": "AWS-SETUP-A-POST",
            "post_marker": cli.aws_post_marker(
                run_id, "AWS-SETUP-A-POST"
            ),
            "created_post_id": 57,
            "request_attempted": True,
        }],
    }

    run_json = tmp_path / "results.json"
    run_json.write_text(
        json.dumps(state), encoding="utf-8"
    )

    monkeypatch.setattr(
        cli, "bounded_send",
        lambda *args, **kwargs: pytest.fail(
            "Dry Run에서 HTTP 요청이 발생했습니다"
        )
    )

    result = cli.main([
        "recover",
        "--run-json", str(run_json),
        "--target", "https://orchestration-haven.cloud",
        "--allowlist",
        str(ROOT / "fixtures" / "allowlist_aws.json"),
        "--cases",
        str(ROOT / "fixtures" / "cases_haven_aws.json"),
        "--fixture-dir", str(ROOT / "fixtures"),
        "--dry-run",
    ])

    assert result == 0

    output = capsys.readouterr().out
    assert '"recovery_count": 1' in output
    assert '"saved_post_id": 57' in output
    assert '"member_a"' in output


@pytest.mark.parametrize(
    "mode",
    ["remaining", "already_empty", "lookup_failed"],
)
def test_aws_recover_apply_uses_marker_verified_id(
    tmp_path, monkeypatch, mode
):
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )
    run_id = "11111111-2222-4333-8444-555555555555"

    state = {
        "schema_version": 1,
        "source": "live_http_run",
        "target_origin": cli.canonical_origin(
            "https://orchestration-haven.cloud"
        ),
        "suite_id": suite["suite_id"],
        "selected_phase": None,
        "run_id": run_id,
        "cleanup_complete": False,
        "cleanup_results": [],
        "results": [{
            "case_id": "AWS-SETUP-A-POST",
            "post_marker": cli.aws_post_marker(
                run_id, "AWS-SETUP-A-POST"
            ),
            "created_post_id": None,
            "request_attempted": True,
        }],
    }

    run_json = tmp_path / "original_results.json"
    run_json.write_text(
        json.dumps(state), encoding="utf-8"
    )
    original_bytes = run_json.read_bytes()

    shared = mode == "remaining"
    deleted = False
    sent = []
    login_roles = []

    def fake_login(session, target, budget, role, *args):
        login_roles.append(role)
        assert role == "member_a"
        session._haven_username = "aws_test_a"
        session.cookies.set("csrftoken", "synthetic-csrf")

    def fake_lookup(
        session, target, budget, run_id_arg, marker
    ):
        budget.begin()
        assert run_id_arg == run_id
        assert marker == cli.aws_post_marker(
            run_id, "AWS-SETUP-A-POST"
        )
        return 57

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        nonlocal shared, deleted

        budget.begin()
        sent.append((method, path))

        on_send = kwargs.get("on_send")
        if on_send:
            on_send(cli.utc_now())

        if method == "GET" and path == "/posts/57/shares/":
            if mode == "lookup_failed":
                return phase2_detail(403), None

            row = ""
            if shared:
                row = """
                <li>
                  <h3 class="record-title">aws_test_b</h3>
                  <form method="post"
                        action="/posts/57/shares/209/revoke/">
                  </form>
                </li>
                """

            html = f"""
            <section aria-labelledby="share-list-heading">
              <ul>{row}</ul>
            </section>
            """.encode("utf-8")

            return phase2_detail(200), html

        if method == "POST" and path == (
            "/posts/57/shares/209/revoke/"
        ):
            assert shared is True
            shared = False
            return phase2_detail(302), None

        if method == "POST" and path == "/posts/57/delete/":
            assert shared is False
            deleted = True
            return phase2_detail(302), None

        if method == "GET" and path == "/posts/57/":
            assert deleted is True
            return phase2_detail(404), None

        pytest.fail(f"예상하지 않은 요청: {method} {path}")

    monkeypatch.setattr(cli, "prep_login", fake_login)
    monkeypatch.setattr(
        cli, "find_aws_post_by_marker", fake_lookup
    )
    monkeypatch.setattr(cli, "bounded_send", fake_send)
    monkeypatch.setattr(
        cli,
        "csrf_for_post",
        lambda *args, **kwargs: "synthetic-csrf",
    )

    # cleanup_post_shares는 실제 함수를 실행한다.
    output_dir = tmp_path / "recovery_output"

    result = cli.main([
        "recover",
        "--run-json", str(run_json),
        "--target", "https://orchestration-haven.cloud",
        "--allowlist",
        str(ROOT / "fixtures" / "allowlist_aws.json"),
        "--cases",
        str(ROOT / "fixtures" / "cases_haven_aws.json"),
        "--fixture-dir", str(ROOT / "fixtures"),
        "--output-dir", str(output_dir),
        "--apply",
    ])

    recovery = cli.load_json(
        output_dir / "results.json"
    )
    cleanup = recovery["cleanup_results"][0]

    # 이전 실행의 B 세션 없이 A 로그인만으로 복구한다.
    assert login_roles == ["member_a"]
    assert cleanup["verified_post_id"] == 57
    assert run_json.read_bytes() == original_bytes

    if mode == "lookup_failed":
        assert result == 2
        assert recovery["cleanup_complete"] is False
        assert cleanup["transport_status"] == "ERROR"
        assert deleted is False
        assert sent == [
            ("GET", "/posts/57/shares/")
        ]
        return

    assert result == 0
    assert recovery["cleanup_complete"] is True
    assert cleanup["shares_absent_verified"] is True
    assert cleanup["revoked_share_count"] == (
        1 if mode == "remaining" else 0
    )
    assert cleanup["response_summary"]["verification"][
        "post_inaccessible"
    ] is True

    assert shared is False
    assert deleted is True

    expected = [("GET", "/posts/57/shares/")]

    if mode == "remaining":
        expected += [
            ("POST", "/posts/57/shares/209/revoke/"),
            ("GET", "/posts/57/shares/"),
        ]

    expected += [
        ("POST", "/posts/57/delete/"),
        ("GET", "/posts/57/"),
    ]

    assert sent == expected


@pytest.mark.parametrize(
    "role",
    ["member_a", "member_b", "member_c", "anonymous"],
)
def test_dynamic_post_detail_allows_read_by_other_roles(role):
    create = phase2_make_case(
        "CREATE",
        method="POST",
        path="/posts/new/",
        role="member_a",
        status=302,
        capture_post_id=True,
    )
    read = phase2_make_case(
        "READ",
        method="GET",
        path="/posts/{post_id}/",
        role=role,
        status=200 if role == "member_a" else (
            302 if role == "anonymous" else 404
        ),
        post_reference="CREATE",
    )

    cli.validate_suite(
        phase2_make_suite([create, read]),
        ROOT / "fixtures",
    )


def test_dynamic_post_cleanup_rejects_other_role():
    create = phase2_make_case(
        "CREATE",
        method="POST",
        path="/posts/new/",
        role="member_a",
        status=302,
        capture_post_id=True,
    )
    cleanup = phase2_make_case(
        "CLEANUP",
        method="POST",
        path="/posts/{post_id}/delete/",
        role="member_b",
        status=302,
        post_reference="CREATE",
        after_case="CREATE",
    )

    with pytest.raises(cli.ConfigError, match="복구 게시글 참조"):
        cli.validate_suite(
            phase2_make_suite(
                [create],
                cleanup_cases=[cleanup],
            ),
            ROOT / "fixtures",
        )


@pytest.mark.parametrize("post_id", [15, 25, 57])
def test_dynamic_post_reads_use_actual_created_id(
    tmp_path, monkeypatch, post_id
):
    create = phase2_make_case(
        "CREATE",
        method="POST",
        path="/posts/new/",
        role="member_a",
        status=302,
        capture_post_id=True,
    )

    reads = [
        phase2_make_case(
            f"READ-{role}",
            method="GET",
            path="/posts/{post_id}/",
            role=role,
            status=200 if role == "member_a" else 404,
            post_reference="CREATE",
        )
        for role in ("member_a", "member_b", "member_c")
    ]

    args = phase2_make_args(
        tmp_path,
        phase2_make_suite([create, *reads]),
    )

    session_roles = {}
    sent = []

    def fake_login(session, target, budget, role, *args):
        session_roles[id(session)] = role
        session.cookies.set("csrftoken", "synthetic-csrf")

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        budget.begin()
        role = session_roles[id(session)]
        sent.append((role, method, path))

        if method == "POST":
            return phase2_detail(
                302, f"/posts/{post_id}/"
            ), None

        return phase2_detail(
            200 if role == "member_a" else 404
        ), None

    monkeypatch.setattr(cli, "prep_login", fake_login)
    monkeypatch.setattr(cli, "bounded_send", fake_send)
    monkeypatch.setattr(
        cli,
        "csrf_for_post",
        lambda *args, **kwargs: "synthetic-csrf",
    )

    # 로그 대조 전이므로 UNKNOWN 종료 코드가 정상이다.
    assert cli.run(args) == 3

    assert sent == [
        ("member_a", "POST", "/posts/new/"),
        ("member_a", "GET", f"/posts/{post_id}/"),
        ("member_b", "GET", f"/posts/{post_id}/"),
        ("member_c", "GET", f"/posts/{post_id}/"),
    ]

    result = cli.load_json(
        args.output_dir / "results.json"
    )
    assert result["unexecuted_cases"] == 0
    assert all(
        row["http_expectation_match"]
        for row in result["results"]
    )


@pytest.mark.parametrize("login_ok", [True, False])
def test_login_remembers_username_only_after_success(
    monkeypatch, login_ok
):
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: "aws_test_b",
    )
    monkeypatch.setattr(
        cli.getpass,
        "getpass",
        lambda prompt: "synthetic-password",
    )

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        if method == "GET":
            session.cookies.set(
                "csrftoken", "synthetic-csrf"
            )
            return phase2_detail(200), None

        assert kwargs["fields"]["username"] == "aws_test_b"
        assert kwargs["fields"]["password"] == "synthetic-password"

        if login_ok:
            session.cookies.set(
                "sessionid", "synthetic-session"
            )
            return phase2_detail(302, "/posts/"), None

        return phase2_detail(200), None

    monkeypatch.setattr(
        cli, "bounded_send", fake_send
    )

    with cli.new_session() as session:
        session._haven_username = "old-account"
        prep_events = []

        def login():
            cli.prep_login(
                session,
                cli.canonical_origin(
                    "https://orchestration-haven.cloud"
                ),
                None,
                "member_b",
                "synthetic-run",
                prep_events,
                cli.MAX_RESPONSE,
            )

        if login_ok:
            login()
            assert session._haven_username == "aws_test_b"
        else:
            with pytest.raises(
                cli.ExecutionError,
                match="로그인 인증 준비 실패",
            ):
                login()

            assert not hasattr(
                session, "_haven_username"
            )

        assert "synthetic-password" not in json.dumps(
            prep_events
        )
        assert "synthetic-password" not in repr(
            vars(session)
        )


def test_share_recipient_uses_actual_login_username():
    case = {
        "auth_role": "member_a",
        "share_recipient_role": "member_b",
    }
    fields = {
        "username": "member_b",
        "csrfmiddlewaretoken": "synthetic-csrf",
    }

    sessions = {
        "member_a": Namespace(_haven_username="aws_test_a"),
        "member_b": Namespace(_haven_username="aws_test_b"),
    }
    prepped = {"member_a": True, "member_b": True}

    actual = cli.bind_share_recipient(
        case, fields, sessions, prepped
    )

    assert actual["username"] == "aws_test_b"
    assert actual["csrfmiddlewaretoken"] == "synthetic-csrf"

    # 원본 입력은 변경하지 않는다.
    assert fields["username"] == "member_b"


@pytest.mark.parametrize("recipient, logged_in", [
    (None, True),
    ("aws_test_b", False),
    ("aws_test_a", True),
])
def test_share_recipient_rejects_unready_or_same_account(
    recipient, logged_in
):
    case = {
        "auth_role": "member_a",
        "share_recipient_role": "member_b",
    }
    sessions = {
        "member_a": Namespace(_haven_username="aws_test_a"),
        "member_b": Namespace(_haven_username=recipient),
    }

    with pytest.raises(cli.ExecutionError):
        cli.bind_share_recipient(
            case,
            {"username": "member_b"},
            sessions,
            {"member_a": True, "member_b": logged_in},
        )


@pytest.mark.parametrize("recipient_role", [
    "operator", "anonymous", "member_a", "", None, [],
])
def test_share_recipient_role_rejects_invalid_config(
    recipient_role
):
    create = phase2_make_case(
        "CREATE",
        method="POST",
        path="/posts/new/",
        status=302,
        capture_post_id=True,
    )
    share = phase2_make_case(
        "SHARE",
        method="POST",
        path="/posts/{post_id}/shares/",
        status=302,
        post_reference="CREATE",
        share_recipient_role=recipient_role,
        input_reference="basic_share_grant.json",
    )

    with pytest.raises(
        cli.ConfigError, match="share_recipient_role"
    ):
        cli.validate_suite(
            phase2_make_suite([create, share]),
            ROOT / "fixtures",
        )


@pytest.mark.parametrize(
    "post_id, share_id",
    [(15, 81), (25, 103), (57, 209)],
)
def test_created_share_lookup_uses_actual_ids_and_username(
    monkeypatch, post_id, share_id
):
    owner = Namespace(_haven_username="aws_test_a")
    recipient = Namespace(_haven_username="aws_test_b")

    sessions = {
        "member_a": owner,
        "member_b": recipient,
    }
    prepped = {"member_a": True, "member_b": True}
    sent = []

    html = f"""
    <section aria-labelledby="share-list-heading">
      <ul>
        <li>
          <h3 class="record-title">another_user</h3>
          <form method="post"
                action="/posts/{post_id}/shares/999/revoke/">
          </form>
        </li>
        <li>
          <h3 class="record-title">aws_test_b</h3>
          <form method="post"
                action="/posts/{post_id}/shares/{share_id}/revoke/">
          </form>
        </li>
      </ul>
    </section>
    """.encode("utf-8")

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        assert session is owner
        assert kwargs["capture_html"] is True
        sent.append((method, path))
        return phase2_detail(200), html

    monkeypatch.setattr(cli, "bounded_send", fake_send)

    actual = cli.resolve_created_share_id(
        post_id,
        "member_a",
        "member_b",
        sessions,
        prepped,
        cli.canonical_origin(
            "https://orchestration-haven.cloud"
        ),
        None,
        "synthetic-run",
        [],
        cli.MAX_RESPONSE,
    )

    assert actual == share_id
    assert sent == [
        ("GET", f"/posts/{post_id}/shares/")
    ]


@pytest.mark.parametrize(
    "action",
    [
        "/posts/58/shares/209/revoke/",
        "https://other.invalid/posts/57/shares/209/revoke/",
    ],
)
def test_created_share_lookup_rejects_wrong_revoke_target(
    monkeypatch, action
):
    sessions = {
        "member_a": Namespace(_haven_username="aws_test_a"),
        "member_b": Namespace(_haven_username="aws_test_b"),
    }

    html = f"""
    <section aria-labelledby="share-list-heading">
      <ul>
        <li>
          <h3 class="record-title">aws_test_b</h3>
          <form method="post" action="{action}"></form>
        </li>
      </ul>
    </section>
    """.encode("utf-8")

    monkeypatch.setattr(
        cli,
        "bounded_send",
        lambda *args, **kwargs: (phase2_detail(200), html),
    )

    with pytest.raises(cli.ConfigError):
        cli.resolve_created_share_id(
            57,
            "member_a",
            "member_b",
            sessions,
            {"member_a": True, "member_b": True},
            cli.canonical_origin(
                "https://orchestration-haven.cloud"
            ),
            None,
            "synthetic-run",
            [],
            cli.MAX_RESPONSE,
        )


def test_created_share_lookup_rejects_missing_recipient(
    monkeypatch,
):
    sessions = {
        "member_a": Namespace(_haven_username="aws_test_a"),
        "member_b": Namespace(_haven_username="aws_test_b"),
    }

    html = b"""
    <section aria-labelledby="share-list-heading">
      <ul></ul>
    </section>
    """

    monkeypatch.setattr(
        cli,
        "bounded_send",
        lambda *args, **kwargs: (phase2_detail(200), html),
    )

    with pytest.raises(cli.ExecutionError, match="공유 대상 관계"):
        cli.resolve_created_share_id(
            57,
            "member_a",
            "member_b",
            sessions,
            {"member_a": True, "member_b": True},
            cli.canonical_origin(
                "https://orchestration-haven.cloud"
            ),
            None,
            "synthetic-run",
            [],
            cli.MAX_RESPONSE,
        )


@pytest.mark.parametrize(
    "post_id, share_id",
    [(25, 103), (57, 209)],
)
def test_dynamic_share_grant_and_revoke_flow(
    tmp_path, monkeypatch, post_id, share_id
):
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )
    cli.validate_suite(suite, ROOT / "fixtures")
    cli.validate_aws_cleanup_suite(suite)

    args = phase2_make_args(tmp_path, suite)
    args.phase = None

    usernames = {
        "member_a": "aws_test_a",
        "member_b": "aws_test_b",
        "member_c": "aws_test_c",
    }
    session_roles = {}
    sent = []
    shared = False

    def fake_login(session, target, budget, role, *args):
        session_roles[id(session)] = role
        session._haven_username = usernames[role]
        session.cookies.set("csrftoken", "synthetic-csrf")

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        nonlocal shared
        budget.begin()
        role = session_roles[id(session)]
        sent.append((role, method, path))

        if method == "POST" and path == "/posts/new/":
            assert role == "member_a"
            return phase2_detail(
                302, f"/posts/{post_id}/"
            ), None

        if method == "POST" and path == (
            f"/posts/{post_id}/attachments/"
        ):
            assert role == "member_a"
            return phase2_detail(302), None

        if path == f"/posts/{post_id}/shares/":
            assert role == "member_a"

            if method == "POST":
                assert kwargs["fields"]["username"] == "aws_test_b"
                shared = True
                return phase2_detail(302), None

            assert method == "GET"
            assert shared is True

            html = f"""
            <section aria-labelledby="share-list-heading">
              <ul>
                <li>
                  <h3 class="record-title">aws_test_b</h3>
                  <form method="post"
                    action="/posts/{post_id}/shares/{share_id}/revoke/">
                  </form>
                </li>
              </ul>
            </section>
            """.encode("utf-8")

            return phase2_detail(200), html

        if method == "POST" and path == (
            f"/posts/{post_id}/shares/{share_id}/revoke/"
        ):
            assert role == "member_a"
            assert shared is True
            shared = False
            return phase2_detail(302), None

        if method == "GET" and path == f"/posts/{post_id}/":
            allowed = (
                role == "member_a"
                or (role == "member_b" and shared)
            )
            return phase2_detail(200 if allowed else 404), None

        if method == "POST" and path == (
            f"/posts/{post_id}/delete/"
        ):
            assert role == "member_a"
            assert shared is False
            return phase2_detail(302), None

        pytest.fail(f"예상하지 않은 요청: {role} {method} {path}")

    monkeypatch.setattr(cli, "prep_login", fake_login)
    monkeypatch.setattr(cli, "bounded_send", fake_send)
    monkeypatch.setattr(
        cli,
        "csrf_for_post",
        lambda *args, **kwargs: "synthetic-csrf",
    )

    assert cli.run(args) == 3

    result = cli.load_json(
        args.output_dir / "results.json"
    )
    rows = {
        row["case_id"]: row
        for row in result["results"]
    }

    assert len(rows) == 9
    assert result["unexecuted_cases"] == 0
    assert result["cleanup_complete"] is True
    assert all(
        row["http_expectation_match"]
        for row in rows.values()
    )

    assert rows["AWS-B-POST-DENIED"]["http_status"] == 404
    assert rows["AWS-B-SHARED-READ"]["http_status"] == 200
    assert rows["AWS-B-REVOKED-DENIED"]["http_status"] == 404

    revoke = rows["AWS-A-REVOKE-B"]
    assert revoke["resolved_share_id"] == share_id
    assert revoke["path"] == (
        f"/posts/{post_id}/shares/{share_id}/revoke/"
    )

    assert sent[-1] == (
        "member_a", "POST", f"/posts/{post_id}/delete/"
    )


@pytest.mark.parametrize("allow_missing", [False, True])
def test_created_share_lookup_missing_policy(
    monkeypatch, allow_missing
):
    sessions = {
        "member_a": Namespace(_haven_username="aws_test_a"),
        "member_b": Namespace(_haven_username="aws_test_b"),
    }
    sent = []

    # B의 공유는 없지만, 다른 사용자의 공유는 남아 있다.
    html = b"""
    <section aria-labelledby="share-list-heading">
      <ul>
        <li>
          <h3 class="record-title">another_user</h3>
          <form method="post"
                action="/posts/57/shares/999/revoke/">
          </form>
        </li>
      </ul>
    </section>
    """

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        assert session is sessions["member_a"]
        sent.append((method, path))
        return phase2_detail(200), html

    monkeypatch.setattr(cli, "bounded_send", fake_send)

    def lookup():
        return cli.resolve_created_share_id(
            57,
            "member_a",
            "member_b",
            sessions,
            {"member_a": True, "member_b": True},
            cli.canonical_origin(
                "https://orchestration-haven.cloud"
            ),
            None,
            "synthetic-run",
            [],
            cli.MAX_RESPONSE,
            allow_missing=allow_missing,
        )

    if allow_missing:
        assert lookup() is None
    else:
        with pytest.raises(
            cli.ExecutionError, match="공유 대상 관계"
        ):
            lookup()

    # 다른 사용자의 공유를 해제하는 POST는 발생하지 않는다.
    assert sent == [("GET", "/posts/57/shares/")]


@pytest.mark.parametrize("value", [None, 1, "true"])
def test_created_share_lookup_rejects_invalid_missing_policy(
    monkeypatch, value
):
    monkeypatch.setattr(
        cli,
        "bounded_send",
        lambda *args, **kwargs: pytest.fail(
            "설정 오류에서 HTTP 요청이 발생했습니다"
        ),
    )

    with pytest.raises(cli.ConfigError, match="allow_missing"):
        cli.resolve_created_share_id(
            57,
            "member_a",
            "member_b",
            {},
            {},
            cli.canonical_origin(
                "https://orchestration-haven.cloud"
            ),
            None,
            "synthetic-run",
            [],
            cli.MAX_RESPONSE,
            allow_missing=value,
        )


@pytest.mark.parametrize(
    "mode",
    ["already_empty", "remaining", "still_present", "lookup_failed"],
)
def test_cleanup_post_shares(monkeypatch, mode):
    target = cli.canonical_origin(
        "https://orchestration-haven.cloud"
    )
    sent = []
    events = []
    lookups = 0

    empty_html = b"""
    <section aria-labelledby="share-list-heading">
      <ul></ul>
    </section>
    """

    shared_html = b"""
    <section aria-labelledby="share-list-heading">
      <ul>
        <li>
          <h3 class="record-title">aws_test_b</h3>
          <form method="post"
                action="/posts/57/shares/209/revoke/">
          </form>
        </li>
      </ul>
    </section>
    """

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        nonlocal lookups
        sent.append((method, path))

        if method == "GET":
            assert path == "/posts/57/shares/"
            lookups += 1

            if mode == "lookup_failed":
                return phase2_detail(403), None

            if mode == "already_empty":
                return phase2_detail(200), empty_html

            if lookups == 1 or mode == "still_present":
                return phase2_detail(200), shared_html

            return phase2_detail(200), empty_html

        assert method == "POST"
        assert path == "/posts/57/shares/209/revoke/"
        assert kwargs["fields"] == {
            "csrfmiddlewaretoken": "synthetic-csrf"
        }
        return phase2_detail(302), None

    monkeypatch.setattr(cli, "bounded_send", fake_send)
    monkeypatch.setattr(
        cli,
        "csrf_for_post",
        lambda *args, **kwargs: "synthetic-csrf",
    )

    with cli.new_session() as session:
        def cleanup():
            return cli.cleanup_post_shares(
                session,
                57,
                target,
                None,
                "synthetic-run",
                [],
                cli.MAX_RESPONSE,
                events,
            )

        if mode in {"still_present", "lookup_failed"}:
            with pytest.raises(cli.ExecutionError):
                cleanup()
        else:
            assert cleanup() == (
                0 if mode == "already_empty" else 1
            )

    if mode in {"already_empty", "lookup_failed"}:
        assert sent == [
            ("GET", "/posts/57/shares/")
        ]
    else:
        assert sent == [
            ("GET", "/posts/57/shares/"),
            ("POST", "/posts/57/shares/209/revoke/"),
            ("GET", "/posts/57/shares/"),
        ]

    assert len(events) == len(sent)
    assert all(
        event["request_id"] and event["trace_id"]
        for event in events
    )


@pytest.mark.parametrize("interruption", ["network_error", "ctrl_c"])
def test_aws_interrupted_share_runs_cleanup(
    tmp_path, monkeypatch, interruption
):
    suite = cli.load_json(
        ROOT / "fixtures" / "cases_haven_aws.json"
    )
    args = phase2_make_args(tmp_path, suite)
    args.phase = None
    args.target = "https://orchestration-haven.cloud"

    args.allowlist.write_text(
        json.dumps({"approved_origins": [args.target]}),
        encoding="utf-8",
    )

    post_id = 57
    share_id = 209
    shared = False
    deleted = False
    sent = []
    session_roles = {}

    usernames = {
        "member_a": "aws_test_a",
        "member_b": "aws_test_b",
        "member_c": "aws_test_c",
    }

    def fake_login(session, target, budget, role, *args):
        session_roles[id(session)] = role
        session._haven_username = usernames[role]
        session.cookies.set("csrftoken", "synthetic-csrf")

    def fake_lookup(session, target, budget, run_id, marker):
        assert session_roles[id(session)] == "member_a"
        assert marker == cli.aws_post_marker(
            run_id, "AWS-SETUP-A-POST"
        )
        budget.begin()
        return post_id

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        nonlocal shared, deleted

        budget.begin()
        role = session_roles[id(session)]
        sent.append((role, method, path))

        # 실제 전송 직전의 기록 처리도 재현한다.
        on_send = kwargs.get("on_send")
        if on_send:
            on_send(cli.utc_now())

        if method == "POST" and path == "/posts/new/":
            assert role == "member_a"
            return phase2_detail(
                302, f"/posts/{post_id}/"
            ), None

        if method == "POST" and path == (
            f"/posts/{post_id}/attachments/"
        ):
            assert role == "member_a"
            return phase2_detail(302), None

        if path == f"/posts/{post_id}/shares/":
            assert role == "member_a"

            if method == "POST":
                assert kwargs["fields"]["username"] == "aws_test_b"
                shared = True

                if interruption == "ctrl_c":
                    raise KeyboardInterrupt()

                raise cli.ExecutionError(
                    "synthetic response failure after share creation"
                )

            assert method == "GET"

            row = ""
            if shared:
                row = f"""
                <li>
                  <h3 class="record-title">aws_test_b</h3>
                  <form method="post"
                    action="/posts/{post_id}/shares/{share_id}/revoke/">
                  </form>
                </li>
                """

            html = f"""
            <section aria-labelledby="share-list-heading">
              <ul>{row}</ul>
            </section>
            """.encode("utf-8")

            return phase2_detail(200), html

        if method == "POST" and path == (
            f"/posts/{post_id}/shares/{share_id}/revoke/"
        ):
            assert role == "member_a"
            assert shared is True
            shared = False
            return phase2_detail(302), None

        if method == "POST" and path == (
            f"/posts/{post_id}/delete/"
        ):
            assert role == "member_a"
            assert shared is False
            deleted = True
            return phase2_detail(302), None

        if method == "GET" and path == f"/posts/{post_id}/":
            allowed = not deleted and (
                role == "member_a"
                or (role == "member_b" and shared)
            )
            return phase2_detail(200 if allowed else 404), None

        pytest.fail(f"예상하지 않은 요청: {role} {method} {path}")

    monkeypatch.setattr(cli, "prep_login", fake_login)
    monkeypatch.setattr(
        cli, "find_aws_post_by_marker", fake_lookup
    )
    monkeypatch.setattr(cli, "bounded_send", fake_send)
    monkeypatch.setattr(
        cli,
        "csrf_for_post",
        lambda *args, **kwargs: "synthetic-csrf",
    )

    # 본 시험의 중단은 복구 성공 후에도 ERROR로 남긴다.
    assert cli.run(args) == 2

    result = cli.load_json(
        args.output_dir / "results.json"
    )

    assert result["stopped_reason"]
    assert result["unexecuted_cases"] == 3
    assert result["cleanup_complete"] is True

    failed = result["results"][-1]
    assert failed["case_id"] == "AWS-A-SHARE-B"
    assert failed["request_attempted"] is True
    assert failed["transport_status"] == "ERROR"

    cleanup = result["cleanup_results"][0]
    assert cleanup["verified_post_id"] == post_id
    assert cleanup["revoked_share_count"] == 1
    assert cleanup["shares_absent_verified"] is True
    assert cleanup["response_summary"]["verification"][
        "post_inaccessible"
    ] is True

    assert shared is False
    assert deleted is True

    assert sent[-5:] == [
        ("member_a", "GET", f"/posts/{post_id}/shares/"),
        (
            "member_a",
            "POST",
            f"/posts/{post_id}/shares/{share_id}/revoke/",
        ),
        ("member_a", "GET", f"/posts/{post_id}/shares/"),
        ("member_a", "POST", f"/posts/{post_id}/delete/"),
        ("member_a", "GET", f"/posts/{post_id}/"),
    ]


def admin_account_page_html(
    *,
    active=True,
    action="/admin/accounts/37/status/",
    duplicate=False,
    page=1,
):
    status = "활성" if active else "비활성"
    next_state = "false" if active else "true"

    row = f"""
    <tr>
      <th scope="row">aws_test_b</th>
      <td>{status}</td>
      <td>가입일</td>
      <td>최근 로그인</td>
      <td>
        <form method="post" action="{action}">
          <input type="hidden" name="is_active"
                 value="{next_state}">
        </form>
      </td>
    </tr>
    """

    return f"""
    <section aria-labelledby="accounts-heading">
      <h2 id="accounts-heading">계정 목록</h2>
      <table>
        <thead><tr><th scope="col">아이디</th></tr></thead>
        <tbody>{row}{row if duplicate else ""}</tbody>
      </table>
      <span aria-current="page">{page} / 3 페이지</span>
    </section>
    """.encode("utf-8")


@pytest.mark.parametrize("active", [True, False])
def test_parse_admin_account_actual_id_and_state(active):
    accounts, total_pages = cli.parse_admin_account_page(
        admin_account_page_html(active=active),
        1,
    )

    assert accounts == [{
        "username": "aws_test_b",
        "account_id": 37,
        "is_active": active,
    }]
    assert total_pages == 3


@pytest.mark.parametrize("action", [
    "https://other.invalid/admin/accounts/37/status/",
    "/admin/accounts/0/status/",
])
def test_parse_admin_account_rejects_invalid_action(action):
    with pytest.raises(cli.ConfigError, match="경로"):
        cli.parse_admin_account_page(
            admin_account_page_html(action=action),
            1,
        )


def test_parse_admin_account_rejects_duplicate():
    with pytest.raises(cli.ConfigError, match="중복"):
        cli.parse_admin_account_page(
            admin_account_page_html(duplicate=True),
            1,
        )


def test_parse_admin_account_rejects_wrong_page():
    with pytest.raises(cli.ConfigError, match="페이지 번호"):
        cli.parse_admin_account_page(
            admin_account_page_html(page=2),
            1,
        )


@pytest.mark.parametrize(
    "mode",
    ["found", "missing", "duplicate", "page_count_changed", "forbidden"],
)
def test_find_admin_account_across_pages(monkeypatch, mode):
    sent = []
    events = []
    operator_session = object()

    def make_page(page, username, account_id, active, total=2):
        html = admin_account_page_html(
            active=active,
            action=f"/admin/accounts/{account_id}/status/",
            page=page,
        ).decode("utf-8")

        html = html.replace("aws_test_b", username)
        html = html.replace(
            f"{page} / 3 페이지",
            f"{page} / {total} 페이지",
        )
        return html.encode("utf-8")

    def fake_send(
        session, method, target, path,
        budget, request_id, **kwargs
    ):
        assert session is operator_session
        assert method == "GET"
        assert kwargs["capture_html"] is True
        sent.append(path)

        if mode == "forbidden":
            return phase2_detail(403), None

        if path == "/admin/accounts/":
            # 접두사가 같아도 다른 계정으로 취급해야 한다.
            if mode == "duplicate":
                name, account_id = "aws_test_b", 37
            else:
                name, account_id = "aws_test_b_extra", 12

            return phase2_detail(200), make_page(
                1, name, account_id, True
            )

        assert path == "/admin/accounts/?page=2"

        name = (
            "another_user"
            if mode == "missing"
            else "aws_test_b"
        )
        total = 3 if mode == "page_count_changed" else 2

        return phase2_detail(200), make_page(
            2, name, 37, False, total=total
        )

    monkeypatch.setattr(cli, "bounded_send", fake_send)

    def lookup():
        return cli.find_admin_account(
            operator_session,
            cli.canonical_origin(
                "https://orchestration-haven.cloud"
            ),
            None,
            "synthetic-run",
            "aws_test_b",
            events,
            cli.MAX_RESPONSE,
        )

    if mode == "found":
        assert lookup() == {
            "username": "aws_test_b",
            "account_id": 37,
            "is_active": False,
        }
    else:
        with pytest.raises(cli.ExecutionError):
            lookup()

    expected_paths = ["/admin/accounts/"]
    if mode != "forbidden":
        expected_paths.append("/admin/accounts/?page=2")

    assert sent == expected_paths
    assert len(events) == len(sent)
    assert all(
        event["stage"] == "admin_account_lookup"
        and event["request_id"]
        and event["trace_id"]
        for event in events
    )


@pytest.mark.parametrize("active", [True, False])
def test_inspect_accounts_command(
    tmp_path, monkeypatch, capsys, active
):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps({
            "approved_origins": [
                "https://orchestration-haven.cloud"
            ]
        }),
        encoding="utf-8",
    )

    login_roles = []
    looked_up = []

    def fake_login(session, target, budget, role, *args):
        login_roles.append(role)
        session._haven_username = "aws_operator"

    def fake_lookup(
        session, target, budget, run_id,
        username, prep_events, max_response_bytes
    ):
        assert session._haven_username == "aws_operator"
        looked_up.append(username)

        return {
            "username": username,
            "account_id": {
                "aws_test_a": 15,
                "aws_test_b": 37,
            }[username],
            "is_active": active,
        }

    monkeypatch.setattr(cli, "prep_login", fake_login)
    monkeypatch.setattr(
        cli, "find_admin_account", fake_lookup
    )
    monkeypatch.setattr(
        cli,
        "bounded_send",
        lambda *args, **kwargs: pytest.fail(
            "모의 처리 밖의 HTTP 요청이 발생했습니다"
        ),
    )

    result = cli.main([
        "inspect-accounts",
        "--target", "https://orchestration-haven.cloud",
        "--allowlist", str(allowlist),
        "--username", "aws_test_a",
        "--username", "aws_test_b",
    ])

    assert result == 0
    assert login_roles == ["operator"]
    assert looked_up == ["aws_test_a", "aws_test_b"]

    report = json.loads(capsys.readouterr().out)
    assert report["account_state_changed"] is False
    assert report["accounts"] == [
        {
            "username": "aws_test_a",
            "account_id": 15,
            "is_active": active,
        },
        {
            "username": "aws_test_b",
            "account_id": 37,
            "is_active": active,
        },
    ]


def test_inspect_accounts_rejects_duplicate_before_login(
    tmp_path, monkeypatch
):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps({
            "approved_origins": [
                "https://orchestration-haven.cloud"
            ]
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "prep_login",
        lambda *args, **kwargs: pytest.fail(
            "설정 오류인데 로그인이 실행됐습니다"
        ),
    )

    assert cli.main([
        "inspect-accounts",
        "--target", "https://orchestration-haven.cloud",
        "--allowlist", str(allowlist),
        "--username", "aws_test_a",
        "--username", "aws_test_a",
    ]) == 2