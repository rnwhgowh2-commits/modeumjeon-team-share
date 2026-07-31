# -*- coding: utf-8 -*-
"""애플식 상단 탭 — 두 가지가 핵심이다.

  1) 메뉴를 두 번 적지 않는다: 상단 탭은 사이드바 레이아웃을 옮겨 담기만 한다.
     하나라도 빠지거나 겹치면 사장님이 「메뉴가 사라졌다」를 겪는다.
  2) 「현재」 모드는 한 글자도 안 바뀐다: 새 디자인이 깨졌을 때 돌아올 자리다.
     current 인데 상단 탭이 섞여 나오면 안전망이 아니다.
"""
import pytest

from webapp.nav_top import build, 열당_최대


# ── 1) 옮겨 담기: 빠짐 0 · 중복 0 ────────────────────────────────────────
def _레이아웃(stages, standalone=None):
    return {'standalone': standalone if standalone is not None else [{'id': 'i_home', 'name': '홈', 'url': '/'}],
            'stages': stages}


def _항목(i, key=None):
    return {'id': i, 'name': i, 'url': '/' + i, 'active_key': key or i}


def test_사이드바_항목이_하나도_안_빠진다():
    lay = _레이아웃([
        {'id': 's_a', 'name': '가', 'items': [_항목('i1'), _항목('i2')]},
        {'id': 's_b', 'name': '나', 'items': [_항목('i3')]},
    ], standalone=[{'id': 'i_home', 'name': '홈', 'url': '/'},
                   {'id': 'i_road', 'name': '로드맵', 'url': '/roadmap'}])
    t = build(lay)

    담김 = ([t['home']['id']] + [x['id'] for x in t['loose']]
            + [it['id'] for tab in t['tabs'] for c in tab['columns']
               if not c.get('fav') for it in c['items']])
    assert sorted(담김) == ['i1', 'i2', 'i3', 'i_home', 'i_road']
    assert len(담김) == len(set(담김)), '같은 메뉴가 두 군데 나오면 안 된다'


def test_로고가_홈을_대신한다():
    """애플도 로고가 곧 홈이다 — 「홈」을 탭에서 뺀 게 아니라 로고로 옮긴 것."""
    t = build(_레이아웃([{'id': 's_a', 'name': '가', 'items': [_항목('i1')]}]))
    assert t['home']['id'] == 'i_home'
    탭안 = [it['id'] for tab in t['tabs'] for c in tab['columns'] for it in c['items']]
    assert 'i_home' not in 탭안


def test_스테이지가_그대로_상위탭이_된다():
    lay = _레이아웃([{'id': 's_a', 'name': '가', 'items': [_항목('i1')]},
                     {'id': 's_b', 'name': '나', 'items': [_항목('i2')]}])
    t = build(lay)
    assert [x['name'] for x in t['tabs']] == ['가', '나']
    assert [x['id'] for x in t['tabs']] == ['s_a', 's_b']


def test_항목이_많으면_열로_나뉜다():
    """애플 펼침 메뉴도 긴 목록을 열로 끊는다. 첫 열만 제목, 나머지는 이어지는 열."""
    많이 = [_항목('i%d' % n) for n in range(열당_최대 + 2)]
    t = build(_레이아웃([{'id': 's_a', 'name': '가', 'items': 많이}]))
    cols = [c for c in t['tabs'][0]['columns'] if not c.get('fav')]
    assert len(cols) == 2
    assert cols[0]['title'] == '가' and len(cols[0]['items']) == 열당_최대
    assert cols[1]['title'] == '', '이어지는 열에 제목을 또 달면 두 묶음처럼 보인다'
    assert len(cols[1]['items']) == 2


def test_없는_스테이지_즐겨찾기는_조용히_무시된다(monkeypatch):
    monkeypatch.setattr('webapp.nav_top._favorites',
                        lambda: {'s_a': ['i1', '없는놈'], '없는스테이지': ['i9']})
    t = build(_레이아웃([{'id': 's_a', 'name': '가', 'items': [_항목('i1'), _항목('i2')]}]))
    fav = [c for c in t['tabs'][0]['columns'] if c.get('fav')]
    assert len(fav) == 1 and [x['id'] for x in fav[0]['items']] == ['i1']


def test_즐겨찾기는_되풀이일뿐_원래_열에도_남는다():
    """애플 「빠른 링크」와 같다 — 같은 항목이 두 번 보이는 게 의도다."""
    import webapp.nav_top as nt
    원래 = nt._favorites
    nt._favorites = lambda: {'s_a': ['i2']}
    try:
        t = build(_레이아웃([{'id': 's_a', 'name': '가', 'items': [_항목('i1'), _항목('i2')]}]))
    finally:
        nt._favorites = 원래
    본열 = [c for c in t['tabs'][0]['columns'] if not c.get('fav')][0]
    assert 'i2' in [x['id'] for x in 본열['items']]


