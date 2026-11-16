import pytest

import request_verify as rv


NAV = """
<nav aria-label="주요 메뉴">
  <ul>
    <li><a href="/posts/">내 기록</a></li>
    <li>
      <form method="post" action="/accounts/logout/">
        <button>로그아웃</button>
      </form>
    </li>
  </ul>
</nav>
"""


def test_cleanup_ignores_navigation_on_empty_share_page(monkeypatch):
    html = (
        NAV
        + """
        <section aria-labelledby="share-list-heading">
          <h2 id="share-list-heading">현재 공유 대상</h2>
          <section class="empty-state">
            <h3>아직 공유한 사용자가 없습니다</h3>
          </section>
        </section>
        """
    ).encode("utf-8")
    calls = []

    def fake_send(*args, **kwargs):
        calls.append((args[1], args[3]))
        return {"status": 200}, html

    monkeypatch.setattr(rv, "bounded_send", fake_send)
    events = []

    count = rv.cleanup_post_shares(
        object(), 11,
        "https://orchestration-haven.cloud:443",
        object(), "test-run", [], 65536, events,
    )

    assert count == 0
    assert calls == [("GET", "/posts/11/shares/")]
    assert len(events) == 1


def test_navigation_does_not_hide_real_share():
    html = (
        NAV
        + """
        <section aria-labelledby="share-list-heading">
          <h2 id="share-list-heading">현재 공유 대상</h2>
          <ul class="record-list">
            <li class="record-row">
              <h3 class="record-title">member_b</h3>
              <form method="post"
                    action="/posts/11/shares/23/revoke/">
              </form>
            </li>
          </ul>
        </section>
        """
    ).encode("utf-8")

    parser = rv.ShareHtmlParser(11, "member_b")
    parser.feed(html.decode("utf-8"))
    parser.close()

    assert len(parser.rows) == 1
    assert parser.share_id() == 23


def test_member_password_prompted_once_per_execution(monkeypatch):
    prompts = []
    answers = iter(["first-password", "second-password"])

    def fake_getpass(prompt):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr(rv.getpass, "getpass", fake_getpass)

    @rv.member_password_scope
    def execution():
        return [rv.aws_member_password() for _ in range(3)]

    assert execution() == ["first-password"] * 3
    assert execution() == ["second-password"] * 3
    assert len(prompts) == 2
    assert rv._MEMBER_PASSWORDS.get() is None


def test_member_password_scope_cleared_after_error(monkeypatch):
    monkeypatch.setattr(rv.getpass, "getpass", lambda _: "test-password")
    caches = []

    @rv.member_password_scope
    def execution():
        rv.aws_member_password()
        caches.append(rv._MEMBER_PASSWORDS.get())
        raise rv.ExecutionError("test error")

    with pytest.raises(rv.ExecutionError):
        execution()

    assert caches == [{}]
    assert rv._MEMBER_PASSWORDS.get() is None