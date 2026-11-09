"""기록 조회 권한. 모든 화면은 이 함수들로만 기록을 가져온다(명세 3.2).

권한이 없는 기록과 없는 기록을 구분하지 않도록, 호출하는 쪽은 결과에서
get_object_or_404를 쓴다(둘 다 404).
"""
from .models import Post


def owned_posts(user):
    """사용자가 소유한 ACTIVE 기록. 수정·삭제는 이 범위에서만 가능하다."""
    if not user.is_authenticated:
        return Post.objects.none()
    return Post.objects.filter(owner=user, status=Post.Status.ACTIVE)


def readable_posts(user):
    """사용자가 읽을 수 있는 기록. 1회차는 소유 기록만.

    2회차에 공유받은 기록을 더할 때: 공유 조건을 OR로 합치면 같은 글이 중복될 수
    있으므로 .distinct()를 붙이고, 소유자가 활성 계정인지도 함께 확인한다.
    """
    return owned_posts(user)
