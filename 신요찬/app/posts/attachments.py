"""첨부 업로드·다운로드·정리 (명세 3.4, 앱계약.md 3회차).

흐름 (업로드):
  1. view: CSRF(미들웨어) → 로그인 → 소유한 ACTIVE 글(없으면 404)
  2. 파일 이름 검사(400) → 실제 크기 검사(413) → 내용 형식 검사(400)  ← DB를 건드리기 전
  3. reserve(): 소유자 행 → 글 행 순서로 잠그고 개수·계정 용량 검사(400) 후 PENDING 예약
  4. store(): 같은 파일시스템의 staging 파일에 쓰고 fsync → UUID 영구 경로로 link(덮어쓰기 불가)
  5. activate(): 글이 여전히 ACTIVE·소유인지 다시 확인하고 ACTIVE로 전환
  실패하면 ACTIVE로 만들지 않고 파일·예약을 정리한다. 정리도 실패하면 PENDING이 남아
  cleanup_attachments 명령이 다시 시도한다.

DB와 파일시스템은 하나의 transaction이 아니다. 그래서 "접근 차단(DB 상태)"을 먼저 하고
"파일 정리"를 나중에 하며, 정리가 끝나야 용량을 돌려준다.
"""
import hashlib
import io
import logging
import os
import unicodedata
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum

from .models import Attachment, Post

logger = logging.getLogger("haven.attachments")

MAX_FILE_BYTES = 2_097_152  # 2 MiB
MAX_FILES_PER_POST = 3
MAX_BYTES_PER_OWNER = 10_485_760  # 10 MiB
UPLOAD_BODY_LIMIT = 2_162_688  # 2 MiB + 64 KiB (multipart framing·필드 여유)
COUNTED_STATUSES = (Attachment.Status.PENDING, Attachment.Status.ACTIVE, Attachment.Status.DELETE_PENDING)
INCOMING_DIRNAME = ".incoming"  # Django 임시 업로드와 staging. 최종 위치와 같은 파일시스템

TXT_CONTENT_TYPE = "text/plain; charset=utf-8"
PDF_CONTENT_TYPE = "application/pdf"
# 텍스트로 허용하는 제어문자: 탭, 줄바꿈, 캐리지 리턴
_TXT_ALLOWED_CONTROLS = {"\t", "\n", "\r"}


