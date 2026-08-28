# -*- coding: utf-8 -*-
"""애플식 상단 탭 — 두 가지가 핵심이다.

  1) 메뉴를 두 번 적지 않는다: 상단 탭은 사이드바 레이아웃을 옮겨 담기만 한다.
     하나라도 빠지거나 겹치면 사장님이 「메뉴가 사라졌다」를 겪는다.
  2) 「현재」 모드는 한 글자도 안 바뀐다: 새 디자인이 깨졌을 때 돌아올 자리다.
     current 인데 상단 탭이 섞여 나오면 안전망이 아니다.
"""
import pytest

from webapp.nav_top import apply_samba_wave_override, build, 열당_최대


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


def test_화면에는_늘_상단탭이_나온다(client):
    """[2026-08-02 사장님 확정] 타입이 화이트 하나뿐이라 상단 탭은 늘 켜진다.

    예전에는 「기존 타입」에 상단 탭이 섞이면 안 됐다(안전망이라서). 그 타입을
    지웠으므로 지킬 성질이 뒤집혔다 — **늘 나와야** 한다.
    """
    r = client.get('/')
    assert r.status_code == 200, '홈이 안 뜨면 이 검사는 아무것도 증명하지 못한다'
    html = r.get_data(as_text=True)
    assert 'tn-root' in html, '상단 탭이 안 나온다'
    assert 'topnav.css' in html
    assert 'data-design="light"' in html, '화이트 타입 표시가 붙어야 한다'
    assert 'ds-light' in html, '보정이 걸리는 표시가 반드시 있어야 한다'


def test_고르는_단추는_화면에_없다(client):
    """지운 드롭버튼이 되살아나면 여기서 걸린다."""
    html = client.get('/').get_data(as_text=True)
    assert 'class="dmenu"' not in html, '디자인 고르는 단추가 되살아났다'
    assert 'value="current"' not in html, '지운 「기존 타입」 단추가 되살아났다'


def test_옛_타입_표시는_화면에_안_섞인다(client):
    html = client.get('/').get_data(as_text=True)
    for 옛것 in ('ds-mono', 'ds-layer', 'ds-dark'):
        assert 옛것 not in html, f'{옛것} 이 화면에 다시 섞였다'


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


def test_판은_한_번에_하나만_뜬다():
    """라이브 실측 사고 — 「상품 관리」 판 위에 「주문 관리」 판이 겹쳐 글자가 잘렸다.
       탭은 tabindex=0 이라 눌러 본 탭이 포커스를 쥐고, :focus-within 이 그 판을
       붙잡은 채 옆 탭의 판까지 열려서다. 마우스가 막대에 있는 동안에는
       올린 탭 하나만 열어야 한다."""
    assert '.tn-tabs:hover .tn-tab:not(:hover) .tn-mega' in _CSS
    # 키보드 통로는 살아 있어야 한다 — 막대에 마우스가 없을 때 열 길이 이것뿐이다
    assert '.tn-tab:focus-within .tn-mega' in _CSS


def test_마우스로_누른다고_판이_붙잡히지_않는다():
    """포커스가 남으면 마우스를 딴 데로 내려도 판이 본문을 덮는다.
       마우스로 여는 길에서는 포커스를 주지 않는다(Tab 키는 그대로)."""
    assert "addEventListener('mousedown'" in _HTML and 'preventDefault' in _HTML
    assert "addEventListener('mouseleave'" in _HTML, '막대를 벗어나면 놓아 줘야 한다'


# ── 4) 폰(≤768px)에서 탭 줄이 화면을 옆으로 밀지 않는다 ─────────────────────
#    실브라우저 실측(2026-08-05, 라이브 375×812): retrofit 전 화면 문서폭 496~511.
#    넘친 것은 전부 .tn-tab/.tn-tab-n (왼쪽 -109 ~ 오른쪽 511) — 본문은 깨끗했다.
#    원인 = .tn-tabs 의 justify-content:center — 내용이 칸보다 넓으면 가운데를
#    기준으로 **양쪽으로** 삐져나간다(왼쪽 -109 가 그 절반).
#    ★ 이 검사는 CSS 원문을 읽는 고정 핀이다 — 실브라우저 계산값이 아니다.
#      (렌더 확인은 실측 감사가 했고, 여기서는 그 고침이 지워지는 것만 막는다.)

def _폰_블록():
    """@media (max-width: 768px) { ... } 본문 — 중괄호 짝을 세어 떼어 온다."""
    자리 = _CSS.find('@media (max-width: 768px)')
    assert 자리 >= 0, '폰 @media 블록이 통째로 사라졌다 — 375px 에서 문서폭 496 재발'
    깊이 = 0
    시작 = _CSS.index('{', 자리)
    for i in range(시작, len(_CSS)):
        if _CSS[i] == '{':
            깊이 += 1
        elif _CSS[i] == '}':
            깊이 -= 1
            if 깊이 == 0:
                return _CSS[시작 + 1:i]
    raise AssertionError('폰 @media 블록의 중괄호가 안 닫혔다')