def test_빈_레이아웃이어도_안_터진다():
    for 나쁜값 in ({}, None, {'stages': []}, {'standalone': [], 'stages': []}):
        t = build(나쁜값)
        assert t['tabs'] == [] and t['home'] is None


def test_즐겨찾기_파일이_깨져도_상단탭은_뜬다(tmp_path, monkeypatch):
    깨진 = tmp_path / 'nav_favorites.json'
    깨진.write_text('{ 이건 JSON 이 아니다', encoding='utf-8')
    monkeypatch.setattr('webapp.nav_top._FAV_PATH', str(깨진))
    t = build(_레이아웃([{'id': 's_a', 'name': '가', 'items': [_항목('i1')]}]))
    assert len(t['tabs']) == 1
    assert not any(c.get('fav') for c in t['tabs'][0]['columns'])


def test_실제_저장본으로도_빠짐_중복이_없다():
    """지어낸 값이 아니라 프로그램이 실제로 쓰는 레이아웃으로 검사한다."""
    from webapp.routes.api_sidebar import get_layout_for_template
    lay = get_layout_for_template()
    t = build(lay)
    전체 = ([it['id'] for it in lay.get('standalone') or []]
            + [it['id'] for st in lay.get('stages') or [] for it in st.get('items') or []])
    담김 = ([t['home']['id']] if t['home'] else []) + [x['id'] for x in t['loose']] \
        + [it['id'] for tab in t['tabs'] for c in tab['columns']
           if not c.get('fav') for it in c['items']]
    assert sorted(담김) == sorted(전체)
    assert len(담김) == len(set(담김))


# ── 2) 안전망: 「현재」 모드에는 상단 탭이 한 글자도 안 섞인다 ──────────────
def _사용자_만들기(email='topnav@test.local'):
    """DISABLE_AUTH 로 자동 로그인되는 사용자를 임시 DB 에 만든다.

    이게 없으면 /auth/design-mode 가 저장할 대상이 없어 모드가 안 바뀌고,
    화면은 계속 current 로 뜬다 — 그러면 「새 모드에서 상단 탭이 뜨는가」를
    확인하려던 검사가 조용히 아무것도 증명하지 못한다.
    """
    from shared.db import SessionLocal
    from webapp.auth.models import User

    with SessionLocal() as s:
        u = User(email=email, name='상단탭테스트', password_hash='x',
                 role='admin', is_active=True)
        s.add(u)
        s.commit()
        return u.id


def test_현재모드_화면에는_상단탭이_없다(client):
    r = client.get('/')
    assert r.status_code == 200, '홈이 안 뜨면 이 검사는 아무것도 증명하지 못한다'
    html = r.get_data(as_text=True)
    assert 'tn-root' not in html, '「현재」 모드에 상단 탭이 나오면 안전망이 아니다'
    assert 'topnav.css' not in html
    assert 'class="sidebar' in html or 'sb3-root' in html, '사이드바는 그대로 있어야 한다'


@pytest.mark.parametrize('모드', ['mono', 'layer', 'light'])
def test_새_모드에서는_상단탭이_나오고_사이드바가_빠진다(client_with_auth, 모드):
    _사용자_만들기()
    r0 = client_with_auth.post('/auth/design-mode', data={'mode': 모드, 'next': '/'})
    assert r0.status_code == 302, '모드 저장 자체가 안 되면 아래 검사는 무의미하다'
    r = client_with_auth.get('/')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'data-design="%s"' % 모드 in html, '모드가 실제로 바뀐 화면이어야 한다'
    assert 'tn-root' in html
    assert 'topnav.css' in html
    assert 'sb3-root' not in html, '상단 탭을 쓰면 왼쪽 사이드바는 사라져야 한다'


@pytest.mark.parametrize('모드', ['mono', 'layer', 'light'])
def test_어느_모드에서나_기존타입으로_되돌리는_통로가_있다(client_with_auth, 모드):
    """새 디자인이 화면을 깨뜨렸을 때 되돌릴 통로가 반드시 있어야 한다.

    [2026-07-31] 그 통로가 사이드바·상단탭·내 계정 세 벌에서 화면 오른쪽 위
    붙박이 드롭버튼 한 벌(partials/design_mode_menu.html)로 합쳐졌다.
    검사하는 성질은 그대로다 — 「기존 타입」으로 가는 제출 단추가 화면에 있는가.
    """
    _사용자_만들기()
    client_with_auth.post('/auth/design-mode', data={'mode': 모드, 'next': '/'})
    r = client_with_auth.get('/')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'data-design="%s"' % 모드 in html
    assert 'class="dmenu"' in html, '오른쪽 위 디자인 드롭버튼이 사라졌다'
    assert 'value="current"' in html, '「기존 타입」으로 되돌아갈 단추가 반드시 있어야 한다'


