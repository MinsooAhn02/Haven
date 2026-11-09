"""공통 응답 처리."""
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string


class PrivateNoStoreMiddleware:
    """로그인 사용자 화면에 Cache-Control: private, no-store (앱계약.md 3.1).

    공용 캐시나 브라우저 뒤로 가기 캐시에 다른 사람이 볼 수 있는 화면이 남지 않게 한다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not response.has_header("Cache-Control"):
            response["Cache-Control"] = "private, no-store"
        return response


class MethodNotAllowedPageMiddleware:
    """405 응답에 errors/405.html 화면을 붙인다. Django 기본 405는 빈 본문이다.

    템플릿이 없으면 원래 응답을 그대로 둔다. Allow 헤더는 유지한다.
    """

    template_name = "errors/405.html"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 405 and not response.content:
            try:
                response.content = render_to_string(self.template_name, request=request)
            except TemplateDoesNotExist:
                return response
            response["Content-Type"] = "text/html; charset=utf-8"
        return response
