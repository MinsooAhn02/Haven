"""공통 응답 처리."""
from django.http import HttpResponse
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.urls import Resolver404, resolve

# 글 작성·수정 POST의 전체 body 한도 (명세 0장 "글 요청 크기", APP-11). CSRF 토큰과 폼 인코딩을 포함한 바이트 수.
POST_BODY_LIMIT = 8192
POST_BODY_LIMITED_VIEWS = frozenset({"posts:create", "posts:edit"})


class PostBodyLimitMiddleware:
    """글 작성·수정 POST body가 8,192바이트를 넘으면 413 (앱계약 결정 9: 413이 CSRF보다 먼저).

    - 이 검사는 view 실행 전 단계(__call__)에서 한다. CSRF 검사(process_view)와 로그인 검사(view)는
      그 뒤에 일어나므로, 크기 초과는 토큰이 없거나 비로그인이어도 413이다(Nginx client_max_body_size와 같은 순서).
    - 글 경로에만 적용한다. 로그인·가입 등 다른 폼과 3회차 첨부 업로드 경로는 건드리지 않는다(명세 4장).
    - Content-Length가 한도를 넘으면 body를 읽지 않고 거부한다. 한도 이내라고 적힌 요청도 실제로 읽은
      바이트를 다시 센다. Django는 Content-Length만큼만 읽으므로 이보다 많이 읽는 일은 없다.
    - 숫자가 아니거나 음수인 Content-Length는 400(오류 화면). 보통은 Nginx·Gunicorn이 먼저 거부한다.
    """

    template_name = "errors/413.html"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and self._is_limited(request):
            status = self._check(request)
            if status:
                return self._reject(request, status)
        return self.get_response(request)

    @staticmethod
    def _is_limited(request):
        try:
            return resolve(request.path_info).view_name in POST_BODY_LIMITED_VIEWS
        except Resolver404:
            return False

    @staticmethod
    def _check(request):
        """거부할 상태 코드. 통과면 None."""
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            # 숫자가 아닌 Content-Length. Django는 body를 읽다 500을 내므로 여기서 400으로 끊는다.
            return 400
        if declared < 0:
            return 400
        if declared > POST_BODY_LIMIT or len(request.body) > POST_BODY_LIMIT:
            return 413
        return None

    def _reject(self, request, status):
        template = self.template_name if status == 413 else "400.html"
        try:
            content = render_to_string(template, request=request)
        except TemplateDoesNotExist:
            content = ""
        return HttpResponse(content, status=status)


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
