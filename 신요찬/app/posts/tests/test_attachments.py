"""3회차 첨부 (명세 3.4, 8.1.1 UP-01~09, SH-03).

A = 소유자, B = 공유 대상, C = 비대상, operator = 운영 관리자.
업로드 폴더는 시험마다 새 임시 폴더(HAVEN_UPLOAD_DIR)를 쓴다.
위험한 파일 이름은 Django 시험 클라이언트가 basename만 보내므로 multipart를 직접 만든다.
"""
import hashlib
import io
import os
import shutil
import stat
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings

from posts import attachments
from posts.models import Attachment, Post, PostShare

BOUNDARY = "----HavenTestBoundary7c1f"


def pdf_bytes(encrypt=False, owner_only=False):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if encrypt:
        writer.encrypt("virtual-pass", algorithm="RC4-128")
    if owner_only:
        # 열람 비밀번호는 비우고 권한 비밀번호만 건 PDF. 파서가 그냥 열 수 있어 암호화 검사가 따로 필요하다.
        writer.encrypt(user_password="", owner_password="virtual-owner", algorithm="RC4-128")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def multipart(files, fields=None):
    """files: [(field, filename, data, content_type)]. 반환: (body bytes, content_type)."""
    parts = []
    for name, value in (fields or {}).items():
        parts.append(
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode() + value.encode() + b"\r\n"
        )
    for field, filename, data, ctype in files:
        head = (
            f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        )
        parts.append(head.encode("utf-8") + data + b"\r\n")
    parts.append(f"--{BOUNDARY}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={BOUNDARY}"


class UploadDirMixin:
    def setUp(self):
        super().setUp()
        self.upload_dir = Path(tempfile.mkdtemp(prefix="haven-up-"))
        override = override_settings(HAVEN_UPLOAD_DIR=self.upload_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.upload_dir, True)

    def stored_files(self):
        return sorted(p.name for p in self.upload_dir.iterdir() if p.is_file())

    def incoming_files(self):
        inc = self.upload_dir / attachments.INCOMING_DIRNAME
        return sorted(p.name for p in inc.iterdir()) if inc.is_dir() else []

    def send(self, client, post, files, fields=None, **extra):
        body, ctype = multipart(files, fields)
        return client.generic("POST", f"/posts/{post.pk}/attachments/", body, content_type=ctype, **extra)

    def upload(self, client, post, name, data, ctype="text/plain", **kw):
        return self.send(client, post, [("attachment", name, data, ctype)], **kw)

    def assert_nothing_stored(self):
        self.assertFalse(Attachment.objects.exists())
        self.assertEqual(self.stored_files(), [])
        self.assertEqual(self.incoming_files(), [])


class AttachmentBase(UploadDirMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = User.objects.create_user("member_a")
        cls.b = User.objects.create_user("member_b")
        cls.c = User.objects.create_user("member_c")
        cls.op = User.objects.create_user("operator")
        cls.op.user_permissions.add(*Permission.objects.filter(content_type__app_label="adminpanel"))
        cls.p1 = Post.objects.create(owner=cls.a, title="A의 기록", body="본문")
        cls.p2 = Post.objects.create(owner=cls.a, title="A의 다른 기록", body="본문")
        PostShare.objects.create(post=cls.p1, recipient=cls.b)

    def as_user(self, user):
        client = Client()
        client.force_login(user)
        return client

    def make_active(self, post=None, name="note.txt", data=b"hello"):
        res = self.upload(self.as_user(self.a), post or self.p1, name, data)
        self.assertEqual(res.status_code, 302, res.content[:300])
        return Attachment.objects.latest("id")


class UploadDownloadTests(AttachmentBase):
    def test_up01_owner_uploads_txt_and_pdf(self):
        client = self.as_user(self.a)
        txt = "한국어 첨부\n둘째 줄\t탭".encode()
        pdf = pdf_bytes()
        for name, data, ctype in (("메모.txt", txt, "text/plain; charset=utf-8"), ("report.pdf", pdf, "application/pdf")):
            with self.subTest(name=name):
                res = self.upload(client, self.p1, name, data)
                self.assertRedirects(res, f"/posts/{self.p1.pk}/", fetch_redirect_response=False)
                att = Attachment.objects.latest("id")
                self.assertEqual(
                    (att.status, att.original_name, att.size_bytes, att.content_type, att.sha256),
                    ("ACTIVE", name, len(data), ctype, hashlib.sha256(data).hexdigest()),
                )
                path = self.upload_dir / str(att.storage_key)
                self.assertEqual(path.read_bytes(), data)
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(self.incoming_files(), [])

    def test_up01_owner_and_recipient_download_with_safe_headers(self):
        data = "보고서 본문".encode()
        att = self.make_active(name="보고서.txt", data=data)
        url = f"/posts/{self.p1.pk}/attachments/{att.pk}/download/"
        for user in (self.a, self.b):
            with self.subTest(user=user.username):
                res = self.as_user(user).get(url)
                self.assertEqual(res.status_code, 200)
                self.assertEqual(b"".join(res.streaming_content), data)
                self.assertEqual(res["Content-Type"], "text/plain; charset=utf-8")
                self.assertTrue(res["Content-Disposition"].startswith("attachment;"))
                self.assertIn("filename*=utf-8''%EB%B3%B4%EA%B3%A0%EC%84%9C.txt", res["Content-Disposition"])
                self.assertEqual(res["X-Content-Type-Options"], "nosniff")
                self.assertEqual(res["Cache-Control"], "private, no-store")

    def test_detail_context_lists_active_attachments_and_owner_only_form(self):
        att = self.make_active()
        Attachment.objects.create(post=self.p1, original_name="pending.txt", size_bytes=1)
        res = self.as_user(self.a).get(f"/posts/{self.p1.pk}/")
        self.assertEqual([x.pk for x in res.context["attachments"]], [att.pk])
        self.assertIsNotNone(res.context["attachment_form"])
        self.assertEqual(res.context["attachment_limits"]["max_files_per_post"], 3)
        res = self.as_user(self.b).get(f"/posts/{self.p1.pk}/")
        self.assertEqual([x.pk for x in res.context["attachments"]], [att.pk])
        self.assertIsNone(res.context["attachment_form"])
        self.assertNotContains(res, str(att.storage_key))

    def test_extension_case_is_normalized_and_client_mime_ignored(self):
        client = self.as_user(self.a)
        self.assertEqual(self.upload(client, self.p1, "NOTE.TXT", b"ok", ctype="application/pdf").status_code, 302)
        self.assertEqual(Attachment.objects.latest("id").content_type, "text/plain; charset=utf-8")
        self.assertEqual(self.upload(client, self.p1, "doc.Pdf", pdf_bytes(), ctype="text/plain").status_code, 302)
        self.assertEqual(Attachment.objects.latest("id").content_type, "application/pdf")


class ContentRejectionTests(AttachmentBase):
    def test_up02_wrong_or_unsafe_content_is_400(self):
        cases = [
            ("bad.txt", b"\xff\xfe\xfa not utf8"),
            ("nul.txt", b"abc\x00def"),
            ("esc.txt", b"abc\x1b[31m"),
            ("pdf_in_txt.txt", pdf_bytes()),
            ("text_in_pdf.pdf", b"just text"),
            ("broken.pdf", b"%PDF-1.4\n1 0 obj << >> garbage"),
            ("locked.pdf", pdf_bytes(encrypt=True)),
            ("owner_locked.pdf", pdf_bytes(owner_only=True)),
            ("empty.txt", b""),
            ("harmless.php", b"Haven harmless TXT fixture"),
            ("page.html", b"<html></html>"),
            ("image.svg", b"<svg></svg>"),
            ("tool.exe", b"MZ\x90\x00"),
            ("archive.zip", b"PK\x03\x04"),
            ("noext", b"plain"),
            ("note.txt.php", b"plain"),
        ]
        client = self.as_user(self.a)
        for name, data in cases:
            with self.subTest(name=name):
                res = self.upload(client, self.p1, name, data)
                self.assertEqual(res.status_code, 400)
                self.assertTemplateUsed(res, "posts/detail.html")
                self.assertTrue(res.context["attachment_form"].errors)
        self.assert_nothing_stored()

    def test_encrypted_pdf_is_rejected_as_encrypted(self):
        client = self.as_user(self.a)
        for name, data in (("locked.pdf", pdf_bytes(encrypt=True)), ("owner_locked.pdf", pdf_bytes(owner_only=True))):
            with self.subTest(name=name):
                res = self.upload(client, self.p1, name, data)
                self.assertEqual(res.status_code, 400)
                self.assertEqual(res.context["attachment_form"].errors["attachment"], ["암호화된 PDF는 올릴 수 없습니다."])
        self.assert_nothing_stored()

    def test_sec32_fixture_php_name_with_php_mime_is_400(self):
        res = self.upload(self.as_user(self.a), self.p1, "harmless.php", b"Haven harmless TXT fixture\n", "application/x-php")
        self.assertEqual(res.status_code, 400)
        self.assert_nothing_stored()

    def test_up03_unsafe_file_names_are_400(self):
        names = [
            "../escape.txt",
            "..\\escape.txt",
            "dir/inner.txt",
            "C:\\temp\\x.txt",
            "a\x00b.txt",
            "a\x07b.txt",
            "\u202etxt.exe",  # 오른쪽→왼쪽 표시 문자로 확장자 위장
            "a&lt;b.txt",  # HTML 엔티티(Django가 풀어 버림)
            "a..b.txt",
            " lead.txt",
            "x" * 252 + ".txt",
            "..",
        ]
        client = self.as_user(self.a)
        for name in names:
            with self.subTest(name=repr(name)):
                res = self.upload(client, self.p1, name, b"plain")
                self.assertEqual(res.status_code, 400)
        self.assert_nothing_stored()

    def test_no_file_and_multiple_files_are_400(self):
        client = self.as_user(self.a)
        self.assertEqual(self.send(client, self.p1, [], fields={"note": "x"}).status_code, 400)
        res = self.send(
            client,
            self.p1,
            [("attachment", "one.txt", b"1", "text/plain"), ("attachment", "two.txt", b"2", "text/plain")],
        )
        self.assertEqual(res.status_code, 400)
        self.assert_nothing_stored()


class SizeAndQuotaTests(AttachmentBase):
    def test_up04_file_size_boundary(self):
        client = self.as_user(self.a)
        self.assertEqual(self.upload(client, self.p1, "max.txt", b"a" * 2_097_152).status_code, 302)
        res = self.upload(client, self.p2, "over.txt", b"a" * 2_097_153)
        self.assertEqual(res.status_code, 413)
        self.assertEqual(Attachment.objects.count(), 1)
        self.assertEqual(len(self.stored_files()), 1)
        self.assertEqual(self.incoming_files(), [])

    def _sized_request(self, total, token=None):
        """파일은 작게, 나머지는 무시되는 필드로 채워 전체 body를 정확히 total바이트로 만든다."""
        files = [("attachment", "small.txt", b"ok", "text/plain")]
        fields = {"csrfmiddlewaretoken": token} if token else {}
        base, _ = multipart(files, {**fields, "pad": ""})
        body, ctype = multipart(files, {**fields, "pad": "p" * (total - len(base))})
        self.assertEqual(len(body), total)
        return body, ctype

    def test_up04_request_body_boundary_and_413_before_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.a)
        token = str(client.get(f"/posts/{self.p1.pk}/").context["csrf_token"])
        url = f"/posts/{self.p1.pk}/attachments/"
        body, ctype = self._sized_request(2_162_688, token)
        self.assertEqual(client.generic("POST", url, body, content_type=ctype).status_code, 302)
        body, ctype = self._sized_request(2_162_689, token)
        res = client.generic("POST", url, body, content_type=ctype)
        self.assertEqual(res.status_code, 413)
        self.assertTemplateUsed(res, "errors/413.html")
        body, ctype = self._sized_request(2_162_689)  # 토큰 없음: 결정 9에 따라 413이 먼저
        self.assertEqual(client.generic("POST", url, body, content_type=ctype).status_code, 413)
        self.assertEqual(Attachment.objects.count(), 1)
        self.assertEqual(self.incoming_files(), [])

    def test_up05_three_per_post_including_pending_and_delete_pending(self):
        client = self.as_user(self.a)
        for i in range(3):
            self.assertEqual(self.upload(client, self.p1, f"f{i}.txt", b"x").status_code, 302)
        self.assertEqual(self.upload(client, self.p1, "f3.txt", b"x").status_code, 400)
        Attachment.objects.filter(post=self.p1).update(status=Attachment.Status.DELETE_PENDING)
        self.assertEqual(self.upload(client, self.p1, "f4.txt", b"x").status_code, 400)
        Attachment.objects.filter(post=self.p1).update(status=Attachment.Status.PENDING)
        self.assertEqual(self.upload(client, self.p1, "f5.txt", b"x").status_code, 400)
        self.assertEqual(Attachment.objects.filter(post=self.p1).count(), 3)

    def test_up05_owner_quota_10mib_counts_every_status(self):
        # 합계 10,485,750바이트(한도 - 10)를 세 상태에 나눠 채운다. 파일 하나는 2 MiB 이하.
        mib2 = 2_097_152
        sizes = [
            (Attachment.Status.ACTIVE, mib2), (Attachment.Status.DELETE_PENDING, mib2),
            (Attachment.Status.PENDING, mib2), (Attachment.Status.ACTIVE, mib2),
            (Attachment.Status.ACTIVE, 10_485_760 - 10 - 4 * mib2),
        ]
        for status, size in sizes:
            post = Post.objects.create(owner=self.a, title="채움", body="b")
            Attachment.objects.create(post=post, original_name="fill.txt", size_bytes=size, status=status,
                                      content_type="text/plain; charset=utf-8", sha256="0" * 64)
        client = self.as_user(self.a)
        self.assertEqual(self.upload(client, self.p1, "over.txt", b"x" * 11).status_code, 400)
        self.assertEqual(self.upload(client, self.p1, "fits.txt", b"x" * 10).status_code, 302)
        self.assertEqual(self.upload(client, self.p2, "one_more.txt", b"x").status_code, 400)


class PrecheckOrderTests(AttachmentBase):
    """어차피 거절될 업로드는 내용 검사(PDF 분석) 전에 돌려보낸다(#62 부하 시험 발견)."""

    PDF = b"%PDF-1.4\n" + b"0" * 100

    def test_full_post_rejected_before_content_check(self):
        for i in range(3):
            self.make_active(name=f"f{i}.txt")
        with mock.patch.object(attachments, "detect_content_type", wraps=attachments.detect_content_type) as spy:
            res = self.upload(self.as_user(self.a), self.p1, "doc.pdf", self.PDF)
        self.assertEqual(res.status_code, 400)
        self.assertContains(res, "글 하나에 첨부는 3개까지입니다.", status_code=400)
        spy.assert_not_called()
        self.assertEqual(Attachment.objects.filter(post=self.p1).count(), 3)

    def test_owner_quota_rejected_before_content_check(self):
        for _ in range(5):  # 2 MiB x 5 = 10 MiB, 남은 용량 0
            post = Post.objects.create(owner=self.a, title="채움", body="b")
            Attachment.objects.create(post=post, original_name="fill.txt", size_bytes=2_097_152,
                                      status=Attachment.Status.ACTIVE,
                                      content_type="text/plain; charset=utf-8", sha256="0" * 64)
        with mock.patch.object(attachments, "detect_content_type", wraps=attachments.detect_content_type) as spy:
            res = self.upload(self.as_user(self.a), self.p1, "doc.pdf", self.PDF)
        self.assertContains(res, "계정 첨부 용량(10 MiB)을 넘습니다.", status_code=400)
        spy.assert_not_called()

    def test_content_still_checked_when_limits_ok(self):
        with mock.patch.object(attachments, "detect_content_type", wraps=attachments.detect_content_type) as spy:
            res = self.upload(self.as_user(self.a), self.p1, "doc.pdf", self.PDF)
        self.assertContains(res, "PDF 파일을 확인해 주세요.", status_code=400)
        spy.assert_called_once()
        self.assertEqual(Attachment.objects.count(), 0)

    def test_precheck_none_for_missing_or_foreign_post(self):
        self.assertFalse(attachments.precheck(self.b, self.p1.pk, 1))
        self.assertFalse(attachments.precheck(self.a, 999_999, 1))
        self.assertTrue(attachments.precheck(self.a, self.p1.pk, 1))


class PermissionTests(AttachmentBase):
    def test_up06_recipient_and_others_cannot_change(self):
        att = self.make_active()
        upload_url = f"/posts/{self.p1.pk}/attachments/"
        delete_url = f"/posts/{self.p1.pk}/attachments/{att.pk}/delete/"
        for user in (self.b, self.c, self.op):
            with self.subTest(user=user.username):
                client = self.as_user(user)
                body, ctype = multipart([("attachment", "x.txt", b"x", "text/plain")])
                self.assertEqual(client.generic("POST", upload_url, body, content_type=ctype).status_code, 404)
                self.assertEqual(client.post(delete_url).status_code, 404)
        self.assertEqual(list(Attachment.objects.values_list("pk", "status")), [(att.pk, "ACTIVE")])
        self.assertEqual(self.stored_files(), [str(att.storage_key)])

    def test_up06_download_denied_for_non_recipients(self):
        att = self.make_active()
        url = f"/posts/{self.p1.pk}/attachments/{att.pk}/download/"
        for user in (self.c, self.op):
            with self.subTest(user=user.username):
                self.assertEqual(self.as_user(user).get(url).status_code, 404)
        self.assertRedirects(Client().get(url), f"/accounts/login/?next={url}", fetch_redirect_response=False)

    def test_anonymous_upload_redirects_and_stores_nothing(self):
        res = self.upload(Client(), self.p1, "x.txt", b"x")
        self.assertEqual(res.status_code, 302)
        self.assert_nothing_stored()

    def test_sh03_revoked_share_and_inactive_owner_block_download(self):
        att = self.make_active()
        url = f"/posts/{self.p1.pk}/attachments/{att.pk}/download/"
        client = self.as_user(self.b)
        self.assertEqual(client.get(url).status_code, 200)
        User.objects.filter(pk=self.a.pk).update(is_active=False)
        self.assertEqual(client.get(url).status_code, 404)
        User.objects.filter(pk=self.a.pk).update(is_active=True)
        PostShare.objects.filter(post=self.p1, recipient=self.b).delete()
        self.assertEqual(client.get(url).status_code, 404)

    def test_up03_other_posts_attachment_id_is_404(self):
        att = self.make_active(post=self.p1)
        client = self.as_user(self.a)
        self.assertEqual(client.get(f"/posts/{self.p2.pk}/attachments/{att.pk}/download/").status_code, 404)
        self.assertEqual(client.post(f"/posts/{self.p2.pk}/attachments/{att.pk}/delete/").status_code, 404)
        self.assertEqual(Attachment.objects.get(pk=att.pk).status, "ACTIVE")

    def test_up09_no_public_path_to_stored_files(self):
        att = self.make_active()
        client = self.as_user(self.a)
        for path in (f"/uploads/{att.storage_key}", f"/media/{att.storage_key}", f"/static/{att.storage_key}",
                     f"/posts/{self.p1.pk}/attachments/{att.storage_key}/download/"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)

    def test_pending_and_delete_pending_are_never_downloadable(self):
        att = self.make_active()
        url = f"/posts/{self.p1.pk}/attachments/{att.pk}/download/"
        for status in (Attachment.Status.PENDING, Attachment.Status.DELETE_PENDING):
            with self.subTest(status=status):
                Attachment.objects.filter(pk=att.pk).update(status=status)
                self.assertEqual(self.as_user(self.a).get(url).status_code, 404)
                self.assertEqual(self.as_user(self.b).get(url).status_code, 404)


class BrokenStream:
    """일정 바이트를 준 뒤 연결이 끊긴 것처럼 오류를 내는 요청 본문."""

    def __init__(self, data, fail_after):
        self.data = data
        self.pos = 0
        self.fail_after = fail_after

    def read(self, size=-1):
        if self.pos >= self.fail_after:
            raise ConnectionResetError("client went away")
        end = len(self.data) if size is None or size < 0 else self.pos + size
        end = min(end, self.fail_after)
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def readline(self, size=-1):
        return self.read(size)


class InterruptedUploadTests(AttachmentBase):
    """UP-13: 업로드 도중 끊긴 요청은 행·저장 파일·임시 파일을 남기지 않는다."""

    def test_connection_reset_mid_file_leaves_no_temp_file(self):
        body, ctype = multipart([("attachment", "big.txt", b"a" * 1_000_000, "text/plain")])
        cases = [
            ("로그인, CSRF 검사 없음", self.as_user(self.a)),
            ("로그인, CSRF 검사", self._csrf_client()),
            ("비로그인", Client()),
        ]
        for label, client in cases:
            client.raise_request_exception = False
            with self.subTest(case=label):
                client.generic(
                    "POST",
                    f"/posts/{self.p1.pk}/attachments/",
                    b"",
                    content_type=ctype,
                    CONTENT_TYPE=ctype,  # 본문 인자가 비면 시험 도구가 Content-Type을 붙이지 않는다
                    CONTENT_LENGTH=str(len(body)),
                    **{"wsgi.input": BrokenStream(body, fail_after=600_000)},
                )
                self.assert_nothing_stored()

    def test_temp_file_removed_while_request_still_alive(self):
        """실제 서버에서는 오류 기록이 요청 객체를 붙잡아 임시 파일이 메모리 정리 때까지 남았다.

        요청 객체를 붙잡은 채로, 파싱이 실패한 직후 임시 파일이 이미 지워졌는지 확인한다.
        """
        from django.http import UnreadablePostError
        from django.test import RequestFactory

        from posts.upload_handlers import use_strict_name_parser

        body, ctype = multipart([("attachment", "big.txt", b"a" * 1_000_000, "text/plain")])
        request = RequestFactory().generic(
            "POST",
            f"/posts/{self.p1.pk}/attachments/",
            b"",
            content_type=ctype,
            CONTENT_TYPE=ctype,  # 본문 인자가 비면 시험 도구가 Content-Type을 붙이지 않는다
            CONTENT_LENGTH=str(len(body)),
            **{"wsgi.input": BrokenStream(body, fail_after=600_000)},
        )
        use_strict_name_parser(request)
        with self.assertRaises(UnreadablePostError):
            request.POST  # noqa: B018  (CSRF 미들웨어가 하는 것과 같은 접근)
        self.assertEqual(self.incoming_files(), [])  # request가 아직 살아 있는 상태
        self.assertTrue(request.upload_handlers)  # 붙잡고 있음을 분명히

    def _csrf_client(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.a)
        return client


class CsrfTests(AttachmentBase):
    def test_upload_and_delete_need_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.a)
        self.assertEqual(self.upload(client, self.p1, "x.txt", b"x").status_code, 403)
        self.assert_nothing_stored()
        token = str(client.get(f"/posts/{self.p1.pk}/").context["csrf_token"])
        res = self.send(client, self.p1, [("attachment", "x.txt", b"x", "text/plain")], fields={"csrfmiddlewaretoken": token})
        self.assertEqual(res.status_code, 302)
        att = Attachment.objects.get()
        delete_url = f"/posts/{self.p1.pk}/attachments/{att.pk}/delete/"
        self.assertEqual(client.post(delete_url).status_code, 403)
        self.assertEqual(Attachment.objects.get().status, "ACTIVE")
        self.assertEqual(client.post(delete_url, {"csrfmiddlewaretoken": token}).status_code, 302)
        self.assertFalse(Attachment.objects.exists())


