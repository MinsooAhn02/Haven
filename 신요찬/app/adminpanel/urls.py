from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "adminpanel"

# /admin/ 은 제한된 계정 관리로 연결한다(명세 2.2). Django 기본 관리자 사이트는 연결하지 않는다.
urlpatterns = [
    path("", RedirectView.as_view(pattern_name="adminpanel:accounts", permanent=False), name="index"),
    path("accounts/", views.account_list, name="accounts"),
    path("accounts/<int:pk>/status/", views.account_status, name="account_status"),
    path("account-events/", views.account_events, name="account_events"),
]
