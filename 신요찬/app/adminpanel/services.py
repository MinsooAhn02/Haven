"""계정 상태 변경과 감사 기록 (명세 3.2).

상태 변경과 성공 감사 레코드(Django LogEntry)는 하나의 DB transaction으로 처리한다.
감사 저장이 실패하면 상태 변경도 취소된다. change_message에는 변경 전후 상태만 남긴다.
"""
import json

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

# 이력 화면이 계정 상태 변경만 골라내기 위한 표시
EVENT_KEY = "account_status"
STATE_LABEL = {True: "활성", False: "비활성"}


def account_events():
    """계정 상태 변경 LogEntry만, 최신순."""
    user_ct = ContentType.objects.get_for_model(get_user_model())
    return (
        LogEntry.objects.filter(
            content_type=user_ct,
            action_flag=CHANGE,
            change_message__startswith='{"' + EVENT_KEY + '"',
        )
        .select_related("user")
        .order_by("-action_time", "-id")
    )


def parse_event(entry):
    data = json.loads(entry.change_message)[EVENT_KEY]
    return {
        "action_time": entry.action_time,
        "actor_username": entry.user.username,
        "target_username": entry.object_repr,
        "before": STATE_LABEL[data["before"]],
        "after": STATE_LABEL[data["after"]],
    }


@transaction.atomic
def set_account_status(actor, target, is_active):
    """target의 활성 상태를 바꾸고 감사 기록을 남긴다. 바뀌지 않았으면 False."""
    User = get_user_model()
    locked = User.objects.select_for_update().get(pk=target.pk)
    before = locked.is_active
    if before == is_active:
        return False
    User.objects.filter(pk=locked.pk).update(is_active=is_active)
    LogEntry.objects.create(
        user=actor,
        content_type=ContentType.objects.get_for_model(User),
        object_id=str(locked.pk),
        object_repr=locked.get_username()[:200],
        action_flag=CHANGE,
        change_message=json.dumps({EVENT_KEY: {"before": before, "after": is_active}}),
    )
    return True
