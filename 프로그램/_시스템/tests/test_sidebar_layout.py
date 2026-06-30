"""[TEST] 사이드바 기능별 6분류 재구성 — 기본 레이아웃 계약 + 숨김/주입 회귀."""
from webapp.routes import api_sidebar


def _active_keys(layout) -> list[str]:
    """standalone + 모든 stage 항목의 active_key 를 순서대로 수집(중복 카운트용 list)."""
    keys = [it.get('active_key') for it in layout.get('standalone', [])]
    for st in layout.get('stages', []):
        keys += [it.get('active_key') for it in st.get('items', [])]
    return keys


def test_default_has_six_groups_in_order():
    layout = api_sidebar._default_layout()
    names = [st['name'] for st in layout['stages']]
    assert names == ['모음전 상품관리', '매핑 현황', '크롤링&업로드', '구매', '판매', '기타']


def test_default_stage_ids_match_contract():
    layout = api_sidebar._default_layout()
    ids = [st['id'] for st in layout['stages']]
    assert ids == ['s_bundles', 's_mapping', 's_crawl', 's_buy', 's_sell', 's_etc']


def test_default_validates():
    layout = api_sidebar._default_layout()
    ok, msg = api_sidebar._validate(layout)
    assert ok, msg


def test_hidden_items_absent_from_default():
    keys = _active_keys(api_sidebar._default_layout())
    for hidden in ('accounts_sourcing', 'market_upload', 'boxhero'):
        assert hidden not in keys


def test_default_contains_all_visible_items():
    keys = set(_active_keys(api_sidebar._default_layout()))
    expected = {
        'home',
        'bundles_new', 'bundles', 'bundles_migrate',
        # 'sources'(소싱처 운영센터)는 2026-06-30 단일명부 통합으로 사이드바 숨김(라우트 보존).
        'queue', 'mapping',
        'sourcing_guide', 'source_registry', 'dlq', 'accounts_upload',
        'track',
        'templates', 'orders_list', 'orders_sales', 'orders_margin',
        'trash', 'alerts',
    }
    assert keys == expected


def test_crawl_guide_lives_in_crawl_group():
    layout = api_sidebar._default_layout()
    crawl = next(st for st in layout['stages'] if st['id'] == 's_crawl')
    assert any(it['active_key'] == 'sourcing_guide' for it in crawl['items'])


def test_template_layout_no_duplicate_crawl_guide_and_has_roadmap(monkeypatch, tmp_path):
    # 라이브 파일을 건드리지 않도록 임시 경로 + 캐시 초기화
    monkeypatch.setattr(api_sidebar, 'LAYOUT_PATH', tmp_path / 'sidebar_layout.json')
    monkeypatch.setitem(api_sidebar._layout_cache, 'data', None)
    monkeypatch.setitem(api_sidebar._layout_cache, 'mtime', 0.0)
    out = api_sidebar.get_layout_for_template()
    keys = _active_keys(out)
    assert keys.count('sourcing_guide') == 1          # 이미 포함 → 재주입 없음
    assert any(it['active_key'] == 'roadmap' for it in out['standalone'])


def test_template_layout_injects_sets_dashboard(monkeypatch, tmp_path):
    """판매처 연동 탭이 '모음전 상품관리'(s_bundles)에 한 번 주입된다."""
    monkeypatch.setattr(api_sidebar, 'LAYOUT_PATH', tmp_path / 'sidebar_layout.json')
    monkeypatch.setitem(api_sidebar._layout_cache, 'data', None)
    monkeypatch.setitem(api_sidebar._layout_cache, 'mtime', 0.0)
    out = api_sidebar.get_layout_for_template()
    keys = _active_keys(out)
    assert keys.count('sets_dashboard') == 1
    bundles = next(st for st in out['stages'] if st['id'] == 's_bundles')
    assert any(it['active_key'] == 'sets_dashboard' for it in bundles['items'])


def test_template_layout_respects_user_moved_sets_dashboard(monkeypatch, tmp_path):
    """사용자가 판매처 연동을 다른 묶음(s_sell)으로 옮겼으면 그 위치 존중·재주입 없음."""
    import json
    custom = api_sidebar._default_layout()
    sell = next(st for st in custom['stages'] if st['id'] == 's_sell')
    sell['items'].append({'id': 'i_sets_dash', 'emoji': '🏬', 'name': '판매처 연동',
                          'url': '/api/sets/dashboard', 'active_key': 'sets_dashboard',
                          'badge_key': None})
    p = tmp_path / 'sidebar_layout.json'
    p.write_text(json.dumps(custom), encoding='utf-8')
    monkeypatch.setattr(api_sidebar, 'LAYOUT_PATH', p)
    monkeypatch.setitem(api_sidebar._layout_cache, 'data', None)
    monkeypatch.setitem(api_sidebar._layout_cache, 'mtime', 0.0)
    out = api_sidebar.get_layout_for_template()
    keys = _active_keys(out)
    assert keys.count('sets_dashboard') == 1          # 중복 주입 없음
    bundles = next(st for st in out['stages'] if st['id'] == 's_bundles')
    assert not any(it['active_key'] == 'sets_dashboard' for it in bundles['items'])
    sell2 = next(st for st in out['stages'] if st['id'] == 's_sell')
    assert any(it['active_key'] == 'sets_dashboard' for it in sell2['items'])


def test_get_layout_strips_sources_even_if_saved(monkeypatch, tmp_path):
    """[2026-06-30] 저장된 커스텀 레이아웃에 i_sources 가 남아 있어도 렌더 시 제거."""
    import json as _j
    saved = api_sidebar._default_layout()
    # 저장 레이아웃에 운영센터를 인위적으로 추가
    for st in saved['stages']:
        if st['id'] == 's_mapping':
            st['items'].insert(0, {'id': 'i_sources', 'emoji': '🏠', 'name': '소싱처 운영센터',
                                   'url': '/sources', 'active_key': 'sources', 'badge_key': None})
    p = tmp_path / 'sidebar_layout.json'
    p.write_text(_j.dumps(saved, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(api_sidebar, 'LAYOUT_PATH', p)
    monkeypatch.setitem(api_sidebar._layout_cache, 'data', None)
    monkeypatch.setitem(api_sidebar._layout_cache, 'mtime', 0.0)
    out = api_sidebar.get_layout_for_template()
    keys = _active_keys(out)
    assert 'sources' not in keys                  # 렌더 결과엔 운영센터 없음
    assert 'source_registry' in keys              # 소싱처 사전은 유지
