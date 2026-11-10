"""APP-03 다른 사람 기록 접근 404·DB 불변, APP-04 비로그인 거부, 메서드 405."""
import re

from django.contrib.auth.models import User
from django.test import TestCase

from posts.models import Post


class OtherUserAccessTests(TestCase):
    """B가 A의 기록을 조회·수정·삭제하면 모두 404이고 DB는 바뀌지 않는다."""

    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a")
        cls.b = User.objects.create_user("member_b")
        cls.post = Post.objects.create(owner=cls.a, title="A의 비공개 제목", body="A의 비공개 본문")

    def setUp(self):
        self.client.force_login(self.b)

    def _assert_404_without_leak(self, res):
        self.assertEqual(res.status_code, 404)
        self.assertTemplateUsed(res, "404.html")
        self.assertNotContains(res, "A의 비공개", status_code=404)

    def _assert_unchanged(self):
        post = Post.objects.get(pk=self.post.pk)
        self.assertEqual((post.title, post.body, post.owner_id, post.status), ("A의 비공개 제목", "A의 비공개 본문", self.a.pk, "ACTIVE"))

    def test_get_detail_edit_delete_are_404(self):
        for path in (f"/posts/{self.post.pk}/", f"/posts/{self.post.pk}/edit/", f"/posts/{self.post.pk}/delete/"):
            with self.subTest(path=path):
                self._assert_404_without_leak(self.client.get(path))

    def test_post_edit_is_404_and_unchanged(self):
        self._assert_404_without_leak(self.client.post(f"/posts/{self.post.pk}/edit/", {"title": "B가 바꿈", "body": "x"}))
        self._assert_unchanged()

    def test_post_delete_is_404_and_unchanged(self):
        self._assert_404_without_leak(self.client.post(f"/posts/{self.post.pk}/delete/"))
        self._assert_unchanged()

    def test_other_users_post_and_missing_post_look_the_same(self):
        def body(res):
            # CSRF 토큰은 화면을 그릴 때마다 달라지므로 값만 지우고 비교한다.
            return re.sub(rb'name="csrfmiddlewaretoken" value="[^"]+"', b"", res.content)

        other = self.client.get(f"/posts/{self.post.pk}/")
        missing = self.client.get("/posts/999999/")
        self.assertEqual((other.status_code, body(other)), (missing.status_code, body(missing)))

    def test_non_numeric_id_is_404(self):
        self.assertEqual(self.client.get("/posts/1%20OR%201=1/").status_code, 404)

    def test_owner_cannot_see_deleting_post(self):
        self.client.force_login(self.a)
        Post.objects.filter(pk=self.post.pk).update(status=Post.Status.DELETING)
        self.assertEqual(self.client.get(f"/posts/{self.post.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/posts/{self.post.pk}/edit/", {"title": "t", "body": "b"}).status_code, 404)


class AnonymousAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a")
        cls.post = Post.objects.create(owner=cls.a, title="제목", body="본문")

    def test_protected_pages_redirect_to_login_with_next(self):
        pk = self.post.pk
        for path in ("/posts/", "/posts/new/", "/posts/shared/", f"/posts/{pk}/", f"/posts/{pk}/edit/", f"/posts/{pk}/delete/"):
            with self.subTest(path=path):
                res = self.client.get(path)
                self.assertRedirects(res, f"/accounts/login/?next={path}", fetch_redirect_response=False)

    def test_anonymous_posts_change_nothing(self):
        self.assertEqual(self.client.post("/posts/new/", {"title": "t", "body": "b"}).status_code, 302)
        self.assertEqual(self.client.post(f"/posts/{self.post.pk}/edit/", {"title": "t", "body": "b"}).status_code, 302)
        self.assertEqual(self.client.post(f"/posts/{self.post.pk}/delete/").status_code, 302)
        self.assertEqual(Post.objects.count(), 1)
        self.assertEqual(Post.objects.get().title, "제목")

    def test_home_redirects_by_login_state(self):
        self.assertRedirects(self.client.get("/"), "/accounts/login/", fetch_redirect_response=False)
        self.client.force_login(self.a)
        self.assertRedirects(self.client.get("/"), "/posts/", fetch_redirect_response=False)

    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual((res.status_code, res.content), (200, b"ok"))

    def test_admin_root_goes_to_limited_account_admin_not_django_admin(self):
        # /admin/ 은 제한된 계정 관리로 연결된다. Django 기본 관리자 사이트의 화면은 없다(명세 2.2).
        self.assertRedirects(self.client.get("/admin/"), "/admin/accounts/", fetch_redirect_response=False)
        for path in ("/admin/login/", "/admin/auth/user/", "/admin/auth/user/1/password/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class MethodNotAllowedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a")
        cls.post = Post.objects.create(owner=cls.a, title="제목", body="본문")

    def setUp(self):
        self.client.force_login(self.a)

    def test_disallowed_methods_are_405_with_page(self):
        cases = [
            ("get", "/accounts/logout/"),
            ("post", "/posts/"),
            ("put", f"/posts/{self.post.pk}/"),
            ("delete", f"/posts/{self.post.pk}/delete/"),
        ]
        for method, path in cases:
            with self.subTest(method=method, path=path):
                res = getattr(self.client, method)(path)
                self.assertEqual(res.status_code, 405)
                self.assertTrue(res.has_header("Allow"))
                self.assertTemplateUsed(res, "errors/405.html")
        self.assertEqual(Post.objects.count(), 1)
