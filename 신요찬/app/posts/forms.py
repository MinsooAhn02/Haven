"""기록 작성·수정 폼 (앱계약.md 4장). 필드는 title, body만 받는다.

owner·status는 폼에 없으므로 요청에 넣어 보내도 무시된다.
"""
from django import forms

from .models import Post


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
