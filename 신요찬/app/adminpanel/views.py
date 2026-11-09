"""제한된 계정 관리 화면 (명세 2.2, 2회차 화면 계약 3·4장).

- 운영 관리자만 접근. 일반 회원 403, 비로그인 302.
- 계정 목록에는 username, is_active, date_joined, last_login만 넘긴다(비밀번호·이메일·본문 없음).
- 운영 관리자·최고 관리자·자기 자신은 상태 변경 대상이 아니다.
"""
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import services
from .permissions import is_manageable_member, operator_required

PAGE_SIZE = 20
STATUS_VALUES = {"true": True, "false": False}


@require_GET
@operator_required
def account_list(request):
    members = (
        get_user_model()
        .objects.filter(is_staff=False, is_superuser=False)
        .only("username", "is_active", "date_joined", "last_login")
        .order_by("username", "id")
    )
    page_obj = Paginator(members, PAGE_SIZE).get_page(request.GET.get("page"))
    accounts = [
        SimpleNamespace(
            pk=u.pk,
            username=u.username,
            is_active=u.is_active,
            date_joined=u.date_joined,
            last_login=u.last_login,
        )
        for u in page_obj.object_list
    ]
    return render(request, "adminpanel/accounts.html", {"accounts": accounts, "page_obj": page_obj})


@require_POST
@operator_required
def account_status(request, pk):
    target = get_object_or_404(get_user_model(), pk=pk)
    is_active = STATUS_VALUES.get(request.POST.get("is_active", ""))
    if is_active is None or not is_manageable_member(target) or target.pk == request.user.pk:
        return render(request, "400.html", status=400)
    changed = services.set_account_status(request.user, target, is_active)
    if changed:
        verb = "활성화" if is_active else "비활성화"
        messages.success(request, f"{target.get_username()} 계정을 {verb}했습니다.")
    else:
        messages.info(request, f"{target.get_username()} 계정은 이미 {services.STATE_LABEL[is_active]} 상태입니다.")
    return redirect("adminpanel:accounts")


@require_GET
@operator_required
def account_events(request):
    page_obj = Paginator(services.account_events(), PAGE_SIZE).get_page(request.GET.get("page"))
    events = [SimpleNamespace(**services.parse_event(e)) for e in page_obj.object_list]
    return render(request, "adminpanel/account_events.html", {"events": events, "page_obj": page_obj})
