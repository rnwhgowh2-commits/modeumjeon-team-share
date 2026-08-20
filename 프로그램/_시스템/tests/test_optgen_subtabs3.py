"""[TEST] 「옵션생성 & 상품생성」 하위탭 3개 — 노션 원문 계약.

사장님이 라이브에서 잡은 것: 상단 메뉴 「옵션생성 & 상품생성」 을 펼치면 **한 줄만** 떴다.
노션 원문(「무재고 모음전 솔루션 개발현황」)은 하위탭 3개다 —
  1) 모음전 옵션 생성 (직접)
  2) 모음전 옵션 생성 (내마켓 불러오기)
  3) 모음전 상품 생성

★ 여기서 지키는 건 「화면 안 가로탭」이 아니라 **상단 메뉴 펼침에 3개가 뜨는 것**이다.
  두 곳(webapp/routes/optgen.SUBTABS · api_sidebar._STAGE_SPEC)이 갈리면
  화면만 3개가 되고 메뉴는 옛것으로 남는다 — 그 갈림을 이 파일이 막는다.
"""
import json

import pytest

from webapp import nav_top
from webapp.routes import api_sidebar
from webapp.routes.optgen import SUBTABS

#: 노션 원문 하위탭 3개. 순서까지 계약이다.
노션_하위탭 = ['모음전 옵션 생성 (직접)',
               '모음전 옵션 생성 (내마켓 불러오기)',
               '모음전 상품 생성']


def _collect(layout):
    return next(st for st in layout['stages'] if st['id'] == 's_collect')


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


# ── 상단 메뉴 (사장님이 실제로 본 자리) ──────────────────────────────────
def test_상단메뉴_펼침에_3개가_뜬다():
    """이 검사가 곧 사장님 신고 내용이다 — 펼쳤을 때 한 줄만 뜨면 실패."""
    tabs = nav_top.build(api_sidebar._default_layout())['tabs']
    tab = next(t for t in tabs if t['id'] == 's_collect')
    이름 = [it['name'] for c in tab['columns'] for it in c['items']]
    assert 이름 == 노션_하위탭


def test_상단메뉴_항목마다_갈_곳이_다르다():
    """세 줄이 떠도 셋 다 같은 데로 가면 하위탭이 아니다."""
    tabs = nav_top.build(api_sidebar._default_layout())['tabs']
    tab = next(t for t in tabs if t['id'] == 's_collect')
    urls = [it['url'] for c in tab['columns'] for it in c['items']]
    assert urls == ['/optgen?tab=direct', '/optgen?tab=market', '/optgen?tab=product']
    assert len(set(urls)) == 3


def test_화면_가로탭과_상단메뉴가_같은_3개다():
    """🔴 두 곳이 갈리면 「화면만 고치고 메뉴는 옛것」 이 된다 — 실제로 그렇게 났다."""
    메뉴 = [it['name'] for it in _collect(api_sidebar._default_layout())['items']]
    화면 = [t['label'] for t in SUBTABS]
    assert 메뉴 == 화면 == 노션_하위탭


# ── 저장본 마이그레이션 (라이브가 쓰는 길) ───────────────────────────────
def _옛_저장본():
    """하위탭이 갈리기 전 저장본 모양 — 합본 항목 1개."""
    return {
        'version': 1, 'schema': 8, 'updated_at': None,
        'standalone': [{'id': 'i_home', 'emoji': '⌂', 'name': '홈', 'url': '/',
                        'active_key': 'home', 'badge_key': None}],
        'stages': [
            {'id': 's_collect', 'emoji': '📥', 'name': '옵션생성 & 상품생성',
             'color': '#3182F6', 'collapsed': False,
             'items': [api_sidebar._ITEM_DEFS and {
                 'id': 'i_optgen', 'emoji': '📥', 'name': '옵션생성 & 상품생성',
                 'url': '/optgen', 'active_key': 'optgen', 'badge_key': None}]},
            {'id': 's_catalog', 'emoji': '📦', 'name': '상품 관리',
             'color': '#06B6D4', 'collapsed': False,
             'items': [{'id': 'i_bundles', 'emoji': '📋', 'name': '모음전 상품관리',
                        'url': '/bundles', 'active_key': 'bundles', 'badge_key': None},
                       {'id': 'i_matrix', 'emoji': '🧱', 'name': '모음전 옵션관리',
                        'url': '/matrix', 'active_key': 'matrix', 'badge_key': None}]},
        ],
    }


def test_옛_저장본이_3개로_갈린다():
    layout = _옛_저장본()
    assert api_sidebar._migrate_optgen3(layout) is True
    ids = [it['id'] for it in _collect(layout)['items']]
    assert ids == ['i_optgen_direct', 'i_optgen_market', 'i_optgen_product']


def test_합본_항목은_어디에_있든_걷힌다():
    """사장님이 드래그로 딴 묶음에 옮겨놨을 수도 있다."""
    layout = _옛_저장본()
    layout['stages'][1]['items'].append(dict(layout['stages'][0]['items'][0]))
    layout['stages'][0]['items'] = []
    api_sidebar._migrate_optgen3(layout)
    남은 = [it['id'] for st in layout['stages'] for it in st['items']]
    assert 'i_optgen' not in 남은


def test_두번_돌려도_그대로다():
    layout = _옛_저장본()
    api_sidebar._migrate_optgen3(layout)
    첫판 = json.dumps(layout, ensure_ascii=False, sort_keys=True)
    assert api_sidebar._migrate_optgen3(layout) is False
    assert json.dumps(layout, ensure_ascii=False, sort_keys=True) == 첫판


