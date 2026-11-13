"""로그인 실패 제한 (APP-10, 앱계약 8장 13번, 신요찬/로그인실패제한_안.md 5장).

조장 결정(#75): 관찰 15분 / 같은 아이디 5번 / 같은 IP 30번 / 자동 회복 / 평소 실패 400, 제한 중 429.
"""
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts import login_limit
from accounts.forms import LOGIN_FAILED_MESSAGE
from accounts.login_limit import LIMITED_MESSAGE, MAX_PER_ACCOUNT, MAX_PER_IP, WINDOW
from accounts.models import LoginFailure

User = get_user_model()
PASSWORD = "haven-test-pass-2026"
URL = "/accounts/login/"


class Clock:
    """login_limit.now()를 바꿔 끼우는 가짜 시계."""

    def __init__(self):
        self.at = timezone.now()

    def __call__(self):
        return self.at

    def advance(self, delta):
        self.at += delta


# 비밀번호 해시는 이 시험의 대상이 아니다. 실패를 수십 번 내므로 빠른 해시를 쓴다(제한 판정과 무관).
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LoginLimitBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("member_a", password=PASSWORD)
        User.objects.create_user("inactive_member", password=PASSWORD, is_active=False)

    def setUp(self):
        self.clock = Clock()
        patcher = mock.patch.object(login_limit, "now", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def attempt(self, username, password, ip="198.51.100.1", **extra):
        return self.client.post(URL, {"username": username, "password": password}, REMOTE_ADDR=ip, **extra)

    def fail_login(self, username="member_a", times=1, ip="198.51.100.1", **extra):
        statuses = [self.attempt(username, "wrong-password", ip, **extra).status_code for _ in range(times)]
        return statuses

    def assert_limited(self, res):
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.context["form"].non_field_errors(), [LIMITED_MESSAGE])
        self.assertTemplateUsed(res, "registration/login.html")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def assert_logged_in(self, res):
        self.assertEqual(res.status_code, 302)
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.user.pk)


class AccountAxisTests(LoginLimitBase):
    def test_sixth_attempt_is_429_even_with_correct_password(self):
        self.assertEqual(self.fail_login(times=MAX_PER_ACCOUNT), [400] * MAX_PER_ACCOUNT)
        self.assert_limited(self.attempt("member_a", PASSWORD))

    def test_recovers_after_window(self):
        self.fail_login(times=MAX_PER_ACCOUNT)
        self.clock.advance(WINDOW - timedelta(seconds=1))
        self.assert_limited(self.attempt("member_a", PASSWORD))
        self.clock.advance(timedelta(seconds=1))
        self.assert_logged_in(self.attempt("member_a", PASSWORD))

    def test_attempts_while_limited_are_not_checked_or_counted(self):
        self.fail_login(times=MAX_PER_ACCOUNT)
        rows = LoginFailure.objects.count()
        with mock.patch("django.contrib.auth.forms.authenticate") as spy:
            statuses = {self.attempt("member_a", "wrong-password").status_code for _ in range(50)}
        self.assertEqual(statuses, {429})
        spy.assert_not_called()
        self.assertEqual(LoginFailure.objects.count(), rows)
        self.clock.advance(WINDOW)  # 마지막 실패에서 15분: 막힌 동안의 시도가 회복을 늦추지 않는다
        self.assert_logged_in(self.attempt("member_a", PASSWORD))

    def test_distributed_attack_from_different_ips(self):
        for i in range(MAX_PER_ACCOUNT):
            self.assertEqual(self.fail_login(ip=f"203.0.113.{i + 1}"), [400])
        self.assert_limited(self.attempt("member_a", PASSWORD, ip="203.0.113.99"))

    def test_username_variants_counted_as_one_account(self):
        # 로그인 폼은 앞뒤 공백 제거·NFKC로 같은 아이디로 인증한다. 대소문자는 더 엄격하게 묶는다.
        variants = ["member_a ", " MEMBER_A", "ｍｅｍｂｅｒ＿ａ", "Member_A", "member_a　"]
        for name in variants:
            self.assertEqual(self.attempt(name, "wrong-password").status_code, 400)
        self.assert_limited(self.attempt("member_a", PASSWORD, ip="203.0.113.50"))

    def test_success_clears_account_axis_only(self):
        self.fail_login(times=MAX_PER_ACCOUNT - 1)
        self.assert_logged_in(self.attempt("member_a", PASSWORD))
        self.assertFalse(LoginFailure.objects.filter(axis="account").exists())
        self.assertEqual(LoginFailure.objects.filter(axis="ip").count(), MAX_PER_ACCOUNT - 1)
        self.client.logout()
        self.assertEqual(self.fail_login(times=MAX_PER_ACCOUNT), [400] * MAX_PER_ACCOUNT)
        self.assert_limited(self.attempt("member_a", PASSWORD))


class IpAxisTests(LoginLimitBase):
    def test_one_ip_many_usernames(self):
        for i in range(MAX_PER_IP):
            self.assertEqual(self.fail_login(username=f"guess_{i}"), [400])
        self.assert_limited(self.attempt("guess_new", "wrong-password"))
        self.assert_limited(self.attempt("member_a", PASSWORD))  # 같은 IP는 맞는 비밀번호도 막힘
        other_ip = self.attempt("member_a", PASSWORD, ip="198.51.100.2")
        self.assert_logged_in(other_ip)  # 다른 IP의 같은 아이디는 영향 없음

    def test_ip_axis_recovers(self):
        for i in range(MAX_PER_IP):
            self.fail_login(username=f"guess_{i}")
        self.clock.advance(WINDOW)
        self.assert_logged_in(self.attempt("member_a", PASSWORD))