class FailureTests(AttachmentBase):
    def setUp(self):
        super().setUp()
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.a)

    def test_up07_storage_failure_leaves_nothing_active(self):
        with mock.patch.object(attachments, "store", side_effect=OSError("disk full")):
            res = self.upload(self.client, self.p1, "x.txt", b"x")
        self.assertEqual(res.status_code, 500)
        self.assert_nothing_stored()

    def test_up07_db_failure_on_activation_removes_file_and_reservation(self):
        with mock.patch.object(attachments, "activate", side_effect=DatabaseError("db down")):
            res = self.upload(self.client, self.p1, "x.txt", b"x")
        self.assertEqual(res.status_code, 500)
        self.assert_nothing_stored()

    def test_up07_post_deleted_while_uploading_is_not_activated(self):
        real_store = attachments.store

        def store_then_delete_post(att, data):
            real_store(att, data)
            Post.objects.filter(pk=att.post_id).update(status=Post.Status.DELETING)

        with mock.patch.object(attachments, "store", side_effect=store_then_delete_post):
            res = self.upload(self.client, self.p1, "x.txt", b"x")
        self.assertEqual(res.status_code, 404)
        self.assert_nothing_stored()

    def test_up07_cleanup_failure_keeps_pending_for_retry(self):
        with mock.patch.object(attachments, "activate", side_effect=DatabaseError("db down")), \
                mock.patch.object(attachments, "_unlink", side_effect=PermissionError("busy")):
            res = self.upload(self.client, self.p1, "x.txt", b"x")
        self.assertEqual(res.status_code, 500)
        att = Attachment.objects.get()
        self.assertEqual(att.status, "PENDING")  # 정리 목록에 남음, 다운로드 불가
        self.assertEqual(self.client.get(f"/posts/{self.p1.pk}/attachments/{att.pk}/download/").status_code, 404)
        Attachment.objects.filter(pk=att.pk).update(created_at=att.created_at - __import__("datetime").timedelta(hours=2))
        call_command("cleanup_attachments", stdout=io.StringIO())
        self.assert_nothing_stored()

    def test_active_row_with_missing_file_is_error_not_empty_success(self):
        att = self.make_active()
        (self.upload_dir / str(att.storage_key)).unlink()
        res = self.client.get(f"/posts/{self.p1.pk}/attachments/{att.pk}/download/")
        self.assertEqual(res.status_code, 500)

    def test_existing_storage_key_is_never_overwritten(self):
        att = self.make_active(data=b"original")
        clash = Attachment(pk=att.pk, post=self.p1, storage_key=att.storage_key, original_name="x.txt", size_bytes=1)
        with self.assertRaises(FileExistsError):
            attachments.store(clash, b"evil")
        self.assertEqual((self.upload_dir / str(att.storage_key)).read_bytes(), b"original")


