"""Haven Django 설정.

값은 모두 환경변수에서 읽는다(앱계약.md 1.2). `.env` 파일은 자동으로 읽지 않는다.
필수값이 없으면 시작에 실패하며, DB 설정이 없을 때 SQLite로 대체하지 않는다.
DB 비밀번호는 DB_PASSWORD 또는 pgpass 파일 중 하나로 공급한다.
"""
import os
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

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "posts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.PrivateNoStoreMiddleware",
    "config.middleware.MethodNotAllowedPageMiddleware",
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

# 1회차에는 메일 기능이 없다. 로컬·CI에서 실제로 보내지 않는다. 메일 설정은 3회차에 정한다.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
