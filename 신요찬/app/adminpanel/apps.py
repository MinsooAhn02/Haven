from django.apps import AppConfig


class AdminpanelConfig(AppConfig):
    """제한된 계정 관리 (명세 2.2·3.2). Django 기본 관리자 사이트는 연결하지 않는다."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "adminpanel"
