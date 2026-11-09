from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

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
    """로그인 성공 시 세션 키를 교체한다(Django login()). 실패는 400(명세 2.1)."""

    form_class = LoginForm
    http_method_names = ["get", "post"]

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form), status=400)


class LogoutView(auth_views.LogoutView):
    """POST만 허용. GET은 405(Django 기본)."""
