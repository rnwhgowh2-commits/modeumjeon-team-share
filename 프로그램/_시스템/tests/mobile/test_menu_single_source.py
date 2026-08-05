# -*- coding: utf-8 -*-
"""폰 '전체' 메뉴는 PC 메뉴와 같은 원천을 쓴다.

따로 정의하면 새 화면을 만들 때 한쪽에만 넣고 다른 쪽엔 빼먹는다.
이 프로젝트엔 '만든 화면을 메뉴에 안 넣어 두 달간 주소를 직접 쳐야 했던' 기록이 있다.

★ 이 파일은 '낱말이 화면 어딘가 있나'로 검사하지 않는다 — 형제 화면(Task 3)에서
  그 방식이 네 번이나 헛통과했다(주석·변수 선언·엉뚱한 헤더·죽은 코드가 낱말을 대 줬다).
  그래서 HTML 을 **줄 단위로 파싱해** (주소, 배지) 짝을 보고 판정한다.
"""
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

# flask_app 픽스처는 tests/mobile/conftest.py 에 있다(네 파일이 쓴다).


class _MenuRows(HTMLParser):
    """class="mm-row" 인 <a> 를 (주소, 이름, 배지) 로 모은다.

    ★ 왜 문자열 검색을 안 쓰나 — `'폰 전용' in html` 은 주석·CSS 클래스명·죽은 갈래에
      그 낱말이 남아 있기만 해도 통과한다. 여기서 확인하려는 건 '어떤 줄에 어떤 배지가
      붙었나'라, 줄과 배지를 **묶어서** 봐야 한다.
    """

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []
        self._cur: dict | None = None
        self._slot: str | None = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = (d.get('class') or '').split()
        if tag == 'a' and 'mm-row' in cls:
            self._cur = {'url': d.get('href'), 'name': '', 'badge': None,
                         'badge_class': []}
            return
        if self._cur is None:
            return
        if tag == 'span' and 'mm-name' in cls:
            self._slot = 'name'
        elif tag == 'span' and 'mm-badge' in cls:
            self._slot = 'badge'
            self._cur['badge'] = ''
            # 색을 정하는 건 class 다 — 글자만 보면 '문구는 PC 화면인데 파랗게 뜨는'
            # 어긋남을 못 잡는다(실측: 그 변이가 시험을 그대로 통과했다).
            self._cur['badge_class'] = cls

    def handle_data(self, data):
        if self._cur is not None and self._slot:
            self._cur[self._slot] = (self._cur[self._slot] or '') + data.strip()

    def handle_endtag(self, tag):
        if tag == 'span':
            self._slot = None
        elif tag == 'a' and self._cur is not None:
            self.rows.append(self._cur)
            self._cur = None


def _all_urls(layout):
    urls = [it.get('url') for it in layout.get('standalone', [])]
    for st in layout.get('stages', []):
        urls += [it.get('url') for it in st.get('items', [])]
    return [u for u in urls if u]


@pytest.fixture
def client(flask_app):
    """이 화면은 권한 게이트가 없어 사용자를 만들 필요가 없다.

    (DISABLE_AUTH=1 이 전역 로그인 벽을 통과시킨다 — webapp/auth/__init__.py:73.)
    사용자를 안 만드니 진짜 DB 를 건드릴 일도 없다 → require_sqlite 가 필요 없다.
    """
    return flask_app.test_client()


def menu_rows(client):
    """'전체' 메뉴의 줄 목록 — 200 이 아니면 거기서 세운다.

    ★ 본문이 비면(302·404) '없는지 보는' 시험이 저절로 통과한다. 형제 화면에서 실제로
      그렇게 새서 아무것도 검증하지 못한 시험이 초록불이었다. 그래서 먼저 못 박는다.
    """
    r = client.get('/mobile/menu')
    assert r.status_code == 200, \
        f"'전체' 메뉴가 안 열린다(status={r.status_code}) — 아래 시험은 의미가 없다"
    p = _MenuRows()
    p.feed(r.get_data(as_text=True))
    assert p.rows, '메뉴에서 줄(mm-row)을 하나도 못 찾았다 — 이 시험이 헛돈다'
    return p.rows


def test_PC_메뉴의_모든_항목이_폰_메뉴에도_있다(client):
    from webapp.routes.api_sidebar import get_layout_for_template
    want = _all_urls(get_layout_for_template())
    assert want, 'PC 메뉴 원천이 비어 있다 — 이 시험이 헛돈다'
    have = {r['url'] for r in menu_rows(client)}
    missing = [u for u in want if u not in have]
    assert not missing, f'폰 메뉴에서 빠진 항목: {missing}'


