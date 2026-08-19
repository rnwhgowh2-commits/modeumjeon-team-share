# -*- coding: utf-8 -*-
"""[2026-08-19 사장님 확정] 「상품 가공」 → 「상품 정책화」 + 「정책 적용」 → 「정책 매칭」 개명.

★ 왜 시험이 이렇게 많나 — 이 프로젝트가 같은 자리에서 반복해서 넘어졌다.
  `_ITEM_DEFS`/`_STAGE_SPEC`(코드 상수)만 고치면 화면은 안 바뀐다. 서버가 읽는 건
  저장본(`data/sidebar_layout.json`)이고, `get_layout_for_template()` 은 저장본에
  **이미 있는** 항목을 `_item()` 을 안 거치고 그대로 통과시킨다 → `_FORCE_RENAME` 도
  분류(stage) 이름까지는 안 닿는다. (i_policies · i_automation · s_auto · 상품관리
  하위탭 때 반복된 그 자리 — `test_catalog_tabs_rename.py` 참조)
"""
from webapp.routes import api_sidebar as SB


def _stage(out, sid):
    for st in out.get('stages', []):
        if st.get('id') == sid:
            return st
    return None


# ── ① 상수 ────────────────────────────────────────────────────

def test_상수_이름이_바뀌었다():
    assert SB._ITEM_DEFS['i_policy_apply']['name'] == '정책 매칭'
    spec = {s[0]: s for s in SB._STAGE_SPEC}
    assert spec['s_process'][2] == '상품 정책화'


def test_개명_대상에_그대로_들어_있다():
    assert 'i_policy_apply' in SB._FORCE_RENAME


def test_주소와_활성키는_안_건드린다():
    """이름만 바꾼다 — url·active_key 를 건드리면 모바일 메뉴·강조표시가 깨진다."""
    assert SB._ITEM_DEFS['i_policy_apply']['url'] == '/policies/apply'
    assert SB._ITEM_DEFS['i_policy_apply']['active_key'] == 'policy_apply'


# ── ② 저장본 마이그레이션 ─────────────────────────────────────

def _live_saved():
    """개명 전 라이브 저장본을 그대로 흉내낸다(data/sidebar_layout.json 기준)."""
    return {
        'version': 1, 'schema': SB._SCHEMA, 'standalone': [],
        'stages': [
            {'id': 's_process', 'emoji': '🔧', 'name': '상품 가공', 'color': '#F59E0B',
             'items': [
                 {'id': 'i_policies', 'emoji': '🔧', 'name': '정책 생성',
                  'url': '/policies', 'active_key': 'policies'},
                 {'id': 'i_policy_apply', 'emoji': '🧩', 'name': '정책 적용',
                  'url': '/policies/apply', 'active_key': 'policy_apply'},
             ]},
        ],
    }


def test_저장본_이름이_갈아끼워진다():
    layout = _live_saved()
    assert SB._migrate_process_rename(layout) is True
    proc = _stage(layout, 's_process')
    assert proc['name'] == '상품 정책화'
    names = {it['id']: it['name'] for it in proc['items']}
    assert names == {'i_policies': '정책 생성', 'i_policy_apply': '정책 매칭'}


def test_개명은_어긋나면_다시_고치고_맞으면_안_건드린다():
    """개명은 **늘** 다시 걸어야 한다 — 저장본이 어긋나도 스스로 낫게."""
    layout = _live_saved()
    assert SB._migrate_process_rename(layout) is True
    assert SB._migrate_process_rename(layout) is False, '매 요청마다 저장을 유발한다'
    # 나중에 누가 옛 이름으로 되돌려 놓아도 다음 로드에 낫는다
    _stage(layout, 's_process')['items'][1]['name'] = '정책 적용'
    assert SB._migrate_process_rename(layout) is True


def test_분류가_없는_저장본에도_안_터진다():
    layout = {'version': 1, 'schema': SB._SCHEMA, 'standalone': [], 'stages': []}
    assert SB._migrate_process_rename(layout) is False


def test_항목이_비어_있어도_분류_이름은_고쳐진다():
    """이 워크트리의 실제 로컬 저장본이 이 모양이다(items: []) — 주입은 렌더 때 따로 일어난다."""
    layout = {'version': 1, 'schema': SB._SCHEMA, 'standalone': [],
              'stages': [{'id': 's_process', 'emoji': '🔧', 'name': '상품 가공',
                          'color': '#F59E0B', 'items': []}]}
    assert SB._migrate_process_rename(layout) is True
    assert _stage(layout, 's_process')['name'] == '상품 정책화'


# ── ③ 화면(렌더) 결과 ──────────────────────────────────────────

def test_화면에는_새_이름으로_뜬다(monkeypatch):
    """상수·저장본·렌더 필터 중 하나만 어긋나도 여기서 잡힌다."""
    layout = _live_saved()
    SB._migrate_process_rename(layout)
    monkeypatch.setattr(SB, '_load', lambda: layout)
    out = SB.get_layout_for_template()
    proc = _stage(out, 's_process')
    assert proc['name'] == '상품 정책화'
    names = {it['id']: it['name'] for it in proc['items']}
    assert names == {'i_policies': '정책 생성', 'i_policy_apply': '정책 매칭'}


def test_항목이_아예_빠진_저장본에도_주입되며_새_이름을_쓴다(monkeypatch):
    """정책 생성·정책 매칭이 저장본에 없으면 스펙에서 주입되는데, 그때도 새 이름이어야 한다."""
    layout = {'version': 1, 'schema': SB._SCHEMA, 'standalone': [],
              'stages': [{'id': 's_process', 'emoji': '🔧', 'name': '상품 정책화',
                          'color': '#F59E0B', 'items': []}]}
    monkeypatch.setattr(SB, '_load', lambda: layout)
    out = SB.get_layout_for_template()
    names = {it['id']: it['name'] for it in _stage(out, 's_process')['items']}
    assert names == {'i_policies': '정책 생성', 'i_policy_apply': '정책 매칭'}
