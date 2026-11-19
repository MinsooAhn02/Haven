import hashlib
import json
from argparse import Namespace
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests

import request_verify as rv

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
SUITE = FIXTURES / "cases_aws_session_attach.json"
TARGET = "https://orchestration-haven.cloud"
HOST = urlsplit(TARGET).hostname


def load_suite():
    data = rv.load_json(SUITE)
    rv.validate_suite(data, FIXTURES)
    return data


def case_by_id(data, case_id):
    return next(c for c in data["cases"] if c["case_id"] == case_id)


def test_suite_is_valid_for_aws():
    rv.validate_aws_cleanup_suite(rv.expand_suite_variants(load_suite(), FIXTURES))


def upload_fixture_bytes():
    upload = case_by_id(load_suite(), "SEC-30-41-A-UPLOAD")
    payload = rv.read_payload(FIXTURES, upload["input_reference"])
    return (FIXTURES / payload["file"]["local_fixture_path"]).read_bytes()


def test_download_expectation_matches_fixture_hash():
    data = upload_fixture_bytes()
    # Git이 줄바꿈을 바꾸면 해시가 달라지므로, 줄바꿈 없는 파일만 쓴다.
    assert b"\n" not in data and b"\r" not in data
    expected = case_by_id(load_suite(), "SEC-41-A-DOWNLOAD")["expected_app"]
    assert expected["sha256"] == hashlib.sha256(data).hexdigest()
    assert expected["body_bytes"] == len(data)


@pytest.mark.parametrize("case_id, change", [
    ("SEC-18-B-FIXATION-PROBE", {"auth_role": "member_a"}),        # A는 이미 앞에서 로그인
    ("SEC-19-C-LOGOUT-REUSE", {"method": "POST", "input_reference": "post_empty_valid.json"}),
    ("SEC-29-CROSS-SHARE-ID", {"share_post_reference": "AWS-SA-SETUP-P1"}),  # 같은 글이면 의미 없음
    ("SEC-41-A-DOWNLOAD", {"attachment_reference": "AWS-SA-SETUP-P1"}),     # 업로드 케이스가 아님
    ("SEC-30-C-DOWNLOAD-DENIED", {"post_reference": "AWS-SA-SETUP-P2"}),    # 첨부가 있는 글과 다름
])
def test_rejects_misconfigured_new_fields(case_id, change):
    data = load_suite()
    case_by_id(data, case_id).update(change)
    with pytest.raises(rv.ConfigError):
        rv.validate_suite(data, FIXTURES)


def test_logout_reuse_must_be_last_request_of_role():
    data = load_suite()
    data["cases"].append({
        "case_id": "LATE-C", "phase": 3, "category": "x", "method": "GET",
        "path": "/posts/{post_id}/", "post_reference": "AWS-SA-SETUP-P2",
        "auth_role": "member_c", "input_reference": None,
        "expected_app": {"http_status": 404}, "expected_waf": "NOT_APPLICABLE",
        "max_requests": 1, "verification_mode": "manual_required", "note": "x",
    })
    with pytest.raises(rv.ConfigError):
        rv.validate_suite(data, FIXTURES)


def server_cookie(value):
    return requests.cookies.create_cookie(
        "sessionid", value, domain=HOST, path="/", secure=True,
        rest={"HttpOnly": None, "SameSite": "Lax"},
    )


def test_session_report_never_contains_cookie_value():
    s = requests.Session()
    s.cookies.set_cookie(server_cookie("secret-session-value"))
    report = rv.session_cookie_report(s, TARGET)
    assert "secret-session-value" not in json.dumps(report)
    assert rv.session_report_ok(report)


def test_session_report_flags_fixation():
    s = requests.Session()
    s.cookies.set_cookie(server_cookie(rv.FIXATION_SESSION_VALUE))
    assert not rv.session_report_ok(rv.session_cookie_report(s, TARGET))


