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


@pytest.mark.parametrize(
    "mode,expected_code,expected_status,expected_verdict",
    [
        ("matched", 0, "MATCHED", "PASS"),
        ("missing", 3, "UNRESOLVED", "UNKNOWN"),
        ("duplicate", 3, "UNRESOLVED", "UNKNOWN"),
        ("mismatch", 1, "MATCHED", "FAIL"),
        ("legacy", 3, "UNRESOLVED", "UNKNOWN"),
    ],
)
def test_verification_get_correlation(
    tmp_path, mode, expected_code, expected_status, expected_verdict
):
    run_id = "synthetic-verification-run"
    timestamp = "2026-11-16T01:49:44+00:00"

    def make_row(case_id, stage):
        row = cli.base_record(run_id, {
            "case_id": case_id,
            "category": "crud",
            "method": "POST",
            "path": "/posts/12/delete/",
            "auth_role": "member_a",
            "expected_app": {"http_status": 302},
            "expected_waf": "ALLOW",
            "verification_mode": "http_only",
        })
        row.update(
            timestamp_utc=timestamp,
            http_status=302,
            transport_status="OK",
            request_attempted=True,
            http_expectation_match=True,
            execution_stage=stage,
            verdict="UNKNOWN",
        )
        return row

    test_row = make_row("TEST-POST", "test")
    cleanup = make_row("CLEANUP-POST", "cleanup")
    cleanup["verified_post_id"] = 12
    cleanup["response_summary"] = {
        "verification": {
            "method": "GET",
            "timestamp_utc": "2026-11-16T01:49:46+00:00",
            "path": "/posts/12/",
            "http_status": 404,
            "request_id": "synthetic-verification-id",
            "trace_id": cli.new_trace_id(),
        }
    }
    if mode == "legacy":
        del cleanup["response_summary"]["verification"]["timestamp_utc"]

    state = {
        "run_id": run_id,
        "target_origin": "https://orchestration-haven.cloud:443",
        "results": [test_row],
        "cleanup_results": [cleanup],
        "cleanup_complete": True,
    }
    verification = cli.correlation_verification_records(state)[0]

    def event(row, **extra):
        return {
            "trace_id": row["trace_id"],
            "run_id": run_id,
            "ts": row["timestamp_utc"] or "2026-11-16T01:49:46+00:00",
            "synthetic_fixture": True,
            **extra,
        }

    waf = [
        event(row, action="ALLOW")
        for row in [test_row, cleanup, verification]
    ]
    app = [
        event(test_row, status=302),
        event(cleanup, status=302),
    ]
    if mode != "missing":
        app.append(event(
            verification,
            status=200 if mode == "mismatch" else 404,
        ))
    if mode == "duplicate":
        app.append(dict(app[-1]))

    run_path = tmp_path / "run.json"
    original = json.dumps(state)
    run_path.write_text(original, encoding="utf-8")

    for filename, events in (("waf.jsonl", waf), ("app.jsonl", app)):
        selected = cli.select_cloudwatch_run_logs(
            [{"message": json.dumps(item)} for item in events],
            state,
        )
        assert selected["counts"]["selected"] == len(events)
        (tmp_path / filename).write_text(
            "".join(
                json.dumps(item) + "\n"
                for item in selected["events"]
            ),
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
    assert result["cleanup_results"][0]["verdict"] == "PASS"
    assert len(result["cleanup_verification_results"]) == 1

    checked = result["cleanup_verification_results"][0]
    assert checked["method"] == "GET"
    assert checked["expected_app"] == {"http_status": 404}
    assert checked["correlation_status"] == expected_status
    assert checked["verdict"] == expected_verdict
    assert checked["response_summary"]["file_cleanup_verified"] is False
    assert run_path.read_text(encoding="utf-8") == original


def test_correlated_csv_includes_count_rule_ids(tmp_path):
    import csv
    import request_verify as rv

    record = {
        "case_id": "WAF-SQLI-QUERY-COUNT",
        "expected_app": {"http_status": 200},
        "response_summary": None,
        "count_rule_ids": [
            "AWS#AWSManagedRulesSQLiRuleSet::SQLi_QUERYARGUMENTS",
            "AWS#AWSManagedRulesSQLiRuleSet::SQLiExtendedPatterns_QUERYARGUMENTS",
        ],
    }
    normal = {
        "case_id": "WAF-NORMAL-LOGIN-GET",
        "expected_app": {"http_status": 200},
        "response_summary": None,
    }

    rv.save_results(tmp_path, {}, [record, normal], correlation=True)

    with (tmp_path / "correlated_summary.csv").open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    assert rows[0]["count_rule_ids"] == (
        "AWS#AWSManagedRulesSQLiRuleSet::SQLi_QUERYARGUMENTS;"
        "AWS#AWSManagedRulesSQLiRuleSet::SQLiExtendedPatterns_QUERYARGUMENTS"
    )
    assert rows[1]["count_rule_ids"] == ""
    # JSON 상세에는 원래 목록이 그대로 남는다.
    assert record["count_rule_ids"][0].endswith("SQLi_QUERYARGUMENTS")