def test_옛_마이그레이션이_다시_돌아_항목을_겹치지_않는다():
    """🔴 이 함정이 진짜다.

    옛 마이그레이션은 「i_optgen 이 있으면 이미 했다」로 판정했다. 하위탭 3개로
    갈리며 그 id 가 사라지므로, 그대로 두면 **다음 로드 때 다시 돌아**
    상품관리에 i_bundles·i_matrix 를 한 번 더 밀어 넣는다(같은 메뉴가 두 번).
    """
    layout = _옛_저장본()
    api_sidebar._migrate_optgen3(layout)
    assert api_sidebar._migrate_optgen(layout) is False, '옛 마이그레이션이 다시 돌았다'
    ids = [it['id'] for st in layout['stages'] for it in st['items']]
    겹침 = sorted({i for i in ids if ids.count(i) > 1})
    assert 겹침 == [], f'같은 메뉴가 두 번 있다: {겹침}'


def test_갈린_뒤에도_저장검증을_통과한다():
    layout = _옛_저장본()
    api_sidebar._migrate_optgen3(layout)
    ok, msg = api_sidebar._validate(layout)
    assert ok, msg


def test_저장본에_합본이_남아도_화면엔_안_뜬다():
    """마이그레이션이 못 돈 경우의 안전망 — 렌더에서 한 번 더 거른다."""
    assert 'i_optgen' in api_sidebar._REMOVED_IDS


# ── 화면 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('tab, 있어야', [
    ('direct', '만들고 색상·사이즈 짜러 가기'),
    ('market', '상품명 · 상품번호로 찾기'),   # [2026-08-04] C4 — 브랜드는 검색 지문에서 뺌(B3)
    ('product', '어느 옵션 묶음으로 만들까요'),
])
def test_탭마다_제_내용이_나온다(client, tab, 있어야):
    html = client.get(f'/optgen?tab={tab}').get_data(as_text=True)
    assert 있어야 in html


def test_내마켓_탭이_화면_안에서_찾는다():
    """A1 확정 — 탭을 눌렀는데 주소가 딴 화면으로 튀면 안 된다."""
    assert {t['key'] for t in SUBTABS} == {'direct', 'market', 'product'}


def test_옛_주소는_탭으로_이어진다(client):
    """저장해 둔 바로가기가 조용히 죽지 않게."""
    assert '만들고 색상·사이즈 짜러 가기' in client.get(
        '/optgen?tab=option').get_data(as_text=True)
    r = client.get('/optgen/import')
    assert r.status_code == 302 and 'tab=market' in r.headers['Location']


def test_모르는_탭은_기본탭으로(client):
    html = client.get('/optgen?tab=없는탭').get_data(as_text=True)
    assert '만들고 색상·사이즈 짜러 가기' in html


def test_옵션_탭_두곳_모두에_묶음_목록이_있다(client):
    """B2 확정 — 어느 쪽으로 만들었든 이어서 할 자리를 한 군데서 찾는다.
    [2026-08-04 사장님 확정] 목록 이름은 「옵션 매트릭스」."""
    for tab in ('direct', 'market'):
        html = client.get(f'/optgen?tab={tab}').get_data(as_text=True)
        assert '옵션 매트릭스' in html, tab


def test_지우기_단추가_내마켓_탭에서도_살아있다(client):
    """🔴 만들기 칸이 없다고 스크립트가 일찍 빠져나가면 지우기가 죽는다.

    「내마켓」 탭엔 만들기 칸(ob-make)이 없고 묶음 목록만 있다.
    옛 스크립트는 그 칸이 없으면 곧장 return 해서 지우기 처리기까지 못 달았다.
    """
    js = client.get('/optgen?tab=market').get_data(as_text=True)
    assert "getElementById('ob-make')" in js
    assert 'if (!btn) return;' not in js, '만들기 칸이 없으면 지우기까지 죽는다'
    assert "querySelectorAll('[data-del]')" in js


# ── [2026-08-12 노션 하위탭 a · 사장님 A1 확정] 2단 위상 ──────────────────
#   「옵션 생성」과 「상품 생성」은 다른 일이다 — 평평한 3탭은 같은 급으로 보였다.
#   🔴 위 검사들이 지키는 계약(같은 3개·같은 label·같은 순서)은 그대로 둔 채
#      화면이 그리는 방식만 2단으로 바꾼다.

def test_하위탭이_옵션생성_상품생성_두_묶음으로_갈린다():
    from webapp.routes.optgen import subtab_groups
    g = subtab_groups()
    assert [x[0] for x in g] == ['option', 'product']
    assert [x[1] for x in g] == ['옵션 생성', '상품 생성']
    assert [t['key'] for t in g[0][2]] == ['direct', 'market'], '옵션 생성 아래 2개'
    assert [t['key'] for t in g[1][2]] == ['product']


def test_묶음을_눌러도_원래_탭_주소로_간다(client):
    """윗단은 그 묶음의 **첫 하위탭**으로 보낸다 — 새 주소를 만들지 않는다."""
    from webapp.routes.optgen import subtab_groups
    for _g, _lb, items in subtab_groups():
        r = client.get('/optgen?tab=' + items[0]['key'])
        assert r.status_code == 200
    html = client.get('/optgen?tab=direct').get_data(as_text=True)
    assert 'href="/optgen?tab=direct"' in html
    assert 'href="/optgen?tab=product"' in html
    # 아랫단은 옵션 생성일 때만 (상품 생성은 하위가 하나뿐).
    # 🔴 `og-subtabs` 는 CSS 에도 나온다 — **마크업**만 본다.
    assert '<div class="og-subtabs">' in html
    assert '<div class="og-subtabs">' not in \
        client.get('/optgen?tab=product').get_data(as_text=True)
