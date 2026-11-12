"""시험 메일 발송 (명세 6.5·EXT-03·EXT-04, AWS 운영결정 6번 "SES API(443)", 앱계약.md 1.2.2).

- 서버에서만 `HAVEN_MAIL_BACKEND=ses`로 켠다. 로컬·CI는 콘솔 백엔드라 실제로 보내지 않는다.
- AWS 키를 쓰지 않는다. boto3가 Web EC2 Role(인스턴스 메타데이터)의 임시 자격 증명을 쓴다.
- 보내는 내용은 텍스트 한 가지(제목·본문)뿐이다. 참조·숨은 참조·회신 주소·추가 헤더·첨부·HTML은 받지 않는다
  (조용히 버리지 않고 오류).
- 한 번만 시도한다(자동 재시도 없음, 연결 5초·응답 10초 제한). 밤에 NAT가 내려가 있어도 오래 멈추지 않고,
  같은 메일이 두 번 나가지 않는다. 실패하면 사람이 보고 다시 실행한다.
- SES가 접수하면(MessageId) 성공이다. 실제 도착은 받은 편지함에서 따로 확인한다(명세 6.5).
"""
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class UnsupportedMessage(ValueError):
    """이 백엔드가 보내지 않는 형태(참조·숨은 참조·회신 주소·추가 헤더·첨부·HTML)."""


def _client():
    """SES v2 클라이언트. boto3는 서버에만 설치하고, 시험은 이 함수를 바꿔 끼운다."""
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1})
    return boto3.client("sesv2", region_name=settings.HAVEN_SES_REGION, config=config)


def check_supported(message):
    extras = (message.cc, message.bcc, message.reply_to, message.extra_headers, message.attachments,
              getattr(message, "alternatives", None))
    if any(extras):
        raise UnsupportedMessage("시험 메일은 받는 사람(To)과 텍스트 본문만 보낸다.")
    if not message.to:
        raise UnsupportedMessage("받는 사람이 없다.")


class SesEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        client = None
        for message in email_messages:
            try:
                check_supported(message)
                if client is None:
                    client = _client()
                response = client.send_email(
                    FromEmailAddress=message.from_email,
                    Destination={"ToAddresses": list(message.to)},
                    Content={
                        "Simple": {
                            "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                            "Body": {"Text": {"Data": message.body, "Charset": "UTF-8"}},
                        }
                    },
                )
                message_id = response.get("MessageId") if isinstance(response, dict) else None
                if not message_id:
                    raise RuntimeError("SES 응답에 MessageId가 없다.")
                message.ses_message_id = message_id
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return sent
