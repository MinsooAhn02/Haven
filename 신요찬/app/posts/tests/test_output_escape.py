"""APP-06 한국어·따옴표·코드·HTML 모양 입력: 저장은 그대로, 화면에서는 HTML/스크립트로 실행되지 않음(명세 8.1.1).

A = 소유자, B = 공유 대상. 제목·본문·첨부 이름이 나오는 모든 화면(작성자 목록·상세·수정·삭제 확인·공유 설정,
공유받은 목록·상세)에서 태그가 그대로 나오지 않고 이스케이프된 글자로만 나오는지 본다.
템플릿에서 이스케이프를 끄면(`|safe` 등) 이 시험이 실패해야 한다.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from posts.models import Attachment, Post, PostShare
from posts.tests.test_attachments import UploadDirMixin

TITLE = '<script>alert("t")</script> 제목 \'따옴표\' & {{ 7|add:42 }}'
BODY = (
    "한국어 본문입니다.\n"
    '<script>alert("b")</script>\n'
    "<img src=x onerror=alert(2)>\n"
    "<a href=\"javascript:alert(3)\">링크</a>\n"
    "{{ 7|add:42 }} {% now 'Y' %}\n"
    "if (a < b && c > d) { return \"코드\"; }"
)
FILE_NAME = "<img src=y onerror=alert(4)>.txt"

# 화면에 이 문자열이 그대로 있으면 태그나 템플릿 문법이 살아 있는 것이다.
RAW_MARKERS = (
    '<script>alert("t")',
    '<script>alert("b")',
    "<img src=x onerror",
    "<img src=y onerror",
    '<a href="javascript:alert(3)"',
)


class OutputEscapeTests(UploadDirMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a")
        cls.b = User.objects.create_user("member_b")

    def setUp(self):
        super().setUp()
        self.client.force_login(self.a)
        res = self.client.post("/posts/new/", {"title": TITLE, "body": BODY})
        self.assertEqual(res.status_code, 302)
        self.post = Post.objects.get(owner=self.a)
        res = self.upload(self.client, self.post, FILE_NAME, "가상 첨부".encode())
        self.assertEqual(res.status_code, 302)
        PostShare.objects.create(post=self.post, recipient=self.b)

    def assert_escaped(self, res, where):
        self.assertEqual(res.status_code, 200, where)
        html = res.content.decode()
        for marker in RAW_MARKERS:
            self.assertNotIn(marker, html, f"{where}: {marker}")
        self.assertIn("{{ 7|add:42 }}", html, f"{where}: 템플릿 문법이 글자로 남아야 함")
        self.assertIn("&lt;script&gt;alert(&quot;t&quot;)&lt;/script&gt;", html, where)
        return html

    def test_app06_input_saved_unchanged(self):
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, TITLE)
        self.assertEqual(self.post.body.replace("\r\n", "\n"), BODY)
        self.assertEqual(Attachment.objects.get(post=self.post).original_name, FILE_NAME)

    def test_app06_owner_pages_escape_title_body_and_file_name(self):
        pk = self.post.pk
        for path in ("/posts/", f"/posts/{pk}/edit/", f"/posts/{pk}/delete/", f"/posts/{pk}/shares/"):
            self.assert_escaped(self.client.get(path), path)
        html = self.assert_escaped(self.client.get(f"/posts/{pk}/"), "owner detail")
        self.assertIn("&lt;img src=x onerror=alert(2)&gt;", html)
        self.assertIn("&lt;img src=y onerror=alert(4)&gt;.txt", html)
        self.assertIn("{% now &#x27;Y&#x27; %}", html)
        self.assertIn("if (a &lt; b &amp;&amp; c &gt; d)", html)

    def test_app06_recipient_pages_escape_title_body_and_file_name(self):
        self.client.force_login(self.b)
        self.assert_escaped(self.client.get("/posts/shared/"), "shared list")
        html = self.assert_escaped(self.client.get(f"/posts/{self.post.pk}/"), "recipient detail")
        self.assertIn("&lt;img src=y onerror=alert(4)&gt;.txt", html)
        self.assertIn("&lt;a href=&quot;javascript:alert(3)&quot;&gt;", html)


class SqlShapedInputTests(TestCase):
    """APP-06 코드 모양 입력 중 SQL 모양: 글자 그대로 저장되고, 로그인을 우회하지 못한다(ORM 값 바인딩)."""

    SQL = ["' OR '1'='1", "admin'--", "x' UNION SELECT password FROM auth_user--", "1; DROP TABLE posts_post;--"]

    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a", password="Virtual-Pass-2026!")

    def test_app06_sql_shaped_text_is_stored_as_text(self):
        self.client.force_login(self.a)
        for s in self.SQL:
            self.assertEqual(self.client.post("/posts/new/", {"title": s, "body": s}).status_code, 302)
        self.assertEqual(sorted(Post.objects.values_list("title", flat=True)), sorted(self.SQL))
        self.assertEqual(sorted(Post.objects.values_list("body", flat=True)), sorted(self.SQL))

    def test_app06_sql_shaped_login_is_rejected(self):
        for s in self.SQL:
            res = self.client.post("/accounts/login/", {"username": s, "password": s})
            self.assertEqual(res.status_code, 400, s)
            self.assertNotIn("_auth_user_id", self.client.session)
        res = self.client.post("/accounts/login/", {"username": "member_a", "password": "' OR '1'='1"})
        self.assertEqual(res.status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(User.objects.count(), 1)
