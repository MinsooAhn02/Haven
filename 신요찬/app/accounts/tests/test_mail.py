"""시험 메일 (명세 6.5·EXT-03·EXT-04, 앱계약.md 1.2.2).

실제 SES는 부르지 않는다. config.mail._client를 가짜 클라이언트로 바꿔 끼운다(boto3 없이 돈다).
"""
import io
import os
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

from django.core import mail
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from config import mail as haven_mail

APP_DIR = Path(__file__).resolve().parents[2]
SES = dict(HAVEN_MAIL_BACKEND="ses", EMAIL_BACKEND="config.mail.SesEmailBackend",
           DEFAULT_FROM_EMAIL="noreply@haven.test", HAVEN_SES_REGION="ap-northeast-2")
TO = "virtual-recipient@haven.test"


class FakeSes:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = {"MessageId": "0100018f-test-message-id"} if response is None else response
        self.error = error

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClientError(Exception):
    """botocore ClientError와 같은 모양(response["Error"]["Code"])."""

    def __init__(self, code, message):
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


class SettingsFromEnvTests(SimpleTestCase):
    def run_settings(self, **env_values):
        env = {k: v for k, v in os.environ.items() if not k.startswith("HAVEN_MAIL") and k != "HAVEN_SES_REGION"}
        env.update(env_values, DJANGO_SETTINGS_MODULE="config.settings")
        code = ("import django;django.setup();from django.conf import settings as s;"
                "print(s.HAVEN_MAIL_BACKEND, s.EMAIL_BACKEND, s.DEFAULT_FROM_EMAIL, s.HAVEN_SES_REGION)")
        return subprocess.run([sys.executable, "-c", code], cwd=APP_DIR, env=env, capture_output=True, text=True, timeout=60)

    def test_default_is_console_and_does_not_send(self):
        r = self.run_settings()
        self.assertEqual(r.stdout.split()[:2], ["console", "django.core.mail.backends.console.EmailBackend"], r.stderr[-400:])

    def test_ses_needs_from_address(self):
        r = self.run_settings(HAVEN_MAIL_BACKEND="ses")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("HAVEN_MAIL_FROM", r.stderr)

    def test_ses_with_from_address(self):
        r = self.run_settings(HAVEN_MAIL_BACKEND="ses", HAVEN_MAIL_FROM="noreply@haven.test")
        self.assertEqual(r.stdout.split(), ["ses", "config.mail.SesEmailBackend", "noreply@haven.test", "ap-northeast-2"], r.stderr[-400:])

    def test_unknown_backend_fails_to_start(self):
        r = self.run_settings(HAVEN_MAIL_BACKEND="smtp")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("HAVEN_MAIL_BACKEND", r.stderr)


@override_settings(**SES)
class SesBackendTests(SimpleTestCase):
    def test_sends_plain_text_with_exact_ses_parameters(self):
        fake = FakeSes()
        message = EmailMessage("제목", "본문", "noreply@haven.test", [TO])
        with mock.patch.object(haven_mail, "_client", return_value=fake):
            self.assertEqual(message.send(), 1)
        self.assertEqual(fake.calls, [{
            "FromEmailAddress": "noreply@haven.test",
            "Destination": {"ToAddresses": [TO]},
            "Content": {"Simple": {"Subject": {"Data": "제목", "Charset": "UTF-8"},
                                   "Body": {"Text": {"Data": "본문", "Charset": "UTF-8"}}}},
        }])
        self.assertEqual(message.ses_message_id, "0100018f-test-message-id")

    def test_ses_error_is_raised_not_hidden(self):
        fake = FakeSes(error=FakeClientError("MessageRejected", "Email address is not verified"))
        with mock.patch.object(haven_mail, "_client", return_value=fake), self.assertRaises(FakeClientError):
            EmailMessage("s", "b", "noreply@haven.test", [TO]).send()

    def test_missing_message_id_is_failure(self):
        with mock.patch.object(haven_mail, "_client", return_value=FakeSes(response={})), self.assertRaises(RuntimeError):
            EmailMessage("s", "b", "noreply@haven.test", [TO]).send()

    def test_fail_silently_returns_zero(self):
        fake = FakeSes(error=FakeClientError("Throttling", "slow down"))
        with mock.patch.object(haven_mail, "_client", return_value=fake):
            self.assertEqual(EmailMessage("s", "b", "noreply@haven.test", [TO]).send(fail_silently=True), 0)

    def test_unsupported_parts_are_rejected_not_dropped(self):
        cases = {
            "cc": EmailMessage("s", "b", "noreply@haven.test", [TO], cc=["other@haven.test"]),
            "bcc": EmailMessage("s", "b", "noreply@haven.test", [TO], bcc=["other@haven.test"]),
            "reply_to": EmailMessage("s", "b", "noreply@haven.test", [TO], reply_to=["other@haven.test"]),
            "headers": EmailMessage("s", "b", "noreply@haven.test", [TO], headers={"X-Extra": "1"}),
            "attachment": EmailMessage("s", "b", "noreply@haven.test", [TO], attachments=[("a.txt", "x", "text/plain")]),
        }
        html = EmailMultiAlternatives("s", "b", "noreply@haven.test", [TO])
        html.attach_alternative("<b>b</b>", "text/html")
        cases["html"] = html
        for name, message in cases.items():
            with self.subTest(part=name):
                fake = FakeSes()
                with mock.patch.object(haven_mail, "_client", return_value=fake), \
                        self.assertRaises(haven_mail.UnsupportedMessage):
                    message.send()
                self.assertEqual(fake.calls, [])


