import collections
from pathlib import Path

import pytest

import request_verify as rv

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
SUITE = FIXTURES / "cases_aws_sec_remaining.json"
MARKER = "<script>alert('haven-waf-test')</script>".encode()


def expanded():
    suite = rv.load_json(SUITE)
    rv.validate_suite(suite, FIXTURES)
    return rv.expand_suite_variants(suite, FIXTURES)


def payload_of(case):
    if "_variant_payload" in case:
        return case["_variant_payload"]
    return rv.read_payload(FIXTURES, case["input_reference"])


def cases_by_prefix(prefix):
    return [c for c in expanded()["cases"] if c["case_id"].startswith(prefix)]


def test_sec_remaining_suite_is_valid_for_aws():
    rv.validate_aws_cleanup_suite(expanded())


def test_login_failures_stay_far_below_rate_limits():
    # 로그인 실패 제한: 계정당 15분 5회, IP당 15분 30회
    logins = [
        c for c in expanded()["cases"]
        if c["path"] == "/accounts/login/" and c["method"] == "POST"
    ]
    per_user = collections.Counter(payload_of(c)["fields"]["username"] for c in logins)
    assert len(logins) <= 15
    assert max(per_user.values()) == 1


def test_signup_variants_never_create_accounts():
    # 비밀번호 확인을 일부러 다르게 넣어 폼 오류(400)만 나야 한다.
    signups = cases_by_prefix("SEC-58-SIGNUP-BENIGN")
    assert len(signups) == 3
    for case in signups:
        fields = payload_of(case)["fields"]
        assert fields["password1"] != fields["password2"]
        assert case["expected_app"]["http_status"] == 400


def test_aws_mode_rejects_signup_that_expects_success():
    suite = expanded()
    signup = next(c for c in suite["cases"] if c["path"] == "/accounts/signup/")
    signup["expected_app"] = {"http_status": 302}
    with pytest.raises(rv.ConfigError):
        rv.validate_aws_cleanup_suite(suite)


def test_upload_marker_is_before_and_after_waf_8kb_limit():
    uploads = sorted(cases_by_prefix("SEC-60-UPLOAD-BODY-OFFSET"), key=lambda c: c["case_id"])
    offsets = []
    for case in uploads:
        data = (FIXTURES / payload_of(case)["file"]["local_fixture_path"]).read_bytes()
        assert len(data) < 2 * 1024 * 1024
        data.decode("utf-8")
        offsets.append(data.index(MARKER))
    # P01은 파일 맨 앞, P02는 파일 안에서도 8KB 뒤(multipart 머리말까지 더하면 더 뒤)
    assert offsets[0] == 0
    assert offsets[1] > 8192


def test_created_posts_are_cleaned_up():
    suite = rv.load_json(SUITE)
    creators = {c["case_id"] for c in suite["cases"] if c.get("capture_post_id")}
    cleaned = {c["post_reference"] for c in suite["cleanup_cases"]}
    assert creators == cleaned
