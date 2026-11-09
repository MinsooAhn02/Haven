"""SH-01~07 읽기 전용 공유 (명세 3.3, 8.1.1).

A = 소유자, B = 공유 대상, C = 공유하지 않은 회원, operator = 제한된 운영 관리자.
"""
from django.contrib.auth.models import User
from django.test import Client, TestCase

from posts.forms import SHARE_TARGET_ERROR
from posts.models import Post, PostShare


class SharingBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a")
        cls.b = User.objects.create_user("member_b")
        cls.c = User.objects.create_user("member_c")
        cls.op = User.objects.create_user("operator", is_staff=True)
        cls.p1 = Post.objects.create(owner=cls.a, title="A의 공유 기록", body="A의 공유 본문")
        cls.p2 = Post.objects.create(owner=cls.a, title="A의 다른 기록", body="다른 본문")

    def as_user(self, user):
        self.client.force_login(user)
        return self.client

    def share(self, post=None, recipient=None):
        return PostShare.objects.create(post=post or self.p1, recipient=recipient or self.b)


class OwnerShareManagementTests(SharingBase):
    def test_owner_can_open_share_page(self):
        res = self.as_user(self.a).get(f"/posts/{self.p1.pk}/shares/")
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "posts/shares.html")
        self.assertEqual(res.context["post"], self.p1)
        self.assertEqual(list(res.context["form"].fields), ["username"])
        self.assertEqual(list(res.context["shares"]), [])
        self.assertEqual(res["Cache-Control"], "private, no-store")

    def test_owner_shares_with_active_member(self):
        res = self.as_user(self.a).post(f"/posts/{self.p1.pk}/shares/", {"username": "member_b"})
        self.assertRedirects(res, f"/posts/{self.p1.pk}/shares/", fetch_redirect_response=False)
        self.assertEqual(list(PostShare.objects.values_list("post_id", "recipient_id")), [(self.p1.pk, self.b.pk)])
        listed = self.client.get(f"/posts/{self.p1.pk}/shares/").context["shares"]
        self.assertEqual([s.recipient.username for s in listed], ["member_b"])

    def test_duplicate_share_creates_no_second_row(self):
        """SH-04: 같은 대상 중복 공유는 행을 더 만들지 않는다."""
        self.share()
        res = self.as_user(self.a).post(f"/posts/{self.p1.pk}/shares/", {"username": "member_b"})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(PostShare.objects.count(), 1)

    def test_disallowed_targets_get_one_generic_error(self):
        """SH-04: 없는/자기 자신/비활성/운영 관리자/최고 관리자 대상은 같은 문구의 400."""
        User.objects.create_user("inactive_member", is_active=False)
        User.objects.create_superuser("root_admin")
        client = self.as_user(self.a)
        for username in ("no_such_member", "member_a", "inactive_member", "operator", "root_admin"):
            with self.subTest(username=username):
                res = client.post(f"/posts/{self.p1.pk}/shares/", {"username": username})
                self.assertEqual(res.status_code, 400)
                self.assertEqual(res.context["form"].errors["username"], [SHARE_TARGET_ERROR])
        self.assertFalse(PostShare.objects.exists())

    def test_empty_username_is_400(self):
        res = self.as_user(self.a).post(f"/posts/{self.p1.pk}/shares/", {"username": ""})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(PostShare.objects.exists())

    def test_owner_revokes_share(self):
        share = self.share()
        res = self.as_user(self.a).post(f"/posts/{self.p1.pk}/shares/{share.pk}/revoke/")
        self.assertRedirects(res, f"/posts/{self.p1.pk}/shares/", fetch_redirect_response=False)
        self.assertFalse(PostShare.objects.exists())

    def test_revoke_get_is_405(self):
        share = self.share()
        res = self.as_user(self.a).get(f"/posts/{self.p1.pk}/shares/{share.pk}/revoke/")
        self.assertEqual(res.status_code, 405)
        self.assertTrue(PostShare.objects.filter(pk=share.pk).exists())

    def test_owner_with_other_posts_share_id_is_404(self):
        """SH-05: 소유자라도 다른 글의 share_id 조합은 거부, 공유 유지."""
        share_on_p2 = self.share(post=self.p2)
        res = self.as_user(self.a).post(f"/posts/{self.p1.pk}/shares/{share_on_p2.pk}/revoke/")
        self.assertEqual(res.status_code, 404)
        self.assertTrue(PostShare.objects.filter(pk=share_on_p2.pk).exists())


