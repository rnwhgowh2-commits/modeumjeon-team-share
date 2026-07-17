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
    """대량등록 페이지에서 '대량등록' 카드만 on, 모음전은 off."""
    html = client.get('/bulk/').get_data(as_text=True)
    # 모드 카드 3개가 모두 있다
    assert '대량등록' in html
    assert '모음전' in html
    assert '재고관리' in html
    # 대량등록 링크에만 on
    assert 'href="/bulk/" class="sb-mode on"' in html
    assert 'href="/" class="sb-mode on"' not in html, '모음전이 잘못 켜졌다(부정조건 버그)'


def test_bundles_page_marks_bundles_mode_on(client):
    """모음전 페이지에서는 모음전이 켜져야 한다 (전역 기본값 'bundles')."""
    html = client.get('/').get_data(as_text=True)
    assert 'href="/" class="sb-mode on"' in html
    assert 'href="/bulk/" class="sb-mode on"' not in html


def test_unknown_tab_falls_back_to_default(client):
    """?tab=zzz 가 빈 화면 200 을 내지 않는다 — 모르는 탭은 manual 로."""
    html = client.get('/bulk/?tab=zzz').get_data(as_text=True)
    assert '준비 중' in html
    assert '<a class="nav-item active" href="/bulk/?tab=manual">' in html


def test_inventory_page_marks_inventory_mode_on(client):
    """재고관리 사이드바가 하드코딩 on 을 잃고 active_app 의존으로 바뀌었다 — 회귀 방지."""
    html = client.get('/inventory/').get_data(as_text=True)
    assert 'href="/inventory/" class="sb-mode on"' in html
    assert 'href="/" class="sb-mode on"' not in html