def test_메뉴는_하드코딩된_목록을_쓰지_않는다():
    """템플릿에 메뉴 이름을 직접 적어두면 원천이 둘로 갈라진다."""
    from pathlib import Path
    import config
    tpl = Path(config.PROJECT_ROOT) / 'webapp' / 'templates' / 'mobile' / 'menu.html'
    src = tpl.read_text(encoding='utf-8')
    assert 'layout' in src, '레이아웃 원천을 안 쓰고 있다'
    for hardcoded in ('모음전 상품관리', '주문 내역', '마진 계산기'):
        assert hardcoded not in src, f'메뉴 이름을 템플릿에 박아뒀다: {hardcoded}'


def test_로그아웃이_메뉴에_있다(client):
    assert any(r['url'] == '/auth/logout' for r in menu_rows(client)), \
        '로그아웃 줄이 없다 — 폰에서 계정을 바꿀 길이 없어진다'


def test_배지_두_종류가_실제로_한_줄씩은_붙는다(client):
    """🔴 배지 집합이 메뉴 주소와 안 맞으면 **모든 줄이 조용히 'PC 화면'** 이 된다.

    에러도 안 나고 화면도 멀쩡해 보여서, 배지가 통째로 죽은 걸 아무도 모른다.
    실제로 PC 메뉴(sidebar_layout)에는 /mobile/* 주소가 하나도 없다 — 폰 전용 화면을
    메뉴에 같이 싣지 않으면 '폰 전용' 배지는 영영 한 줄도 안 붙는다.
    """
    rows = menu_rows(client)
    badges = {r['badge'] for r in rows if r['badge']}
    assert '폰 전용' in badges, "'폰 전용' 배지가 붙은 줄이 하나도 없다 — 배지가 죽었다"
    assert 'PC 화면' in badges, "'PC 화면' 배지가 붙은 줄이 하나도 없다"


def test_폰_전용_화면이_전부_메뉴에_그려진다(client):
    """🔴 목록에 있는데 **그려지지 않는** 경우 — 이 화면이 존재하는 이유 그 자체.

    실측으로 드러난 구멍: 템플릿 반복문에 조건을 하나 붙여 3줄을 빼도
    시험 10개가 전부 통과했다. 「화면도 있고 목록에도 있는데 메뉴엔 안 뜬다」 —
    두 달간 주소를 직접 쳤던 그 사고와 정확히 같은 모양이다.

    왜 안 잡혔나: PC 항목 검사는 PC 25줄만 보고, 배지 검사는 **그려진 줄을 순회**할
    뿐이라 빠진 줄을 볼 수 없고(한 줄만 남아도 통과), 역방향 관문은 라우트와 **목록**만
    맞춰 볼 뿐 렌더 결과를 안 본다. 그래서 목록 → 렌더 방향을 여기서 못 박는다.
    """
    from webapp.routes.mobile_shell import phone_native_rows
    have = {r['url'] for r in menu_rows(client)}
    # member 기준으로 본다 — admin 전용 줄(리모컨)은 안 그려지는 게 정상이라
    # 여기 넣으면 시험이 그 정상 동작을 결함으로 신고한다.
    want = {it['url'] for it in phone_native_rows(False)}
    assert want, '폰 전용 목록이 비었다 — 이 시험이 헛돈다'
    assert not (want - have), f'폰 전용인데 메뉴에 안 그려진 줄: {sorted(want - have)}'


