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
    "origin_mode, expected_origin",
    [
        (None, "https://haven.example:443"),
        ("same", "https://haven.example:443"),
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
        "https://haven.example:443"
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
