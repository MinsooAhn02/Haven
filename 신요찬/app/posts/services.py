"""기록 변경 처리. 화면 코드는 DB 변경을 여기에 맡긴다."""
from django.db import transaction
from django.http import Http404

from . import attachments
from .models import Attachment, Post, PostShare


def delete_post(post_id, owner):
    """글 삭제 (명세 3.4 "삭제와 복원").

    1) 한 transaction: DELETING 전환 → 공유 삭제 → 첨부를 DELETE_PENDING으로. 이 시점부터 모든 접근이 막힌다.
    2) 첨부 파일 정리. 모두 끝나면 글을 최종 삭제한다.
       정리가 하나라도 실패하면 글은 DELETING으로 남고 cleanup_attachments 명령이 다시 시도한다.
    같은 글에 삭제 요청이 동시에 와도 한 번만 처리되도록 행을 잠근다.
    """
    with transaction.atomic():
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
        post.attachments.exclude(status=Attachment.Status.DELETE_PENDING).update(
            status=Attachment.Status.DELETE_PENDING
        )
    finish_post_deletion(post)


def finish_post_deletion(post):
    """DELETING 글의 첨부 파일을 정리하고, 남은 첨부가 없으면 글을 지운다. 끝났으면 True."""
    for attachment in list(post.attachments.all()):
        attachments.purge(attachment)
    with transaction.atomic():
        locked = Post.objects.select_for_update().filter(pk=post.pk, status=Post.Status.DELETING).first()
        if locked is None:
            return True
        if locked.attachments.exists():
            return False
        locked.delete()
    return True