@override_settings(HAVEN_HTTPS=True)
class ForwardedForTests(LoginLimitBase):
    ALB_IP = "10.0.1.20"  # Nginx가 붙이는 값(ALB 주소)

    def xff(self, user_ip, spoofed=None):
        values = ([spoofed] if spoofed else []) + [user_ip, self.ALB_IP]
        return {"HTTP_X_FORWARDED_FOR": ", ".join(values)}

    def test_spoofed_front_values_are_ignored(self):
        for i in range(MAX_PER_IP):
            extra = self.xff("203.0.113.7", spoofed=f"192.0.2.{i}")
            self.assertEqual(self.fail_login(username=f"guess_{i}", ip=self.ALB_IP, **extra), [400])
        res = self.attempt("member_a", PASSWORD, ip=self.ALB_IP, **self.xff("203.0.113.7", spoofed="192.0.2.250"))
        self.assert_limited(res)

    def test_other_users_behind_same_alb_are_not_affected(self):
        for i in range(MAX_PER_IP):
            self.fail_login(username=f"guess_{i}", ip=self.ALB_IP, **self.xff("203.0.113.7"))
        self.assert_logged_in(self.attempt("member_a", PASSWORD, ip=self.ALB_IP, **self.xff("203.0.113.8")))

    def test_client_ip_rules(self):
        rf = RequestFactory()
        cases = [
            ({"HTTP_X_FORWARDED_FOR": "192.0.2.1, 203.0.113.7, 10.0.1.20"}, "203.0.113.7"),
            ({"HTTP_X_FORWARDED_FOR": "203.0.113.7, 10.0.1.20"}, "203.0.113.7"),
            ({"HTTP_X_FORWARDED_FOR": "10.0.1.20"}, "10.0.0.9"),  # 값이 하나뿐: 믿지 않는다
            ({"HTTP_X_FORWARDED_FOR": "not-an-ip, 10.0.1.20"}, "10.0.0.9"),
            ({}, "10.0.0.9"),
        ]
        for meta, expected in cases:
            with self.subTest(meta=meta):
                self.assertEqual(login_limit.client_ip(rf.post(URL, REMOTE_ADDR="10.0.0.9", **meta)), expected)

    @override_settings(HAVEN_HTTPS=False)
    def test_local_http_ignores_forwarded_for(self):
        request = RequestFactory().post(URL, REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="192.0.2.1, 203.0.113.7")
        self.assertEqual(login_limit.client_ip(request), "127.0.0.1")


class NoAccountEnumerationTests(LoginLimitBase):
    def sequence(self, username, ip):
        out = []
        for _ in range(MAX_PER_ACCOUNT + 1):
            res = self.attempt(username, "wrong-password", ip=ip)
            errors = [str(e) for e in res.context["form"].non_field_errors()]
            out.append((res.status_code, errors, res.templates[0].name))
        return out

    def test_unknown_existing_and_inactive_users_look_the_same(self):
        existing = self.sequence("member_a", "198.51.100.11")
        unknown = self.sequence("no_such_member", "198.51.100.12")
        inactive = self.sequence("inactive_member", "198.51.100.13")
        self.assertEqual(existing, unknown)
        self.assertEqual(existing, inactive)
        for seq in (existing, unknown, inactive):
            self.assertEqual([status for status, _, _ in seq], [400] * MAX_PER_ACCOUNT + [429])
        self.assertEqual(existing[0][1], [LOGIN_FAILED_MESSAGE])


class NotCountedTests(LoginLimitBase):
    def test_blank_fields_are_400_and_not_counted(self):
        for data in ({"username": "", "password": ""}, {"username": "member_a", "password": ""},
                     {"username": "", "password": "x"}):
            for _ in range(MAX_PER_IP + 1):
                self.assertEqual(self.client.post(URL, data, REMOTE_ADDR="198.51.100.1").status_code, 400)
        self.assertFalse(LoginFailure.objects.exists())
        self.assert_logged_in(self.attempt("member_a", PASSWORD))

    def test_get_is_not_limited(self):
        for i in range(MAX_PER_IP):
            self.fail_login(username=f"guess_{i}")
        self.assertEqual(self.client.get(URL, REMOTE_ADDR="198.51.100.1").status_code, 200)


class StorageAndLogTests(LoginLimitBase):
    def test_db_keeps_no_plaintext_and_prunes_old_rows(self):
        self.fail_login(username="member_a", ip="203.0.113.7")
        rows = list(LoginFailure.objects.values_list("axis", "key"))
        self.assertEqual(sorted(axis for axis, _ in rows), ["account", "ip"])
        for _, key in rows:
            self.assertRegex(key, r"^[0-9a-f]{64}$")
            self.assertNotIn("member_a", key)
            self.assertNotIn("203.0.113.7", key)
        self.clock.advance(WINDOW)
        self.fail_login(username="someone_else", ip="203.0.113.8")
        self.assertEqual(LoginFailure.objects.count(), 2)  # 15분 지난 두 행은 지워지고 새 두 행만

    def test_request_log_marks_limited_without_credentials(self):
        self.fail_login(times=MAX_PER_ACCOUNT)
        with self.assertLogs("haven.request", "INFO") as cm:
            self.attempt("member_a", PASSWORD)
        raw = "\n".join(record.getMessage() for record in cm.records)
        event = json.loads(cm.records[-1].getMessage())
        self.assertEqual((event["action"], event["status"], event["result"]), ("login_limited", 429, "denied"))
        for text in ("member_a", PASSWORD, "198.51.100.1"):
            self.assertNotIn(text, raw)
