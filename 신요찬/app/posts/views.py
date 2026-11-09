"""기록 화면 (앱계약.md 3·5장).

- 조회는 permissions.owned_posts()로만 한다. 다른 사람 글·없는 글은 모두 404.
- 입력 검증 실패는 400, 성공한 POST는 302(PRG).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from . import services
from .forms import PostForm
from .models import Post
from .permissions import owned_posts

PAGE_SIZE = 20


def _page(request, queryset):
    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    return {"posts": page_obj.object_list, "page_obj": page_obj}


@require_GET
@login_required
def post_list(request):
    return render(request, "posts/list.html", _page(request, owned_posts(request.user)))


@require_GET
@login_required
def shared_list(request):
    # 1회차에는 URL 이름만 먼저 등록한다(공통 메뉴 링크가 깨지지 않게). 2회차에 공유 조회로 바꾼다.
    return render(request, "posts/shared_list.html", _page(request, Post.objects.none()))


@require_http_methods(["GET", "POST"])
@login_required
def post_create(request):
    if request.method == "POST":
        form = PostForm(request.POST)
        if form.is_valid():
            post = form.save(commit=False)
            post.owner = request.user
            post.save()
            messages.success(request, "기록을 저장했습니다.")
            return redirect("posts:detail", pk=post.pk)
        return _render_form(request, form, "create", None, status=400)
    return _render_form(request, PostForm(), "create", None)


@require_GET
@login_required
def post_detail(request, pk):
    post = get_object_or_404(owned_posts(request.user), pk=pk)
    return render(request, "posts/detail.html", {"post": post, "is_owner": True})


@require_http_methods(["GET", "POST"])
@login_required
def post_edit(request, pk):
    post = get_object_or_404(owned_posts(request.user), pk=pk)
    if request.method == "POST":
        form = PostForm(request.POST, instance=post)
        if form.is_valid():
            form.save()
            messages.success(request, "기록을 수정했습니다.")
            return redirect("posts:detail", pk=post.pk)
        return _render_form(request, form, "edit", post, status=400)
    return _render_form(request, PostForm(instance=post), "edit", post)


@require_http_methods(["GET", "POST"])
@login_required
def post_delete(request, pk):
    post = get_object_or_404(owned_posts(request.user), pk=pk)
    if request.method == "POST":
        services.delete_post(post.pk, request.user)
        messages.success(request, "기록을 삭제했습니다.")
        return redirect("posts:list")
    return render(request, "posts/confirm_delete.html", {"post": post})


def _render_form(request, form, mode, post, status=200):
    return render(request, "posts/form.html", {"form": form, "mode": mode, "post": post}, status=status)
