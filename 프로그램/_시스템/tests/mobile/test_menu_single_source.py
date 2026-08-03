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


def test_배지가_줄마다_맞게_붙는다(client):
    """어느 줄에 어느 배지가 붙는지까지 본다 — 종류만 세면 뒤바뀐 걸 못 잡는다."""
    from webapp.routes.api_sidebar import get_layout_for_template
    from webapp.routes.mobile import PHONE_NATIVE_URLS
    pc_urls = set(_all_urls(get_layout_for_template()))

    checked_pc = checked_phone = 0
    for r in menu_rows(client):
        if r['url'] in PHONE_NATIVE_URLS:
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


def test_폰_전용_주소가_진짜_있는_라우트다(flask_app):
    """🔴 '/mobile/crawl' 처럼 빗금 하나만 틀려도 배지가 조용히 'PC 화면' 이 된다.

    배지가 틀리는 건 에러를 안 내니, 주소가 진짜 있는 화면인지 여기서 못 박는다.
    """
    from webapp.routes.mobile import PHONE_NATIVE_URLS
    known = {str(r.rule) for r in flask_app.url_map.iter_rules()}
    for url in sorted(PHONE_NATIVE_URLS):
        path = url.split('?')[0]
        assert path in known or path + '/' in known, \
            f'{url} 은 등록된 라우트가 아니다 — 눌러도 404 인 줄이거나 배지가 안 붙는다'


def test_리모컨_줄은_admin_에게만_보인다(flask_app, monkeypatch):
    """크롤 리모컨은 admin 전용(mobile_crawl._admin_only)이다.

    member 에게 보여 주면 눌러도 403 만 나오는 줄이 된다 — 이 설계가 가장 피하려는
    '눌러도 아무 일 없는 조작칸'이 목록 형태로 되살아난다.

    ★ 라우트가 스스로 계산한 is_admin 을 쓰는지 보려고 **뷰 함수를 직접** 부른다.
      (`_phone_native_rows(True/False)` 만 시험하면, 라우트가 True 를 박아 넣어도 통과한다.)
    """
    import flask_login
    from webapp.routes.mobile import menu as menu_view

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
