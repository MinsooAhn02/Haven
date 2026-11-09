from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import include, path
from django.views.decorators.http import require_GET


@require_GET
def healthz(request):
    """프로세스 응답만 확인한다. DB는 확인하지 않고 버전도 노출하지 않는다(앱계약.md 3장)."""
    return HttpResponse("ok", content_type="text/plain; charset=utf-8")


@require_GET
def home(request):
    return redirect("posts:list" if request.user.is_authenticated else "accounts:login")


# Django 관리자 사이트는 연결하지 않는다. /admin/accounts/는 2회차 전용 화면 자리다(명세 2.2).
urlpatterns = [
    path("", home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("posts/", include("posts.urls")),
    path("healthz", healthz, name="healthz"),
]
