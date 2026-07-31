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


def test_스펙의_수집단계는_옵션생성_상품생성_하나뿐이다():
    spec = {s[0]: s for s in SB._STAGE_SPEC}
    sid, emoji, name, color, ids = spec['s_collect']
    assert name == '옵션생성 & 상품생성'
    assert ids == ['i_optgen']


def test_스펙의_상품관리에_모음전_상품관리와_옵션관리가_들어간다():
    spec = {s[0]: s for s in SB._STAGE_SPEC}
    ids = spec['s_catalog'][4]
    assert ids == ['i_bundles', 'i_matrix', 'i_catalog']


def test_삭제확정_3개는_렌더에서_걸러진다():
    """신규 모음전 등록·기존 마켓 연동·판매처 연동 — 사장님 확정 삭제."""
    for iid in ('i_new', 'i_migrate', 'i_sets_dash'):
        assert iid in SB._REMOVED_IDS


def test_옮긴_항목은_이름이_강제로_바뀐다():
    """사장님이 예전에 고쳐둔 이름이 남아 있어도 새 이름으로 보여야 한다."""
    for iid in ('i_bundles', 'i_matrix', 'i_catalog'):
        assert iid in SB._FORCE_RENAME
    assert SB._ITEM_DEFS['i_bundles']['name'] == '모음전 상품관리'
    assert SB._ITEM_DEFS['i_matrix']['name'] == '모음전 옵션관리'
    assert SB._ITEM_DEFS['i_catalog']['name'] == '마켓 상품 현황'
    assert SB._ITEM_DEFS['i_optgen']['url'] == '/optgen'


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
    assert _ids(layout, 's_collect') == ['i_optgen']
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
    assert names['i_bundles'] == '모음전 상품관리'
    assert names['i_matrix'] == '모음전 옵션관리'
    assert names['i_optgen'] == '옵션생성 & 상품생성'
