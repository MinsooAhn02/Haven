import json

import pytest

import request_verify as rv


ROOT = "1-6afa5821-3594cf6aaebd448c933fab1a"
PREFIX = (
    "2026-11-16T01:10:58.135132+00:00 "
    "ip-WEB1-MASKED gunicorn[1479]: "
)
EVENT = {
    "ts": "2026-11-16T01:10:58.134Z",
    "trace_id": ROOT,
    "run_id": "f3aeb054-5f30-4c37-b939-366347d9a1a9",
    "status": 200,
}


def test_gunicorn_message_selected_without_changing_evidence():
    raw = {
        "logStreamName": "i-0123456789abcdef0/app",
        "message": PREFIX + json.dumps(EVENT),
    }
    state = {"results": [{"trace_id": "Root=" + ROOT}]}

    result = rv.select_cloudwatch_run_logs(
        [raw], state, allow_app_prefix=True
    )

    assert result["events"] == [EVENT]
    assert result["counts"]["selected"] == 1
    assert result["counts"]["non_json"] == 0


def test_plain_json_still_supported():
    raw = {"message": json.dumps(EVENT)}

    assert rv.parse_cloudwatch_message(raw) == EVENT


@pytest.mark.parametrize(
    "stream,message,enabled",
    [
        ("i-abc/app", PREFIX + json.dumps(EVENT), False),
        ("i-abc/nginx-access", PREFIX + json.dumps(EVENT), True),
        ("i-abc/app", "arbitrary text " + json.dumps(EVENT), True),
        ("i-abc/app", PREFIX + json.dumps(EVENT) + " trailing", True),
        ("i-abc/app", PREFIX + '{"status":}', True),
    ],
)
def test_unsupported_message_is_rejected(stream, message, enabled):
    raw = {"logStreamName": stream, "message": message}

    with pytest.raises(ValueError):
        rv.parse_cloudwatch_message(
            raw, allow_app_prefix=enabled
        )