# -*- coding: utf-8 -*-
"""「옵션생성 & 상품생성」 1단계 — 사이드바 재편이 라이브에 도달하는지 지킨다.

★ 스펙(_STAGE_SPEC)만 고치면 라이브에 안 나온다. 서버는 사장님이 드래그로
  저장한 레이아웃을 쓰기 때문(api_sidebar.py:187 실사고 기록).
  그래서 스펙·저장본 마이그레이션·렌더 필터 셋을 다 지킨다.
"""
from webapp.routes import api_sidebar as SB


def _stage(out, sid):
    for st in out.get('stages', []):
        if st.get('id') == sid:
            return st
    return None


def _ids(out, sid):
    st = _stage(out, sid)
    return [it.get('id') for it in (st or {}).get('items', [])]


def test_스펙의_수집단계는_노션_하위탭_3개다():
    """[2026-08-02] 합본 1개였다 — 사장님이 「메뉴에 3개 떠야 한다」고 잡았다.

    자세한 계약은 tests/test_optgen_subtabs3.py. 여기서는 스펙 자리만 지킨다.
    """
    spec = {s[0]: s for s in SB._STAGE_SPEC}
    sid, emoji, name, color, ids = spec['s_collect']
    assert name == '옵션생성 & 상품생성'
    assert ids == ['i_optgen_direct', 'i_optgen_market', 'i_optgen_product']


def test_스펙의_상품관리에_옵션관리와_상품관리가_들어간다():
    """[2026-08-12 노션 b항] 순서를 옵션 먼저로 뒤집었다.
    개명·재정렬 계약 전체는 tests/catalog/test_catalog_tabs_rename.py."""
    spec = {s[0]: s for s in SB._STAGE_SPEC}
    ids = spec['s_catalog'][4]
    assert ids == ['i_matrix', 'i_bundles', 'i_catalog']


def test_삭제확정_3개는_렌더에서_걸러진다():
    """신규 모음전 등록·기존 마켓 연동·판매처 연동 — 사장님 확정 삭제."""
    for iid in ('i_new', 'i_migrate', 'i_sets_dash'):
        assert iid in SB._REMOVED_IDS


def test_옮긴_항목은_이름이_강제로_바뀐다():
    """사장님이 예전에 고쳐둔 이름이 남아 있어도 새 이름으로 보여야 한다."""
    for iid in ('i_bundles', 'i_matrix', 'i_catalog'):
        assert iid in SB._FORCE_RENAME
    # [2026-08-12 노션 a항] 「모음전」을 뗐다.
    assert SB._ITEM_DEFS['i_bundles']['name'] == '상품관리'
    assert SB._ITEM_DEFS['i_matrix']['name'] == '옵션관리'
    assert SB._ITEM_DEFS['i_catalog']['name'] == '실마켓 상품 현황'
    assert SB._ITEM_DEFS['i_optgen_direct']['url'] == '/optgen?tab=direct'


def _old_saved():
    """1단계 전 라이브 저장본을 흉내낸다 — 사장님이 이름을 고쳐둔 상태까지."""
    return {
        'version': 1, 'schema': 8, 'standalone': [],
        'stages': [
            {'id': 's_collect', 'emoji': '📥', 'name': '상품수집·생성', 'items': [
                {'id': 'i_new', 'name': '신규 모음전 등록', 'url': '/bundles/new'},
                {'id': 'i_bundles', 'name': '내가 고친 이름', 'url': '/bundles'},
                {'id': 'i_matrix', 'name': '매트릭스 옵션', 'url': '/matrix'},
                {'id': 'i_migrate', 'name': '기존 마켓 연동', 'url': '/bundles/migrate'},
                {'id': 'i_sets_dash', 'name': '판매처 연동', 'url': '/api/sets/dashboard'},
            ]},
            {'id': 's_catalog', 'emoji': '📦', 'name': '상품 관리', 'items': [
                {'id': 'i_catalog', 'name': '상품관리', 'url': '/catalog/'},
            ]},
        ],
    }


def test_저장본이_재편된다():
    layout = _old_saved()
    assert SB._migrate_optgen(layout) is True
    assert _ids(layout, 's_collect') == ['i_optgen_direct', 'i_optgen_market',
                                         'i_optgen_product']
    assert _ids(layout, 's_catalog') == ['i_bundles', 'i_matrix', 'i_catalog']
    assert _stage(layout, 's_collect')['name'] == '옵션생성 & 상품생성'


def test_삭제확정_3개가_저장본에서도_사라진다():
    layout = _old_saved()
    SB._migrate_optgen(layout)
    left = {it.get('id') for st in layout['stages'] for it in st['items']}
    assert not ({'i_new', 'i_migrate', 'i_sets_dash'} & left)


