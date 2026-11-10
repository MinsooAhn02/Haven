"""운영 관리자 화면 접근 (판정 규칙은 accounts/roles.py).

- 계정 목록·상태 변경: `adminpanel.manage_account_status`
- 상태 변경 이력: `adminpanel.view_account_status_events`
- is_staff만으로는 허용하지 않고, superuser는 운영 흐름에 넣지 않는다(명세 2.2, 3.2).
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from accounts.roles import MANAGE_ACCOUNT_STATUS, VIEW_ACCOUNT_STATUS_EVENTS, is_member, is_operator_with


def operator_required(codename):
    """비로그인은 로그인으로 302, 권한 없는 로그인 사용자는 403(명세 2.1)."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not is_operator_with(request.user, codename):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


manage_required = operator_required(MANAGE_ACCOUNT_STATUS)
events_required = operator_required(VIEW_ACCOUNT_STATUS_EVENTS)


def is_manageable_member(user):
    """운영 관리자가 상태를 바꿀 수 있는 대상: 일반 회원만(관리자 계정·superuser 제외)."""
    return is_member(user)
