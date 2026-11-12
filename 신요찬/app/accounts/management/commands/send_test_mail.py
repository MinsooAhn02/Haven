"""시험 메일 한 통 보내기 (명세 6.5 "가상 수신자 대상 최소 알림 한 가지", EXT-03·EXT-04).

    python manage.py send_test_mail --to <가상 수신 주소>

- `HAVEN_MAIL_BACKEND=ses`가 아니면 보내지 않고 실패로 끝낸다(콘솔 출력만 하고 "보냈다"고 하지 않기 위해).
- SES가 접수하면(MessageId) "접수"라고만 쓴다. 실제 도착은 받은 편지함에서 따로 확인한다.
- 실패하면 종료 코드 1, "보냈다"는 출력 없음(EXT-04). 오류는 종류·코드만 쓰고, 오류 원문은 쓰지 않는다
  (SES 오류 문구에 주소가 들어 있을 수 있음).
- 본문은 고정 문구 + 실행 시각 + 실행 ID뿐이다. 회원 정보·비밀값을 넣지 않는다.
"""
import logging
import uuid
from datetime import datetime, timezone

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

logger = logging.getLogger("haven.mail")

SUBJECT = "[Haven] 시험 메일"


def mask(address):
    """출력용: 받는 사람 주소를 a***@domain 형태로 줄인다."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


def error_code(exc):
    """botocore ClientError면 SES 오류 코드, 아니면 예외 이름. 오류 원문은 쓰지 않는다."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)[:64]
    return type(exc).__name__


class Command(BaseCommand):
    help = "가상 수신 주소로 시험 메일 한 통을 SES로 보낸다(서버, HAVEN_MAIL_BACKEND=ses)."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="SES에서 받을 수 있게 인증한 가상 수신 주소")

    def handle(self, *args, to, **options):
        to = to.strip()
        try:
            validate_email(to)
        except ValidationError:
            raise CommandError("받는 주소 형식이 올바르지 않습니다.")
        if settings.HAVEN_MAIL_BACKEND != "ses":
            raise CommandError("HAVEN_MAIL_BACKEND=ses가 아니어서 보내지 않았습니다(로컬·CI는 실제 발송 없음).")

        run_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        body = (
            "Haven 시험 메일입니다.\n"
            "가상 수신 주소로 보내는 발송·수신 확인용 메시지이며, 답장할 필요가 없습니다.\n\n"
            f"보낸 시각(UTC): {now}\n"
            f"실행 ID: {run_id}\n"
        )
        message = EmailMessage(SUBJECT, body, settings.DEFAULT_FROM_EMAIL, [to])
        try:
            sent = message.send(fail_silently=False)
        except Exception as exc:
            code = error_code(exc)
            logger.warning("test mail failed run_id=%s code=%s", run_id, code)
            raise CommandError(f"메일을 보내지 못했습니다 (오류: {code}, 실행 ID: {run_id}).")
        message_id = getattr(message, "ses_message_id", None)
        if sent != 1 or not message_id:
            logger.warning("test mail not accepted run_id=%s", run_id)
            raise CommandError(f"SES가 메일을 접수하지 않았습니다 (실행 ID: {run_id}).")
        logger.info("test mail accepted run_id=%s message_id=%s", run_id, message_id)
        self.stdout.write(
            f"SES 접수 message_id={message_id} to={mask(to)} run_id={run_id}\n"
            "실제 도착은 받은 편지함에서 확인하세요(스팸함 포함)."
        )
