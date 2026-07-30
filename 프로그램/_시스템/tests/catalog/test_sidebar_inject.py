# -*- coding: utf-8 -*-
"""상품관리 메뉴는 「없으면 주입」이어야 한다.

★ [2026-07-24 라이브에서 발견] data/sidebar_layout.json 만 고쳤더니 라이브 사이드바에
  메뉴가 **아예 안 떴다**. 서버는 사장님이 드래그로 바꾼 저장본을 쓰기 때문.
  사장님이 URL 을 직접 치지 않으면 이 화면에 들어갈 수 없었다.
"""
from webapp.routes import api_sidebar as SB


def _layout_without_catalog():
    """사장님이 커스터마이징해 상품관리가 없는 저장본을 흉내낸다."""
    return {
        'version': 1, 'standalone': [],
        'stages': [
            {'id': 's_bundles', 'name': '모음전 구성', 'items': []},
            {'id': 's_sell', 'name': '판매', 'items': [
                {'id': 'i_orders', 'name': '주문 내역', 'url': '/orders/'},
                {'id': 'i_margin', 'name': '마진 계산기', 'url': '/orders/?tab=margin'},
            ]},
            {'id': 's_etc', 'name': '기타', 'items': []},
        ],
    }


def _items(out, stage_id):
    for st in out.get('stages', []):
        if st.get('id') == stage_id:
            return st.get('items', [])
    return []


def test_저장본에_없으면_주입된다(monkeypatch):
    monkeypatch.setattr(SB, '_load', _layout_without_catalog)
    out = SB.get_layout_for_template()
    sell = _items(out, 's_sell')
    got = [i for i in sell if i.get('id') == 'i_catalog']
    assert got, '상품관리 메뉴가 주입되지 않았다 — 사장님이 화면에 못 들어간다'
    assert got[0]['url'] == '/catalog/'
    assert got[0]['name'] == '상품관리'


def test_판매_그룹_맨_앞에_온다(monkeypatch):
    """주문·송장·마진보다 먼저 보는 화면이라 맨 앞."""
    monkeypatch.setattr(SB, '_load', _layout_without_catalog)
    sell = _items(SB.get_layout_for_template(), 's_sell')
    assert sell[0]['id'] == 'i_catalog'


def test_이미_있으면_두_번_넣지_않는다(monkeypatch):
    """사장님이 옮겨둔 자리를 덮어쓰거나 중복으로 늘리면 안 된다."""
    lay = _layout_without_catalog()
    lay['stages'][1]['items'].append(
        {'id': 'i_catalog', 'name': '상품관리', 'url': '/catalog/'})
    monkeypatch.setattr(SB, '_load', lambda: lay)
    sell = _items(SB.get_layout_for_template(), 's_sell')
    assert len([i for i in sell if i.get('id') == 'i_catalog']) == 1
    assert sell[-1]['id'] == 'i_catalog', '사장님이 둔 자리를 옮겨버렸다'


def test_판매_그룹이_없어도_터지지_않는다(monkeypatch):
    """사장님이 그룹을 지웠을 수도 있다 — 그래도 앱이 떠야 한다."""
    lay = _layout_without_catalog()
    lay['stages'] = [st for st in lay['stages'] if st['id'] != 's_sell']
    monkeypatch.setattr(SB, '_load', lambda: lay)
    out = SB.get_layout_for_template()
    assert isinstance(out.get('stages'), list)
