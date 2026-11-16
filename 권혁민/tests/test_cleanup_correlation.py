import argparse
import json

import pytest

import request_verify as cli


@pytest.mark.parametrize(
    "mode,expected_code,expected_status,expected_verdict",
    [
        ("matched", 0, "MATCHED", "PASS"),
        ("missing", 3, "UNRESOLVED", "UNKNOWN"),
        ("duplicate", 3, "UNRESOLVED", "UNKNOWN"),
        ("mismatch", 1, "MATCHED", "FAIL"),
    ],
)
def test_cleanup_logs_are_selected_and_correlated(
    tmp_path, mode, expected_code, expected_status, expected_verdict
):
    run_id = "synthetic-cleanup-run"
    timestamp = "2026-11-16T01:49:44+00:00"

    def make_row(case_id, status, stage):
        row = cli.base_record(run_id, {
            "case_id": case_id,
            "category": "crud",
            "method": "POST",
            "path": "/posts/12/delete/",
            "auth_role": "member_a",
            "expected_app": {"http_status": status},
            "expected_waf": "ALLOW",
            "verification_mode": "http_only",
        })
        row.update(
            timestamp_utc=timestamp,
            http_status=status,
            transport_status="OK",
            request_attempted=True,
            http_expectation_match=True,
            execution_stage=stage,
            verdict="UNKNOWN",
        )
        return row

    test_row = make_row("TEST-POST", 200, "test")
    cleanup_row = make_row("CLEANUP-POST", 302, "cleanup")
    state = {
        "run_id": run_id,
        "target_origin": "https://orchestration-haven.cloud:443",
        "results": [test_row],
        "cleanup_results": [cleanup_row],
        "cleanup_complete": True,
    }

    def event(row, **extra):
        return {
            "trace_id": row["trace_id"],
            "run_id": run_id,
            "ts": timestamp,
            "synthetic_fixture": True,
            **extra,
        }

    waf = [
        event(test_row, action="ALLOW"),
        event(cleanup_row, action="ALLOW"),
    ]
    app = [event(test_row, status=200)]

    if mode != "missing":
        app.append(event(
            cleanup_row,
            status=500 if mode == "mismatch" else 302,
        ))
    if mode == "duplicate":
        app.append(dict(app[-1]))

    run_path = tmp_path / "run.json"
    original = json.dumps(state)
    run_path.write_text(original, encoding="utf-8")

    for filename, events in (("waf.jsonl", waf), ("app.jsonl", app)):
        raw = [{"message": json.dumps(item)} for item in events]
        selected = cli.select_cloudwatch_run_logs(raw, state)
        assert selected["counts"]["selected"] == len(events)
        (tmp_path / filename).write_text(
            "".join(json.dumps(item) + "\n"
                    for item in selected["events"]),
            encoding="utf-8",
        )

    output = tmp_path / "correlated"
    code = cli.correlate(argparse.Namespace(
        run_json=run_path,
        waf_log=tmp_path / "waf.jsonl",
        app_log=tmp_path / "app.jsonl",
        output_dir=output,
    ))

    result = cli.load_json(output / "correlated_results.json")
    assert code == expected_code
    assert len(result["results"]) == 1
    assert len(result["cleanup_results"]) == 1
    assert result["results"][0]["verdict"] == "PASS"
    cleanup = result["cleanup_results"][0]
    assert cleanup["correlation_status"] == expected_status
    assert cleanup["verdict"] == expected_verdict
    assert run_path.read_text(encoding="utf-8") == original