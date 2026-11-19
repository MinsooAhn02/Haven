import copy
from pathlib import Path

import pytest

import request_verify as rv

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
AWS = "https://orchestration-haven.cloud"
SUITE = FIXTURES / "cases_aws_security_phase2.json"


def load_suite():
    return rv.load_json(SUITE)


def find(suite, case_id):
    return next(c for c in suite["cases"] if c["case_id"] == case_id)


def validate_for_aws(suite):
    rv.validate_suite(suite, FIXTURES)
    rv.validate_aws_cleanup_suite(rv.expand_suite_variants(suite, FIXTURES))


def test_aws_security_suite_is_valid_for_aws():
    validate_for_aws(load_suite())


def test_non_owner_delete_allowed_only_as_denial():
    suite = load_suite()
    find(suite, "SEC-25")["expected_app"]["http_status"] = 302

    with pytest.raises(rv.ConfigError):
        validate_for_aws(suite)


def test_owner_delete_in_main_cases_is_rejected():
    suite = load_suite()
    case = find(suite, "SEC-25")
    case["auth_role"] = "member_a"

    with pytest.raises(rv.ConfigError):
        validate_for_aws(suite)


def test_share_lookup_role_requires_revoke_role():
    suite = load_suite()
    case = find(suite, "SEC-28")
    del case["share_revoke_role"]

    with pytest.raises(rv.ConfigError):
        rv.validate_suite(suite, FIXTURES)


def test_self_revoke_needs_separate_lookup_owner():
    suite = load_suite()
    del find(suite, "SEC-28")["share_lookup_role"]

    with pytest.raises(rv.ConfigError):
        rv.validate_suite(suite, FIXTURES)


def test_lookup_owner_must_differ_from_recipient():
    suite = load_suite()
    find(suite, "SEC-28")["share_lookup_role"] = "member_b"

    with pytest.raises(rv.ConfigError):
        rv.validate_suite(suite, FIXTURES)


def test_delete_confirmation_get_is_allowed_but_other_gets_are_not():
    suite = load_suite()
    find(suite, "SEC-45-DELETE-GET")["path"] = "/posts/{post_id}/edit/"

    with pytest.raises(rv.ConfigError):
        rv.validate_suite(suite, FIXTURES)


def test_aws_edit_keeps_creation_marker(monkeypatch):
    monkeypatch.setattr(rv, "csrf_for_post", lambda *a, **k: "test-csrf")
    case = copy.deepcopy(find(load_suite(), "SEC-11-PREP"))
    case["path"] = "/posts/57/edit/"
    run_id = "11111111-2222-4333-8444-555555555555"

    with rv.new_session() as session:
        fields, _headers, _file = rv.prepare_case_request(
            session, case, FIXTURES, rv.canonical_origin(AWS),
            None, run_id, [], rv.MAX_RESPONSE,
        )

    marker = rv.aws_post_marker(run_id, "AWS-SEC-SETUP-A-POST")
    assert fields["title"].startswith(marker + " ")
    assert "SEC mix" in fields["title"]


def test_local_edit_title_is_unchanged(monkeypatch):
    monkeypatch.setattr(rv, "csrf_for_post", lambda *a, **k: "test-csrf")
    case = copy.deepcopy(find(load_suite(), "SEC-11-PREP"))
    case["path"] = "/posts/57/edit/"

    with rv.new_session() as session:
        fields, _headers, _file = rv.prepare_case_request(
            session, case, FIXTURES, rv.canonical_origin("http://127.0.0.1:8000"),
            None, "11111111-2222-4333-8444-555555555555", [], rv.MAX_RESPONSE,
        )

    assert not fields["title"].startswith("[HAVEN-AWS:")


def test_share_recipient_must_log_in_before_share():
    suite = load_suite()
    suite["cases"] = [
        c for c in suite["cases"] if c["case_id"] != "AWS-SEC-B-BEFORE-SHARE"
    ]

    with pytest.raises(rv.ConfigError, match="공유 수신자"):
        rv.validate_suite(suite, FIXTURES)


def test_revoke_needs_owner_and_recipient_logged_in():
    suite = load_suite()
    # SEC-28을 B의 첫 요청보다 앞으로 옮기면 B가 아직 로그인 전이다.
    sec28 = find(suite, "SEC-28")
    suite["cases"].remove(sec28)
    share_index = next(
        i for i, c in enumerate(suite["cases"])
        if c["case_id"] == "AWS-SEC-B-BEFORE-SHARE"
    )
    sec28["auth_role"] = "member_c"
    suite["cases"].insert(share_index, sec28)

    with pytest.raises(rv.ConfigError):
        rv.validate_suite(suite, FIXTURES)


def test_cleanup_reserve_covers_shares_and_every_post():
    suite = rv.expand_suite_variants(load_suite(), FIXTURES)

    reserve = rv.aws_cleanup_reserve(
        suite["cases"], suite["cleanup_cases"]
    )

    # 11/19 실제 실행: 게시글 5개 정리 + 남은 공유 1개 = 23건 필요(예약 20건에서 부족)
    assert reserve >= 5 * 4 + 1 * 3
    assert reserve == 28


def test_cleanup_reserve_keeps_minimum_for_small_suite():
    assert rv.aws_cleanup_reserve([], [{"case_id": "X"}]) == 9
    assert rv.aws_cleanup_reserve([], []) == 8