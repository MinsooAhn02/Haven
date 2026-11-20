import copy
import json
from argparse import Namespace
from pathlib import Path

import pytest

import request_verify as rv

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
PROFILE_FILE = FIXTURES / "block_expectations.json"
TARGET = "https://orchestration-haven.cloud"


def profile():
    return rv.load_json(PROFILE_FILE)


def expanded(suite_file):
    suite = rv.load_json(FIXTURES / suite_file)
    rv.validate_suite(suite, FIXTURES)
    return rv.expand_suite_variants(suite, FIXTURES)


def suite_files():
    return sorted({entry["suite_file"] for entry in profile()["suites"].values()})


def blocked_ids(suite_file, stage):
    suite = rv.apply_block_profile(expanded(suite_file), profile(), stage)
    rv.validate_aws_cleanup_suite(suite)
    return {c["case_id"] for c in suite["cases"] if c["expected_waf"] == "BLOCK"}, suite


@pytest.mark.parametrize("suite_file", suite_files())
@pytest.mark.parametrize("stage", [1, 2, 3])
def test_profile_matches_every_suite(suite_file, stage):
    # 프로필의 케이스 ID가 시험 묶음과 어긋나면 ConfigError가 난다.
    blocked, suite = blocked_ids(suite_file, stage)
    for case in suite["cases"]:
        assert case["verification_mode"] == "http_only"
        if case["case_id"] in blocked:
            assert case["expected_app"] == {"http_status": 403}
        else:
            assert case["expected_waf"] == "ALLOW"


@pytest.mark.parametrize("suite_file", suite_files())
def test_stages_are_cumulative(suite_file):
    one, _ = blocked_ids(suite_file, 1)
    two, _ = blocked_ids(suite_file, 2)
    three, _ = blocked_ids(suite_file, 3)
    assert one <= two <= three


@pytest.mark.parametrize("suite_file, case_id", [
    ("cases_aws_sec_remaining.json", "SEC-58-LOGIN-SPECIAL-CHARS-P01"),   # 로그인 SQLi_BODY 예외
    ("cases_aws_sec_remaining.json", "SEC-58-UPLOAD-PDF-XMP-P02"),        # 업로드 XSS 예외
    ("cases_aws_sec_remaining.json", "SEC-60-UPLOAD-BODY-OFFSET-P01"),    # 업로드 XSS 예외
    ("cases_aws_sec_remaining.json", "SEC-60-UPLOAD-BODY-OFFSET-P02"),    # SizeRestrictions_BODY Count
    ("cases_aws_upload.json", "UP-01-04-A-VALID-EXTRA-P02"),              # 2 MiB 정상 업로드
    ("cases_aws_waf_verify.json", "SEC-14-FILENAME-XSS-UPLOAD-P01"),      # 업로드 XSS 예외
    ("cases_aws_header.json", "HDR-NO-UA"),                               # NoUserAgent_HEADER Count
    ("cases_aws_header.json", "HDR-FP-BROWSER-UA"),                       # 정상
])
def test_exceptions_and_normal_requests_are_never_blocked(suite_file, case_id):
    blocked, suite = blocked_ids(suite_file, 3)
    assert case_id in {c["case_id"] for c in suite["cases"]}
    assert case_id not in blocked


@pytest.mark.parametrize("suite_file, case_id, stage", [
    ("cases_aws_waf_verify.json", "WAF-PATH-ENV", 1),
    ("cases_aws_header.json", "HDR-LOG4J-OBFUSCATED", 1),
    ("cases_aws_security_phase2.json", "SEC-01-P02", 2),   # 로그인 SQLi는 Extended 규칙으로 막힘
    ("cases_aws_waf_verify.json", "SEC-02-PASSWORD-SQLI-P01", 2),
    ("cases_aws_waf_verify.json", "SEC-12-Q-SVG", 3),
    ("cases_aws_header.json", "HDR-BADBOT-UA", 3),
])
def test_attacks_are_blocked_from_their_stage(suite_file, case_id, stage):
    if stage > 1:
        before, _ = blocked_ids(suite_file, stage - 1)
        assert case_id not in before
    blocked, _ = blocked_ids(suite_file, stage)
    assert case_id in blocked


def test_blocked_creation_marks_cleanup_as_expect_absent():
    _, suite = blocked_ids("cases_aws_security_phase2.json", 2)
    creations = {c["case_id"] for c in suite["cases"] if c.get("blocked_creation")}
    assert creations == {"SEC-06", "SEC-07", "SEC-10"}
    absent = {c["post_reference"] for c in suite["cleanup_cases"] if c.get("expect_absent")}
    assert absent == creations


def test_unknown_case_in_profile_is_rejected():
    data = profile()
    entry = next(e for e in data["suites"].values() if e["suite_file"] == "cases_aws_header.json")
    entry["block"]["NO-SUCH-CASE"] = {"stage": 1}
    with pytest.raises(rv.ConfigError):
        rv.apply_block_profile(expanded("cases_aws_header.json"), data, 1)


