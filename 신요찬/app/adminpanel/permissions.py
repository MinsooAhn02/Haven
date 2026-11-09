"""운영 관리자 판정.

운영 관리자 = 활성 + is_staff + 최고 관리자 아님.
명세 2.2 "일반 운영 흐름에 복구용 최고권한 계정은 포함하지 않는다"에 따라 superuser는 제외한다.
구분 방식(is_staff)은 2회차 화면 계약 7장의 기본값이며 안민수 결정에 따라 바뀔 수 있다.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def is_operator(user):
    return bool(
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and not user.is_superuser
    )


def is_manageable_member(user):
    """운영 관리자가 상태를 바꿀 수 있는 대상: 일반 회원만."""
    return not user.is_staff and not user.is_superuser


def operator_required(view):
    """비로그인은 로그인으로 302, 로그인한 일반 회원은 403(명세 2.1)."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_operator(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
