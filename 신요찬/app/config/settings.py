"""Haven Django 설정.

값은 모두 환경변수에서 읽는다(앱계약.md 1.2). `.env` 파일은 자동으로 읽지 않는다.
필수값이 없으면 시작에 실패하며, DB 설정이 없을 때 SQLite로 대체하지 않는다.
DB 비밀번호는 DB_PASSWORD 또는 pgpass 파일 중 하나로 공급한다.
"""
import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# manage.py가 있는 앱 루트 (현재 신요찬/app/, 통합 후 app/ 예정)
BASE_DIR = Path(__file__).resolve().parent.parent


def find_repo_root(start):
    """노푸른/ 폴더가 있는 상위 폴더를 저장소 루트로 본다.

    앱 위치가 신요찬/app/에서 app/으로 옮겨져도 코드를 고치지 않기 위해서다.
    서버처럼 저장소 구조가 없으면 앱 루트의 부모를 쓰며, 그때는 HAVEN_* 변수로 경로를 준다.
    """
    for folder in (start, *start.parents):
        if (folder / "노푸른").is_dir():
            return folder
    return start.parent


REPO_ROOT = find_repo_root(BASE_DIR)


def env_required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"필수 환경변수 {name}가 설정되지 않았습니다.")
    return value


def env_optional(name, default=""):
    value = os.environ.get(name, "").strip()
    return value or default


def env_bool(name, default=False):
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true"}:
        return True
    if raw in {"0", "false"}:
        return False
    raise ImproperlyConfigured(f"환경변수 {name}는 0/1 또는 true/false여야 합니다.")


def env_list(name, required=False):
    raw = env_required(name) if required else env_optional(name)
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = env_required("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", required=True)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# HTTPS (명세 3.2 "cookie Secure/HttpOnly/SameSite와 프록시 신뢰를 명시", DEP-03, 앱계약.md 1.2).
# ALB가 TLS를 끝내고 Nginx(80)를 거쳐 Gunicorn으로 넘긴다. ALB가 원래 scheme을 X-Forwarded-Proto로 붙이고
# Nginx는 그 값만 그대로 넘긴다(안민수/server/web-setup.sh). Web의 80은 ALB SG에서만 열려 있어 이 헤더를
# 신뢰하는 범위는 ALB를 거친 요청뿐이다. 그래서 HTTPS 배포에서만 켜고, 로컬·CI(HTTP)에서는 끈다.
HAVEN_HTTPS = env_bool("DJANGO_HTTPS", default=False)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if HAVEN_HTTPS else None
SESSION_COOKIE_SECURE = HAVEN_HTTPS
CSRF_COOKIE_SECURE = HAVEN_HTTPS
# 아래는 켜고 끔과 관계없이 명시한다. 화면 JS가 쿠키를 읽지 않으므로(폼의 csrf_token 사용) CSRF 쿠키도 HttpOnly.
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
# HTTP→HTTPS 전환은 ALB가 한다. 앱에서 SECURE_SSL_REDIRECT를 켜면 ALB 상태 검사(HTTP /healthz)가 301로 실패한다.
SECURE_SSL_REDIRECT = False
# HSTS (check --deploy security.W004, 조장 운영기록 11/17). HTTPS로 판정된 응답에만 붙는다(Django SecurityMiddleware).
# 한 번 받은 브라우저는 그 기간 동안 HTTP로 되돌리지 못하므로 1시간으로 시작한다(앱계약.md 1.2.1).
# 하위 도메인 포함(W005)과 preload(W021)는 켜지 않는다: 이 도메인의 다른 이름까지 묶거나 브라우저 목록에 영구 등록하지 않는다.
SECURE_HSTS_SECONDS = 3600 if HAVEN_HTTPS else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

INSTALLED_APPS = [
    # LogEntry(계정 상태 변경 이력)를 쓰기 위해 설치만 한다. 관리자 사이트 URL은 연결하지 않는다(config/urls.py).
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "posts",
    "adminpanel",
]

