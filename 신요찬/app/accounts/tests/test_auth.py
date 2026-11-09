"""APP-01 가입·로그인·로그아웃, APP-04 비활성 계정 세션 거부."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone

from accounts.forms import LOGIN_FAILED_MESSAGE

PASSWORD = "Virtual-Pass-2026!"


class SignupTests(TestCase):
    url = "/accounts/signup/"

    def test_get_renders_form(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "accounts/signup.html")
        self.assertEqual(list(res.context["form"].fields), ["username", "password1", "password2"])

    def test_valid_signup_redirects_to_login_without_logging_in(self):
        res = self.client.post(self.url, {"username": "new_member", "password1": PASSWORD, "password2": PASSWORD})
        self.assertRedirects(res, "/accounts/login/", fetch_redirect_response=False)
        user = User.objects.get(username="new_member")
        self.assertNotEqual(user.password, PASSWORD)  # 해시로 저장
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_empty_signup_is_400_and_creates_nothing(self):
        res = self.client.post(self.url, {})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_password_mismatch_error_on_password2(self):
        res = self.client.post(self.url, {"username": "m1", "password1": PASSWORD, "password2": PASSWORD + "x"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("password2", res.context["form"].errors)
        self.assertFalse(User.objects.filter(username="m1").exists())

    def test_weak_password_error_on_password2(self):
        res = self.client.post(self.url, {"username": "m2", "password1": "12345678", "password2": "12345678"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("password2", res.context["form"].errors)

    def test_duplicate_username_error_on_username(self):
        User.objects.create_user("taken", password=PASSWORD)
        res = self.client.post(self.url, {"username": "taken", "password1": PASSWORD, "password2": PASSWORD})
        self.assertEqual(res.status_code, 400)
        self.assertIn("username", res.context["form"].errors)
        self.assertEqual(User.objects.filter(username="taken").count(), 1)

    def test_password_not_refilled_after_failure(self):
        res = self.client.post(self.url, {"username": "m3", "password1": PASSWORD, "password2": "different"})
        self.assertEqual(res.status_code, 400)
        self.assertNotContains(res, PASSWORD, status_code=400)


class LoginTests(TestCase):
    url = "/accounts/login/"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("member_a", password=PASSWORD)
        cls.inactive = User.objects.create_user("inactive_member", password=PASSWORD, is_active=False)

    def _assert_login_failed(self, data):
        res = self.client.post(self.url, data)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.context["form"].non_field_errors(), [LOGIN_FAILED_MESSAGE])
        self.assertNotIn(SESSION_KEY, self.client.session)
        return res

    def test_success_redirects_to_posts(self):
        res = self.client.post(self.url, {"username": "member_a", "password": PASSWORD})
        self.assertRedirects(res, "/posts/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.user.pk)

    def test_session_key_rotates_on_login(self):
        session = self.client.session
        session["pre_login"] = True
        session.save()
        before = session.session_key
        self.client.post(self.url, {"username": "member_a", "password": PASSWORD})
        self.assertNotEqual(self.client.session.session_key, before)

    def test_session_expires_at_browser_close_and_within_one_hour(self):
        self.client.post(self.url, {"username": "member_a", "password": PASSWORD})
        cookie = self.client.cookies[settings.SESSION_COOKIE_NAME]
        self.assertEqual(cookie["expires"], "")  # 브라우저 종료 시 만료
        self.assertEqual(cookie["max-age"], "")
        self.assertTrue(cookie["httponly"])
        expire = Session.objects.get(session_key=self.client.session.session_key).expire_date
        self.assertLessEqual(expire - timezone.now(), timedelta(seconds=3600))

    def test_session_not_extended_by_later_requests(self):
        """최대 수명 1시간: 로그인 후 요청을 보내도 만료 시각이 뒤로 밀리지 않는다(명세 2.1)."""
        self.client.post(self.url, {"username": "member_a", "password": PASSWORD})
        key = self.client.session.session_key
        remaining = timezone.now() + timedelta(minutes=10)  # 50분이 지난 상황
        Session.objects.filter(session_key=key).update(expire_date=remaining)
        self.assertEqual(self.client.get("/posts/").status_code, 200)
        self.assertEqual(Session.objects.get(session_key=key).expire_date, remaining)

    def test_wrong_password_same_message(self):
        self._assert_login_failed({"username": "member_a", "password": "wrong-password"})

    def test_unknown_user_same_message(self):
        self._assert_login_failed({"username": "no_such_member", "password": PASSWORD})

    def test_inactive_user_same_message(self):
        self._assert_login_failed({"username": "inactive_member", "password": PASSWORD})

    def test_empty_login_is_400(self):
        res = self.client.post(self.url, {})
        self.assertEqual(res.status_code, 400)

    def test_safe_next_is_followed(self):
        res = self.client.post(self.url + "?next=/posts/new/", {"username": "member_a", "password": PASSWORD, "next": "/posts/new/"})
        self.assertRedirects(res, "/posts/new/", fetch_redirect_response=False)

    def test_external_next_is_ignored(self):
        res = self.client.post(self.url, {"username": "member_a", "password": PASSWORD, "next": "https://evil.example/"})
        self.assertRedirects(res, "/posts/", fetch_redirect_response=False)


class LogoutTests(TestCase):
    url = "/accounts/logout/"

    def setUp(self):
        self.user = User.objects.create_user("member_a", password=PASSWORD)
        self.client.force_login(self.user)

    def test_get_logout_is_405_and_keeps_session(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 405)
        self.assertIn(SESSION_KEY, self.client.session)

    def test_post_logout_redirects_to_login_and_ends_session(self):
        res = self.client.post(self.url)
        self.assertRedirects(res, "/accounts/login/", fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.client.get("/posts/").status_code, 302)


class InactiveSessionTests(TestCase):
    """APP-04: 로그인 중에 비활성화된 계정의 기존 세션은 다음 요청부터 비로그인으로 처리된다."""

    def test_existing_session_rejected_after_deactivation(self):
        user = User.objects.create_user("member_a", password=PASSWORD)
        self.client.force_login(user)
        self.assertEqual(self.client.get("/posts/").status_code, 200)
        User.objects.filter(pk=user.pk).update(is_active=False)
        res = self.client.get("/posts/")
        self.assertRedirects(res, "/accounts/login/?next=/posts/", fetch_redirect_response=False)
