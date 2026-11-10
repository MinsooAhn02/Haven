"""기록 화면 (앱계약.md 3·5장, 2회차 화면 계약).

- 수정·삭제·공유 관리는 permissions.owned_posts()로만 찾는다(소유자만).
- 상세는 readable_posts(), 공유받은 목록은 shared_posts()로 찾는다.
- 권한이 없는 글과 없는 글은 모두 404.
- 입력 검증 실패는 400, 성공한 POST는 302(PRG).
- 첨부(3회차): 업로드·삭제는 owned_posts(), 다운로드는 readable_posts()와 ACTIVE 첨부만(명세 3.4).
"""
from django.http import FileResponse, Http404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import attachments, services
from .forms import AttachmentForm, PostForm, ShareForm
from .models import Attachment, PostShare
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
    return _render_detail(request, post)


def _render_detail(request, post, attachment_form=None, status=200):
    # is_owner가 거짓이면 공유받은 읽기 전용 화면이다(2회차 화면 계약 6장). 업로드 폼은 소유자에게만.
    is_owner = post.owner_id == request.user.pk
    context = {
        "post": post,
        "is_owner": is_owner,
        "attachments": post.attachments.filter(status=Attachment.Status.ACTIVE),
        "attachment_form": (attachment_form or AttachmentForm()) if is_owner else None,
        "attachment_limits": {
            "max_file_bytes": attachments.MAX_FILE_BYTES,
            "max_files_per_post": attachments.MAX_FILES_PER_POST,
            "max_bytes_per_owner": attachments.MAX_BYTES_PER_OWNER,
        },
    }
    return render(request, "posts/detail.html", context, status=status)


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


@require_POST
@login_required
def attachment_upload(request, pk):
    """첨부 업로드: 소유자의 ACTIVE 글만(그 외 404). 형식·개수·용량 400, 파일 크기 413(명세 3.4)."""
    post = get_object_or_404(owned_posts(request.user).select_related("owner"), pk=pk)
    form = AttachmentForm(request.POST, request.FILES)
    if getattr(request, "unsafe_upload_name", False):
        # 경로 구분자·제어문자·".." 등이 든 파일 이름(Django가 고치기 전 원래 이름 기준). 명세 3.4: 400
        form.add_error(None, "파일 이름을 확인해 주세요.")
    if not form.is_valid():
        return _render_detail(request, post, form, status=400)
    try:
        attachment = attachments.upload(request.user, post.pk, form.cleaned_data["attachment"])
    except attachments.AttachmentRejected as exc:
        form.add_error("attachment", exc.message)
        return _render_detail(request, post, form, status=exc.status)
    if attachment is None:  # 처리 중 글이 삭제됐거나 소유자가 바뀐 경우
        raise Http404
    messages.success(request, "첨부를 올렸습니다.")
    return redirect("posts:detail", pk=post.pk)


@require_GET
@login_required
def attachment_download(request, pk, attachment_id):
    """다운로드: 소유자 또는 지금 공유받은 사람, ACTIVE 첨부만. 다른 글의 첨부 id는 404(명세 3.4)."""
    post = get_object_or_404(readable_posts(request.user), pk=pk)
    attachment = get_object_or_404(Attachment, pk=attachment_id, post=post, status=Attachment.Status.ACTIVE)
    response = FileResponse(
        attachments.open_for_download(attachment),
        as_attachment=True,
        filename=attachment.original_name,  # Django가 RFC 6266/5987 형식으로 인코딩한다
        content_type=attachment.content_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
@login_required
def attachment_delete(request, pk, attachment_id):
    """첨부 삭제: 소유자만. DELETE_PENDING으로 먼저 막고 파일을 정리한다(정리 실패는 재시도 대상)."""
    attachment = attachments.mark_delete_pending(pk, attachment_id, request.user)
    if attachment is None:
        raise Http404
    attachments.purge(attachment)
    messages.success(request, "첨부를 삭제했습니다.")
    return redirect("posts:detail", pk=pk)


def _render_form(request, form, mode, post, status=200):
    return render(request, "posts/form.html", {"form": form, "mode": mode, "post": post}, status=status)
