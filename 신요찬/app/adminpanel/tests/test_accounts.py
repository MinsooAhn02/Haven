"""APP-07 일반 회원 관리자 접근 403, APP-09 운영 관리자 범위, UI-03 상태 변경·감사 원자성 (명세 3.2, 8.1)."""
import json
from unittest import mock

from django.contrib.admin.models import LogEntry
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.test import Client, TestCase

from adminpanel import services
from posts.models import Post


class AdminBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a", email="a@example.invalid", password="Virtual-Pass-2026!")
        cls.b = User.objects.create_user("member_b")
        cls.op = User.objects.create_user("operator", is_staff=True)
        cls.op2 = User.objects.create_user("operator2", is_staff=True)
        cls.root = User.objects.create_superuser("root_admin")
        cls.p1 = Post.objects.create(owner=cls.a, title="A의 비공개 제목", body="A의 비공개 본문")

    def as_user(self, user):
        self.client.force_login(user)
        return self.client


class AccessBoundaryTests(AdminBase):
    pages = ("/admin/accounts/", "/admin/account-events/")

    def test_app07_member_gets_403(self):
        client = self.as_user(self.a)
        for path in self.pages:
            with self.subTest(path=path):
                res = client.get(path)
                self.assertEqual(res.status_code, 403)
                self.assertTemplateUsed(res, "403.html")

    def test_app07_member_cannot_change_status(self):
        res = self.as_user(self.a).post(f"/admin/accounts/{self.b.pk}/status/", {"is_active": "false"})
        self.assertEqual(res.status_code, 403)
        self.b.refresh_from_db()
        self.assertTrue(self.b.is_active)
        self.assertFalse(LogEntry.objects.exists())

    def test_anonymous_redirected_to_login(self):
        for path in self.pages:
            with self.subTest(path=path):
                self.assertRedirects(self.client.get(path), f"/accounts/login/?next={path}", fetch_redirect_response=False)

    def test_superuser_is_not_operator(self):
        """명세 2.2: 복구용 최고권한 계정은 일반 운영 흐름에 포함하지 않는다."""
        self.assertEqual(self.as_user(self.root).get("/admin/accounts/").status_code, 403)

    def test_inactive_operator_session_rejected(self):
        client = self.as_user(self.op)
        User.objects.filter(pk=self.op.pk).update(is_active=False)
        self.assertEqual(client.get("/admin/accounts/").status_code, 302)

    def test_status_get_is_405(self):
        self.assertEqual(self.as_user(self.op).get(f"/admin/accounts/{self.b.pk}/status/").status_code, 405)


