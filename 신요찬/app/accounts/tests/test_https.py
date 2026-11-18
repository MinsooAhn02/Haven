"""HTTPS 배포 설정 (명세 3.2 쿠키·프록시 신뢰, DEP-03, 앱계약.md 1.2 DJANGO_HTTPS).

- DJANGO_HTTPS=1이면 ALB가 붙인 X-Forwarded-Proto=https를 믿고, 세션·CSRF 쿠키에 Secure를 붙인다.
- 끈 상태(로컬·CI)에서는 같은 헤더를 보내도 HTTPS로 취급하지 않는다(헤더 위조로 scheme을 바꾸지 못함).
- 켠 상태에서 다른 scheme의 Origin(http://같은 호스트)이나 출처 정보가 없는 POST는 CSRF 403.
"""
import os
import subprocess
import sys
from http.cookies import SimpleCookie
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings

PASSWORD = "Virtual-Pass-2026!"
HTTPS_ON = dict(
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    SECURE_HSTS_SECONDS=3600,
)
HTTPS_OFF = dict(
    SECURE_PROXY_SSL_HEADER=None, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, SECURE_HSTS_SECONDS=0
)
HSTS = "Strict-Transport-Security"
APP_DIR = Path(__file__).resolve().parents[2]


def alb_client():
    """ALB → Nginx를 거친 브라우저 요청처럼 Host를 보낸다(Nginx `proxy_set_header Host $host`, 포트 없음).

    Django 시험 도구는 기본으로 Host 없이 SERVER_PORT=80을 보내서, HTTPS로 판정되면 호스트가
    testserver:80이 되어 Origin과 어긋난다. 실제 서버에서는 생기지 않는 시험 도구 차이다.
    """
    return Client(enforce_csrf_checks=True, HTTP_HOST="testserver")


def cookie_attrs(response, name):
    """Set-Cookie 헤더에서 쿠키 속성을 읽는다(test client의 cookies 대신 실제 헤더 문자열 기준)."""
    morsel = response.cookies.get(name)
    assert morsel is not None, f"{name} 쿠키가 없음"
    header = morsel.output(header="").strip()
    parsed = SimpleCookie()
    parsed.load(header)
    m = parsed[name]
    return {"secure": bool(m["secure"]), "httponly": bool(m["httponly"]), "samesite": m["samesite"]}


class SettingsFromEnvTests(SimpleTestCase):
    """settings.py가 DJANGO_HTTPS를 읽는 방식(프로세스를 새로 띄워 환경변수 그대로 확인)."""

    def run_settings(self, value):
        env = {k: v for k, v in os.environ.items() if k != "DJANGO_HTTPS"}
        if value is not None:
            env["DJANGO_HTTPS"] = value
        code = (
            "import django;django.setup();from django.conf import settings as s;"
            "print(s.SECURE_PROXY_SSL_HEADER, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_SSL_REDIRECT,"
            " s.SECURE_HSTS_SECONDS, s.SECURE_HSTS_INCLUDE_SUBDOMAINS, s.SECURE_HSTS_PRELOAD)"
        )
        env["DJANGO_SETTINGS_MODULE"] = "config.settings"
        return subprocess.run([sys.executable, "-c", code], cwd=APP_DIR, env=env, capture_output=True, text=True, timeout=60)

    def test_off_by_default_and_on_with_1(self):
        off = self.run_settings(None)
        self.assertEqual(off.stdout.strip(), "None False False False 0 False False", off.stderr[-500:])
        on = self.run_settings("1")
        self.assertEqual(
            on.stdout.strip(), "('HTTP_X_FORWARDED_PROTO', 'https') True True False 3600 False False", on.stderr[-500:]
        )

    def test_deploy_check_has_no_hsts_warning_when_on(self):
        """운영 경고 점검(DEP-05): 켠 상태에서 W004(HSTS 없음)는 사라지고, 일부러 남긴 예외 셋은 그대로 나온다."""
        env = {k: v for k, v in os.environ.items() if k != "DJANGO_HTTPS"}
        env.update(DJANGO_HTTPS="1", DJANGO_SETTINGS_MODULE="config.settings")
        res = subprocess.run([sys.executable, "manage.py", "check", "--deploy"], cwd=APP_DIR, env=env,
                             capture_output=True, text=True, timeout=60)
        out = res.stdout + res.stderr
        self.assertNotIn("security.W004", out)
        for kept in ("security.W008", "security.W005", "security.W021"):  # 앱계약.md 1.2.1 예외
            self.assertIn(kept, out)

    def test_invalid_value_fails_to_start(self):
        bad = self.run_settings("yes")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("DJANGO_HTTPS", bad.stderr)

    def test_cookie_flags_are_explicit(self):
        self.assertEqual(
            (settings.SESSION_COOKIE_HTTPONLY, settings.CSRF_COOKIE_HTTPONLY,
             settings.SESSION_COOKIE_SAMESITE, settings.CSRF_COOKIE_SAMESITE),
            (True, True, "Lax", "Lax"),
        )


class HttpsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("member_a", password=PASSWORD)

    def login_via_https(self, client, **extra):
        page = client.get("/accounts/login/", HTTP_X_FORWARDED_PROTO="https")
        token = str(page.context["csrf_token"])
        data = {"username": "member_a", "password": PASSWORD, "csrfmiddlewaretoken": token}
        return page, client.post("/accounts/login/", data, HTTP_X_FORWARDED_PROTO="https", **extra)


@override_settings(**HTTPS_ON)
class HttpsOnTests(HttpsBase):
    def test_cookies_are_secure_httponly_lax_behind_alb(self):
        client = alb_client()
        page, res = self.login_via_https(client, HTTP_ORIGIN="https://testserver")
        self.assertTrue(page.wsgi_request.is_secure())
        self.assertEqual(res.status_code, 302)
        expected = {"secure": True, "httponly": True, "samesite": "Lax"}
        self.assertEqual(cookie_attrs(page, "csrftoken"), expected)
        self.assertEqual(cookie_attrs(res, "sessionid"), expected)

    def test_http_origin_on_https_request_is_403(self):
        client = alb_client()
        _, res = self.login_via_https(client, HTTP_ORIGIN="http://testserver")
        self.assertEqual(res.status_code, 403)
        self.assertNotIn("sessionid", res.cookies)

    def test_https_post_needs_origin_or_same_origin_referer(self):
        client = alb_client()
        _, res = self.login_via_https(client)  # Origin·Referer 둘 다 없음
        self.assertEqual(res.status_code, 403)
        client = alb_client()
        _, res = self.login_via_https(client, HTTP_REFERER="https://testserver/accounts/login/")
        self.assertEqual(res.status_code, 302)
        client = alb_client()
        _, res = self.login_via_https(client, HTTP_REFERER="https://evil.example/accounts/login/")
        self.assertEqual(res.status_code, 403)

    def test_request_without_alb_header_is_not_secure(self):
        """상태 검사처럼 X-Forwarded-Proto 없이 온 HTTP 요청: HTTPS로 보지 않고, 리다이렉트도 하지 않는다."""
        res = Client().get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.wsgi_request.is_secure())
        res = Client().get("/accounts/login/", HTTP_X_FORWARDED_PROTO="http")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.wsgi_request.is_secure())

    def test_hsts_only_on_https_responses(self):
        """HSTS는 ALB를 거친 HTTPS 응답(오류 응답 포함)에만 붙고, 하위 도메인·preload는 넣지 않는다."""
        for path in ("/accounts/login/", "/posts/999999/"):
            res = alb_client().get(path, HTTP_X_FORWARDED_PROTO="https")
            self.assertIn(res.status_code, (200, 302), path)
            self.assertEqual(res.headers.get(HSTS), "max-age=3600", path)
        self.assertEqual(alb_client().get("/no-such-page/", HTTP_X_FORWARDED_PROTO="https").headers.get(HSTS),
                         "max-age=3600")
        # ALB 상태 검사(HTTP, 헤더 없음)와 HTTP로 표시된 요청에는 붙지 않는다(브라우저도 HTTP 응답의 HSTS는 무시한다, RFC 6797).
        self.assertNotIn(HSTS, Client().get("/healthz").headers)
        self.assertNotIn(HSTS, Client().get("/accounts/login/", HTTP_X_FORWARDED_PROTO="http").headers)


@override_settings(**HTTPS_OFF)  # 서버 환경변수와 관계없이 '끈 상태'를 시험한다
class HttpsOffTests(HttpsBase):
    def test_forwarded_proto_is_ignored_when_off(self):
        """로컬·CI: 헤더만 보내서 HTTPS로 위장할 수 없고, 쿠키에 Secure가 붙지 않는다(HTTP에서 로그인 가능)."""
        client = alb_client()
        page, res = self.login_via_https(client)
        self.assertFalse(page.wsgi_request.is_secure())
        self.assertEqual(res.status_code, 302)
        self.assertEqual(cookie_attrs(res, "sessionid"), {"secure": False, "httponly": True, "samesite": "Lax"})
        self.assertEqual(cookie_attrs(page, "csrftoken")["secure"], False)
        self.assertNotIn(HSTS, page.headers)  # 헤더 위조로 HSTS를 받아 로컬 HTTP가 막히는 일이 없다
