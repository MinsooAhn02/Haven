from pathlib import Path

import pytest

import request_verify as rv

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
SUITE = FIXTURES / "cases_aws_upload.json"


def load_suite():
    return rv.load_json(SUITE)


def find(suite, case_id):
    return next(c for c in suite["cases"] if c["case_id"] == case_id)


def test_aws_upload_suite_is_valid_for_aws():
    suite = load_suite()
    rv.validate_suite(suite, FIXTURES)
    rv.validate_aws_cleanup_suite(rv.expand_suite_variants(suite, FIXTURES))


def test_aws_upload_suite_uses_only_created_posts():
    suite = load_suite()
    creators = {
        c["case_id"] for c in suite["cases"] if c.get("capture_post_id")
    }

    for case in suite["cases"]:
        assert "/posts/1/" not in case["path"]
        assert "/posts/2/" not in case["path"]
        if "{post_id}" in case["path"]:
            assert case["post_reference"] in creators

    assert {c["post_reference"] for c in suite["cleanup_cases"]} == creators


def test_anonymous_upload_allowed_only_as_login_redirect():
    suite = load_suite()
    find(suite, "UP-13-ANON-VALID-CSRF")["expected_app"]["http_status"] = 200

    with pytest.raises(rv.ConfigError):
        rv.validate_suite(suite, FIXTURES)


def test_logged_in_non_owner_redirect_is_not_a_denial():
    suite = load_suite()
    find(suite, "UP-06-C-UPLOAD-DENIED")["expected_app"]["http_status"] = 302

    with pytest.raises(rv.ConfigError):
        rv.validate_suite(suite, FIXTURES)


def test_upload_cleanup_reserve():
    suite = rv.expand_suite_variants(load_suite(), FIXTURES)

    # 게시글 2개 정리 × 4 + 남은 B 공유 1개 × 3 + 여유 5
    assert rv.aws_cleanup_reserve(
        suite["cases"], suite["cleanup_cases"]
    ) == 16