class DeletionTests(AttachmentBase):
    def test_up08_owner_deletes_attachment_and_quota_returns(self):
        client = self.as_user(self.a)
        for i in range(3):
            self.upload(client, self.p1, f"f{i}.txt", b"x")
        att = Attachment.objects.first()
        res = client.post(f"/posts/{self.p1.pk}/attachments/{att.pk}/delete/")
        self.assertRedirects(res, f"/posts/{self.p1.pk}/", fetch_redirect_response=False)
        self.assertFalse(Attachment.objects.filter(pk=att.pk).exists())
        self.assertNotIn(str(att.storage_key), self.stored_files())
        self.assertEqual(client.get(f"/posts/{self.p1.pk}/attachments/{att.pk}/download/").status_code, 404)
        self.assertEqual(self.upload(client, self.p1, "again.txt", b"x").status_code, 302)

    def test_up08_file_removal_failure_blocks_download_but_keeps_quota(self):
        att = self.make_active()
        client = self.as_user(self.a)
        with mock.patch.object(attachments, "_unlink", side_effect=PermissionError("busy")):
            self.assertEqual(client.post(f"/posts/{self.p1.pk}/attachments/{att.pk}/delete/").status_code, 302)
        att.refresh_from_db()
        self.assertEqual(att.status, "DELETE_PENDING")
        self.assertEqual(self.as_user(self.b).get(f"/posts/{self.p1.pk}/attachments/{att.pk}/download/").status_code, 404)
        self.assertIn(str(att.storage_key), self.stored_files())
        for i in range(2):
            self.upload(client, self.p1, f"n{i}.txt", b"x")
        self.assertEqual(self.upload(client, self.p1, "fourth.txt", b"x").status_code, 400)  # 정리 전에는 개수에 포함
        call_command("cleanup_attachments", stdout=io.StringIO())
        self.assertFalse(Attachment.objects.filter(pk=att.pk).exists())
        self.assertNotIn(str(att.storage_key), self.stored_files())

    def test_up08_post_delete_removes_shares_files_and_post(self):
        att = self.make_active()
        res = self.as_user(self.a).post(f"/posts/{self.p1.pk}/delete/")
        self.assertRedirects(res, "/posts/", fetch_redirect_response=False)
        self.assertFalse(Post.objects.filter(pk=self.p1.pk).exists())
        self.assertFalse(PostShare.objects.exists())
        self.assertFalse(Attachment.objects.exists())
        self.assertNotIn(str(att.storage_key), self.stored_files())

    def test_up08_post_delete_cleanup_failure_hides_post_until_retry(self):
        att = self.make_active()
        with mock.patch.object(attachments, "_unlink", side_effect=PermissionError("busy")):
            res = self.as_user(self.a).post(f"/posts/{self.p1.pk}/delete/")
        self.assertEqual(res.status_code, 302)
        post = Post.objects.get(pk=self.p1.pk)
        self.assertEqual(post.status, "DELETING")
        self.assertEqual(Attachment.objects.get().status, "DELETE_PENDING")
        self.assertFalse(PostShare.objects.exists())
        for user, path in ((self.a, f"/posts/{self.p1.pk}/"), (self.b, f"/posts/{self.p1.pk}/attachments/{att.pk}/download/")):
            self.assertEqual(self.as_user(user).get(path).status_code, 404)
        call_command("cleanup_attachments", stdout=io.StringIO())
        self.assertFalse(Post.objects.filter(pk=self.p1.pk).exists())
        self.assertEqual(self.stored_files(), [])