@pytest.mark.parametrize('길, 표식', [('/inventory/', 'inventory'), ('/bulk/', 'bulk')])
def test_전용_사이드바는_상단탭을_켜도_살아있다(client_with_auth, 길, 표식):
    """재고관리·대량등록 사이드바에는 거기에만 있는 링크가 있다
       (/inventory/adjust·count·barcode …). 상단 탭으로 갈아치우면 그 화면들로 갈
       길이 통째로 사라진다 — 전역 막대는 위, 그 화면 전용 메뉴는 왼쪽에 함께 둔다."""
    _사용자_만들기()
    client_with_auth.post('/auth/design-mode', data={'mode': 'layer', 'next': '/'})
    r = client_with_auth.get(길)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'tn-root' in html, '전역 상단 막대는 있어야 한다'
    assert 'class="sidebar' in html, '%s 전용 사이드바가 사라졌다' % 표식


def test_재고관리_전용링크가_상단탭_모드에서도_남는다(client_with_auth):
    _사용자_만들기()
    client_with_auth.post('/auth/design-mode', data={'mode': 'layer', 'next': '/'})
    html = client_with_auth.get('/inventory/').get_data(as_text=True)
    for 길 in ('/inventory/adjust', '/inventory/count', '/inventory/barcode'):
        assert 길 in html, '%s 로 갈 길이 없어졌다' % 길


# ── 3) 펼침 메뉴는 「자기 탭」 밑에 붙는다 (사장님 결정: 시안 B) ─────────────
import os
import re

_여기 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CSS = open(os.path.join(_여기, 'webapp', 'static', 'topnav.css'), encoding='utf-8').read()
_HTML = open(os.path.join(_여기, 'webapp', 'templates', 'partials', 'topnav.html'), encoding='utf-8').read()


def _규칙(선택자):
    m = re.search(re.escape(선택자) + r'\s*\{([^}]*)\}', _CSS)
    assert m, '%s 규칙이 사라졌다' % 선택자
    return m.group(1)


def test_펼침의_기준은_막대가_아니라_탭이다():
    """기준이 .tn(막대 전체)이면 탭이 화면 한가운데 있어도 펼침은 늘 화면 왼쪽 끝에서
       시작한다 — 라이브 1920 실측에서 최대 1,221 어긋났던 원인이 이것뿐이다."""
    본문 = _규칙('.tn-tab')
    assert 'position: relative' in 본문
    assert 'position: static' not in 본문


def test_메뉴_줄이_탭_왼쪽끝에_맞는다():
    """맞추는 기준은 판이 아니라 글자다. 판의 안쪽 여백(16)과 테두리(1)를 빼지 않으면
       메뉴 글자가 그만큼 안으로 밀려 탭 글자와 어긋난다(실측으로 잡힌 1px 어긋남)."""
    본문 = _규칙('.tn-mega')
    assert 'var(--sp-4, 16px)' in 본문 and '1px' in 본문, '여백·테두리 보정이 빠졌다'
    assert 'right: auto' in 본문, '왼쪽 기준으로 바꿨으면 오른쪽 고정은 풀어야 한다'
    assert 'width: max-content' in 본문, '판은 내용 폭이어야 한다(화면 폭 띠 아님)'
    assert 'var(--tn-shift, 0px)' in 본문, '넘칠 때 되당길 자리가 없다'


def test_판은_화면폭_띠가_아니라_카드다():
    본문 = _규칙('.tn-mega')
    assert 'left: 0' not in 본문 and 'right: 0' not in 본문
    assert 'border: 1px solid' in 본문 and 'border-radius' in 본문


def test_그림자는_여전히_없다():
    """디자인 규칙에서 그림자는 전면 금지다 — 카드로 바꾸면서 슬쩍 넣기 쉽다."""
    assert 'box-shadow' not in _CSS


def test_넘침_되당김이_실제로_배선돼_있다():
    """오른쪽 끝 탭에서 판이 화면 밖으로 나가면 조용히 잘린다.
       CSS 만으로는 못 막는다 — 값을 넣어 주는 쪽이 있어야 한다."""
    assert "setProperty('--tn-shift'" in _HTML


def test_되당김은_올릴_때_잰다_화면_뜰_때가_아니라():
    """실측 사고 재발 방지 — 화면이 뜨는 순간엔 바로 위 <link> 의 topnav.css 가
       아직 안 붙어 있을 수 있다. 그 상태에서 재면 탭이 기준이 아닌 채로 측정돼
       8개 탭 전부 엉뚱한 되당김(-308~+308)이 박히고, 펼침이 모두 같은 자리에 겹친다."""
    assert "addEventListener('mouseenter'" in _HTML
    assert "addEventListener('focusin'" in _HTML
    # 화면 뜨자마자 전체를 훑는 호출이 남아 있으면 같은 사고가 되풀이된다
    assert 'document.fonts' not in _HTML
    assert '되당김_재기()' not in _HTML, '인자 없이 부르는 = 화면 뜰 때 미리 재던 그 호출'


def test_스크립트가_죽어도_펼침은_열린다():
    """되당김은 거들 뿐이다. 여는 것은 CSS :hover 여야 한다."""
    assert '.tn-tab:hover .tn-mega' in _CSS
