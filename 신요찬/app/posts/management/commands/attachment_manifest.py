"""첨부 백업 manifest와 복원 대조 (명세 3.4 "백업", UP-10, DB-04).

출력: ACTIVE 첨부마다 한 줄 `post_id,attachment_id,storage_key,size_bytes,sha256` (CSV, 머리줄 포함).
원본 파일 이름은 쓰지 않는다(공개 증거에 민감한 원본 이름을 올리지 않음).

--verify: 각 행의 파일이 HAVEN_UPLOAD_DIR에 있고 크기·sha256이 DB와 같은지 확인한다.
          하나라도 없거나 다르면 실패(종료 코드 1). 복원 뒤 대조에 쓴다.
"""
import csv
import hashlib

from django.core.management.base import BaseCommand, CommandError

from posts import attachments
from posts.models import Attachment


class Command(BaseCommand):
    help = "ACTIVE 첨부 manifest를 출력하고(--verify면) 파일 크기·sha256을 대조한다."

    def add_arguments(self, parser):
        parser.add_argument("--verify", action="store_true")

    def handle(self, *args, verify, **options):
        writer = csv.writer(self.stdout, lineterminator="\n")
        writer.writerow(["post_id", "attachment_id", "storage_key", "size_bytes", "sha256"])
        rows = Attachment.objects.filter(status=Attachment.Status.ACTIVE).order_by("post_id", "id")
        problems = 0
        for att in rows:
            writer.writerow([att.post_id, att.pk, att.storage_key, att.size_bytes, att.sha256])
            if verify:
                problem = self._check(att)
                if problem:
                    problems += 1
                    self.stderr.write(f"MISMATCH attachment_id={att.pk} {problem}")
        if verify:
            if problems:
                raise CommandError(f"첨부 {problems}개가 없거나 DB와 다릅니다. 복원 완료로 처리하지 마세요.")
            self.stderr.write(f"OK  {rows.count()} attachments match")

    @staticmethod
    def _check(att):
        path = attachments.final_path(att.storage_key)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return "missing"
        if len(data) != att.size_bytes:
            return "size"
        if hashlib.sha256(data).hexdigest() != att.sha256:
            return "sha256"
        return None
