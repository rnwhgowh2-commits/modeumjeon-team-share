"""[TEST] 사이드바 기능별 6분류 재구성 — 기본 레이아웃 계약 + 숨김/주입 회귀."""
import pytest

from webapp.routes import api_sidebar


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


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

    [2026-08-02] 「자동화」 → 전송 분류 개명 (#687). 화면만 바꾸고 이 계약을 안
    고쳐서 **그 뒤 모든 배포가 이 검사에서 막혔다**(내 것·다른 세션 것 전부).
    이름을 바꿀 땐 여기도 같이 — 그게 이 테스트의 존재 이유다.

    [2026-08-06 사장님 지시] 전송 분류 이름 → 「상품수집&전송」.

    [2026-08-19 사장님 확정] 「상품 가공」 → 「상품 정책화」.
    """
    layout = api_sidebar._default_layout()
    names = [st['name'] for st in layout['stages']]
    assert names == ['옵션생성 & 상품생성', '상품 정책화', '상품수집&전송', '상품 관리',
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
        # [2026-08-12 사장님 확정 ㉠] 「휴지통·변경 이력」을 뺐다 — 휴지통을 안 쓴다.
        #   기록(/trash·/audit)은 지우지 않았고 메뉴에서만 감췄다.
        'home',
        # [2026-08-02 사장님 확정 · C안] 오른쪽 바로가기. 여태 어느 메뉴에도 링크가
        #   없어 주소를 직접 쳐야 들어갔다(「옵션생성 & 상품생성」 재편 때 빠진 채였다).
        'bulk',
        # [2026-08-02] 노션 원문대로 하위탭 3개 — 합본 'optgen' 하나였다.
        'optgen_direct', 'optgen_market', 'optgen_product',
        'policies', 'policy_apply', 'templates',         # 상품 정책화
        # [2026-08-02] 「자동화」가 전송 분류로 바뀌며 하위탭이 늘었다(#687).
        'automation', 'market_send',                     # 상품수집&전송
        'bundles', 'matrix', 'catalog',                  # 상품 관리
        'orders_list', 'orders_ship', 'orders_cs',       # 주문 관리
        'orders_settle_plan',                            # [2026-08-06] 정산예정금액
        'orders_margin',                                 # 통계·분석
        'inventory',                                     # 재고관리
        # 기타 — 크롤링 가이드는 2026-08-01 기준 여기 산다(예전엔 s_crawl 묶음).
        'sourcing_guide', 'accounts_upload', 'live_send_test',
        'alerts', 'data_guide',
        # [2026-08-02] 노션 일일보고 점검 화면 — 여태 어느 메뉴에도 링크가 없어
        #   주소를 직접 쳐야만 들어갈 수 있었다(사장님 지적으로 발견).
        'notion_report',
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


def test_template_layout_no_duplicate_crawl_guide_and_no_roadmap(monkeypatch, tmp_path):
    """[2026-08-02 사장님 확정] 「로드맵」을 메뉴에서 뺐다.

    예전에는 저장본에 없어도 **매번 자동으로 끼워 넣어** 모두에게 보이게 했다.
    그 주입을 멈췄으므로, 이제는 **안 들어 있어야** 한다.
    화면 자체(/roadmap)는 그대로 살아 있고 주소로 열린다.
    """
    # 라이브 파일을 건드리지 않도록 임시 경로 + 캐시 초기화
    monkeypatch.setattr(api_sidebar, 'LAYOUT_PATH', tmp_path / 'sidebar_layout.json')
    monkeypatch.setitem(api_sidebar._layout_cache, 'data', None)
    monkeypatch.setitem(api_sidebar._layout_cache, 'mtime', 0.0)
    out = api_sidebar.get_layout_for_template()
    keys = _active_keys(out)
    assert keys.count('sourcing_guide') == 1          # 이미 포함 → 재주입 없음
    assert not any(it.get('active_key') == 'roadmap' for it in out['standalone']),         '로드맵이 메뉴에 다시 주입됐다'



def test_대량등록은_오른쪽_바로가기다(monkeypatch, tmp_path):
    """[2026-08-02 사장님 확정 · C안] 「대량등록」을 오른쪽 바로가기로 넣었다.

    ★ 왜 묶음(stage) 안이 아닌가 — 대량등록 화면 **안에** 「상품관리·주문관리·통계」가
      따로 또 있다. 묶음에 넣으면 같은 이름이 두 곳에 생겨 매번 헷갈린다.
      그래서 standalone 에 둔다(위쪽 막대가 홈 다음 것들을 오른쪽에 늘어놓는다).

    여태 이 화면은 어느 메뉴에도 링크가 없어 주소를 직접 쳐야 들어갔다.
    """
    monkeypatch.setattr(api_sidebar, 'LAYOUT_PATH', tmp_path / 'sidebar_layout.json')
    monkeypatch.setitem(api_sidebar._layout_cache, 'data', None)
    monkeypatch.setitem(api_sidebar._layout_cache, 'mtime', 0.0)
    out = api_sidebar.get_layout_for_template()

    단독 = out['standalone']
    assert 단독[0]['url'] == '/', '첫 자리는 홈이어야 한다(로고가 대신한다)'
    대량 = [i for i in 단독 if i.get('id') == 'i_bulk']
    assert len(대량) == 1, f'대량등록이 오른쪽에 한 번만 있어야 한다: {단독}'
    assert 대량[0]['url'] == '/bulk/'

    # 묶음 안에는 들어가면 안 된다 — 이름 겹침이 되살아난다
    for st in out.get('stages', []):
        ids = [i.get('id') for i in st.get('items', [])]
        assert 'i_bulk' not in ids, f"「{st.get('name')}」 묶음에 대량등록이 들어갔다"


def test_대량등록_주입은_두_번_안_된다(monkeypatch, tmp_path):
    """저장본을 갈아끼우는 방식이라 여러 번 읽어도 하나여야 한다."""
    monkeypatch.setattr(api_sidebar, 'LAYOUT_PATH', tmp_path / 'sidebar_layout.json')
    monkeypatch.setitem(api_sidebar._layout_cache, 'data', None)
    monkeypatch.setitem(api_sidebar._layout_cache, 'mtime', 0.0)
    for _ in range(3):
        monkeypatch.setitem(api_sidebar._layout_cache, 'data', None)
        monkeypatch.setitem(api_sidebar._layout_cache, 'mtime', 0.0)
        out = api_sidebar.get_layout_for_template()
    assert len([i for i in out['standalone'] if i.get('id') == 'i_bulk']) == 1
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


def test_편집_화면이_실제_사이드바와_같은_것을_본다(client):
    """🔴 편집 화면(GET /api/sidebar/layout)은 저장본을 날것으로 줬다.

    저장본에 없고 스펙에서 주입되는 항목(정책 생성·정책 매칭)이 편집 화면에서만
    사라져, 「상품 가공」(현 「상품 정책화」) 서랍이 텅 빈 채로 보였다 — 실제
    사이드바에는 둘 다 있는데. 옮기기 작업(옵션 맵핑 템플릿 → 기타) 뒤 이 어긋남이
    눈에 띄었다.
    """
    got = client.get('/api/sidebar/layout').get_json()
    ids = {i['id'] for st in got['stages'] for i in st['items']}
    assert 'i_policies' in ids, '편집 화면에 「정책 생성」이 없다'
    assert 'i_policy_apply' in ids, '편집 화면에 「정책 매칭」이 없다'

    proc = [st for st in got['stages'] if st['id'] == 's_process']
    assert proc and proc[0]['items'], '「상품 정책화」 서랍이 비어 보인다'


def test_편집_화면에도_중복_id_가_없다(client):
    """주입이 이미 있는 항목을 또 넣으면 저장 시 유니크 검사에서 400 이 난다."""
    got = client.get('/api/sidebar/layout').get_json()
    ids = [i['id'] for st in got['stages'] for i in st['items']]
    ids += [i['id'] for i in got.get('standalone', [])]
    assert len(ids) == len(set(ids)), f'중복: {[x for x in ids if ids.count(x) > 1]}'