class CommandTests(AttachmentBase):
    def test_cleanup_handles_stale_pending_temp_and_orphans(self):
        keep = self.make_active()
        stale = Attachment.objects.create(post=self.p1, original_name="s.txt", size_bytes=1)
        fresh = Attachment.objects.create(post=self.p1, original_name="f.txt", size_bytes=1)
        (self.upload_dir / str(stale.storage_key)).write_bytes(b"s")
        Attachment.objects.filter(pk=stale.pk).update(created_at=stale.created_at - __import__("datetime").timedelta(hours=2))
        inc = self.upload_dir / attachments.INCOMING_DIRNAME
        old_tmp = inc / "upload-old.tmp"
        old_tmp.write_bytes(b"t")
        os.utime(old_tmp, (time.time() - 7200, time.time() - 7200))
        orphan = self.upload_dir / "11111111-1111-1111-1111-111111111111"
        orphan.write_bytes(b"o")
        out = io.StringIO()
        call_command("cleanup_attachments", stdout=out)
        self.assertEqual(sorted(Attachment.objects.values_list("pk", flat=True)), sorted([keep.pk, fresh.pk]))
        self.assertFalse(old_tmp.exists())
        self.assertTrue(orphan.exists())  # 기본은 목록만
        self.assertIn("orphan 11111111-1111-1111-1111-111111111111", out.getvalue())
        out = io.StringIO()
        call_command("cleanup_attachments", "--delete-orphans", stdout=out)
        self.assertTrue(orphan.exists())  # 막 생긴 파일은 업로드 중일 수 있어 지우지 않는다
        self.assertIn("orphans_kept=1", out.getvalue())
        os.utime(orphan, (time.time() - 7200, time.time() - 7200))
        call_command("cleanup_attachments", "--delete-orphans", stdout=io.StringIO())
        self.assertFalse(orphan.exists())
        self.assertTrue((self.upload_dir / str(keep.storage_key)).exists())

    def test_cleanup_reports_failure_with_nonzero_exit(self):
        att = self.make_active()
        Attachment.objects.filter(pk=att.pk).update(status=Attachment.Status.DELETE_PENDING)
        with mock.patch.object(attachments, "_unlink", side_effect=PermissionError("busy")), \
                self.assertRaises(CommandError):
            call_command("cleanup_attachments", stdout=io.StringIO())
        self.assertTrue(Attachment.objects.filter(pk=att.pk).exists())

    def test_manifest_lists_active_only_without_names_and_verifies(self):
        att = self.make_active(name="비밀 이름.txt", data=b"payload")
        Attachment.objects.create(post=self.p1, original_name="pending.txt", size_bytes=1)
        out, err = io.StringIO(), io.StringIO()
        call_command("attachment_manifest", "--verify", stdout=out, stderr=err)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(lines[0], "post_id,attachment_id,storage_key,size_bytes,sha256")
        self.assertEqual(lines[1:], [f"{self.p1.pk},{att.pk},{att.storage_key},7,{hashlib.sha256(b'payload').hexdigest()}"])
        self.assertNotIn("비밀", out.getvalue())
        (self.upload_dir / str(att.storage_key)).write_bytes(b"tampered")
        with self.assertRaises(CommandError):
            call_command("attachment_manifest", "--verify", stdout=io.StringIO(), stderr=io.StringIO())
        (self.upload_dir / str(att.storage_key)).unlink()
        with self.assertRaises(CommandError):
            call_command("attachment_manifest", "--verify", stdout=io.StringIO(), stderr=io.StringIO())


