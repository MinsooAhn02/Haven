"""계정 역할 판정 (명세 2.2, 3.2).

- 운영 관리자: 활성 + 최고 관리자(superuser) 아님 + 전용 권한 보유.
  `adminpanel.manage_account_status`(계정 목록·상태 변경), `adminpanel.view_account_status_events`(이력).
  is_staff만으로는 운영 관리자가 아니다(명세 3.2 "is_staff만으로 작업을 허용하지 않는다").
- 관리자 계정: 운영 권한이 있거나 is_staff 또는 superuser인 계정. 계정 관리 대상과 공유 대상에서 빠진다.
- 일반 회원: 관리자 계정이 아닌 계정. 권한을 개인으로 받든 그룹으로 받든 같게 본다.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q

PERM_APP = "adminpanel"
MANAGE_ACCOUNT_STATUS = "manage_account_status"
VIEW_ACCOUNT_STATUS_EVENTS = "view_account_status_events"
OPERATOR_CODENAMES = (MANAGE_ACCOUNT_STATUS, VIEW_ACCOUNT_STATUS_EVENTS)


def is_operator_with(user, codename):
    """해당 운영 권한을 가진 활성 운영 관리자인가. superuser는 모든 권한이 있어 보여도 제외한다."""
    return bool(
        user.is_authenticated
        and user.is_active
        and not user.is_superuser
        and user.has_perm(f"{PERM_APP}.{codename}")
    )


def _operator_perm_q(prefix=""):
    return Q(
        **{
            f"{prefix}user_permissions__content_type__app_label": PERM_APP,
            f"{prefix}user_permissions__codename__in": OPERATOR_CODENAMES,
        }
    ) | Q(
        **{
            f"{prefix}groups__permissions__content_type__app_label": PERM_APP,
            f"{prefix}groups__permissions__codename__in": OPERATOR_CODENAMES,
        }
    )


def admin_account_ids():
    """관리자 계정 id (is_staff, superuser, 운영 권한 보유)."""
    return (
        get_user_model()
        .objects.filter(Q(is_staff=True) | Q(is_superuser=True) | _operator_perm_q())
        .values("pk")
    )


def members():
    """일반 회원 queryset."""
    return get_user_model().objects.exclude(pk__in=admin_account_ids())


def is_member(user):
    return bool(user is not None and user.pk is not None and members().filter(pk=user.pk).exists())
