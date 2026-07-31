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
