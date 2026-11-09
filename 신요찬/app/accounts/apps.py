from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """가입·로그인·로그아웃. 별도 모델 없이 Django 기본 User를 쓴다(명세 3.1)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