def test_배지가_줄마다_맞게_붙는다(client):
    """어느 줄에 어느 배지가 붙는지까지 본다 — 종류만 세면 뒤바뀐 걸 못 잡는다.

    ⚠️ 정직하게 적어 둔다 — 이 반복문은 화면과 **같은 판정**(is_phone_native)을 쓴다.
      판정 자체가 틀리면 여기선 안 걸린다. 그래서 아래에 판정과 무관한 **고정 예**
      두 줄을 따로 못 박는다(그게 진짜 잡는 부분이다).
    """
    from webapp.routes.api_sidebar import get_layout_for_template
    from webapp.routes.mobile_shell import is_phone_native
    pc_urls = set(_all_urls(get_layout_for_template()))
    by_url = {r['url']: r for r in menu_rows(client)}

    # 판정 함수를 안 거치는 고정 예 — 뒤바뀜·전멸을 여기서 잡는다.
    assert by_url['/mobile/scan']['badge'] == '폰 전용'
    assert 'native' in by_url['/mobile/scan']['badge_class']
    assert by_url['/orders/?tab=list']['badge'] == 'PC 화면'
    assert 'native' not in by_url['/orders/?tab=list']['badge_class']

    checked_pc = checked_phone = 0
    for r in menu_rows(client):
        if is_phone_native(r['url']):
            assert r['badge'] == '폰 전용', f"폰 전용 화면인데 배지가 {r['badge']!r}: {r['url']}"
            assert 'native' in r['badge_class'], \
                f"'폰 전용' 인데 색이 PC 배지와 같다(native 없음): {r['url']}"
            checked_phone += 1
        elif r['url'] in pc_urls:
            assert r['badge'] == 'PC 화면', f"PC 화면인데 배지가 {r['badge']!r}: {r['url']}"
            assert 'native' not in r['badge_class'], \
                f"'PC 화면' 인데 폰 전용 색(native)으로 뜬다: {r['url']}"
            checked_pc += 1
    assert checked_phone, '폰 전용 줄을 한 개도 못 봤다 — 이 시험이 헛돈다'
    assert checked_pc, 'PC 화면 줄을 한 개도 못 봤다 — 이 시험이 헛돈다'


def test_설치안내_줄이_메뉴에_있다(client):
    """제외 목록이 적은 이유("고정줄에 이미 있다")가 **참인지** 확인한다.

    이유는 검증 가능한 사실 주장인데 아무도 안 보면, 누가 고정줄을 지웠을 때
    그 화면은 완전히 도달 불가가 되면서 시험은 초록불이다.
    """
    assert any(r['url'] == '/mobile/install' for r in menu_rows(client)), \
        '제외 목록은 "고정줄에 이미 있다"고 적었는데 그 줄이 메뉴에 없다'


def test_폰_전용_주소가_진짜_있는_라우트다(flask_app):
    """🔴 '/mobile/scann' 처럼 한 글자만 틀려도 배지가 조용히 'PC 화면' 이 된다.

    배지가 틀리는 건 에러를 안 내니, 주소가 진짜 있는 화면인지 여기서 못 박는다.
    """
    from webapp.routes.mobile_shell import PHONE_NATIVE_BADGE_URLS, same_route
    known = {same_route(str(r.rule)) for r in flask_app.url_map.iter_rules()}
    for url in sorted(PHONE_NATIVE_BADGE_URLS):
        assert same_route(url) in known, \
            f'{url} 은 등록된 라우트가 아니다 — 눌러도 404 인 줄이거나 배지가 안 붙는다'


def test_주소_모양이_달라도_같은_화면으로_본다():
    """🔴 정규화가 **프로덕션에** 있어야 한다 — 시험에만 있으면 배지가 조용히 틀린다.

    3단계 지침이 PC 주소를 배지 집합에 더하라고 안내하는데, 사이드바가
    '/orders?tab=list'(빗금 없음)로 갖고 있으면 생 문자열 비교는 안 맞는다.
    그런데 배지가 틀려도 에러가 안 난다 — 조용히 'PC 화면' 으로 되돌아간다.
    """
    from webapp.routes.mobile_shell import is_phone_native, same_screen

    # 끝 빗금·#조각은 화면을 안 가른다
    assert is_phone_native('/mobile') and is_phone_native('/mobile/')
    assert is_phone_native('/mobile/inventory/')
    assert is_phone_native('/mobile/scan#top')
    assert same_screen('/orders/?tab=list') == same_screen('/orders?tab=list')

    # 🔴 물음표 뒤(탭)는 **화면을 가른다** — 주문 관리는 한 주소의 탭 4개가
    #   메뉴에서 각각 다른 줄이다. 여기서 같다고 보면 하나만 폰 전용으로 바꿔도
    #   네 줄 전부에 '폰 전용' 이 붙는다.
    assert same_screen('/orders/?tab=list') != same_screen('/orders/?tab=ship')
    assert is_phone_native('/mobile/scan-batch?mode=in')
    assert not is_phone_native('/mobile/scan-batch?mode=zzz')

    # 남남인 주소는 안 걸려야 한다
    # [배치4b 정정] 예시가 /inventory/ 였는데 그 화면이 진짜 폰 대응이 됐다(READY 등록).
    #   「/mobile/inventory 와 /inventory 를 헷갈리지 않는다」는 원래 취지는
    #   아직 전환 안 된 괴물 화면(/orders — 배치5)으로 잇는다.
    assert not is_phone_native('/mobile/scann')
    assert not is_phone_native('/orders/?tab=list')