class AttachmentRejected(Exception):
    """사용자 입력 문제. status는 400(형식·개수·용량) 또는 413(파일 크기)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------- 위치

def upload_root():
    return Path(settings.HAVEN_UPLOAD_DIR)


def incoming_dir():
    return upload_root() / INCOMING_DIRNAME


def ensure_dirs():
    """업로드 폴더와 임시 폴더를 만든다(이미 있으면 그대로). 권한은 소유자만."""
    for path in (upload_root(), incoming_dir()):
        path.mkdir(mode=0o700, parents=True, exist_ok=True)


def final_path(storage_key):
    """저장 위치는 서버가 만든 UUID로만 정한다. 사용자 파일 이름은 경로에 쓰지 않는다."""
    return upload_root() / str(storage_key)


# ---------------------------------------------------------------- 검사

def validate_filename(name):
    """표시용 원본 이름 검사. 경로 구분자·NUL·제어문자·경로 이동은 400(명세 3.4)."""
    if not isinstance(name, str) or not name or len(name) > 255:
        raise AttachmentRejected("파일 이름을 확인해 주세요.")
    if name != name.strip() or name in (".", "..") or ".." in name:
        raise AttachmentRejected("파일 이름을 확인해 주세요.")
    if any(ch in name for ch in ("/", "\\")):
        raise AttachmentRejected("파일 이름을 확인해 주세요.")
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in name):
        raise AttachmentRejected("파일 이름을 확인해 주세요.")
    return name


def _extension(name):
    _, dot, ext = name.rpartition(".")
    return ext.lower() if dot else ""


def _check_txt(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise AttachmentRejected("UTF-8 텍스트 파일만 올릴 수 있습니다.")
    # NUL·ESC 등 C0/C1 제어문자와 DEL을 거부한다(탭·줄바꿈만 허용).
    if any(unicodedata.category(ch) == "Cc" and ch not in _TXT_ALLOWED_CONTROLS for ch in text):
        raise AttachmentRejected("텍스트 파일에 허용하지 않는 제어문자가 있습니다.")
    return TXT_CONTENT_TYPE


def _check_pdf(data):
    if not data.startswith(b"%PDF-"):
        raise AttachmentRejected("PDF 파일이 아닙니다.")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise AttachmentRejected("암호화된 PDF는 올릴 수 없습니다.")
        if len(reader.pages) < 1:
            raise AttachmentRejected("PDF 파일을 확인해 주세요.")
    except AttachmentRejected:
        raise
    except Exception:
        # 파서가 구조를 읽지 못하면 PDF로 인정하지 않는다. 내용·예외 메시지는 기록하지 않는다.
        raise AttachmentRejected("PDF 파일을 확인해 주세요.")
    return PDF_CONTENT_TYPE


def detect_content_type(name, data):
    """확장자와 실제 내용이 모두 맞아야 통과. 클라이언트가 보낸 MIME은 쓰지 않는다."""
    if not data:
        raise AttachmentRejected("빈 파일은 올릴 수 없습니다.")
    ext = _extension(name)
    if ext == "txt":
        if data.startswith(b"%PDF-"):
            raise AttachmentRejected("파일 확장자와 내용이 다릅니다.")
        return _check_txt(data)
    if ext == "pdf":
        return _check_pdf(data)
    raise AttachmentRejected("TXT 또는 PDF 파일만 올릴 수 있습니다.")


def read_upload(uploaded):
    """실제로 받은 bytes로 크기를 확인한다(Content-Length나 브라우저 값을 믿지 않음)."""
    data = bytearray()
    for chunk in uploaded.chunks():
        data.extend(chunk)
        if len(data) > MAX_FILE_BYTES:
            raise AttachmentRejected("파일은 2 MiB까지 올릴 수 있습니다.", status=413)
    return bytes(data)


# ---------------------------------------------------------------- 예약·저장·확정

def after_quota_check():
    """동시성 시험에서 검사와 예약 사이에 지연을 넣기 위한 자리(평소에는 아무것도 하지 않음)."""


@transaction.atomic
def reserve(owner, post_id, name, size):
    """소유자 행 → 글 행 순서로 잠그고 개수·용량을 검사한 뒤 PENDING으로 예약한다."""
    get_user_model().objects.select_for_update().get(pk=owner.pk)
    post = (
        Post.objects.select_for_update()
        .filter(pk=post_id, owner=owner, status=Post.Status.ACTIVE)
        .first()
    )
    if post is None:
        return None
    counted = Attachment.objects.filter(status__in=COUNTED_STATUSES)
    if counted.filter(post=post).count() >= MAX_FILES_PER_POST:
        raise AttachmentRejected("글 하나에 첨부는 3개까지입니다.")
    used = counted.filter(post__owner=owner).aggregate(total=Sum("size_bytes"))["total"] or 0
    if used + size > MAX_BYTES_PER_OWNER:
        raise AttachmentRejected("계정 첨부 용량(10 MiB)을 넘습니다.")
    after_quota_check()
    return Attachment.objects.create(post=post, original_name=name, size_bytes=size)


def store(attachment, data):
    """staging에 쓰고 fsync한 뒤 UUID 경로로 link한다. 이미 있는 저장키는 덮어쓰지 않는다."""
    ensure_dirs()
    staging = incoming_dir() / f"{attachment.storage_key}.part"
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(staging, final_path(attachment.storage_key))  # 대상이 있으면 FileExistsError
    finally:
        _unlink_quietly(staging)


@transaction.atomic
def activate(attachment, owner, content_type, sha256):
    """최종 전환 직전에도 글이 ACTIVE이고 소유자 것인지 다시 확인한다."""
    post = (
        Post.objects.select_for_update()
        .filter(pk=attachment.post_id, owner=owner, status=Post.Status.ACTIVE)
        .first()
    )
    if post is None:
        return False
    updated = Attachment.objects.filter(pk=attachment.pk, status=Attachment.Status.PENDING).update(
        status=Attachment.Status.ACTIVE, content_type=content_type, sha256=sha256
    )
    return updated == 1


def upload(owner, post_id, uploaded):
    """업로드 전체. 성공하면 Attachment, 글이 없거나 권한이 없으면 None. 입력 문제는 AttachmentRejected."""
    name = validate_filename(uploaded.name)
    data = read_upload(uploaded)
    content_type = detect_content_type(name, data)
    sha256 = hashlib.sha256(data).hexdigest()

    attachment = reserve(owner, post_id, name, len(data))
    if attachment is None:
        return None
    try:
        store(attachment, data)
        if not activate(attachment, owner, content_type, sha256):
            discard(attachment)
            return None
    except BaseException:
        discard(attachment)
        raise
    attachment.refresh_from_db()
    return attachment


def discard(attachment):
    """실패한 예약 정리: 파일을 먼저 지우고 예약 행을 지운다. 실패하면 PENDING이 남아 재시도 대상."""
    try:
        _unlink(final_path(attachment.storage_key))
        _unlink_quietly(incoming_dir() / f"{attachment.storage_key}.part")
        Attachment.objects.filter(pk=attachment.pk, status=Attachment.Status.PENDING).delete()
    except Exception:
        logger.warning("attachment cleanup deferred id=%s", attachment.pk)


# ---------------------------------------------------------------- 삭제·정리

def mark_delete_pending(post_id, attachment_id, owner):
    """소유자의 ACTIVE 첨부를 DELETE_PENDING으로. 이 시점부터 다운로드가 막힌다."""
    with transaction.atomic():
        post = (
            Post.objects.select_for_update()
            .filter(pk=post_id, owner=owner, status=Post.Status.ACTIVE)
            .first()
        )
        if post is None:
            return None
        attachment = (
            Attachment.objects.select_for_update()
            .filter(pk=attachment_id, post=post, status=Attachment.Status.ACTIVE)
            .first()
        )
        if attachment is None:
            return None
        attachment.status = Attachment.Status.DELETE_PENDING
        attachment.save(update_fields=["status"])
    return attachment


def purge(attachment):
    """DELETE_PENDING(또는 오래된 PENDING) 첨부의 파일을 지우고 메타데이터를 지운다.

    파일 삭제가 실패하면 행을 남겨 둔다(디스크에 파일이 있는 동안 용량을 돌려주지 않음).
    """
    try:
        _unlink(final_path(attachment.storage_key))
    except OSError:
        logger.warning("attachment file removal failed id=%s", attachment.pk)
        return False
    _unlink_quietly(incoming_dir() / f"{attachment.storage_key}.part")
    Attachment.objects.filter(pk=attachment.pk).delete()
    return True


def _unlink(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _unlink_quietly(path):
    try:
        _unlink(path)
    except OSError:
        pass


def open_for_download(attachment):
    """ACTIVE 첨부 파일을 연다. DB는 ACTIVE인데 파일이 없으면 예외(일반 오류로 응답)."""
    path = final_path(attachment.storage_key)
    try:
        return open(path, "rb")
    except FileNotFoundError:
        logger.error("attachment file missing id=%s", attachment.pk)
        raise