@override_settings(**SES)
class SesClientTests(SimpleTestCase):
    def test_client_is_sesv2_in_region_single_attempt_short_timeouts(self):
        """재시도 없이 한 번만, 짧은 제한 시간으로(NAT가 내려가 있어도 오래 멈추지 않고 두 번 보내지 않는다).

        boto3가 없는 환경(로컬·CI)에서도 돌도록 가짜 모듈을 끼운다.
        """
        seen = {}

        class FakeConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        def fake_client(service, **kwargs):
            seen.update(kwargs, service=service)
            return "client"

        modules = {"boto3": types.SimpleNamespace(client=fake_client), "botocore": types.ModuleType("botocore"),
                   "botocore.config": types.SimpleNamespace(Config=FakeConfig)}
        with mock.patch.dict(sys.modules, modules):
            self.assertEqual(haven_mail._client(), "client")
        self.assertEqual((seen["service"], seen["region_name"]), ("sesv2", "ap-northeast-2"))
        self.assertEqual(seen["config"].kwargs,
                         {"connect_timeout": 5, "read_timeout": 10, "retries": {"total_max_attempts": 1}})


@override_settings(**SES)
class SendTestMailCommandTests(SimpleTestCase):
    def run_command(self, fake, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(haven_mail, "_client", return_value=fake):
            call_command("send_test_mail", *args, stdout=out, stderr=err)
        return out.getvalue()

    def test_accepted_mail_reports_message_id_not_delivery(self):
        fake = FakeSes()
        with self.assertLogs("haven.mail", "INFO") as logs:
            out = self.run_command(fake, "--to", TO)
        self.assertIn("SES 접수 message_id=0100018f-test-message-id", out)
        self.assertIn("to=v***@haven.test", out)
        self.assertIn("실제 도착은 받은 편지함에서 확인", out)
        self.assertNotIn(TO, out)
        self.assertNotIn(TO, "\n".join(logs.output))
        sent = fake.calls[0]
        self.assertEqual(sent["Destination"], {"ToAddresses": [TO]})
        self.assertEqual(sent["FromEmailAddress"], "noreply@haven.test")
        body = sent["Content"]["Simple"]["Body"]["Text"]["Data"]
        self.assertIn("Haven 시험 메일", body)
        self.assertIn("실행 ID:", body)

    def test_ses_failure_exits_nonzero_without_success_or_raw_error(self):
        fake = FakeSes(error=FakeClientError("MessageRejected", f"Email address is not verified: {TO}"))
        out = io.StringIO()
        with self.assertLogs("haven.mail", "WARNING") as logs, \
                mock.patch.object(haven_mail, "_client", return_value=fake), \
                self.assertRaises(CommandError) as ctx:
            call_command("send_test_mail", "--to", TO, stdout=out)
        self.assertIn("MessageRejected", str(ctx.exception))
        self.assertNotIn("접수", out.getvalue())
        for text in (str(ctx.exception), "\n".join(logs.output)):
            self.assertNotIn(TO, text)
            self.assertNotIn("not verified", text)

    def test_no_message_id_is_failure(self):
        with self.assertLogs("haven.mail", "WARNING"), self.assertRaises(CommandError):
            self.run_command(FakeSes(response={}), "--to", TO)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_backend_without_ses_receipt_is_not_reported_as_sent(self):
        """백엔드가 "1통"이라고만 하고 SES 접수 ID를 주지 않으면 성공으로 표시하지 않는다(EXT-04)."""
        out = io.StringIO()
        with self.assertLogs("haven.mail", "WARNING"), self.assertRaises(CommandError) as ctx:
            call_command("send_test_mail", "--to", TO, stdout=out)
        self.assertIn("접수하지 않았습니다", str(ctx.exception))
        self.assertNotIn("SES 접수", out.getvalue())
        self.assertEqual(len(mail.outbox), 1)  # 백엔드는 "보냈다"고 했지만

    def test_invalid_address_is_rejected_before_sending(self):
        for bad in ("not-an-address", "a@b@c", "x@y.z\nBcc: evil@haven.test", ""):
            with self.subTest(bad=bad[:20]):
                fake = FakeSes()
                with self.assertRaises(CommandError):
                    self.run_command(fake, "--to", bad)
                self.assertEqual(fake.calls, [])

    @override_settings(HAVEN_MAIL_BACKEND="console", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_console_mode_does_not_claim_to_send(self):
        fake = FakeSes()
        with self.assertRaises(CommandError) as ctx:
            self.run_command(fake, "--to", TO)
        self.assertIn("보내지 않았습니다", str(ctx.exception))
        self.assertEqual(fake.calls, [])
        self.assertEqual(mail.outbox, [])
