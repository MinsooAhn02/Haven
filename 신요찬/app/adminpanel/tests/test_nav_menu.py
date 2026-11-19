"""운영 관리자 메뉴 (앱계약 5장 base.html 조건, 11/19 조장 APP-07·09 발견).

계정 관리 메뉴: `perms.adminpanel.manage_account_status and not user.is_superuser`
이력 메뉴:     `perms.adminpanel.view_account_status_events and not user.is_superuser`
메뉴 이름은 템플릿 담당이 바꿀 수 있어 링크 주소로 확인한다. 권한 검사는 서버가 따로 한다(test_accounts.py).
"""
from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from .test_accounts import EVENTS, MANAGE, grant

ACCOUNTS_LINK = 'href="/admin/accounts/"'
EVENTS_LINK = 'href="/admin/account-events/"'


class OperatorMenuTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.op = grant(User.objects.create_user("operator"), MANAGE, EVENTS)
        cls.manage_only = grant(User.objects.create_user("manage_only"), MANAGE)
        cls.events_only = grant(User.objects.create_user("events_only"), EVENTS)
        cls.group_op = User.objects.create_user("group_operator")
        group = Group.objects.create(name="operators")
        group.permissions.set(Permission.objects.filter(content_type__app_label="adminpanel", codename__in=(MANAGE, EVENTS)))
        cls.group_op.groups.add(group)
        cls.member = User.objects.create_user("member_a")
        cls.staff_only = User.objects.create_user("staff_only", is_staff=True)
        cls.root = User.objects.create_superuser("root_admin")

    def menu(self, user, path="/posts/"):
        self.client.force_login(user)
        res = self.client.get(path)
        self.assertEqual(res.status_code, 200, f"{user.username} {path}")
        html = res.content.decode()
        return ACCOUNTS_LINK in html, EVENTS_LINK in html

    def test_operator_sees_both_menus(self):
        self.assertEqual(self.menu(self.op), (True, True))
        self.assertEqual(self.menu(self.group_op), (True, True))

    def test_each_menu_follows_its_own_permission(self):
        self.assertEqual(self.menu(self.manage_only), (True, False))
        self.assertEqual(self.menu(self.events_only), (False, True))

    def test_menu_is_on_admin_pages_too(self):
        self.assertEqual(self.menu(self.op, "/admin/accounts/"), (True, True))
        self.assertEqual(self.menu(self.op, "/admin/account-events/"), (True, True))

    def test_no_menu_for_member_staff_superuser_or_anonymous(self):
        for user in (self.member, self.staff_only, self.root):
            self.assertEqual(self.menu(user), (False, False), user.username)
        self.client.logout()
        html = self.client.get("/accounts/login/").content.decode()
        self.assertNotIn(ACCOUNTS_LINK, html)
        self.assertNotIn(EVENTS_LINK, html)
