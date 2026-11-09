"""기록 변경 처리. 화면 코드는 DB 변경을 여기에 맡긴다."""
from django.db import transaction
from django.http import Http404

from .models import Post, PostShare


@transaction.atomic
def delete_post(post_id, owner):
    """한 transaction에서 DELETING 전환 → 공유 삭제 → 최종 삭제(앱계약.md 6장).

    같은 글에 삭제 요청이 동시에 와도 한 번만 처리되도록 행을 잠근다.
    3회차에는 첨부 파일 정리가 끝난 뒤 최종 삭제하도록 바뀐다.
    """
    post = (
        Post.objects.select_for_update()
        .filter(pk=post_id, owner=owner, status=Post.Status.ACTIVE)
        .first()
    )
    if post is None:
        raise Http404
    post.status = Post.Status.DELETING
    post.save(update_fields=["status", "updated_at"])
    PostShare.objects.filter(post=post).delete()
    post.delete()