class OperatorScopeTests(AdminBase):
    def setUp(self):
        self.client = self.as_user(self.op)

    def test_app09_list_shows_only_members_with_limited_fields(self):
        res = self.client.get("/admin/accounts/")
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "adminpanel/accounts.html")
        accounts = list(res.context["accounts"])
        self.assertEqual([acc.username for acc in accounts], ["member_a", "member_b"])
        self.assertEqual(set(vars(accounts[0])), {"pk", "username", "is_active", "date_joined", "last_login"})
        self.assertNotContains(res, self.a.password)  # 비밀번호 해시
        self.assertNotContains(res, "a@example.invalid")
        self.assertNotContains(res, "A의 비공개")
        self.assertEqual(res["Cache-Control"], "private, no-store")

    def test_app09_operator_deactivates_and_activates_member_with_audit(self):
        res = self.client.post(f"/admin/accounts/{self.b.pk}/status/", {"is_active": "false"})
        self.assertRedirects(res, "/admin/accounts/", fetch_redirect_response=False)
        self.b.refresh_from_db()
        self.assertFalse(self.b.is_active)
        self.client.post(f"/admin/accounts/{self.b.pk}/status/", {"is_active": "true"})
        self.b.refresh_from_db()
        self.assertTrue(self.b.is_active)
        entries = list(LogEntry.objects.order_by("id"))
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].user, self.op)
        self.assertEqual(entries[0].object_id, str(self.b.pk))
        self.assertEqual(json.loads(entries[0].change_message), {"account_status": {"before": True, "after": False}})

    def test_same_status_records_nothing(self):
        res = self.client.post(f"/admin/accounts/{self.b.pk}/status/", {"is_active": "true"})
        self.assertEqual(res.status_code, 302)
        self.assertFalse(LogEntry.objects.exists())

    def test_app09_cannot_change_operator_superuser_or_self(self):
        for target in (self.op2, self.root, self.op):
            with self.subTest(target=target.username):
                res = self.client.post(f"/admin/accounts/{target.pk}/status/", {"is_active": "false"})
                self.assertEqual(res.status_code, 400)
                target.refresh_from_db()
                self.assertTrue(target.is_active)
        self.assertFalse(LogEntry.objects.exists())

    def test_invalid_value_is_400_and_missing_target_404(self):
        for value in ("", "yes", "False", "0"):
            with self.subTest(value=value):
                self.assertEqual(self.client.post(f"/admin/accounts/{self.b.pk}/status/", {"is_active": value}).status_code, 400)
        self.assertEqual(self.client.post("/admin/accounts/999999/status/", {"is_active": "false"}).status_code, 404)
        self.assertFalse(LogEntry.objects.exists())

    def test_app09_no_body_or_password_access(self):
        for path in (f"/posts/{self.p1.pk}/", f"/posts/{self.p1.pk}/edit/", f"/admin/accounts/{self.a.pk}/password/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_deactivated_member_loses_existing_session(self):
        member = Client()
        member.force_login(self.b)
        self.assertEqual(member.get("/posts/").status_code, 200)
        self.client.post(f"/admin/accounts/{self.b.pk}/status/", {"is_active": "false"})
        self.assertEqual(member.get("/posts/").status_code, 302)
        self.assertEqual(member.post("/accounts/login/", {"username": "member_b", "password": "x"}).status_code, 400)

    def test_events_page_lists_status_changes_newest_first(self):
        self.client.post(f"/admin/accounts/{self.a.pk}/status/", {"is_active": "false"})
        self.client.post(f"/admin/accounts/{self.b.pk}/status/", {"is_active": "false"})
        LogEntry.objects.create(  # 계정 상태 변경이 아닌 다른 기록은 이력에 나오지 않아야 함
            user=self.op, content_type_id=LogEntry.objects.first().content_type_id, object_id="1",
            object_repr="other", action_flag=2, change_message='[{"changed": {"fields": ["email"]}}]',
        )
        res = self.client.get("/admin/account-events/")
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "adminpanel/account_events.html")
        events = list(res.context["events"])
        self.assertEqual([e.target_username for e in events], ["member_b", "member_a"])
        self.assertEqual(
            vars(events[0]).keys(), {"action_time", "actor_username", "target_username", "before", "after"}
        )
        self.assertEqual((events[0].actor_username, events[0].before, events[0].after), ("operator", "활성", "비활성"))


class AuditAtomicityTests(AdminBase):
    def test_ui03_audit_failure_rolls_back_status(self):
        with mock.patch.object(LogEntry.objects, "create", side_effect=RuntimeError("audit store down")):
            with self.assertRaises(RuntimeError):
                services.set_account_status(self.op, self.b, False)
        self.b.refresh_from_db()
        self.assertTrue(self.b.is_active)
        self.assertFalse(LogEntry.objects.exists())


class AdminCsrfTests(AdminBase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.op)

    def test_status_without_token_is_403(self):
        res = self.client.post(f"/admin/accounts/{self.b.pk}/status/", {"is_active": "false"})
        self.assertEqual(res.status_code, 403)
        self.b.refresh_from_db()
        self.assertTrue(self.b.is_active)

    def test_status_with_token_succeeds(self):
        token = str(self.client.get("/admin/accounts/").context["csrf_token"])
        res = self.client.post(f"/admin/accounts/{self.b.pk}/status/", {"is_active": "false", "csrfmiddlewaretoken": token})
        self.assertEqual(res.status_code, 302)
        self.b.refresh_from_db()
        self.assertFalse(self.b.is_active)
        self.assertIn(SESSION_KEY, self.client.session)
