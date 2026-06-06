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
        'sources', 'queue', 'mapping',
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
