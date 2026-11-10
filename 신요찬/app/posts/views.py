"""기록 화면 (앱계약.md 3·5장, 2회차 화면 계약).

- 수정·삭제·공유 관리는 permissions.owned_posts()로만 찾는다(소유자만).
- 상세는 readable_posts(), 공유받은 목록은 shared_posts()로 찾는다.
- 권한이 없는 글과 없는 글은 모두 404.
- 입력 검증 실패는 400, 성공한 POST는 302(PRG).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import services
from .forms import PostForm, ShareForm
from .models import PostShare
from .permissions import owned_posts, readable_posts, shared_posts

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
    """지금 공유받은 기록만. 해제됐거나 소유자가 비활성인 글은 빠진다(명세 3.3)."""
    return render(request, "posts/shared_list.html", _page(request, shared_posts(request.user)))


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
    post = get_object_or_404(readable_posts(request.user).select_related("owner"), pk=pk)
    # is_owner가 거짓이면 공유받은 읽기 전용 화면이다(2회차 화면 계약 6장).
    return render(request, "posts/detail.html", {"post": post, "is_owner": post.owner_id == request.user.pk})


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


@require_http_methods(["GET", "POST"])
@login_required
def post_shares(request, pk):
    """공유 관리: 소유자만. 공유 대상·다른 회원은 404(명세 SH-02)."""
    post = get_object_or_404(owned_posts(request.user), pk=pk)
    status = 200
    if request.method == "POST":
        form = ShareForm(request.POST, owner=request.user)
        if form.is_valid():
            _, created = PostShare.objects.get_or_create(post=post, recipient=form.recipient)
            if created:
                messages.success(request, "공유했습니다.")
            else:
                messages.info(request, "이미 공유 중인 사용자입니다.")
            return redirect("posts:shares", pk=post.pk)
        status = 400
    else:
        form = ShareForm(owner=request.user)
    shares = post.shares.select_related("recipient").order_by("-created_at", "-id")
    return render(request, "posts/shares.html", {"post": post, "form": form, "shares": shares}, status=status)


@require_POST
@login_required
def share_revoke(request, pk, share_id):
    """공유 해제: 소유자만, share_id가 이 글의 공유인지 다시 확인한다(명세 SH-05). 해제는 행 삭제."""
    post = get_object_or_404(owned_posts(request.user), pk=pk)
    share = get_object_or_404(PostShare, pk=share_id, post=post)
    share.delete()
    messages.success(request, "공유를 해제했습니다.")
    return redirect("posts:shares", pk=post.pk)


def _render_form(request, form, mode, post, status=200):
    return render(request, "posts/form.html", {"form": form, "mode": mode, "post": post}, status=status)
