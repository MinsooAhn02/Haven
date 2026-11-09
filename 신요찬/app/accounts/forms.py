"""가입·로그인 폼 (앱계약.md 4장)."""
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

# 없는 계정·틀린 비밀번호·비활성 계정에 같은 문구를 쓴다(계정 존재 여부를 드러내지 않음).
LOGIN_FAILED_MESSAGE = "로그인할 수 없습니다. 아이디와 비밀번호를 확인해 주세요."


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": LOGIN_FAILED_MESSAGE,
        "inactive": LOGIN_FAILED_MESSAGE,
    }


class SignupForm(UserCreationForm):
    """필드: username, password1, password2. 비밀번호 정책·불일치 오류는 password2에 붙는다."""
