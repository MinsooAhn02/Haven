"""요청 단위 구조화 로그 (D5, 명세 3.1·UP-12, 앱계약.md 7장).

- 요청 하나당 JSON 한 줄(권혁민 CLI correlate는 같은 Trace에 두 줄이면 판정 불가)
- trace_id·client_request_id·run_id는 형식이 맞을 때만
- 로그인 성공/실패·로그아웃·CSRF 실패·크기 초과를 action으로 구분
- 비밀번호·본문·파일 이름/내용·쿼리 문자열·세션/CSRF 토큰은 남기지 않는다
"""
import json
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase, override_settings

from posts import attachments
from posts.models import Attachment, Post, PostShare

TRACE = "1-6730a1b2-0123456789abcdef01234567"
PASSWORD = "Virtual-Pass-2026!"


def trace_header(root=TRACE):
    return f"Root={root};Self=1-6730a1b3-aaaaaaaaaaaaaaaaaaaaaaaa"


class RequestLogBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a", password=PASSWORD)
        cls.b = User.objects.create_user("member_b", password=PASSWORD)
        cls.op = User.objects.create_user("operator", password=PASSWORD)
        cls.op.user_permissions.add(*Permission.objects.filter(content_type__app_label="adminpanel"))
        cls.p1 = Post.objects.create(owner=cls.a, title="제목", body="본문")
        PostShare.objects.create(post=cls.p1, recipient=cls.b)

    def logged(self, func):
        """func()을 실행하고 haven.request 로그 줄들을 JSON으로 돌려준다."""
        with self.assertLogs("haven.request", "INFO") as cm:
            response = func()
        return response, [json.loads(record.getMessage()) for record in cm.records]

    def one(self, func):
        response, events = self.logged(func)
        self.assertEqual(len(events), 1, events)
        return response, events[0]


