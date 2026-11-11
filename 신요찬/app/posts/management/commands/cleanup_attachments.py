"""첨부 정리 재시도 (명세 3.4 "생성과 실패", "삭제와 복원").

다시 실행해도 안전하다. 처리 순서:
  1. DELETE_PENDING 첨부: 파일 삭제 → 메타데이터 삭제 (파일 삭제 실패 시 행 유지)
  2. 오래된 PENDING 첨부(--pending-minutes, 기본 60분): 업로드가 중간에 끊긴 예약. 파일·행 삭제
  3. DELETING 글: 남은 첨부가 없으면 최종 삭제
  4. .incoming의 오래된 임시 파일(같은 기준 시간) 삭제
  5. 어떤 행과도 맞지 않는 파일(고아)은 목록만 출력. --delete-orphans일 때만 삭제

동시 업로드와 겹칠 때 (권혁민 #38 리뷰):
  - 1·2는 지우기 직전에 행을 잠그고 상태·시각을 다시 확인한다(attachments.purge). 그 사이 ACTIVE가 된 첨부는 건너뛴다.
  - 5는 기준 시간보다 오래된 파일만 지우고, 지우기 직전에 같은 저장키의 행이 생겼는지 다시 확인한다.
    업로드는 행을 먼저 만들고(reserve) 파일을 나중에 만들기(store) 때문에, "파일이 있는데 행이 없다"를
    지우기 직전에 확인하면 업로드 중인 파일을 고아로 잘못 보지 않는다.

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
        skipped = 0

        purged = 0
        for att in Attachment.objects.filter(status=Attachment.Status.DELETE_PENDING):
            result = attachments.purge(att)
            purged += result == attachments.PURGED
            skipped += result == attachments.SKIPPED
            failed += result == attachments.FAILED

        stale = 0
        for att in Attachment.objects.filter(status=Attachment.Status.PENDING, created_at__lt=cutoff):
            result = attachments.purge(att, statuses=(Attachment.Status.PENDING,), created_before=cutoff)
            stale += result == attachments.PURGED
            skipped += result == attachments.SKIPPED
            failed += result == attachments.FAILED

        finished = 0
        for post in Post.objects.filter(status=Post.Status.DELETING):
            if services.finish_post_deletion(post):
                finished += 1
            else:
                failed += 1

        temp_removed = 0
        limit = time.time() - pending_minutes * 60
        incoming = attachments.incoming_dir()
        if incoming.is_dir():
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
            known = self._known_keys()
            for path in root.iterdir():
                if path.name == attachments.INCOMING_DIRNAME or not path.is_file():
                    continue
                if path.name not in known:
                    orphans.append(path)
        orphan_removed = 0
        orphan_kept = 0
        for path in orphans:
            self.stdout.write(f"orphan {self._safe_name(path.name)}")
            if delete_orphans:
                if not self._still_orphan(path, limit):
                    orphan_kept += 1
                    continue
                try:
                    path.unlink()
                    orphan_removed += 1
                except FileNotFoundError:
                    pass
                except OSError:
                    failed += 1

        self.stdout.write(
            f"delete_pending_purged={purged} stale_pending_purged={stale} posts_finished={finished} "
            f"temp_removed={temp_removed} orphans={len(orphans)} orphans_removed={orphan_removed} "
            f"orphans_kept={orphan_kept} skipped={skipped} failed={failed}"
        )
        if failed:
            raise CommandError(f"정리하지 못한 항목 {failed}개. 잠시 뒤 다시 실행하세요.")

    @staticmethod
    def _known_keys():
        return {str(k) for k in Attachment.objects.values_list("storage_key", flat=True)}

    @staticmethod
    def _still_orphan(path, limit):
        """지우기 직전 재확인: 기준 시간보다 오래됐고, 같은 저장키의 행이 지금도 없을 때만 고아."""
        try:
            if path.stat().st_mtime >= limit:
                return False  # 막 생긴 파일(업로드 중일 수 있음)
        except FileNotFoundError:
            return False
        try:
            key = uuid.UUID(path.name)
        except ValueError:
            return True  # 저장키 모양이 아니면 어떤 행과도 맞을 수 없다
        return not Attachment.objects.filter(storage_key=key).exists()

    @staticmethod
    def _safe_name(name):
        """UUID 모양이면 그대로, 아니면 이름을 출력하지 않는다."""
        try:
            return str(uuid.UUID(name))
        except ValueError:
            return "(non-uuid file)"
