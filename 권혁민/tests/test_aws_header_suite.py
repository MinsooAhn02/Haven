import copy
import types
from pathlib import Path

import pytest
import requests

import request_verify as rv

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
SUITE = FIXTURES / "cases_aws_header.json"
TARGET = "https://orchestration-haven.cloud"


def suite():
    data = rv.load_json(SUITE)
    rv.validate_suite(data, FIXTURES)
    return data


def case_by_id(data, case_id):
    return next(c for c in data["cases"] if c["case_id"] == case_id)


def test_header_suite_is_valid_for_aws():
    rv.validate_aws_cleanup_suite(rv.expand_suite_variants(suite(), FIXTURES))


def test_header_suite_is_anonymous_get_only():
    for case in suite()["cases"]:
        assert case["method"] == "GET"
        assert case["auth_role"] == "anonymous"
        assert case["request_headers"]


def test_paths_are_accepted_by_path_validation():
    for case in suite()["cases"]:
        rv.validate_path(case["path"])


@pytest.mark.parametrize("bad", [
    {"Cookie": "sessionid=x"},
    {"X-Amzn-Trace-Id": "Root=1-00000000-000000000000000000000000"},
    {"X-Haven-Run-ID": "x"},
    {"User-Agent": "a\r\nX-Injected: 1"},
    {"User-Agent": "한글"},
    {"User-Agent": "x" * 257},
    {"Host": None},
    {},
])
def test_rejects_unsafe_request_headers(bad):
    data = suite()
    data["cases"][0]["request_headers"] = bad
    with pytest.raises(rv.ConfigError):
        rv.validate_suite(data, FIXTURES)


@pytest.mark.parametrize("change", [
    {"method": "POST", "input_reference": "post_empty_valid.json"},
    {"auth_role": "member_a"},
])
def test_request_headers_only_for_anonymous_get(change):
    data = suite()
    data["cases"][0].update(change)
    with pytest.raises(rv.ConfigError):
        rv.validate_suite(data, FIXTURES)


def test_prepare_adds_headers_and_none_removes_user_agent():
    data = suite()
    case = copy.deepcopy(case_by_id(data, "HDR-NO-UA"))
    budget = rv.RequestBudget(types.SimpleNamespace(max_requests=10, rate=10, max_duration=60, timeout=5))
    fields, headers, file_info = rv.prepare_case_request(
        requests.Session(), case, FIXTURES, TARGET, budget, "run", [], 1024
    )
    assert fields is None and file_info is None
    assert headers[rv.RUN_ID_HEADER] == "run"
    prepared = requests.Session().prepare_request(
        requests.Request("GET", TARGET + case["path"], headers=headers)
    )
    # urllib3가 기본 User-Agent를 넣지 않도록 생략 표시가 전달되어야 한다.
    assert prepared.headers["User-Agent"] == rv.SKIP_HEADER


def test_host_header_override_keeps_target_url():
    case = copy.deepcopy(case_by_id(suite(), "HDR-HOST-LOCALHOST"))
    budget = rv.RequestBudget(types.SimpleNamespace(max_requests=10, rate=10, max_duration=60, timeout=5))
    _, headers, _ = rv.prepare_case_request(
        requests.Session(), case, FIXTURES, TARGET, budget, "run", [], 1024
    )
    prepared = requests.Session().prepare_request(
        requests.Request("GET", TARGET + case["path"], headers=headers)
    )
    assert prepared.headers["Host"] == "localhost"
    assert prepared.url.startswith(TARGET + "/")
