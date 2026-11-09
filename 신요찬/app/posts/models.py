"""기록과 읽기 공유 모델 (명세 3.1, 앱계약.md 6장).

Attachment는 3회차에 별도 migration으로 추가한다.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q


class Post(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "활성"
        DELETING = "DELETING", "삭제 중"

    # 소유자는 서버가 정하고 바꾸지 않는다. 사용자 삭제 기능이 없으므로 PROTECT로 실수 삭제를 막는다.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="posts",
    )
    title = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(max_length=10, choices=Status, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="post_owner_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["ACTIVE", "DELETING"]),
                name="post_status_valid",
            ),
            models.CheckConstraint(condition=~Q(title=""), name="post_title_not_empty"),
        ]

    def __str__(self):
        # 제목·본문을 로그나 오류 화면에 흘리지 않도록 id만 쓴다.
        return f"Post {self.pk}"


class PostShare(models.Model):
    """읽기 전용 공유. 해제하면 행을 삭제한다(명세 3.3)."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="shares")
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_shares",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "recipient"], name="post_share_unique_recipient"),
        ]

    def __str__(self):
        return f"PostShare {self.pk}"