def test_배지집합에_넣은_PC주소는_사이드바에_실제로_있다():
    """3단계에서 PC 화면을 폰 전용으로 바꿀 때 적는 주소가 사이드바와 맞는지.

    ⚠️ 정직하게 적어 둔다 — **지금은 해당 항목이 0건이라 이 시험은 헛돈다(vacuous).**
      3단계에서 첫 PC 주소가 들어오는 순간부터 지켜진다. 그때 사이드바가 가진
      모양과 한 글자라도 다르면 배지가 조용히 안 붙는데, 그걸 여기서 잡는다.
    """
    from webapp.routes.api_sidebar import get_layout_for_template
    from webapp.routes.mobile_shell import PHONE_NATIVE_BADGE_URLS, same_screen
    sidebar = {same_screen(u) for u in _all_urls(get_layout_for_template())}
    for url in sorted(PHONE_NATIVE_BADGE_URLS):
        if url.startswith('/mobile'):
            continue                      # 폰 전용 화면 — 사이드바에 없는 게 정상
        assert same_screen(url) in sidebar, \
            f'{url} 은 PC 메뉴에 없는 주소다 — 배지가 한 줄도 안 붙는다'


def test_모든_폰_화면은_메뉴에_실리거나_빠진_이유가_적혀있다(flask_app):
    """🔴 반대 방향 — 새로 만든 폰 화면이 메뉴에 실렸나.

    PHONE_NATIVE 만으로는 '적어 둔 주소가 진짜 있나' 한 방향밖에 못 지킨다.
    그러면 Task 6·7 에서 폰 화면을 만들고 목록에 안 넣어도 **아무것도 안 깨진다** —
    이 화면이 존재하는 이유였던 그 사고(만든 화면이 메뉴에 없어 두 달간 주소를 직접 침)가
    폰 쪽에서 그대로 되살아난다. 그래서 등록된 라우트 쪽에서 거꾸로 훑는다.

    빼는 게 맞는 화면이면 MENU_EXEMPT_ROUTE_RULES 에 **이유와 함께** 적으면 통과한다.
    (동적 주소도 자동으로 안 봐준다 — 이유는 그 목록 주석에 적어 뒀다.)
    """
    from webapp.routes.mobile_shell import (
        MENU_EXEMPT_ROUTE_RULES, PHONE_NATIVE_BADGE_URLS, same_route)
    listed = {same_route(u) for u in PHONE_NATIVE_BADGE_URLS}

    seen, orphans = 0, []
    for r in flask_app.url_map.iter_rules():
        rule = str(r.rule)
        if not rule.startswith('/mobile') or 'GET' not in r.methods:
            continue
        if '/api/' in rule:            # 화면이 아니라 데이터 창구
            continue
        seen += 1
        if rule in MENU_EXEMPT_ROUTE_RULES or same_route(rule) in listed:
            continue
        orphans.append(rule)

    assert seen >= 5, f'폰 화면 라우트를 {seen}개밖에 못 찾았다 — 이 시험이 헛돈다'
    assert not orphans, (
        '메뉴 어디에도 없는 폰 화면이 있다(주소를 직접 쳐야만 들어간다): '
        f'{orphans}\n'
        '  → 메뉴에 넣으려면 webapp/routes/mobile_shell.py 의 PHONE_NATIVE_ROWS 에,\n'
        '     일부러 빼는 거면 같은 파일 MENU_EXEMPT_ROUTE_RULES 에 이유와 함께 적으세요.')


def test_빼둔_이유_목록이_썩지_않았다(flask_app):
    """없어진 라우트가 제외 목록에 남아 있으면, 다음 사람이 그걸 근거로 착각한다."""
    from webapp.routes.mobile_shell import MENU_EXEMPT_ROUTE_RULES
    known = {str(r.rule) for r in flask_app.url_map.iter_rules()}
    assert MENU_EXEMPT_ROUTE_RULES, '제외 목록이 비었다 — 이 시험이 헛돈다'
    for rule, why in MENU_EXEMPT_ROUTE_RULES.items():
        assert rule in known, f'{rule} 은 이제 없는 라우트다 — 제외 목록에서 빼세요'
        assert why.strip(), f'{rule} 을 왜 뺐는지가 안 적혀 있다'