class RecipientReadOnlyTests(SharingBase):
    def setUp(self):
        self.s = self.share()

    def test_sh01_recipient_reads_shared_post(self):
        client = self.as_user(self.b)
        listed = client.get("/posts/shared/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([p.pk for p in listed.context["posts"]], [self.p1.pk])
        detail = client.get(f"/posts/{self.p1.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertIs(detail.context["is_owner"], False)
        self.assertEqual(detail.context["post"].owner.username, "member_a")

    def test_sh01_owner_still_sees_own_post_as_owner(self):
        detail = self.as_user(self.a).get(f"/posts/{self.p1.pk}/")
        self.assertIs(detail.context["is_owner"], True)
        self.assertEqual(list(self.client.get("/posts/shared/").context["posts"]), [])

    def test_sh01_non_recipient_cannot_see(self):
        client = self.as_user(self.c)
        self.assertEqual(client.get(f"/posts/{self.p1.pk}/").status_code, 404)
        self.assertEqual(list(client.get("/posts/shared/").context["posts"]), [])

    def test_sh01_unshared_post_of_same_owner_still_hidden(self):
        self.assertEqual(self.as_user(self.b).get(f"/posts/{self.p2.pk}/").status_code, 404)

    def test_sh02_recipient_cannot_change_anything(self):
        client = self.as_user(self.b)
        pk = self.p1.pk
        requests = [
            ("get", f"/posts/{pk}/edit/", None),
            ("post", f"/posts/{pk}/edit/", {"title": "B가 바꿈", "body": "x"}),
            ("get", f"/posts/{pk}/delete/", None),
            ("post", f"/posts/{pk}/delete/", {}),
            ("get", f"/posts/{pk}/shares/", None),
            ("post", f"/posts/{pk}/shares/", {"username": "member_c"}),
            ("post", f"/posts/{pk}/shares/{self.s.pk}/revoke/", {}),
        ]
        for method, path, data in requests:
            with self.subTest(method=method, path=path):
                res = getattr(client, method)(path, data) if data is not None else getattr(client, method)(path)
                self.assertEqual(res.status_code, 404)
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.title, self.p1.status), ("A의 공유 기록", "ACTIVE"))
        self.assertEqual(list(PostShare.objects.values_list("recipient__username", flat=True)), ["member_b"])

    def test_sh02_shares_page_does_not_leak_recipients_to_others(self):
        res = self.as_user(self.c).get(f"/posts/{self.p1.pk}/shares/")
        self.assertEqual(res.status_code, 404)
        self.assertNotContains(res, "member_b", status_code=404)

    def test_sh03_revoked_share_denied_from_next_request(self):
        client_b = Client()
        client_b.force_login(self.b)
        self.assertEqual(client_b.get(f"/posts/{self.p1.pk}/").status_code, 200)
        self.as_user(self.a).post(f"/posts/{self.p1.pk}/shares/{self.s.pk}/revoke/")
        self.assertEqual(client_b.get(f"/posts/{self.p1.pk}/").status_code, 404)
        self.assertEqual(list(client_b.get("/posts/shared/").context["posts"]), [])
        self.assertEqual(self.client.get(f"/posts/{self.p1.pk}/").status_code, 200)  # 소유자 A는 그대로

    def test_sh05_recipient_or_stranger_cannot_revoke(self):
        for user in (self.b, self.c):
            with self.subTest(user=user.username):
                res = self.as_user(user).post(f"/posts/{self.p1.pk}/shares/{self.s.pk}/revoke/")
                self.assertEqual(res.status_code, 404)
        self.assertTrue(PostShare.objects.filter(pk=self.s.pk).exists())

    def test_sh06_inactive_owner_hides_shared_post(self):
        User.objects.filter(pk=self.a.pk).update(is_active=False)
        client = self.as_user(self.b)
        self.assertEqual(client.get(f"/posts/{self.p1.pk}/").status_code, 404)
        self.assertEqual(list(client.get("/posts/shared/").context["posts"]), [])
        self.assertTrue(PostShare.objects.filter(pk=self.s.pk).exists())  # 관계는 남아 있음

    def test_sh06_inactive_recipient_existing_session_rejected(self):
        client = self.as_user(self.b)
        self.assertEqual(client.get(f"/posts/{self.p1.pk}/").status_code, 200)
        User.objects.filter(pk=self.b.pk).update(is_active=False)
        for path in (f"/posts/{self.p1.pk}/", "/posts/shared/"):
            with self.subTest(path=path):
                res = client.get(path)
                self.assertRedirects(res, f"/accounts/login/?next={path}", fetch_redirect_response=False)

    def test_deleting_post_removes_access(self):
        Post.objects.filter(pk=self.p1.pk).update(status=Post.Status.DELETING)
        client = self.as_user(self.b)
        self.assertEqual(client.get(f"/posts/{self.p1.pk}/").status_code, 404)
        self.assertEqual(list(client.get("/posts/shared/").context["posts"]), [])  # 공유 목록에서도 빠짐

    def test_owner_detail_works_when_shared_with_several_members(self):
        """여러 명에게 공유한 글도 소유자 상세가 한 건으로 열린다(OR 조건 중복 방지)."""
        self.share(recipient=self.c)
        for user in (self.a, self.b, self.c):
            with self.subTest(user=user.username):
                self.assertEqual(self.as_user(user).get(f"/posts/{self.p1.pk}/").status_code, 200)

    def test_shared_list_has_no_duplicates(self):
        p3 = Post.objects.create(owner=self.c, title="C의 기록", body="b")
        self.share(post=p3)
        titles = [p.title for p in self.as_user(self.b).get("/posts/shared/").context["posts"]]
        self.assertEqual(sorted(titles), sorted(["A의 공유 기록", "C의 기록"]))

    def test_sh07_operator_gets_no_body_access(self):
        client = self.as_user(self.op)
        for path in (f"/posts/{self.p1.pk}/", f"/posts/{self.p1.pk}/edit/", f"/posts/{self.p1.pk}/shares/"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)
        self.assertEqual(list(client.get("/posts/shared/").context["posts"]), [])

    def test_sh07_anonymous_redirected(self):
        for path in (f"/posts/{self.p1.pk}/shares/", "/posts/shared/"):
            with self.subTest(path=path):
                res = self.client.get(path)
                self.assertRedirects(res, f"/accounts/login/?next={path}", fetch_redirect_response=False)


class SharingCsrfTests(SharingBase):
    def setUp(self):
        self.s = self.share()
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.a)

    def _token(self):
        return str(self.client.get(f"/posts/{self.p1.pk}/shares/").context["csrf_token"])

    def test_share_without_token_is_403(self):
        res = self.client.post(f"/posts/{self.p1.pk}/shares/", {"username": "member_c"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(PostShare.objects.count(), 1)

    def test_share_with_token_succeeds(self):
        res = self.client.post(f"/posts/{self.p1.pk}/shares/", {"username": "member_c", "csrfmiddlewaretoken": self._token()})
        self.assertEqual(res.status_code, 302)
        self.assertEqual(PostShare.objects.count(), 2)

    def test_revoke_without_token_is_403(self):
        res = self.client.post(f"/posts/{self.p1.pk}/shares/{self.s.pk}/revoke/")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(PostShare.objects.filter(pk=self.s.pk).exists())

    def test_revoke_with_token_succeeds(self):
        res = self.client.post(f"/posts/{self.p1.pk}/shares/{self.s.pk}/revoke/", {"csrfmiddlewaretoken": self._token()})
        self.assertEqual(res.status_code, 302)
        self.assertFalse(PostShare.objects.exists())