class CleanupRaceTests(AttachmentBase):
    """권혁민 #38 리뷰: 정리 명령이 목록을 읽은 뒤 그 사이에 바뀐 첨부·파일을 지우지 않는다."""

    def old_pending_with_file(self):
        att = Attachment.objects.create(post=self.p1, original_name="s.txt", size_bytes=1)
        Attachment.objects.filter(pk=att.pk).update(created_at=att.created_at - timedelta(hours=2))
        (self.upload_dir / str(att.storage_key)).write_bytes(b"s")
        att.refresh_from_db()
        return att

    def test_stale_pending_activated_after_listing_is_skipped(self):
        listed = self.old_pending_with_file()  # 정리 명령이 읽어 둔 옛 상태
        Attachment.objects.filter(pk=listed.pk).update(
            status=Attachment.Status.ACTIVE, content_type=attachments.TXT_CONTENT_TYPE, sha256="0" * 64)
        cutoff = listed.created_at + timedelta(minutes=1)
        result = attachments.purge(listed, statuses=(Attachment.Status.PENDING,), created_before=cutoff)
        self.assertEqual(result, attachments.SKIPPED)
        self.assertEqual(Attachment.objects.get(pk=listed.pk).status, Attachment.Status.ACTIVE)
        self.assertTrue((self.upload_dir / str(listed.storage_key)).exists())

    def test_pending_newer_than_cutoff_is_skipped(self):
        att = Attachment.objects.create(post=self.p1, original_name="n.txt", size_bytes=1)
        result = attachments.purge(att, statuses=(Attachment.Status.PENDING,), created_before=att.created_at)
        self.assertEqual(result, attachments.SKIPPED)
        self.assertTrue(Attachment.objects.filter(pk=att.pk).exists())

    def test_command_skips_attachment_activated_during_run(self):
        listed = self.old_pending_with_file()
        real_purge = attachments.purge

        def activate_then_purge(att, **kw):
            # 목록을 읽은 뒤, 지우기 직전에 업로드가 끝난 상황
            Attachment.objects.filter(pk=att.pk).update(
                status=Attachment.Status.ACTIVE, content_type=attachments.TXT_CONTENT_TYPE, sha256="0" * 64)
            return real_purge(att, **kw)

        out = io.StringIO()
        with mock.patch.object(attachments, "purge", side_effect=activate_then_purge):
            call_command("cleanup_attachments", stdout=out)
        self.assertIn("stale_pending_purged=0", out.getvalue())
        self.assertIn("skipped=1", out.getvalue())
        self.assertTrue((self.upload_dir / str(listed.storage_key)).exists())
        self.assertEqual(self.as_user(self.b).get(
            f"/posts/{self.p1.pk}/attachments/{listed.pk}/download/").status_code, 200)

    def test_orphan_is_rechecked_against_rows_before_delete(self):
        att = self.make_active()
        path = self.upload_dir / str(att.storage_key)
        os.utime(path, (time.time() - 7200, time.time() - 7200))
        out = io.StringIO()
        # 정리 명령이 행 목록을 읽은 뒤에 이 업로드의 행이 생긴 상황(목록에는 없음)
        with mock.patch("posts.management.commands.cleanup_attachments.Command._known_keys", return_value=set()):
            call_command("cleanup_attachments", "--delete-orphans", stdout=out)
        self.assertTrue(path.exists())
        self.assertIn("orphans_kept=1", out.getvalue())
        self.assertIn("orphans_removed=0", out.getvalue())

    def test_deleting_post_with_leftover_pending_is_finished(self):
        """DELETING 글에 PENDING이 남아 있어도(activate는 ACTIVE 글에서만 성공) 정리가 끝까지 간다."""
        att = Attachment.objects.create(post=self.p2, original_name="p.txt", size_bytes=1)
        (self.upload_dir / str(att.storage_key)).write_bytes(b"p")
        Post.objects.filter(pk=self.p2.pk).update(status=Post.Status.DELETING)
        out = io.StringIO()
        call_command("cleanup_attachments", stdout=out)
        self.assertIn("posts_finished=1", out.getvalue())
        self.assertFalse(Post.objects.filter(pk=self.p2.pk).exists())
        self.assertFalse((self.upload_dir / str(att.storage_key)).exists())

    def test_old_non_uuid_file_is_still_removed(self):
        junk = self.upload_dir / "leftover.bin"
        junk.write_bytes(b"x")
        os.utime(junk, (time.time() - 7200, time.time() - 7200))
        out = io.StringIO()
        call_command("cleanup_attachments", "--delete-orphans", stdout=out)
        self.assertFalse(junk.exists())
        self.assertIn("orphan (non-uuid file)", out.getvalue())