class FieldTests(RequestLogBase):
    def test_one_json_line_with_contract_fields(self):
        self.client.force_login(self.a)
        res, ev = self.one(lambda: self.client.get(f"/posts/{self.p1.pk}/"))
        self.assertEqual(
            set(ev),
            {"ts", "request_id", "trace_id", "client_request_id", "run_id", "method", "path", "view", "action",
             "actor_id", "resource_id", "status", "result", "elapsed_ms"},
        )
        self.assertEqual(
            (ev["method"], ev["path"], ev["view"], ev["action"], ev["actor_id"], ev["resource_id"], ev["status"], ev["result"]),
            ("GET", f"/posts/{self.p1.pk}/", "posts:detail", "posts:detail", self.a.pk, f"post:{self.p1.pk}", 200, "ok"),
        )
        self.assertEqual(res["X-Request-ID"], ev["request_id"])
        self.assertRegex(ev["request_id"], r"^[0-9a-f]{32}$")
        self.assertRegex(ev["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        ts = datetime.fromisoformat(ev["ts"].replace("Z", "+00:00"))
        self.assertLess(abs(datetime.now(timezone.utc) - ts), timedelta(seconds=30))

    def test_cli_headers_are_recorded_when_well_formed(self):
        rid, run = str(uuid.uuid4()), "run-20261110T030000Z-ab12"
        self.client.force_login(self.a)
        _, ev = self.one(lambda: self.client.get(
            "/posts/", HTTP_X_AMZN_TRACE_ID=trace_header(TRACE.upper().replace("1-", "1-", 1)),
            HTTP_X_HAVEN_REQUEST_ID=rid, HTTP_X_HAVEN_RUN_ID=run,
        ))
        self.assertEqual((ev["trace_id"], ev["client_request_id"], ev["run_id"]), (TRACE, rid, run))

    def test_malformed_or_injected_header_values_become_null(self):
        bad_traces = [
            "Root=1-xyz-123",
            f"Root={TRACE};Root=1-6730a1b2-ffffffffffffffffffffffff",  # Root 두 개
            "Self=1-6730a1b2-0123456789abcdef01234567",  # Root 없음
            "Root=" + TRACE + "\nINJECTED",
            "x" * 300,
        ]
        bad_ids = ["abc\ndef", "a b", "<script>", "", "x" * 129, '{"run_id":"evil"}']
        for trace, cid in zip(bad_traces + bad_traces[:1], bad_ids):
            with self.subTest(trace=trace[:30], cid=cid[:20]):
                _, ev = self.one(lambda: Client().get(
                    "/accounts/login/", HTTP_X_AMZN_TRACE_ID=trace, HTTP_X_HAVEN_REQUEST_ID=cid, HTTP_X_HAVEN_RUN_ID=cid,
                ))
                self.assertEqual((ev["trace_id"], ev["client_request_id"], ev["run_id"]), (None, None, None))

    def test_healthz_is_not_logged(self):
        with self.assertNoLogs("haven.request", "INFO"):
            self.assertEqual(self.client.get("/healthz").status_code, 200)


class ActionTests(RequestLogBase):
    def test_login_success_failure_and_logout(self):
        client = Client()
        _, ev = self.one(lambda: client.post("/accounts/login/", {"username": "member_a", "password": PASSWORD}))
        self.assertEqual((ev["action"], ev["status"], ev["result"], ev["actor_id"]), ("login_success", 302, "ok", self.a.pk))
        _, ev = self.one(lambda: client.post("/accounts/logout/"))
        self.assertEqual((ev["action"], ev["status"], ev["actor_id"]), ("logout", 302, None))
        _, ev = self.one(lambda: Client().post("/accounts/login/", {"username": "member_a", "password": "wrong"}))
        self.assertEqual((ev["action"], ev["status"], ev["result"], ev["actor_id"]), ("login_failure", 400, "invalid", None))

    def test_csrf_failure_is_marked(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.a)
        res, ev = self.one(lambda: client.post("/posts/new/", {"title": "t", "body": "b"}))
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, "403_csrf.html")
        self.assertEqual((ev["action"], ev["view"], ev["result"], ev["actor_id"]), ("csrf_failure", "posts:create", "denied", self.a.pk))

    def test_body_too_large_is_marked(self):
        self.client.force_login(self.a)
        _, ev = self.one(lambda: self.client.post("/posts/new/", {"title": "t", "body": "x" * 9000}))
        self.assertEqual((ev["status"], ev["action"], ev["result"]), (413, "body_too_large", "denied"))

    def test_denied_access_records_actor_and_resource(self):
        self.client.force_login(User.objects.create_user("member_c"))
        _, ev = self.one(lambda: self.client.post(f"/posts/{self.p1.pk}/edit/", {"title": "x", "body": "y"}))
        self.assertEqual((ev["status"], ev["result"], ev["view"], ev["resource_id"]), (404, "denied", "posts:edit", f"post:{self.p1.pk}"))
        _, ev = self.one(lambda: self.client.get("/no/such/page/"))
        self.assertEqual((ev["status"], ev["view"], ev["action"], ev["resource_id"]), (404, None, None, None))

    def test_admin_status_change_resource_is_user(self):
        self.client.force_login(self.op)
        _, ev = self.one(lambda: self.client.post(f"/admin/accounts/{self.b.pk}/status/", {"is_active": "false"}))
        self.assertEqual((ev["view"], ev["resource_id"], ev["actor_id"], ev["status"]),
                         ("adminpanel:account_status", f"user:{self.b.pk}", self.op.pk, 302))

    def test_share_revoke_resource(self):
        share = PostShare.objects.get()
        self.client.force_login(self.a)
        _, ev = self.one(lambda: self.client.post(f"/posts/{self.p1.pk}/shares/{share.pk}/revoke/"))
        self.assertEqual(ev["resource_id"], f"post:{self.p1.pk}/share:{share.pk}")


class AttachmentLogTests(RequestLogBase):
    def setUp(self):
        self.upload_dir = Path(tempfile.mkdtemp(prefix="haven-log-"))
        override = override_settings(HAVEN_UPLOAD_DIR=self.upload_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.upload_dir, True)

    def test_up12_upload_download_logs_ids_but_no_file_name_or_content(self):
        from posts.tests.test_attachments import multipart

        self.client.force_login(self.a)
        body, ctype = multipart([("attachment", "비밀파일_계약서.txt", "FILE-SECRET-내용".encode(), "text/plain")])
        res, ev = self.one(lambda: self.client.generic("POST", f"/posts/{self.p1.pk}/attachments/?next=QUERY-SECRET", body, content_type=ctype))
        self.assertEqual((res.status_code, ev["view"], ev["resource_id"]), (302, "posts:attachment_upload", f"post:{self.p1.pk}"))
        att = Attachment.objects.get()
        b = Client()
        b.force_login(self.b)
        res, ev2 = self.one(lambda: b.get(f"/posts/{self.p1.pk}/attachments/{att.pk}/download/"))
        b"".join(res.streaming_content)
        self.assertEqual((ev2["status"], ev2["resource_id"], ev2["actor_id"]), (200, f"post:{self.p1.pk}/attachment:{att.pk}", self.b.pk))
        line = json.dumps([ev, ev2], ensure_ascii=False)
        for secret in ("비밀파일", "계약서", "FILE-SECRET", "QUERY-SECRET", str(att.storage_key)):
            self.assertNotIn(secret, line)

    def test_missing_file_download_is_logged_as_error(self):
        att = Attachment.objects.create(post=self.p1, original_name="x.txt", size_bytes=1, status="ACTIVE",
                                        content_type="text/plain; charset=utf-8", sha256="0" * 64)
        client = Client(raise_request_exception=False)
        client.force_login(self.a)
        with self.assertLogs("haven.attachments", "ERROR"):
            res, ev = self.one(lambda: client.get(f"/posts/{self.p1.pk}/attachments/{att.pk}/download/"))
        self.assertEqual((res.status_code, ev["result"]), (500, "error"))


class NoSecretsTests(RequestLogBase):
    def test_up12_no_password_body_tokens_or_username_attempts(self):
        client = Client(enforce_csrf_checks=True)
        token = str(client.get("/accounts/login/").context["csrf_token"])
        _, events = self.logged(lambda: client.post(
            "/accounts/login/?next=/posts/%3Fq%3DQUERY-SECRET",
            {"username": "typed-wrong-USERNAME", "password": "Secret-Pass-777!", "csrfmiddlewaretoken": token},
        ))
        client.post("/accounts/login/", {"username": "member_a", "password": PASSWORD, "csrfmiddlewaretoken": token})
        token = str(client.get("/posts/new/").context["csrf_token"])
        _, more = self.logged(lambda: client.post(
            "/posts/new/", {"title": "TITLE-SECRET", "body": "BODY-SECRET", "csrfmiddlewaretoken": token},
        ))
        line = json.dumps(events + more, ensure_ascii=False)
        cookies = [c.value for c in client.cookies.values()]
        for secret in ("Secret-Pass-777!", "typed-wrong-USERNAME", "QUERY-SECRET", "TITLE-SECRET", "BODY-SECRET", token, *cookies):
            self.assertNotIn(secret, line)
        self.assertTrue(re.fullmatch(r"/accounts/login/", events[0]["path"]))
