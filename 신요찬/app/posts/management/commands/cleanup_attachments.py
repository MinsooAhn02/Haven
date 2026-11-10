"""첨부 정리 재시도 (명세 3.4 "생성과 실패", "삭제와 복원").

다시 실행해도 안전하다. 처리 순서:
  1. DELETE_PENDING 첨부: 파일 삭제 → 메타데이터 삭제 (파일 삭제 실패 시 행 유지)
  2. 오래된 PENDING 첨부(--pending-minutes, 기본 60분): 업로드가 중간에 끊긴 예약. 파일·행 삭제
  3. DELETING 글: 남은 첨부가 없으면 최종 삭제
  4. .incoming의 오래된 임시 파일(같은 기준 시간) 삭제
  5. 어떤 행과도 맞지 않는 파일(고아)은 목록만 출력. --delete-orphans일 때만 삭제

출력에는 id·개수만 쓰고 원본 파일 이름이나 내용은 쓰지 않는다.
"""
import time
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posts import attachments, services
from posts.models import Attachment, Post


class Command(BaseCommand):
    help = "삭제 대기·끊긴 예약 첨부와 남은 임시 파일을 정리한다."

    def add_arguments(self, parser):
        parser.add_argument("--pending-minutes", type=int, default=60)
        parser.add_argument("--delete-orphans", action="store_true")

    def handle(self, *args, pending_minutes, delete_orphans, **options):
        if pending_minutes < 1:
            raise CommandError("--pending-minutes는 1 이상이어야 합니다.")
        cutoff = timezone.now() - timedelta(minutes=pending_minutes)
        failed = 0

        purged = 0
        for att in Attachment.objects.filter(status=Attachment.Status.DELETE_PENDING):
            if attachments.purge(att):
                purged += 1
            else:
                failed += 1

        stale = 0
        for att in Attachment.objects.filter(status=Attachment.Status.PENDING, created_at__lt=cutoff):
            if attachments.purge(att):
                stale += 1
            else:
                failed += 1

        finished = 0
        for post in Post.objects.filter(status=Post.Status.DELETING):
            if services.finish_post_deletion(post):
                finished += 1
            else:
                failed += 1

        temp_removed = 0
        incoming = attachments.incoming_dir()
        if incoming.is_dir():
            limit = time.time() - pending_minutes * 60
            for path in incoming.iterdir():
                if path.is_file() and path.stat().st_mtime < limit:
                    try:
                        path.unlink()
                        temp_removed += 1
                    except OSError:
                        failed += 1

        orphans = []
        root = attachments.upload_root()
        if root.is_dir():
            known = {str(k) for k in Attachment.objects.values_list("storage_key", flat=True)}
            for path in root.iterdir():
                if path.name == attachments.INCOMING_DIRNAME or not path.is_file():
                    continue
                if path.name not in known:
                    orphans.append(path)
        orphan_removed = 0
        for path in orphans:
            self.stdout.write(f"orphan {self._safe_name(path.name)}")
            if delete_orphans:
                try:
                    path.unlink()
                    orphan_removed += 1
                except OSError:
                    failed += 1

        self.stdout.write(
            f"delete_pending_purged={purged} stale_pending_purged={stale} posts_finished={finished} "
            f"temp_removed={temp_removed} orphans={len(orphans)} orphans_removed={orphan_removed} failed={failed}"
        )
        if failed:
            raise CommandError(f"정리하지 못한 항목 {failed}개. 잠시 뒤 다시 실행하세요.")

    @staticmethod
    def _safe_name(name):
        """UUID 모양이면 그대로, 아니면 이름을 출력하지 않는다."""
        try:
            return str(uuid.UUID(name))
        except ValueError:
            return "(non-uuid file)"
