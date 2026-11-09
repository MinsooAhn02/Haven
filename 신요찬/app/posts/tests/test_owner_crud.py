"""APP-02 소유자 작성·목록·상세·수정·삭제, 입력 검증 400."""
from django.contrib.auth.models import User
from django.test import TestCase

from posts.models import Post, PostShare


class OwnerCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a")
        cls.b = User.objects.create_user("member_b")

    def setUp(self):
        self.client.force_login(self.a)

    def test_create_sets_owner_from_session_and_ignores_owner_status_fields(self):
        res = self.client.post(
            "/posts/new/",
            {"title": "가상 제목", "body": "가상 본문", "owner": self.b.pk, "author_id": self.b.pk, "status": "DELETING"},
        )
        post = Post.objects.get()
        self.assertRedirects(res, f"/posts/{post.pk}/", fetch_redirect_response=False)
        self.assertEqual(post.owner, self.a)
        self.assertEqual(post.status, Post.Status.ACTIVE)

    def test_create_form_get(self):
        res = self.client.get("/posts/new/")
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "posts/form.html")
        self.assertEqual(res.context["mode"], "create")
        self.assertIsNone(res.context["post"])
        self.assertEqual(list(res.context["form"].fields), ["title", "body"])

    def test_list_is_own_posts_newest_first_20_per_page(self):
        for i in range(21):
            Post.objects.create(owner=self.a, title=f"A{i:02d}", body="b")
        Post.objects.create(owner=self.b, title="B의 기록", body="b")
        res = self.client.get("/posts/")
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "posts/list.html")
        titles = [p.title for p in res.context["posts"]]
        self.assertEqual(len(titles), 20)
        self.assertEqual(titles[0], "A20")
        self.assertNotIn("B의 기록", titles)
        self.assertTrue(res.context["page_obj"].has_next())
        page2 = self.client.get("/posts/?page=2")
        self.assertEqual([p.title for p in page2.context["posts"]], ["A00"])

    def test_list_sets_private_no_store(self):
        res = self.client.get("/posts/")
        self.assertEqual(res["Cache-Control"], "private, no-store")

    def test_empty_list(self):
        res = self.client.get("/posts/")
        self.assertEqual(list(res.context["posts"]), [])

    def test_detail(self):
        post = Post.objects.create(owner=self.a, title="가상 제목", body="가상 본문")
        res = self.client.get(f"/posts/{post.pk}/")
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "posts/detail.html")
        self.assertEqual(res.context["post"], post)
        self.assertIs(res.context["is_owner"], True)

    def test_edit(self):
        post = Post.objects.create(owner=self.a, title="수정 전", body="본문")
        get = self.client.get(f"/posts/{post.pk}/edit/")
        self.assertEqual(get.status_code, 200)
        self.assertEqual(get.context["mode"], "edit")
        self.assertEqual(get.context["form"]["title"].value(), "수정 전")
        res = self.client.post(f"/posts/{post.pk}/edit/", {"title": "수정 후", "body": "새 본문"})
        self.assertRedirects(res, f"/posts/{post.pk}/", fetch_redirect_response=False)
        post.refresh_from_db()
        self.assertEqual((post.title, post.body, post.owner), ("수정 후", "새 본문", self.a))

    def test_delete_confirm_get_does_not_delete(self):
        post = Post.objects.create(owner=self.a, title="삭제 대상", body="본문")
        res = self.client.get(f"/posts/{post.pk}/delete/")
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "posts/confirm_delete.html")
        self.assertTrue(Post.objects.filter(pk=post.pk).exists())

    def test_delete_post_removes_post_and_shares(self):
        post = Post.objects.create(owner=self.a, title="삭제 대상", body="본문")
        PostShare.objects.create(post=post, recipient=self.b)
        res = self.client.post(f"/posts/{post.pk}/delete/")
        self.assertRedirects(res, "/posts/", fetch_redirect_response=False)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())
        self.assertFalse(PostShare.objects.exists())
        self.assertEqual(self.client.get(f"/posts/{post.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/posts/{post.pk}/delete/").status_code, 404)

    def test_shared_list_placeholder_is_empty(self):
        res = self.client.get("/posts/shared/")
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "posts/shared_list.html")
        self.assertEqual(list(res.context["posts"]), [])


class PostValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a")

    def setUp(self):
        self.client.force_login(self.a)

    def _assert_rejected(self, data, field):
        res = self.client.post("/posts/new/", data)
        self.assertEqual(res.status_code, 400)
        self.assertIn(field, res.context["form"].errors)
        self.assertEqual(Post.objects.count(), 0)
        return res

    def test_empty_title(self):
        self._assert_rejected({"title": "", "body": "본문"}, "title")

    def test_whitespace_title(self):
        self._assert_rejected({"title": "   ", "body": "본문"}, "title")

    def test_title_201_chars(self):
        self._assert_rejected({"title": "가" * 201, "body": "본문"}, "title")

    def test_whitespace_body(self):
        self._assert_rejected({"title": "제목", "body": " \n\t "}, "body")

    def test_failed_form_keeps_title(self):
        res = self._assert_rejected({"title": "남는 제목", "body": ""}, "body")
        self.assertEqual(res.context["form"]["title"].value(), "남는 제목")

    def test_title_200_chars_ok_and_body_whitespace_preserved(self):
        res = self.client.post("/posts/new/", {"title": "가" * 200, "body": "  들여쓴 본문\n"})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(Post.objects.get().body, "  들여쓴 본문\n")

    def test_invalid_edit_is_400_and_unchanged(self):
        post = Post.objects.create(owner=self.a, title="원래 제목", body="원래 본문")
        res = self.client.post(f"/posts/{post.pk}/edit/", {"title": "", "body": "x"})
        self.assertEqual(res.status_code, 400)
        post.refresh_from_db()
        self.assertEqual(post.title, "원래 제목")