def _폰_규칙(선택자):
    블록 = _폰_블록()
    m = re.search(re.escape(선택자) + r'\s*\{([^}]*)\}', 블록)
    assert m, '@media 폰 블록 안에 %s 규칙이 없다' % 선택자
    return m.group(1)


def test_폰에서_탭줄은_자기_안에서만_스크롤된다():
    본문 = _폰_규칙('.tn-tabs')
    assert 'overflow-x: auto' in 본문, '탭 줄이 스스로 스크롤을 안 가지면 body 가 옆으로 밀린다'
    assert 'flex-start' in 본문, '가운데 정렬이 남으면 탭이 왼쪽 화면 밖(-109px)으로 나간다'


def test_폰에서_탭줄_오른쪽_끝은_흐려진다():
    """더 있음을 알리는 힌트 — sidebar_bulk·optgen 가로 탭과 같은 수법."""
    본문 = _폰_규칙('.tn-tabs')
    assert 'mask-image: linear-gradient(to right' in 본문


def test_폰_보정은_media_밖으로_새지_않는다():
    """PC 렌더 1px 불변이 조건이다 — @media 밖 원 규칙에 overflow 가 붙으면 위반."""
    자리 = _CSS.find('@media')
    미디어_밖 = _CSS[:자리]
    m = re.search(r'\.tn-tabs\s*\{([^}]*)\}', 미디어_밖)
    assert m and 'overflow' not in m.group(1), 'PC 쪽 .tn-tabs 에 overflow 가 새어 들었다'


def test_설치된_앱_껍데기에서는_상단탭을_통째로_숨긴다():
    """.ms-on(mobile_shell.js 가 html 에 붙임) = 껍데기가 자기 상단바+하단탭을
       그리는 상태 — PC 상단 메뉴는 죽은 무게이자 가로 넘침의 원인이라 숨긴다."""
    m = re.search(r'\.ms-on\s+\.tn\s*\{([^}]*)\}', _CSS)
    assert m, '.ms-on .tn 규칙이 없다 — 설치된 앱에서 PC 상단 메뉴가 그대로 뜬다'
    assert 'display: none' in m.group(1)


def test_폰에서_전용사이드바_줄은_세로로_쌓인다():
    """3회차 실측(2026-08-05) — 상단 메뉴를 고치자 드러난 2층의 뿌리.

    .tn-body 가 폰에서도 가로 flex 로 남으면:
      · /bulk/  — sidebar_bulk 의 4a 접힘(@media)이 여기 (0,3,0) sticky 규칙과
        toss 의 flex-shrink:0 에 져서, width:auto 만 적용된 가로 flex 항목이
        내용폭(가로 nav 줄 max-content)=926px 로 부푼다(docW 1,201 실측).
        증거: .sb-modeswitch grid 3×1fr 에서 a.sb-mode R=608 = 926 폭의 2번째 칸 끝.
      · /inventory/ — 240px 사이드바가 가로로 남아 main 이 135px.
        필터 줄의 min-width(칩상자 240·select 140)가 그 칸을 뚫는다(docW 529,
        select R=429 = 289+140 · #chipBox R=529 = 289+240 으로 전부 설명).
    한 곳(.tn-body 세로 전환 + sticky 해제)으로 두 사용처가 같이 낫는다."""
    본문 = _폰_규칙('.app.tn-on > .tn-body')
    assert 'flex-direction: column' in 본문, (
        '.tn-body 세로 전환이 없다 — bulk 926px·inventory 135px main 재발')
    사이드바 = _폰_규칙('.app.tn-on > .tn-body > .sidebar')
    assert 'position: static' in 사이드바, (
        '사이드바 sticky 를 폰에서 안 풀면 (0,3,0) 규칙이 각 화면의 접힘 @media 를 이긴다')
    assert 'width: auto' in 사이드바 and 'height: auto' in 사이드바


# ── 5) 폰 터치로 펼침 판이 열린다 (라이브 상호작용 감사 2026-08-05) ──────────────
#    실측: 375px 에서 .tn-tab 을 click 해도 .tn-mega 가 display:none 그대로.
#    열림 통로가 :hover/:focus-within 뿐인데 폰 터치엔 :hover 가 없고,
#    mousedown preventDefault(PC 「닫히지 않는 판」 방지용 — 못 건드림)가
#    포커스 경로까지 막아서다. 고침 = 폰 분기(matchMedia)에서 click 이 .tn-open 토글.

def test_폰에서는_탭_클릭이_판을_토글한다():
    블록 = _폰_블록()
    assert '.tn-tab.tn-open .tn-mega' in 블록, (
        '@media 폰 블록에 .tn-open 열림 규칙이 없다 — 폰에서 상단 메뉴가 다시 안 열린다')
    m = re.search(r'\.tn-open[^{;]*\{([^}]*)\}', 블록)
    assert m and 'display: flex' in m.group(1)


