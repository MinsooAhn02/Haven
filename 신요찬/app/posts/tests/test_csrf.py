"""APP-05 CSRF 누락·오류는 403이고 DB가 바뀌지 않는다. 유효한 토큰은 성공한다(대조군).

Django 시험 클라이언트는 기본적으로 CSRF 검사를 건너뛰므로 enforce_csrf_checks=True를 쓴다.
"""
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.test import Client, TestCase

from posts.models import Post


class CsrfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a")

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.a)
        self.post = Post.objects.create(owner=self.a, title="원래 제목", body="원래 본문")

    def _token(self, path="/posts/new/"):
        res = self.client.get(path)
        return str(res.context["csrf_token"])

    def _assert_csrf_rejected(self, res):
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, "403_csrf.html")

    def _assert_unchanged(self):
        self.post.refresh_from_db()
        self.assertEqual((self.post.title, Post.objects.count()), ("원래 제목", 1))

    def test_create_without_token_is_403(self):
        self._assert_csrf_rejected(self.client.post("/posts/new/", {"title": "t", "body": "b"}))
        self._assert_unchanged()

    def test_create_with_wrong_token_is_403(self):
        self._token()
        res = self.client.post("/posts/new/", {"title": "t", "body": "b", "csrfmiddlewaretoken": "x" * 64})
        self._assert_csrf_rejected(res)
        self._assert_unchanged()

    def test_create_with_valid_token_succeeds(self):
        res = self.client.post("/posts/new/", {"title": "새 제목", "body": "b", "csrfmiddlewaretoken": self._token()})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(Post.objects.count(), 2)

    def test_foreign_origin_with_valid_token_is_403(self):
        token = self._token()
        res = self.client.post("/posts/new/", {"title": "t", "body": "b", "csrfmiddlewaretoken": token}, HTTP_ORIGIN="https://evil.example")
        self._assert_csrf_rejected(res)
        self._assert_unchanged()

    def test_edit_without_token_is_403(self):
        self._assert_csrf_rejected(self.client.post(f"/posts/{self.post.pk}/edit/", {"title": "바뀜", "body": "b"}))
        self._assert_unchanged()

    def test_edit_with_valid_token_succeeds(self):
        token = self._token(f"/posts/{self.post.pk}/edit/")
        res = self.client.post(f"/posts/{self.post.pk}/edit/", {"title": "바뀜", "body": "b", "csrfmiddlewaretoken": token})
        self.assertEqual(res.status_code, 302)
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, "바뀜")

    def test_delete_without_token_is_403(self):
        self._assert_csrf_rejected(self.client.post(f"/posts/{self.post.pk}/delete/"))
        self._assert_unchanged()

    def test_delete_with_valid_token_succeeds(self):
        token = self._token(f"/posts/{self.post.pk}/delete/")
        res = self.client.post(f"/posts/{self.post.pk}/delete/", {"csrfmiddlewaretoken": token})
        self.assertEqual(res.status_code, 302)
        self.assertFalse(Post.objects.filter(pk=self.post.pk).exists())

    def test_logout_without_token_is_403_and_stays_logged_in(self):
        self._assert_csrf_rejected(self.client.post("/accounts/logout/"))
        self.assertIn(SESSION_KEY, self.client.session)


class AnonymousCsrfTests(TestCase):
    """CSRF 실패는 로그인 여부와 무관하게 403, CSRF가 유효한 비로그인 요청은 로그인으로 302(명세 2.1)."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_anonymous_without_token_is_403(self):
        res = self.client.post("/posts/new/", {"title": "t", "body": "b"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(Post.objects.count(), 0)

    def test_anonymous_with_valid_token_redirects_to_login(self):
        token = str(self.client.get("/accounts/login/").context["csrf_token"])
        res = self.client.post("/posts/new/", {"title": "t", "body": "b", "csrfmiddlewaretoken": token})
        self.assertRedirects(res, "/accounts/login/?next=/posts/new/", fetch_redirect_response=False)
        self.assertEqual(Post.objects.count(), 0)

    def test_login_without_token_is_403(self):
        User.objects.create_user("member_a", password="Virtual-Pass-2026!")
        res = self.client.post("/accounts/login/", {"username": "member_a", "password": "Virtual-Pass-2026!"})
        self.assertEqual(res.status_code, 403)
        self.assertNotIn(SESSION_KEY, self.client.session)