def test_두_번_돌려도_같다():
    """마이그레이션은 매 요청마다 불린다 — 두 번째부터는 아무것도 안 해야 한다."""
    layout = _old_saved()
    SB._migrate_optgen(layout)
    snapshot = [(_stage(layout, s)['name'], _ids(layout, s))
                for s in ('s_collect', 's_catalog')]
    assert SB._migrate_optgen(layout) is False
    after = [(_stage(layout, s)['name'], _ids(layout, s))
             for s in ('s_collect', 's_catalog')]
    assert snapshot == after


def test_옮긴_뒤_화면에는_새_이름으로_뜬다(monkeypatch):
    """사장님이 고쳐둔 「내가 고친 이름」이 아니라 「모음전 상품관리」로 보여야 한다."""
    layout = _old_saved()
    SB._migrate_optgen(layout)
    monkeypatch.setattr(SB, '_load', lambda: layout)
    out = SB.get_layout_for_template()
    names = {it['id']: it['name']
             for st in out['stages'] for it in st['items']}
    assert names['i_bundles'] == '상품관리'
    assert names['i_matrix'] == '옵션관리'
    assert names['i_optgen_direct'] == '모음전 옵션 생성 (직접)'
    # 🔴 라이브에서 잡은 것 — 옮겨온 항목만 개명되고, 원래 그 자리에 있던
    #   i_catalog 는 옛 이름 그대로 떴다. 강제 개명은 저장본에
    #   **이미 있던** 항목에도 걸려야 한다.
    assert names['i_catalog'] == '실마켓 상품 현황'


import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_허브가_뜬다(client):
    r = client.get('/optgen')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert '옵션생성 &amp; 상품생성' in html or '옵션생성 & 상품생성' in html


def test_가로탭이_세_개다(client):
    """[2026-08-02] 두 개였다 — 노션 원문은 셋(직접 / 내마켓 / 상품 생성)."""
    html = client.get('/optgen').get_data(as_text=True)
    assert '모음전 옵션 생성 (직접)' in html
    assert '모음전 옵션 생성 (내마켓 불러오기)' in html
    assert '모음전 상품 생성' in html


def test_직접_탭에는_만들기_입구만_있다(client):
    """[2026-08-02] 한 탭에 카드 두 장이던 것을 탭 두 개로 갈랐다.
    [2026-08-04 사장님 확정 A4] 큰 「직접 만들기」 카드 → 목록 머리줄 오른쪽 단추."""
    html = client.get('/optgen?tab=direct').get_data(as_text=True)
    assert '옵션 매트릭스 생성' in html
    assert '상품명 · 상품번호로 찾기' not in html   # [2026-08-04] C4 placeholder


def test_모르는_탭은_옵션생성으로_돌아온다(client):
    """조용히 빈 화면을 그리지 않는다."""
    html = client.get('/optgen?tab=__없는탭__').get_data(as_text=True)
    assert '옵션 매트릭스 생성' in html


def test_만들기는_단추_눌러_창으로(client):
    """[2026-08-04 사장님 확정 A4] 만들기 = 머리줄 단추(ob-open) + 가운데 창(ob-back).

    큰 카드(og-card)는 없어졌고, 만들기 창은 direct 탭에만 있다 —
    내마켓 탭은 「마켓에서 상품 찾기」로 만들므로 단추가 없어야 헷갈리지 않는다.
    """
    html = client.get('/optgen?tab=direct').get_data(as_text=True)
    assert 'id="ob-open"' in html and 'id="ob-back"' in html
    assert 'og-card' not in html
    # 스크립트 글자가 아니라 **마크업**으로 잰다 — 열기 배선 JS는 두 탭이 같이 싣는다.
    m = client.get('/optgen?tab=market').get_data(as_text=True)
    assert 'id="ob-open"' not in m and 'id="ob-back"' not in m


def test_카드가_진짜_화면으로_이어진다(client):
    """[2026-08-01 갱신] 1단계에선 「자리만」이라 안내문(「지금은…」)을 지켰다.
    3·5단계에서 둘 다 진짜로 만들어졌으므로, 이제는 **실제로 이어지는지**를 지킨다.
    안내문만 남고 기능이 없으면 눌러도 아무 일이 안 일어난다.
    """
    assert 'ob-make' in client.get('/optgen?tab=direct').get_data(as_text=True)
    # [2026-08-02] 내마켓은 별도 화면이 아니라 탭 ② 안이다 — 찾기칸이 그 자리에 있어야 한다.
    assert 'im-go' in client.get('/optgen?tab=market').get_data(as_text=True)