class CleanupLockTests(UploadDirMixin, TransactionTestCase):
    """정리와 업로드 완료(activate)가 같은 순간에 겹쳐도 "성공했는데 파일 없음"이 생기지 않는다."""

    def test_activate_waits_for_cleanup_and_fails_cleanly(self):
        a = User.objects.create_user("member_a")
        post = Post.objects.create(owner=a, title="t", body="b")
        att = Attachment.objects.create(post=post, original_name="s.txt", size_bytes=1)
        Attachment.objects.filter(pk=att.pk).update(created_at=att.created_at - timedelta(hours=2))
        att.refresh_from_db()
        (self.upload_dir / str(att.storage_key)).write_bytes(b"s")
        cutoff = att.created_at + timedelta(minutes=1)
        claimed = threading.Event()
        results = {}

        def cleanup():
            try:
                def hold():
                    claimed.set()
                    time.sleep(0.5)  # 행을 잠근 채로 머문다
                with mock.patch.object(attachments, "after_claim", side_effect=hold):
                    results["purge"] = attachments.purge(
                        att, statuses=(Attachment.Status.PENDING,), created_before=cutoff)
            finally:
                connection.close()

        def finish_upload():
            try:
                claimed.wait(5)
                started = time.monotonic()
                results["activate"] = attachments.activate(att, a, attachments.TXT_CONTENT_TYPE, "0" * 64)
                results["waited"] = time.monotonic() - started
            finally:
                connection.close()

        threads = [threading.Thread(target=cleanup), threading.Thread(target=finish_upload)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results["purge"], attachments.PURGED)
        self.assertFalse(results["activate"])  # 업로드는 성공으로 끝나지 않는다
        self.assertGreater(results["waited"], 0.3)  # 행 잠금 때문에 기다렸다
        self.assertFalse(Attachment.objects.filter(pk=att.pk).exists())
        self.assertFalse((self.upload_dir / str(att.storage_key)).exists())


    def test_cleanup_waits_for_activation_and_then_skips(self):
        """반대 순서(리뷰가 지적한 상황): 업로드 완료가 진행 중일 때 정리가 겹치면, 정리가 기다렸다가 건너뛴다."""
        a = User.objects.create_user("member_a")
        post = Post.objects.create(owner=a, title="t", body="b")
        att = Attachment.objects.create(post=post, original_name="s.txt", size_bytes=1)
        Attachment.objects.filter(pk=att.pk).update(created_at=att.created_at - timedelta(hours=2))
        att.refresh_from_db()  # 정리 명령이 목록에서 읽어 둔 옛 상태(PENDING)
        path = self.upload_dir / str(att.storage_key)
        path.write_bytes(b"s")
        cutoff = att.created_at + timedelta(minutes=1)
        activating = threading.Event()
        results = {}

        def finish_upload():
            try:
                with transaction.atomic():  # activate()와 같은 변경을 하고, 커밋 전에 머문다
                    Attachment.objects.filter(pk=att.pk, status=Attachment.Status.PENDING).update(
                        status=Attachment.Status.ACTIVE, content_type=attachments.TXT_CONTENT_TYPE, sha256="0" * 64)
                    activating.set()
                    time.sleep(0.5)
            finally:
                connection.close()

        def cleanup():
            try:
                activating.wait(5)
                started = time.monotonic()
                results["purge"] = attachments.purge(
                    att, statuses=(Attachment.Status.PENDING,), created_before=cutoff)
                results["waited"] = time.monotonic() - started
            finally:
                connection.close()

        threads = [threading.Thread(target=finish_upload), threading.Thread(target=cleanup)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results["purge"], attachments.SKIPPED)
        self.assertGreater(results["waited"], 0.3)  # 커밋을 기다렸다
        self.assertEqual(Attachment.objects.get(pk=att.pk).status, Attachment.Status.ACTIVE)
        self.assertTrue(path.exists())