def test_profile_and_stage_must_be_given_together(tmp_path):
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"approved_origins": [TARGET]}), encoding="utf-8")
    args = Namespace(
        target=TARGET, allowlist=allow, cases=FIXTURES / "cases_aws_header.json",
        fixture_dir=FIXTURES, output_dir=tmp_path / "out", phase=None, timeout=3,
        max_requests=50, rate=1, max_duration=60, max_response_bytes=rv.MAX_RESPONSE,
        manual_checkpoints=False, dry_run=True, prompt_seed_password=False,
        expect_profile=PROFILE_FILE, block_stage=None,
    )
    with pytest.raises(rv.ConfigError):
        rv.run(args)


def mini_suite():
    """게시글 하나는 정상 생성, 하나는 차단을 기대하는 최소 묶음."""
    def case(cid, path, inp, status, **kw):
        d = {"case_id": cid, "phase": 3, "category": "x", "method": "POST", "path": path,
             "auth_role": "member_a", "input_reference": inp, "expected_app": {"http_status": status},
             "expected_waf": "NOT_APPLICABLE", "max_requests": 1, "verification_mode": "manual_required",
             "note": "x"}
        d.update(kw)
        return d
    cleanup = [
        case(f"CLEANUP-{ref}", "/posts/{post_id}/delete/", "post_empty_valid.json", 302,
             post_reference=ref, after_case=ref)
        for ref in ("SETUP", "SQL-POST")
    ]
    return {
        "schema_version": 1, "suite_id": "mini-block-001", "suite_kind": "regression",
        "cases": [
            case("SETUP", "/posts/new/", "post_valid_record.json", 302, capture_post_id=True),
            case("SQL-POST", "/posts/new/", "post_valid_record.json", 302, capture_post_id=True),
        ],
        "cleanup_cases": cleanup,
    }


@pytest.mark.parametrize("waf_blocks", [True, False])
def test_blocked_creation_run(tmp_path, monkeypatch, waf_blocks):
    suite_file = tmp_path / "suite.json"
    suite_file.write_text(json.dumps(mini_suite()), encoding="utf-8")
    profile_file = tmp_path / "profile.json"
    profile_file.write_text(json.dumps({"schema_version": 1, "profile_id": "t", "suites": {
        "mini-block-001": {"block": {"SQL-POST": {"stage": 2}}}}}), encoding="utf-8")
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"approved_origins": [TARGET]}), encoding="utf-8")
    args = Namespace(
        target=TARGET, allowlist=allow, cases=suite_file, fixture_dir=FIXTURES,
        output_dir=tmp_path / "out", phase=None, timeout=3, max_requests=50, rate=5,
        max_duration=60, max_response_bytes=rv.MAX_RESPONSE, manual_checkpoints=False,
        dry_run=False, prompt_seed_password=False, expect_profile=profile_file, block_stage=2,
    )
    posts, markers, state = {}, {}, {"next": 70}

    def detail(status, location=None):
        return {"status": status, "location": location, "elapsed_ms": 0.1, "body_bytes": 0,
                "sha256": None, "headers": {}, "request_body_bytes": None}

    def fake_send(s, method, target, path, budget, request_id, **kw):
        budget.begin()
        budget.responses_received += 1
        if kw.get("on_send"):
            kw["on_send"](rv.utc_now())
        if method == "POST" and path == "/posts/new/":
            marker = kw["fields"]["title"].split(" ", 1)[0]
            if waf_blocks and marker.endswith(":SQL-POST]"):
                return detail(403), None
            state["next"] += 1
            posts[state["next"]] = True
            markers[marker] = state["next"]
            return detail(302, f"/posts/{state['next']}/"), None
        pid = int(path.strip("/").split("/")[1])
        if path.endswith("/delete/"):
            posts.pop(pid, None)
            return detail(302, "/posts/"), None
        if path.endswith("/shares/"):
            return detail(200), b'<section aria-labelledby="share-list-heading"><ul></ul></section>'
        return detail(200 if pid in posts else 404), None

    def fake_lookup(session, target, budget, run_id, marker):
        budget.begin()
        budget.responses_received += 1
        pid = markers.get(marker)
        return pid if pid in posts else None

    monkeypatch.setattr(rv, "prep_login", lambda s, *a, **k: s.cookies.set("csrftoken", "x"))
    monkeypatch.setattr(rv, "bounded_send", fake_send)
    monkeypatch.setattr(rv, "csrf_for_post", lambda *a, **k: "x")
    monkeypatch.setattr(rv, "find_aws_post_by_marker", fake_lookup)

    code = rv.run(args)
    result = rv.load_json(args.output_dir / "results.json")
    rows = {r["case_id"]: r for r in result["results"]}
    cleanup = {r["case_id"]: r for r in result["cleanup_results"]}
    assert posts == {}  # 어떤 경우에도 시험 게시글이 남지 않는다
    if waf_blocks:
        assert code == 3  # http_only라도 로그 대조 전이므로 UNKNOWN
        assert rows["SQL-POST"]["creation_blocked"] is True
        assert cleanup["CLEANUP-SQL-POST"]["skip_reason"] == "creation_blocked_absent_verified"
        assert result["cleanup_complete"] is True
    else:
        # 막히지 않으면 실행을 멈추고, 생긴 게시글은 정리하되 실패로 남긴다.
        assert code == 2
        assert result["cleanup_complete"] is False
        assert cleanup["CLEANUP-SQL-POST"]["unexpected_post_created"] is True