def test_리모컨_줄은_admin_에게만_보인다(flask_app, monkeypatch):
    """크롤 리모컨은 admin 전용(mobile_crawl._admin_only)이다.

    member 에게 보여 주면 눌러도 403 만 나오는 줄이 된다 — 이 설계가 가장 피하려는
    '눌러도 아무 일 없는 조작칸'이 목록 형태로 되살아난다.

    ★ 라우트가 스스로 계산한 is_admin 을 쓰는지 보려고 **뷰 함수를 직접** 부른다.
      (`phone_native_rows(True/False)` 만 시험하면, 라우트가 True 를 박아 넣어도 통과한다.)
    """
    import flask_login
    from webapp.routes.mobile_shell import menu as menu_view

    def rows_for(is_admin):
        monkeypatch.setattr(flask_login, 'current_user',
                            SimpleNamespace(is_admin=is_admin))
        with flask_app.test_request_context('/mobile/menu'):
            p = _MenuRows()
            p.feed(menu_view())
        return {r['url'] for r in p.rows}

    member = rows_for(False)
    admin = rows_for(True)
    assert '/mobile/scan' in member, 'member 에게 폰 화면이 통째로 안 보인다 — 이 시험이 헛돈다'
    assert '/mobile/crawl/' not in member, 'member 에게 admin 전용 리모컨 줄이 보인다'
    assert '/mobile/crawl/' in admin, 'admin 에게도 리모컨 줄이 안 보인다'


def test_두_배지는_눈으로_구별된다(client):
    """🔴 뜻은 달라도 **똑같이 보이면** 배지를 단 뜻이 화면에 안 나타난다.

    형제 화면에서 겪은 것과 같은 부류다 — 기능만 맞고 보이는 게 그대로였다.
    (_base.html 이 style 을 인라인으로 실어 브라우저 없이 확인된다.)
    """
    import re
    html = client.get('/mobile/menu').get_data(as_text=True)

    def bg(selector):
        m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', html)
        assert m, f'{selector} 규칙이 없다'
        c = re.search(r'background\s*:\s*([^;]+)', m.group(1))
        assert c, f'{selector} 에 배경색이 없다'
        return c.group(1).strip()

    assert bg('.mm-badge') != bg('.mm-badge.native'), \
        "'폰 전용' 과 'PC 화면' 배지가 똑같이 보인다 — 구별하려고 단 배지가 무의미해진다"


def test_admin_전용_표시가_진짜_게이트와_묶여있다(flask_app, monkeypatch):
    """🔴 `admin_only` 는 mobile_crawl 게이트의 **사본**이다 — 사본은 어긋난다.

    게이트가 벗겨지면(팀원에게도 열기로 하면) 메뉴는 계속 숨긴다. 에러도 안 나고
    아무도 모르는 채 기능이 사라진다 — 이 파일이 잡으려는 '조용한 실패' 그 부류다.
    그래서 표시가 아니라 **게이트를 실제로 불러** 두 사실을 묶는다.
    """
    import flask_login
    from webapp.routes import mobile_crawl, mobile_guide
    from webapp.routes.mobile_shell import PHONE_NATIVE_ROWS

    marked = {it['url'] for it in PHONE_NATIVE_ROWS if it.get('admin_only')}
    # [F-2] 크롤 가이드도 admin — PC 원천(/sourcing-guide/*)의 게이트와 동일 정책.
    assert marked == {'/mobile/crawl/', '/mobile/guide'}, \
        f'admin 전용으로 표시된 줄이 바뀌었다: {marked} — 아래 게이트 확인도 같이 고치세요'

    monkeypatch.setattr(flask_login, 'current_user',
                        SimpleNamespace(is_authenticated=True, is_admin=False))
    for bp_mod, path in ((mobile_crawl, '/mobile/crawl/'),
                         (mobile_guide, '/mobile/guide')):
        gates = flask_app.before_request_funcs.get(bp_mod.bp.name) or []
        assert gates, f'{path} 에 blueprint 게이트가 없다 — 메뉴가 감추는 근거가 사라졌다'
        with flask_app.test_request_context(path):
            blocked = [g for g in gates if g() is not None]
        assert blocked, \
            f'member 인데 {path} 게이트가 통과시킨다 — 메뉴만 숨기고 있어 기능이 조용히 사라졌다'
