"""Unit/integration checks using local synthetic fixture server. No AWS network access."""
from __future__ import annotations

from argparse import Namespace
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

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
    base = tmp_path/"fixtures"
    base.mkdir()
    (base/"good.json").write_text("{}", encoding="utf-8")
    assert cli.safe_relative(base, "good.json").name == "good.json"
    (tmp_path/"private.json").write_text("{}", encoding="utf-8")
    (base/"alias.json").symlink_to(tmp_path/"private.json")
    for ref in ["../private.json", "alias.json", "/etc/passwd", "..\\private.json"]:
        with pytest.raises(cli.ConfigError):
            cli.safe_relative(base, ref)


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
