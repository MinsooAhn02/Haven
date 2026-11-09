"""ASGI 진입점. 기본 배포는 WSGI(Gunicorn)를 사용한다."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
