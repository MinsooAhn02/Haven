"""로그인 실패 제한 (앱계약 8장 13번, 신요찬/로그인실패제한_안.md, #75 조장 결정).

- 최근 15분 안에 같은 아이디로 5번, 또는 같은 IP에서 30번 실패하면 그 아이디·IP의 로그인을 429로 막는다.
- 시간이 지나면 자동으로 풀린다(영구 잠금 없음). 막힌 동안의 시도는 세지 않고 비밀번호도 확인하지 않는다.
- 없는 아이디도 똑같이 센다(계정 존재 여부를 드러내지 않음). 로그인 성공은 그 아이디의 계정 축 기록만 지운다.
- 아이디·IP 원문은 저장하지 않는다. SECRET_KEY로 HMAC한 키만 저장한다.
"""
import ipaddress
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import LoginFailure

WINDOW = timedelta(minutes=15)
MAX_PER_ACCOUNT = 5
MAX_PER_IP = 30
LIMITED_MESSAGE = "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요."
_SALT = "haven.accounts.login_limit."


def now():
    """시험에서 시계를 바꿀 수 있게 한 곳에서만 현재 시각을 읽는다."""
    return timezone.now()


def normalize_username(raw):
    """로그인 폼(UsernameField: 앞뒤 공백 제거 → NFKC)과 같게 정리한 뒤 대소문자를 무시한다.

    정리하지 않으면 `alice `, 전각 `ａｌｉｃｅ`처럼 폼이 같은 아이디로 인증하는 변형으로 계정 축을 피할 수 있다.
    """
    return unicodedata.normalize("NFKC", (raw or "").strip()).strip().casefold()


def client_ip(request):
    """요청한 사용자의 IP.

    서버(DJANGO_HTTPS=1)는 ALB → Nginx 뒤라서 X-Forwarded-For가 `<사용자가 보낸 값...>, <ALB가 붙인 실제 IP>, <Nginx가 붙인 ALB IP>`다.
    믿을 수 있는 것은 끝 두 개뿐이므로 끝에서 두 번째를 쓴다(ALB XFF 처리 방식 append, 이민성 11/12 확인).
    로컬·CI(HTTP)나 값이 이상하면 REMOTE_ADDR를 쓴다.
    """
    remote = request.META.get("REMOTE_ADDR", "")
    if settings.HAVEN_HTTPS:
        parts = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")]
        if len(parts) >= 2:
            try:
                return str(ipaddress.ip_address(parts[-2]))
            except ValueError:
                pass
    return remote


def _key(axis, value):
    return salted_hmac(_SALT + axis, value, algorithm="sha256").hexdigest()


def keys_for(request):
    """(계정 축 키 또는 None, IP 축 키). 아이디가 비어 있으면 계정 축은 보지 않는다."""
    username = normalize_username(request.POST.get("username", ""))
    account_key = _key(LoginFailure.Axis.ACCOUNT, username) if username else None
    return account_key, _key(LoginFailure.Axis.IP, client_ip(request))


def _recent(axis, key):
    return LoginFailure.objects.filter(axis=axis, key=key, created_at__gt=now() - WINDOW)


def is_limited(account_key, ip_key):
    if account_key and _recent(LoginFailure.Axis.ACCOUNT, account_key).count() >= MAX_PER_ACCOUNT:
        return True
    return _recent(LoginFailure.Axis.IP, ip_key).count() >= MAX_PER_IP


def record_failure(account_key, ip_key):
    """실패 한 건을 두 축에 남기고, 15분 지난 기록은 지운다(따로 정리 작업이 필요 없게)."""
    at = now()
    LoginFailure.objects.filter(created_at__lte=at - WINDOW).delete()
    rows = [LoginFailure(axis=LoginFailure.Axis.IP, key=ip_key, created_at=at)]
    if account_key:
        rows.append(LoginFailure(axis=LoginFailure.Axis.ACCOUNT, key=account_key, created_at=at))
    LoginFailure.objects.bulk_create(rows)


def clear_account(account_key):
    """로그인 성공: 그 아이디의 계정 축 기록만 지운다. IP 축은 그대로 둔다."""
    if account_key:
        LoginFailure.objects.filter(axis=LoginFailure.Axis.ACCOUNT, key=account_key).delete()
