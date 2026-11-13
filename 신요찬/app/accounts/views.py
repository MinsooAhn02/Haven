from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.forms.utils import ErrorDict
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from config.request_log import mark

from . import login_limit
from .forms import LoginForm, SignupForm


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            form.save()
            # 가입 후 자동 로그인하지 않고 로그인 화면으로 보낸다(앱계약.md 8장 7번).
            messages.success(request, "가입했습니다. 로그인해 주세요.")
            return redirect("accounts:login")
        return render(request, "accounts/signup.html", {"form": form}, status=400)
    return render(request, "accounts/signup.html", {"form": SignupForm()})


class LoginView(auth_views.LoginView):
    """로그인 성공 시 세션 키를 교체한다(Django login()). 실패는 400(명세 2.1).

    로그인 실패 제한(앱계약 8장 13번): 제한 중이면 비밀번호를 확인하지 않고 429.
    인증까지 가서 실패한 경우만 센다(빈 칸 오류는 세지 않음). 성공하면 그 아이디의 계정 축 기록만 지운다.
    """

    form_class = LoginForm
    http_method_names = ["get", "post"]

    def post(self, request, *args, **kwargs):
        self.account_key, self.ip_key = login_limit.keys_for(request)
        if login_limit.is_limited(self.account_key, self.ip_key):
            return self.limited(request)
        response = super().post(request, *args, **kwargs)
        if response.status_code == 302:
            login_limit.clear_account(self.account_key)
        return response

    def limited(self, request):
        """폼 검증(=비밀번호 확인)을 하지 않고 같은 로그인 화면에 제한 문구만 보여 준다."""
        mark(request, "login_limited")
        form = self.get_form()
        form.cleaned_data = {}
        form._errors = ErrorDict()
        form.add_error(None, login_limit.LIMITED_MESSAGE)
        return self.render_to_response(self.get_context_data(form=form), status=429)

    def form_invalid(self, form):
        if form.has_error("__all__", "invalid_login") or form.has_error("__all__", "inactive"):
            login_limit.record_failure(self.account_key, self.ip_key)
        return self.render_to_response(self.get_context_data(form=form), status=400)


class LogoutView(auth_views.LogoutView):
    """POST만 허용. GET은 405(Django 기본)."""
