"""APP-11 글 body 8,191/8,192/8,193바이트 경계 (명세 0장·4장, 앱계약 결정 9: 413이 CSRF보다 먼저).

body는 실제 application/x-www-form-urlencoded 직렬화 바이트로 센다.
CSRF 토큰, 폼 인코딩, UTF-8 한국어(%XX 9바이트)를 모두 포함한다.
"""
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.test import Client, TestCase

from config.middleware import POST_BODY_LIMIT
from posts.models import Post

FORM = "application/x-www-form-urlencoded"
KOREAN = "한국어 경계 시험 본문 "


def form_body(size, token=None, title="경계 시험"):
    """CSRF 토큰과 한국어를 포함해 직렬화 길이가 정확히 size바이트인 글 폼 body."""
    fields = {"title": title, "body": KOREAN}
    if token is not None:
        fields = {"csrfmiddlewaretoken": token, **fields}
    base = urlencode(fields).encode()
    pad = size - len(base)
    assert pad >= 0, "size가 너무 작습니다"
    fields["body"] = KOREAN + "a" * pad  # ASCII 'a'는 인코딩 후에도 1바이트
    data = urlencode(fields).encode()
    assert len(data) == size
    return data


class BodyLimitBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a")
        cls.b = User.objects.create_user("member_b")
        cls.post = Post.objects.create(owner=cls.a, title="원래 제목", body="원래 본문")

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def login(self, user):
        self.client.force_login(user)
        return str(self.client.get("/posts/new/").context["csrf_token"])

    def anonymous_token(self):
        return str(self.client.get("/accounts/login/").context["csrf_token"])

    def send(self, path, data, **extra):
        return self.client.generic("POST", path, data, content_type=FORM, **extra)

    def assert_413(self, res):
        self.assertEqual(res.status_code, 413)
        self.assertTemplateUsed(res, "errors/413.html")


class CreateBoundaryTests(BodyLimitBase):
    def test_limit_is_8192(self):
        self.assertEqual(POST_BODY_LIMIT, 8192)

    def test_app11_8191_and_8192_create_and_8193_is_413(self):
        token = self.login(self.a)
        for size in (8191, 8192):
            with self.subTest(size=size):
                before = Post.objects.count()
                res = self.send("/posts/new/", form_body(size, token))
                self.assertEqual(res.status_code, 302)
                self.assertEqual(Post.objects.count(), before + 1)
                self.assertTrue(Post.objects.latest("id").body.startswith(KOREAN))
        before = Post.objects.count()
        res = self.send("/posts/new/", form_body(8193, token))
        self.assert_413(res)
        self.assertEqual(Post.objects.count(), before)
        self.assertEqual(res["Cache-Control"], "private, no-store")

    def test_decision9_413_comes_before_csrf(self):
        """8,193바이트면 토큰이 없거나 틀려도 413. 같은 요청이 한도 이내면 CSRF 403."""
        self.login(self.a)
        for token in (None, "wrong-token-" + "x" * 52):
            with self.subTest(token=bool(token)):
                self.assert_413(self.send("/posts/new/", form_body(8193, token)))
                self.assertEqual(self.send("/posts/new/", form_body(8192, token)).status_code, 403)
        self.assertEqual(Post.objects.count(), 1)

    def test_fixture_app11_anonymous_with_valid_token(self):
        """권혁민 fixture APP-11-A/B/C: 비로그인 + 유효 CSRF → 302, 302, 413."""
        token = self.anonymous_token()
        for size, status in ((8191, 302), (8192, 302), (8193, 413)):
            with self.subTest(size=size):
                self.assertEqual(self.send("/posts/new/", form_body(size, token)).status_code, status)
        self.assertEqual(Post.objects.count(), 1)


class EditBoundaryTests(BodyLimitBase):
    def test_edit_8193_is_413_and_unchanged_8192_saves(self):
        token = self.login(self.a)
        path = f"/posts/{self.post.pk}/edit/"
        self.assert_413(self.send(path, form_body(8193, token, title="바뀐 제목")))
        self.post.refresh_from_db()
        self.assertEqual((self.post.title, self.post.body), ("원래 제목", "원래 본문"))
        self.assertEqual(self.send(path, form_body(8192, token, title="바뀐 제목")).status_code, 302)
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, "바뀐 제목")

    def test_other_users_post_413_or_404_and_unchanged(self):
        """크기 검사는 소유 여부와 무관하게 같다(없는 글과 남의 글을 구분하지 않음)."""
        token = self.login(self.b)
        for path in (f"/posts/{self.post.pk}/edit/", "/posts/999999/edit/"):
            with self.subTest(path=path):
                self.assert_413(self.send(path, form_body(8193, token)))
                self.assertEqual(self.send(path, form_body(8192, token)).status_code, 404)
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, "원래 제목")


class ScopeAndHeaderTests(BodyLimitBase):
    def test_other_forms_are_not_limited(self):
        """로그인·가입·공유 폼에는 글 한도를 적용하지 않는다(명세 4장: 다른 폼을 깨뜨리지 않음)."""
        big = "x" * 9000
        token = self.anonymous_token()
        login = urlencode({"csrfmiddlewaretoken": token, "username": "member_a", "password": big}).encode()
        self.assertEqual(self.send("/accounts/login/", login).status_code, 400)
        signup = urlencode({"csrfmiddlewaretoken": token, "username": "new_user", "password1": big, "password2": "y"}).encode()
        self.assertEqual(self.send("/accounts/signup/", signup).status_code, 400)
        token = self.login(self.a)
        share = urlencode({"csrfmiddlewaretoken": token, "username": "member_b" + big}).encode()
        self.assertEqual(self.send(f"/posts/{self.post.pk}/shares/", share).status_code, 400)

    def test_declared_length_over_limit_rejected_without_reading(self):
        token = self.login(self.a)
        res = self.send("/posts/new/", form_body(500, token), CONTENT_LENGTH="8193")
        self.assert_413(res)
        self.assertEqual(Post.objects.count(), 1)

    def test_declared_length_smaller_than_sent_never_reads_past_limit(self):
        """Content-Length를 작게 속여도 서버는 그 길이까지만 읽는다. 저장되는 내용은 한도를 넘지 않는다."""
        token = self.login(self.a)
        res = self.send("/posts/new/", form_body(9000, token), CONTENT_LENGTH="8000")
        self.assertNotEqual(res.status_code, 413)
        for post in Post.objects.exclude(pk=self.post.pk):
            self.assertLess(len(post.body.encode()), 8000)

    def test_malformed_content_length_is_400_not_500(self):
        token = self.login(self.a)
        for value in ("abc", "-1"):
            with self.subTest(content_length=value):
                res = self.send("/posts/new/", form_body(500, token), CONTENT_LENGTH=value)
                self.assertEqual(res.status_code, 400)
                self.assertTemplateUsed(res, "400.html")
        self.assertEqual(Post.objects.count(), 1)

    def test_get_pages_unaffected(self):
        self.login(self.a)
        self.assertEqual(self.client.get("/posts/new/").status_code, 200)
        self.assertEqual(self.client.get(f"/posts/{self.post.pk}/edit/").status_code, 200)