MIDDLEWARE = [
    # 요청 단위 구조화 로그(D5). 가장 바깥에 두어 413·CSRF 403·500을 포함한 최종 응답을 남긴다.
    "config.request_log.RequestLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.PrivateNoStoreMiddleware",
    "config.middleware.MethodNotAllowedPageMiddleware",
    # 글 body 8,192바이트 초과 → 413. 목록 끝에 두어도 CSRF 검사(process_view)보다 먼저 실행된다.
    # 413 화면에도 로그인 메뉴와 Cache-Control이 붙도록 인증·응답 미들웨어 안쪽에 둔다.
    "config.middleware.PostBodyLimitMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# 화면 원본은 노푸른 폴더 한 곳에서만 관리한다(앱계약.md 5장). 앱 폴더에 복사본을 두지 않는다.
TEMPLATES_DIR = Path(env_optional("HAVEN_TEMPLATES_DIR", str(REPO_ROOT / "노푸른" / "templates")))
STATIC_SOURCE_DIR = Path(env_optional("HAVEN_STATIC_DIR", str(REPO_ROOT / "노푸른" / "static")))

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [TEMPLATES_DIR],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_required("DB_NAME"),
        "USER": env_required("DB_USER"),
        # 비우면 libpq가 pgpass 파일에서 읽는다(안민수/dev-db-setup.ps1 방식).
        # 비밀번호가 어디에도 없으면 DB 접속이 거부된다(SQLite 등으로 대체하지 않음).
        "PASSWORD": env_optional("DB_PASSWORD"),
        "HOST": env_optional("DB_HOST", "localhost"),
        "PORT": env_optional("DB_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# 로그인 경로 (앱계약.md 3장).
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "posts:list"
LOGOUT_REDIRECT_URL = "accounts:login"

# 세션: 브라우저를 닫으면 만료, 최대 1시간. 요청마다 연장하지 않는다(명세 2.1).
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 3600
SESSION_SAVE_EVERY_REQUEST = False

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True  # DB에는 UTC로 저장

STATIC_URL = "static/"
# 노푸른 static 폴더가 생기기 전에는 등록하지 않는다(없는 폴더를 등록하면 check 경고가 난다).
STATICFILES_DIRS = [STATIC_SOURCE_DIR] if STATIC_SOURCE_DIR.is_dir() else []

# 시험 메일 (3회차, 명세 6.5·EXT-03·04, AWS 운영결정 6번 SES API, 앱계약.md 1.2.2).
# 기본(로컬·CI)은 콘솔이라 실제로 보내지 않는다. 서버에서 HAVEN_MAIL_BACKEND=ses일 때만 SES로 보낸다.
# SES는 AWS 키 없이 Web EC2 Role로 호출한다(키를 환경변수·파일에 두지 않는다).
HAVEN_MAIL_BACKEND = env_optional("HAVEN_MAIL_BACKEND", "console").lower()
if HAVEN_MAIL_BACKEND not in {"console", "ses"}:
    raise ImproperlyConfigured("환경변수 HAVEN_MAIL_BACKEND는 console 또는 ses여야 합니다.")
HAVEN_SES_REGION = env_optional("HAVEN_SES_REGION", "ap-northeast-2")  # 서울(김보람 SES 설정 리전)
if HAVEN_MAIL_BACKEND == "ses":
    EMAIL_BACKEND = "config.mail.SesEmailBackend"
    DEFAULT_FROM_EMAIL = env_required("HAVEN_MAIL_FROM")  # SES에서 인증한 발신 주소
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    DEFAULT_FROM_EMAIL = env_optional("HAVEN_MAIL_FROM", "haven-test@example.invalid")

# 첨부 (3회차, 명세 3.4). 서버는 /srv/haven/uploads(안민수 web-setup.sh, systemd ReadWritePaths).
# static·코드 밖, 공개 URL 없음. 다운로드는 앱이 권한을 확인한 뒤 직접 보낸다.
HAVEN_UPLOAD_DIR = Path(env_optional("HAVEN_UPLOAD_DIR", "/srv/haven/uploads"))
# 업로드 임시 파일은 최종 위치와 같은 파일시스템(HAVEN_UPLOAD_DIR/.incoming)에 받는다(posts/upload_handlers.py).
# 서버 프로세스가 쓸 수 있는 곳이 uploads 하나뿐이고(ReadWritePaths), 같은 파일시스템이라 원자적 link가 된다.
FILE_UPLOAD_HANDLERS = ["posts.upload_handlers.IncomingFileUploadHandler"]
DATA_UPLOAD_MAX_NUMBER_FILES = 1  # 업로드 한 요청에 파일 하나(명세 3.4). 2개 이상이면 400

# CSRF 실패 화면은 Django 기본(403_csrf.html) 그대로이고, 요청 로그에 csrf_failure로 표시만 한다.
CSRF_FAILURE_VIEW = "config.request_log.csrf_failure"

# 로그 (명세 3.1, 앱계약.md 7장). 요청 로그는 JSON 한 줄씩 표준 출력으로 → 서버에서는 journald(haven.service).
# 시험 실행 중에는 출력을 끈다(시험은 assertLogs로 직접 확인한다).
_TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"raw": {"format": "%(message)s"}},
    "handlers": {
        "stdout": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout", "formatter": "raw"},
    },
    "loggers": {
        "haven.request": {"handlers": ["stdout"], "level": "WARNING" if _TESTING else "INFO", "propagate": False},
        "haven.mail": {"handlers": ["stdout"], "level": "WARNING" if _TESTING else "INFO", "propagate": False},
    },
}