def test_full_run_against_fake_app(tmp_path, monkeypatch):
    """가짜 앱으로 새 기능 전체 흐름(세션 교체·로그아웃 재사용·첨부 ID·교차 공유 ID)을 확인한다."""
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"approved_origins": [TARGET]}), encoding="utf-8")
    args = Namespace(
        target=TARGET, allowlist=allow, cases=SUITE, fixture_dir=FIXTURES,
        output_dir=tmp_path / "out", phase=None, timeout=3, max_requests=150,
        rate=5, max_duration=120, max_response_bytes=rv.MAX_RESPONSE,
        manual_checkpoints=False, dry_run=False, prompt_seed_password=False,
    )
    data = upload_fixture_bytes()
    state = {"posts": {}, "shares": {}, "attachments": {}, "valid": {}, "next": 100,
             "sent": [], "fixation_seen": False, "markers": {}}
    names = {"member_a": "aws_a", "member_b": "aws_b", "member_c": "aws_c"}

    def nid():
        state["next"] += 1
        return state["next"]

    def fake_login(s, target, budget, role, *rest):
        planted = [c for c in s.cookies if c.name == "sessionid"]
        if planted and planted[0].value == rv.FIXATION_SESSION_VALUE:
            state["fixation_seen"] = True
        value = f"sess-{role}-{nid()}"
        state["valid"][value] = role
        s.cookies.set_cookie(server_cookie(value))   # Django처럼 로그인 시 새 세션으로 교체
        s.cookies.set("csrftoken", "synthetic-csrf")
        s._haven_username = names[role]

    def role_of(s):
        values = [c.value for c in s.cookies if c.name == "sessionid"]
        return state["valid"].get(values[0]) if values else None

    def detail(status, location=None, **extra):
        d = {"status": status, "location": location, "elapsed_ms": 0.1, "body_bytes": 0,
             "sha256": None, "headers": {}, "request_body_bytes": None}
        d.update(extra)
        return d

    def can_read(role, pid):
        post = state["posts"].get(pid)
        return post is not None and (post == role or role in state["shares"].get(pid, {}).values())

    def fake_send(s, method, target, path, budget, request_id, **kw):
        budget.begin()
        budget.responses_received += 1
        if kw.get("on_send"):
            kw["on_send"](rv.utc_now())
        role = role_of(s)
        state["sent"].append((role, method, path))
        parts = path.strip("/").split("/")
        if method == "POST" and path == "/accounts/logout/":
            for k, v in list(state["valid"].items()):
                if v == role and k in [c.value for c in s.cookies if c.name == "sessionid"]:
                    del state["valid"][k]
            return detail(302, "/accounts/login/"), None
        if role is None:
            return detail(302, "/accounts/login/?next=x"), None
        if method == "POST" and path == "/posts/new/":
            pid = nid()
            state["posts"][pid] = role
            state["markers"][kw["fields"]["title"].split(" ", 1)[0]] = pid
            return detail(302, f"/posts/{pid}/"), None
        pid = int(parts[1])
        if path == f"/posts/{pid}/" and method == "GET":
            if not can_read(role, pid):
                return detail(404), None
            links = "".join(f'<a href="/posts/{pid}/attachments/{a}/download/">x</a>'
                            for a, p in state["attachments"].items() if p == pid)
            return detail(200), f"<html>{links}</html>".encode()
        if path == f"/posts/{pid}/shares/":
            assert state["posts"][pid] == role
            if method == "POST":
                recipient = next(r for r, n in names.items() if n == kw["fields"]["username"])
                state["shares"].setdefault(pid, {})[nid()] = recipient
                return detail(302, f"/posts/{pid}/shares/"), None
            rows = "".join(
                f'<li class="record-row"><div><h3 class="record-title">{names[r]}</h3></div>'
                f'<form method="post" action="/posts/{pid}/shares/{sid}/revoke/"></form></li>'
                for sid, r in state["shares"].get(pid, {}).items())
            return detail(200), (
                '<html><section aria-labelledby="share-list-heading"><h2 id="share-list-heading">s</h2>'
                f'<ul class="record-list">{rows}</ul></section></html>').encode()
        if parts[2:3] == ["shares"] and parts[-1] == "revoke":
            sid = int(parts[3])
            if state["posts"].get(pid) != role or sid not in state["shares"].get(pid, {}):
                return detail(404), None
            del state["shares"][pid][sid]
            return detail(302, f"/posts/{pid}/shares/"), None
        if path == f"/posts/{pid}/attachments/" and method == "POST":
            state["attachments"][nid()] = pid
            return detail(302, f"/posts/{pid}/"), None
        if parts[2:3] == ["attachments"] and parts[-1] == "download":
            aid = int(parts[3])
            if state["attachments"].get(aid) != pid or not can_read(role, pid):
                return detail(404), None
            return detail(200, body_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), headers={
                "Content-Disposition": 'attachment; filename="haven_test.txt"',
                "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}), None
        if path == f"/posts/{pid}/delete/" and method == "POST":
            assert state["posts"][pid] == role
            del state["posts"][pid]
            state["shares"].pop(pid, None)
            return detail(302, "/posts/"), None
        pytest.fail(f"예상하지 않은 요청: {role} {method} {path}")

    monkeypatch.setattr(rv, "prep_login", fake_login)
    monkeypatch.setattr(rv, "bounded_send", fake_send)
    monkeypatch.setattr(rv, "csrf_for_post", lambda *a, **k: "synthetic-csrf")

    def fake_lookup(session, target, budget, run_id, marker):
        budget.begin()
        budget.responses_received += 1
        pid = state["markers"].get(marker)
        return pid if pid in state["posts"] else None

    monkeypatch.setattr(rv, "find_aws_post_by_marker", fake_lookup)

    assert rv.run(args) == 3   # HTTP는 모두 일치, manual_required라 UNKNOWN만 남음
    result = rv.load_json(args.output_dir / "results.json")
    rows = {r["case_id"]: r for r in result["results"]}
    assert all(r["http_expectation_match"] for r in result["results"]), [
        (r["case_id"], r["http_status"]) for r in result["results"] if not r["http_expectation_match"]]
    assert state["fixation_seen"] is True
    for cid in ("SEC-18-B-FIXATION-PROBE", "SEC-18-C-FIXATION-PROBE"):
        assert rows[cid]["session_check"]["rotated"] is True
    assert rows["SEC-30-41-A-UPLOAD"]["created_attachment_id"] in state["attachments"]
    assert rows["SEC-19-C-LOGOUT-REUSE"]["logout_before_request"] is True
    assert result["cleanup_complete"] is True
    assert state["posts"] == {}
    # 결과 파일에 세션 값이 남지 않아야 한다.
    text = (args.output_dir / "results.json").read_text(encoding="utf-8")
    assert "sess-member" not in text
