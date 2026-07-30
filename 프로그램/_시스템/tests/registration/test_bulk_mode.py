# -*- coding: utf-8 -*-
"""대량등록 모드 — 블루프린트 + 모드 활성 판정."""
import pytest


@pytest.fixture
def client(monkeypatch):
    # 이 저장소의 라우트 테스트 관례 (tests/margin/test_margin_ui_routes.py:10-16)
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_bulk_route_exists(client):
    """/bulk/ 가 200 을 준다."""
    r = client.get('/bulk/')
    assert r.status_code == 200


def test_bulk_page_marks_bulk_mode_on(client):
    """대량등록 페이지에서 '대량등록' 카드만 on, 모음전은 off.

    [2026-07-30] 모드 전환이 **「모음전 ↔ 대량등록」 2개**로 줄었다(사장님 확정).
      재고관리는 모드가 아니라 사이드바 ⑦ 항목으로 내려갔다.
    """
    html = client.get('/bulk/').get_data(as_text=True)
    assert '대량등록' in html
    assert '모음전' in html
    # 대량등록 링크에만 on
    assert 'href="/bulk/" class="sb-mode on"' in html
    assert 'href="/" class="sb-mode on"' not in html, '모음전이 잘못 켜졌다(부정조건 버그)'


def test_모드_전환은_두_개다(client):
    """재고관리를 모드에서 뺐다 — 다시 3개가 되면 사장님 확정과 어긋난다."""
    import re
    html = client.get('/bulk/').get_data(as_text=True)
    # ★ 'sb-mode-ic'·'sb-mode-nm' 같은 하위 클래스가 있어 단순 문자열 세기는 부풀려진다.
    links = re.findall(r'<a href="([^"]+)" class="sb-mode[ "]', html)
    assert sorted(links) == ['/', '/bulk/'], f'모드 카드가 달라졌다: {links}'


def test_bundles_page_marks_bundles_mode_on(client):
    """모음전 페이지에서는 모음전이 켜져야 한다 (전역 기본값 'bundles')."""
    html = client.get('/').get_data(as_text=True)
    assert 'href="/" class="sb-mode on"' in html
    assert 'href="/bulk/" class="sb-mode on"' not in html


def test_unknown_tab_falls_back_to_default(client):
    """?tab=zzz 가 빈 화면 200 을 내지 않는다 — 모르는 탭은 manual 로.

    [Task 9] manual 탭이 '준비 중' 플레이스홀더 → 실제 수기 폼으로 바뀌었다.
    폴백이 여전히 manual 을 렌더하는지는 폼(bulk-manual-form)으로 확인한다.
    """
    html = client.get('/bulk/?tab=zzz').get_data(as_text=True)
    assert 'id="bulk-manual-form"' in html
    assert '<a class="nav-item active" href="/bulk/?tab=manual">' in html


def test_재고관리_화면에서는_어느_모드도_안_켜진다(client):
    """[2026-07-30] 재고관리는 이제 모드가 아니다 — 자기 사이드바가 「재고관리 모드」임을
    따로 표시하므로, 모음전이 잘못 켜지지만 않으면 된다."""
    html = client.get('/inventory/').get_data(as_text=True)
    assert 'href="/" class="sb-mode on"' not in html, '모음전이 잘못 켜졌다'
    assert 'href="/bulk/" class="sb-mode on"' not in html, '대량등록이 잘못 켜졌다'
    assert '재고관리 모드' in html, '어느 모드인지 화면이 말해줘야 한다'