def test_폰_토글은_유령_hover_간섭을_이긴다():
    """터치 뒤 :hover 가 탭 하나에 유령으로 남으면 「한 번에 하나」 규칙
       .tn-tabs:hover .tn-tab:not(:hover) .tn-mega (0,5,0)이 **다른** 탭의 토글 판을
       display:none 으로 덮는다 — 그 경우를 이기는 (0,6,0) 선택자가 같이 있어야 한다."""
    블록 = _폰_블록()
    assert '.tn-tabs:hover .tn-tab.tn-open:not(:hover) .tn-mega' in 블록


def test_폰_토글_JS_가_배선돼_있다():
    assert 'tn-open' in _HTML, '.tn-open 을 붙이는 JS 가 없다 — CSS 규칙만으론 죽은 코드다'
    assert re.search(r"matchMedia\('\(max-width:\s*768px\)'\)", _HTML), (
        '폰 분기(matchMedia 768)가 없다 — PC 마우스 동작과 갈라 탈 수 없다')


def test_폰_토글은_하위_링크_이동을_막지_않는다():
    """탭 토글 click 핸들러가 <a> 클릭까지 삼키면 메뉴 항목으로 못 간다."""
    assert re.search(r"closest\('a'\)", _HTML), '링크 통과 가드(e.target.closest(a))가 없다'


def test_폰_토글이어도_PC_동작은_한_글자도_안_바뀐다():
    """PC 1px 불변이 조건 — @media 밖 CSS 원 규칙과 PC 마우스 JS 가 그대로여야 한다."""
    자리 = _CSS.find('@media')
    미디어_밖 = _CSS[:자리]
    assert '.tn-tab:hover .tn-mega' in 미디어_밖, 'PC hover 열림 규칙이 사라졌다'
    assert '.tn-tab:focus-within .tn-mega' in 미디어_밖, '키보드 통로가 사라졌다'
    assert '.tn-tabs:hover .tn-tab:not(:hover) .tn-mega' in 미디어_밖, (
        'PC 「한 번에 하나」 규칙이 사라졌다')
    assert 'tn-open' not in 미디어_밖, 'PC 쪽 CSS 에 폰 토글이 새어 들었다'
    # JS — 마우스 길의 preventDefault(「닫히지 않는 판」 방지)도 그대로 있어야 한다
    assert "addEventListener('mousedown'" in _HTML and 'preventDefault' in _HTML


def test_폰_판_안_하위_링크는_44px_손끝이다():
    # [2026-08-06 라이브 실측] 탭 토글은 됐는데 열린 판의 링크가 24px 였다 —
    # 겹 하나를 고치면 다음 겹이 드러난다(감사 교훈 그대로).
    블록 = _폰_블록()
    m = re.search(r'\.tn-mega \.tn-ml[^{]*\{([^}]*)\}', 블록)
    assert m, '@media 폰 블록에 .tn-mega .tn-ml 손끝 규칙이 없다 — 링크 24px 재발'
    본문 = m.group(1)
    mh = re.search(r'min-height\s*:\s*([\d.]+)px', 본문)
    assert mh and float(mh.group(1)) >= 44, '판 안 링크 손끝 목표 44px 미만'
    assert 'align-items: center' in 본문, '높이만 늘면 글자가 위에 붙는다 — 세로 가운데 필요'


# ── samba-wave 전환 스위치 — 상단 탭의 「대량등록」도 사이드바 카드와 같은 곳을 봐야 한다 ──
def _대량등록_있는_topnav():
    lay = _레이아웃([], standalone=[
        {'id': 'i_home', 'name': '홈', 'url': '/'},
        {'id': 'i_road', 'name': '로드맵', 'url': '/roadmap', 'active_key': 'roadmap'},
        {'id': 'i_bulk', 'name': '대량등록', 'url': '/bulk/', 'active_key': 'bulk'},
    ])
    return build(lay)


def test_samba_wave_미설정이면_대량등록_링크는_그대로다():
    out = apply_samba_wave_override(_대량등록_있는_topnav(), None)
    by_key = {it['active_key']: it['url'] for it in out['loose']}
    assert by_key['bulk'] == '/bulk/'


def test_samba_wave_설정되면_대량등록_링크만_바뀐다():
    out = apply_samba_wave_override(_대량등록_있는_topnav(), 'https://samba.mou-m.com')
    by_key = {it['active_key']: it['url'] for it in out['loose']}
    assert by_key['bulk'] == 'https://samba.mou-m.com'
    assert by_key['roadmap'] == '/roadmap', '대량등록 아닌 다른 loose 항목까지 바뀌면 안 된다'


def test_samba_wave_원본_topnav는_제자리에서_안_바뀐다():
    """topnav['loose'] 원소는 get_layout_for_template() 이 돌려준 layout 과 같은
    dict 일 수 있다 — 제자리 수정하면 캐시/공유본이 오염돼 다음 요청에도 샌다."""
    원본 = _대량등록_있는_topnav()
    apply_samba_wave_override(원본, 'https://samba.mou-m.com')
    by_key = {it['active_key']: it['url'] for it in 원본['loose']}
    assert by_key['bulk'] == '/bulk/', '원본을 제자리에서 고치면 안 된다'
