"""[TEST] 사이드바 기능별 6분류 재구성 — 기본 레이아웃 계약 + 숨김/주입 회귀."""
from webapp.routes import api_sidebar


def _active_keys(layout) -> list[str]:
    """standalone + 모든 stage 항목의 active_key 를 순서대로 수집(중복 카운트용 list)."""
    keys = [it.get('active_key') for it in layout.get('standalone', [])]
    for st in layout.get('stages', []):
        keys += [it.get('active_key') for it in st.get('items', [])]
    return keys


def test_default_group_names_and_order():
    """묶음 이름·차례는 **일부러 정한 계약**이라 박아 둔다(바꿀 땐 여기도 같이 바꾼다).

    [2026-08-01] 옛 6묶음('모음전 구성'…'기타') 기대값이 그대로 남아 있어 깨져 있었다.
    프로그램은 노션 8분류로 재편됐다 — 프로그램 쪽이 맞아 기대값을 새 사실로 옮긴다.

    [2026-08-02] 「자동화」 → 「상품 마켓 전송」 (#687). 화면만 바꾸고 이 계약을 안
    고쳐서 **그 뒤 모든 배포가 이 검사에서 막혔다**(내 것·다른 세션 것 전부).
    이름을 바꿀 땐 여기도 같이 — 그게 이 테스트의 존재 이유다.
    """
    layout = api_sidebar._default_layout()
    names = [st['name'] for st in layout['stages']]
    assert names == ['옵션생성 & 상품생성', '상품 가공', '상품 마켓 전송', '상품 관리',
                     '주문 관리', '통계·분석', '재고관리', '기타']


def test_default_stage_ids_match_contract():
    layout = api_sidebar._default_layout()
    ids = [st['id'] for st in layout['stages']]
    assert ids == ['s_collect', 's_process', 's_auto', 's_catalog',
                   's_order', 's_stats', 's_inventory', 's_etc']


def test_no_duplicate_items_anywhere():
    """★이름 대조가 아니라 「무엇이 참이어야 하는가」 — 같은 메뉴가 두 번 나오면 안 된다.

    묶음 이름은 개편 때마다 바뀌지만 이 성질은 안 바뀐다. 위 두 검사가 개편 때
    깨지는 동안, 진짜 고장(중복 주입 등)을 잡는 건 이쪽이다.
    """
    keys = _active_keys(api_sidebar._default_layout())
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert dupes == [], f"사이드바에 같은 메뉴가 두 번 있다: {dupes}"
    assert all(k for k in keys), "active_key 가 빈 항목이 있다"


def test_default_validates():
    layout = api_sidebar._default_layout()
    ok, msg = api_sidebar._validate(layout)
    assert ok, msg


def test_hidden_items_absent_from_default():
    keys = _active_keys(api_sidebar._default_layout())
    for hidden in ('accounts_sourcing', 'market_upload', 'boxhero'):
        assert hidden not in keys


def test_default_contains_all_visible_items():
    """[2026-08-01] 노션 8분류 재편 뒤의 실제 구성으로 옮겼다(옛 6묶음 시절 목록이 남아 있었다).

    참고 — 옛 목록에 있다가 지금 없는 것들:
      · bundles_new · bundles_migrate · queue · mapping · track · orders_register
        → 재편 때 빠졌다(라우트는 살아 있을 수 있다).
    """
    keys = set(_active_keys(api_sidebar._default_layout()))
    expected = {
        'home',
        # [2026-08-02] 노션 원문대로 하위탭 3개 — 합본 'optgen' 하나였다.
        'optgen_direct', 'optgen_market', 'optgen_product',
        'policies', 'policy_apply', 'templates',         # 상품 가공
        # [2026-08-02] 「자동화」가 「상품 마켓 전송」으로 바뀌며 하위탭이 늘었다(#687).
        'automation', 'market_send',                     # 상품 마켓 전송
        'bundles', 'matrix', 'catalog',                  # 상품 관리
        'orders_list', 'orders_ship', 'orders_cs',       # 주문 관리
        'orders_margin',                                 # 통계·분석
        'inventory',                                     # 재고관리
        # 기타 — 크롤링 가이드는 2026-08-01 기준 여기 산다(예전엔 s_crawl 묶음).
        'sourcing_guide', 'accounts_upload', 'live_send_test',
        'trash', 'alerts', 'data_guide',
    }
    assert keys == expected


def test_crawl_guide_is_reachable_exactly_once():
    """크롤링 가이드는 **어딘가에 정확히 한 번** 있어야 한다.

    [2026-08-01] 전에는 's_crawl' 묶음 안에 있는지를 봤는데, 재편으로 그 묶음이
    없어져 StopIteration 으로 죽었다. 어느 묶음에 사는지는 개편마다 바뀌지만
    「닿을 수 있어야 한다·두 번 나오면 안 된다」는 안 바뀐다 — 그걸 본다.
    """
    keys = _active_keys(api_sidebar._default_layout())
    assert keys.count('sourcing_guide') == 1


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
    assert 'queue' not in keys and 'mapping' not in keys      # 미맵핑큐·맵핑도 숨김
    assert not any(st.get('id') == 's_mapping' for st in out['stages'])  # 빈 매핑섹션 제거
    assert 'source_registry' not in keys          # 소싱처 사전도 제거(가이드 통합)
    assert 'sourcing_guide' in keys               # 크롤링 가이드 유지
