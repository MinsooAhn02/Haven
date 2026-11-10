"""기록 작성·수정 폼과 공유 대상 폼 (앱계약.md 4장, 2회차 화면 계약 1장).

owner·status는 폼에 없으므로 요청에 넣어 보내도 무시된다.
"""
from django import forms
from django.contrib.auth import get_user_model

from accounts.roles import is_member

from .models import Post

# 없는 아이디·비활성·자기 자신·관리자 계정을 구분하지 않는 하나의 문구(명세 3.3).
SHARE_TARGET_ERROR = "공유할 수 없는 사용자입니다."


class PostForm(forms.ModelForm):
    # 본문은 앞뒤 공백·줄바꿈을 그대로 저장한다. 공백만 있는 본문은 clean_body에서 거부한다.
    body = forms.CharField(widget=forms.Textarea, strip=False)

    class Meta:
        model = Post
        fields = ["title", "body"]

    def clean_body(self):
        body = self.cleaned_data["body"]
        if not body.strip():
            raise forms.ValidationError("내용을 입력해 주세요.", code="blank")
        return body


class ShareForm(forms.Form):
    """공유 대상 지정. 정확한 username 하나만 받는다(검색·자동완성 없음)."""

    username = forms.CharField(max_length=150)

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.recipient = None

    def clean_username(self):
        username = self.cleaned_data["username"]
        user = get_user_model().objects.filter(username=username).first()
        allowed = (
            user is not None
            and user.is_active
            and user.pk != self.owner.pk
            and is_member(user)  # 운영 관리자·is_staff·superuser는 공유 대상이 아니다
        )
        if not allowed:
            raise forms.ValidationError(SHARE_TARGET_ERROR, code="invalid_target")
        self.recipient = user
        return username
