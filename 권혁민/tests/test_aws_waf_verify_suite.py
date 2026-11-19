import collections
import urllib.parse
from pathlib import Path

import request_verify as rv

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
SUITE = FIXTURES / "cases_aws_waf_verify.json"
RUN_ID = "11111111-2222-4333-8444-555555555555"


def expanded():
    suite = rv.load_json(SUITE)
    rv.validate_suite(suite, FIXTURES)
    return rv.expand_suite_variants(suite, FIXTURES)


def payload_of(case):
    # 다중 payload 케이스는 확장 뒤 _variant_payload에 각 입력이 들어 있다.
    if "_variant_payload" in case:
        return case["_variant_payload"]
    return rv.read_payload(FIXTURES, case["input_reference"])


def test_aws_waf_verify_suite_is_valid_for_aws():
    rv.validate_aws_cleanup_suite(expanded())


def test_login_failures_stay_far_below_rate_limits():
    # 로그인 실패 제한: 계정당 15분 5회, IP당 15분 30회
    logins = [
        c for c in expanded()["cases"]
        if c["path"] == "/accounts/login/" and c["method"] == "POST"
    ]
    per_user = collections.Counter(
        payload_of(c)["fields"]["username"] for c in logins
    )

    assert len(logins) <= 10
    assert max(per_user.values()) <= 4


def test_benign_edits_stay_under_app_body_limit_with_marker():
    marker = rv.aws_post_marker(RUN_ID, "AWS-WAF-SETUP-A-POST")

    for case in expanded()["cases"]:
        if not case["case_id"].startswith("SEC-58-BENIGN-EDIT"):
            continue
        fields = dict(payload_of(case)["fields"])
        fields["title"] = f"{marker} {fields['title']}"
        fields["csrfmiddlewaretoken"] = "x" * 64
        body = urllib.parse.urlencode(fields)

        # 앱 글 요청 본문 한도 8,192바이트, WAF SizeRestrictions 기준 8KB 미만
        assert len(body.encode()) < 8192, case["case_id"]
        assert len(fields["title"]) <= 200


def test_setup_post_attachments_within_per_post_limit():
    uploads = [
        c for c in expanded()["cases"]
        if c["path"] == "/posts/{post_id}/attachments/"
    ]

    # 글당 첨부 3개 한도 안에서만 업로드한다
    assert len(uploads) <= 3
