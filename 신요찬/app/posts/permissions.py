"""기록 조회 권한. 모든 화면은 이 함수들로만 기록을 가져온다(명세 3.2·3.3).

권한이 없는 기록과 없는 기록을 구분하지 않도록, 호출하는 쪽은 결과에서
get_object_or_404를 쓴다(둘 다 404).

- 수정·삭제·공유 관리는 owned_posts()로만 찾는다(소유자만).
- 상세 조회는 readable_posts()로 찾는다(소유자 + 유효한 공유 대상).
- 매 요청 현재 상태를 다시 확인한다: ACTIVE 글, 활성 소유자, 지금 있는 공유 관계.
  (요청한 사람이 비활성이면 Django 인증이 세션을 비로그인으로 처리한다.)
"""
from django.db.models import Q

from .models import Post


def owned_posts(user):
    """사용자가 소유한 ACTIVE 기록. 수정·삭제·공유 관리는 이 범위에서만 가능하다."""
    if not user.is_authenticated:
        return Post.objects.none()
    return Post.objects.filter(owner=user, status=Post.Status.ACTIVE)


def shared_posts(user):
    """사용자에게 지금 공유된 기록. 해제됐거나 소유자가 비활성인 글은 빠진다."""
    if not user.is_authenticated:
        return Post.objects.none()
    return (
        Post.objects.filter(
            status=Post.Status.ACTIVE,
            owner__is_active=True,
            shares__recipient=user,
        )
        .exclude(owner=user)
        .distinct()
    )


def readable_posts(user):
    """사용자가 읽을 수 있는 기록: 소유한 글 또는 지금 공유받은 글.

    공유 조건을 OR로 합치면 같은 글이 중복될 수 있어 distinct()를 붙인다.
    """
    if not user.is_authenticated:
        return Post.objects.none()
    return (
        Post.objects.filter(status=Post.Status.ACTIVE, owner__is_active=True)
        .filter(Q(owner=user) | Q(shares__recipient=user))
        .distinct()
    )
