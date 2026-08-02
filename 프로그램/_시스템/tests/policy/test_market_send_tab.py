# -*- coding: utf-8 -*-
"""「자동화」 분류 → 「상품 마켓 전송」 + 하위탭 2개.

🔴 이 파일이 지키는 것 — **하위탭 원천이 두 곳**이라는 사실.
   화면 가로탭(`market_send.SUBTABS`)만 고치면 상단 메뉴는 옛것으로 남는다.
   optgen 하위탭 때 실제로 그렇게 됐다(사장님이 라이브에서 잡음).
"""
import os

import pytest

os.environ.setdefault('DISABLE_AUTH', '1')

from webapp.routes import api_sidebar as SB          # noqa: E402
from webapp.routes.market_send import SUBTABS         # noqa: E402


def _stage(layout, sid):
    return next((s for s in layout['stages'] if s['id'] == sid), None)


# ── 두 원천이 같은 것을 말하는가 ────────────────────────────────────────

def test_상단메뉴와_화면_가로탭이_같은_순서다():
    """한쪽만 고치면 메뉴가 옛것으로 남는다 — 그 사고를 여기서 막는다."""
    메뉴_주소 = [SB._ITEM_DEFS[i]['url'] for i in SB._SEND2]
    화면_주소 = [t['url'] for t in SUBTABS]
    assert 메뉴_주소 == 화면_주소, f'메뉴 {메뉴_주소} vs 화면 {화면_주소}'


def test_기본_레이아웃에_하위탭_2개가_들어있다():
    st = _stage(SB._default_layout(), 's_auto')
    assert st is not None
    assert st['name'] == '상품 마켓 전송'
    assert [i['id'] for i in st['items']] == ['i_market_send', 'i_automation']


def test_자동화_이름은_저장본을_이긴다():
    """라이브에 저장된 옛 이름(「수집·전송 자동화」)이 이기면 개명이 안 보인다."""
    assert 'i_automation' in SB._FORCE_RENAME
    got = SB._item('i_automation', {'name': '수집·전송 자동화', 'emoji': '🌀'})
    assert got['name'] == '자동화'


# ── 저장본 갈아끼우기 ──────────────────────────────────────────────────

def test_옛_저장본을_갈아끼운다():
    old = {'standalone': [], 'stages': [
        {'id': 's_auto', 'emoji': '⚙️', 'name': '자동화', 'color': '#8B5CF6',
         'items': [{'id': 'i_automation', 'emoji': '⚙️', 'name': '수집·전송 자동화'}]}]}
    assert SB._migrate_send2(old) is True
    st = _stage(old, 's_auto')
    assert st['name'] == '상품 마켓 전송'
    assert [i['id'] for i in st['items']] == ['i_market_send', 'i_automation']


def test_두_번_돌려도_안전하다():
    old = {'standalone': [], 'stages': [
        {'id': 's_auto', 'emoji': '⚙️', 'name': '자동화', 'color': '#8B5CF6',
         'items': [{'id': 'i_automation', 'emoji': '⚙️', 'name': '수집·전송 자동화'}]}]}
    SB._migrate_send2(old)
    assert SB._migrate_send2(old) is False        # 두 번째는 아무것도 안 한다
    ids = [i['id'] for i in _stage(old, 's_auto')['items']]
    assert ids == ['i_market_send', 'i_automation'], '중복으로 들어갔다'


def test_s_auto_가_없는_저장본도_받는다():
    """옛 레이아웃엔 분류째로 없을 수 있다 — 그때도 만들어 넣어야 한다."""
    old = {'standalone': [], 'stages': [{'id': 's_etc', 'name': '기타', 'items': []}]}
    assert SB._migrate_send2(old) is True
    assert _stage(old, 's_auto') is not None


# ── 화면 ───────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    from tests.design.conftest import _build_isolated_app, _원래대로_되돌리기
    app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(tmp_path, monkeypatch)
    import sys as _sys
    for _m in list(_sys.modules.values()):
        if _m is None:
            continue
        try:
            if getattr(_m, 'SessionLocal', None) is o_s:
                monkeypatch.setattr(_m, 'SessionLocal', temp_session)
        except Exception:       # noqa: BLE001
            pass
    with app.test_client() as c:
        c._Session = temp_session
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()


def test_마켓전송_화면이_열린다(client):
    r = client.get('/market-send')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert '상품 마켓 전송' in html
    assert 'ms-tab' in html


def test_두_화면_모두_하위탭_2개를_보여준다(client):
    """옆 탭으로 오갈 수 없으면 하위탭이 아니라 그냥 딴 화면이다."""
    for url in ('/market-send', '/automation'):
        html = client.get(url).get_data(as_text=True)
        assert html.count('class="ms-tab') >= 2, f'{url} 에 하위탭이 없다'
        assert '/market-send' in html and '/automation' in html, url


def test_아직_안_만든_화면이라고_말한다(client):
    """빈 화면을 그냥 두면 「고장났나」로 헤맨다."""
    html = client.get('/market-send').get_data(as_text=True)
    assert '아직 만드는 중' in html
    assert '자동화로 가기' in html


def test_자동화_화면은_그대로_돈다(client):
    """탭을 얹었다고 원래 기능이 깨지면 안 된다."""
    html = client.get('/automation').get_data(as_text=True)
    assert '자동화 설정' in html
    assert 'au-root' in html