class ConcurrentUploadTests(UploadDirMixin, TransactionTestCase):
    """UP-05: 동시 업로드가 개수 한도를 넘지 않는다(소유자·글 행 잠금)."""

    def setUp(self):
        super().setUp()
        self.a = User.objects.create_user("member_a")
        self.post = Post.objects.create(owner=self.a, title="t", body="b")
        for i in range(2):
            Attachment.objects.create(post=self.post, original_name=f"e{i}.txt", size_bytes=1, status="ACTIVE",
                                      content_type="text/plain; charset=utf-8", sha256="0" * 64)

    def test_two_simultaneous_uploads_for_the_last_slot(self):
        results = []
        barrier = threading.Barrier(2)

        def worker(name):
            try:
                client = Client()
                client.force_login(self.a)
                barrier.wait()
                res = self.upload(client, self.post, name, b"x")
                results.append(res.status_code)
            finally:
                connection.close()

        # 검사와 예약 사이를 넓혀 잠금이 없으면 둘 다 통과하게 만든다.
        with mock.patch.object(attachments, "after_quota_check", side_effect=lambda: time.sleep(0.3)):
            threads = [threading.Thread(target=worker, args=(f"t{i}.txt",)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(sorted(results), [302, 400])
        self.assertEqual(Attachment.objects.filter(post=self.post).count(), 3)
