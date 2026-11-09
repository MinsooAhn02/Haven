"""seed_demo 명령: 권혁민 fixture 사전 조건(member_a·b·c, A 소유 기록 id 1·2)."""
import os
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import TransactionTestCase, override_settings

from posts.models import Post

SEED_ENV = {"HAVEN_SEED_PASSWORD": "Virtual-Pass-2026!"}


@override_settings(DEBUG=True)
class SeedDemoTests(TransactionTestCase):
    reset_sequences = True  # 빈 DB에서 id가 1부터 시작하는 상황을 재현

    def test_creates_fixture_users_and_posts(self):
        with mock.patch.dict(os.environ, SEED_ENV):
            call_command("seed_demo", stdout=StringIO())
        self.assertEqual(sorted(User.objects.values_list("username", flat=True)), ["member_a", "member_b", "member_c"])
        a = User.objects.get(username="member_a")
        self.assertEqual(list(Post.objects.order_by("pk").values_list("pk", "owner_id")), [(1, a.pk), (2, a.pk)])
        self.assertTrue(a.check_password(SEED_ENV["HAVEN_SEED_PASSWORD"]))

    def test_refuses_non_empty_db(self):
        User.objects.create_user("someone")
        with mock.patch.dict(os.environ, SEED_ENV), self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
        self.assertEqual(Post.objects.count(), 0)

    def test_requires_password(self):
        with mock.patch.dict(os.environ, {"HAVEN_SEED_PASSWORD": ""}), self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
        self.assertEqual(User.objects.count(), 0)

    @override_settings(DEBUG=False)
    def test_refuses_when_debug_off(self):
        with mock.patch.dict(os.environ, SEED_ENV), self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())
        self.assertEqual(User.objects.count(), 0)
