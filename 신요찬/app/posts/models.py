"""기록, 읽기 공유, 첨부 모델 (명세 3.1·3.4, 앱계약.md 6장)."""
import uuid

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


class Attachment(models.Model):
    """첨부 메타데이터 (명세 3.4). 파일 원본은 HAVEN_UPLOAD_DIR/<storage_key>에 있다.

    - PENDING: 예약됨(아직 제공 안 함). ACTIVE: 다운로드 가능. DELETE_PENDING: 다운로드 차단, 파일 정리 대기.
    - 세 상태 모두 글당 개수와 계정 용량에 포함한다.
    - 소유자는 post.owner로 정한다. 글을 지워도 정리 전에는 cascade로 사라지지 않게 PROTECT.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "예약"
        ACTIVE = "ACTIVE", "활성"
        DELETE_PENDING = "DELETE_PENDING", "삭제 대기"

    post = models.ForeignKey(Post, on_delete=models.PROTECT, related_name="attachments")
    storage_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["post", "status"], name="attachment_post_status_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["PENDING", "ACTIVE", "DELETE_PENDING"]),
                name="attachment_status_valid",
            ),
            models.CheckConstraint(condition=Q(size_bytes__lte=2_097_152), name="attachment_size_max_2mib"),
            models.CheckConstraint(condition=~Q(original_name=""), name="attachment_name_not_empty"),
            # ACTIVE면 검증된 형식과 hash가 반드시 있다.
            models.CheckConstraint(
                condition=~Q(status="ACTIVE") | (~Q(content_type="") & Q(sha256__regex=r"^[0-9a-f]{64}$")),
                name="attachment_active_verified",
            ),
        ]

    def __str__(self):
        # 원본 파일 이름을 로그에 흘리지 않도록 id만 쓴다.
        return f"Attachment {self.pk}"
