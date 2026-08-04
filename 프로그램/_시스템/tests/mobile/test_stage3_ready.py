# -*- coding: utf-8 -*-
"""3단계 배치1·2 — 폰 대응 완료(MOBILE_READY) 배선과 화면들의 @media 를 못 박는다.

무엇을 지키나
    ① MOBILE_READY_URLS 는 진짜 라우트다(오타 나면 띠 생략이 조용히 안 먹는다).
    ② base.html JSON(ms-tabs-data)에 ready 가 실려 내려간다.
    ③ mobile_shell.js 가 ready 를 읽고 그 화면에서 안내 띠를 생략한다 —
       판정 줄을 **통째로** 못 박는다(낱말 검사는 이 저장소가 네 번 당한 함정).
    ④ 각 화면의 @media 규칙이 실제 존재하는 선택자를 가리킨다 —
       「기능은 맞는데 화면엔 아무 일도 없는」 함정(1단계 실사고)의 방지.

★ /source-registry 는 배치1 계획에 있었으나 **라우트 자체가 없다** —
  2026-06-30 소싱처 사전 블루프린트 제거(webapp/routes/__init__.py:84,
  크롤링 가이드 전체보기로 통합). 그래서 배치1은 /alerts·/trash(+짝 화면 /audit).

[배치2 · 2026-08-04] 화면 4개 추가 — /catalog/(탭 3개 = partial 3개)·/data-guide·
  /live-send-test·/reports/notion-todo. 노션 일일보고는 템플릿이 아니라
  routes/notion_report.py 의 _CSS 문자열 안에 산다(base.html 밖 독립 화면) —
  소스 로더가 그 파일을 그대로 읽는다.
"""
import json
import re
from pathlib import Path

import pytest

# 같은 폴더의 형제 모듈 — 메뉴 줄(주소, 배지) 파서를 재사용한다(사본 금지).
from test_menu_single_source import _MenuRows
from tests.mobile.conftest import require_sqlite, shell_blob_of

ADMIN_EMAIL = 'stage3-admin@test.local'


@pytest.fixture
def client(flask_app):
    """admin 으로 로그인된 클라이언트 — /trash 가 admin 전용 게이트다.

    ★ admin 을 **직접 만든다** — 안 만들면 실행 순서에 기댄다.
      실측: 파일 단독 실행에서 빈 DB 라 자동 로그인이 집을 사람이 없어
      /trash·/audit 이 302, 심지어 /alerts 도 로그인 벽에 걸렸다.
      전체 실행에선 앞 파일이 남긴 admin 덕에 우연히 통과했다 —
      test_shell_pages.py 의 client 픽스처와 같은 이유·같은 처방이다.
    """
    require_sqlite()
    from shared.db import SessionLocal
    from webapp.auth.models import User
    s = SessionLocal()
    try:
        u = s.query(User).filter(User.email == ADMIN_EMAIL).first()
        if u is None:
            u = User(email=ADMIN_EMAIL, name='admin', password_hash='x',
                     role='admin', is_active=True)
            s.add(u)
        u.is_active = True
        s.commit()
    finally:
        s.close()
    return flask_app.test_client()


def _static(name: str) -> str:
    import config
    return (Path(config.PROJECT_ROOT) / 'webapp' / 'static' / name).read_text(encoding='utf-8')


def _template(rel: str) -> str:
    import config
    return (Path(config.PROJECT_ROOT) / 'webapp' / 'templates' / rel).read_text(encoding='utf-8')


# ─────────────────────────────────────────────────────────────
# ① 집합 자체 — 오타·모순을 여기서 잡는다
# ─────────────────────────────────────────────────────────────

def test_READY_주소가_전부_진짜_라우트다(flask_app):
    """오타(/alert 등)면 에러 없이 안내 띠만 계속 뜬다 — 그래서 라우트와 못 박는다."""
    from webapp.routes.mobile_shell import MOBILE_READY_URLS, same_route
    assert MOBILE_READY_URLS, 'READY 집합이 비었다 — 이 시험이 헛돈다'
    known = {same_route(str(r.rule)) for r in flask_app.url_map.iter_rules()}
    for url in sorted(MOBILE_READY_URLS):
        assert same_route(url) in known, \
            f'{url} 은 등록된 라우트가 아니다 — 띠 생략이 조용히 안 먹는다'


def test_배치1_세_주소가_READY에_있다():
    from webapp.routes.mobile_shell import MOBILE_READY_MENU_URLS, MOBILE_READY_URLS
    assert {'/alerts', '/trash', '/audit'} <= MOBILE_READY_URLS
    # 메뉴 배지 줄도 고정 목록으로 못 박는다 — 아래 배지 시험(④)은 집합을 그대로
    # 돌기 때문에, 집합에서 줄이 빠지면 검사도 같이 빠져 조용히 약해진다.
    assert {'/alerts', '/trash'} <= MOBILE_READY_MENU_URLS


def test_배치2_주소가_READY에_있다():
    """배치2 네 화면 + 카탈로그 탭 3개 — 탭은 물음표 뒤로 갈리므로(same_screen 이
    보존) 탭 주소를 빼먹으면 그 탭에서만 노란 띠가 되살아난다."""
    from webapp.routes.mobile_shell import MOBILE_READY_MENU_URLS, MOBILE_READY_URLS
    assert {'/catalog/', '/catalog/?tab=dashboard', '/catalog/?tab=pick',
            '/catalog/?tab=detail', '/data-guide', '/live-send-test',
            '/reports/notion-todo'} <= MOBILE_READY_URLS
    # 배치1 시험과 같은 이유의 고정 목록 — 배지 시험이 조용히 약해지는 걸 막는다.
    assert {'/catalog/', '/data-guide', '/live-send-test',
            '/reports/notion-todo'} <= MOBILE_READY_MENU_URLS


def test_메뉴배지_집합은_READY의_부분집합이다():
    """READY 에 없는 주소에 배지만 붙으면 「폰 전용이라더니 PC 판」 거짓 표시가 된다."""
    from webapp.routes.mobile_shell import MOBILE_READY_MENU_URLS, MOBILE_READY_URLS
    assert MOBILE_READY_MENU_URLS, '배지용 집합이 비었다 — 이 시험이 헛돈다'
    assert MOBILE_READY_MENU_URLS <= MOBILE_READY_URLS, \
        f'배지만 있고 READY 에 없는 주소: {MOBILE_READY_MENU_URLS - MOBILE_READY_URLS}'


def test_메뉴배지_집합이_배지집합에_실제로_합쳐진다():
    """PHONE_NATIVE_BADGE_URLS 의 합집합 식을 누가 걷어내도 여기서 잡는다."""
    from webapp.routes.mobile_shell import (MOBILE_READY_MENU_URLS,
                                            PHONE_NATIVE_BADGE_URLS)
    assert MOBILE_READY_MENU_URLS <= PHONE_NATIVE_BADGE_URLS


# ─────────────────────────────────────────────────────────────
# ② 서버 → 화면: JSON 블롭에 ready 가 실린다
#    (파서는 conftest.shell_blob_of 하나 — test_shell_pages 와 공용, 사본 금지)
# ─────────────────────────────────────────────────────────────

def test_JSON_블롭에_ready가_실린다(client):
    """JS 는 이 칸만 읽는다 — 서버 집합과 **완전히 같아야** 원천이 하나로 남는다."""
    from webapp.routes.mobile_shell import MOBILE_READY_SCREENS
    r = client.get('/')
    assert r.status_code == 200
    blob = shell_blob_of(r.get_data(as_text=True))
    assert 'ready' in blob, 'JSON 에 ready 칸이 없다 — JS 가 읽을 게 없다'
    assert blob['ready'] == sorted(MOBILE_READY_SCREENS), \
        '화면의 ready 가 서버 원천(MOBILE_READY_SCREENS)과 다르다'
    assert blob['ready'], 'ready 가 빈 목록이다 — 이 시험이 헛돈다'


# ─────────────────────────────────────────────────────────────
# ③ JS — 판정 줄을 통째로 못 박는다
# ─────────────────────────────────────────────────────────────

def test_JS가_ready를_읽고_안내띠를_생략한다():
    src = _static('mobile_shell.js')
    # ready 를 실제로 파싱하는 줄
    assert 'ready: Array.isArray(d.ready) ? d.ready : []' in src, \
        'JSON 의 ready 칸을 안 읽는다'
    # 생략 판정이 입구(mount)에서 실제로 쓰이는 줄 — 함수만 있으면 죽은 장식이다
    assert 'if (!isReadyScreen(data.ready)) body.insertBefore(buildNotice(), body.firstChild);' in src, \
        'ready 판정이 안내 띠 부착을 실제로 거르지 않는다'
    assert 'return ready.indexOf(sameScreen(window.location.pathname, window.location.search)) !== -1;' in src, \
        '지금 주소를 ready 목록과 비교하는 줄이 없다'


def test_JS_주소_다듬기가_서버와_같은_규칙이다():
    """서버 same_screen 과 두 벌이 어긋나면 띠가 조용히 잘못 뜬다 — 규칙 줄을 못 박는다."""
    src = _static('mobile_shell.js')
    assert "var p = path.split('#')[0].replace(/\\/+$/, '') || '/';" in src, \
        '끝 빗금·#조각 다듬기(서버 same_screen 대응)가 없거나 모양이 바뀌었다'
    assert 'return p + (search || \'\');' in src, \
        '물음표 뒤를 보존하는 줄이 없다 — 주문 탭 4개가 한 화면으로 뭉개진다'


def test_JS에_READY_주소를_직접_적지_않는다():
    """원천은 서버 MOBILE_READY_URLS 하나 — JS 에 적으면 두 곳이 갈라진다."""
    from webapp.routes.mobile_shell import MOBILE_READY_URLS
    src = _static('mobile_shell.js')
    for url in MOBILE_READY_URLS:
        assert f"'{url}'" not in src and f'"{url}"' not in src, \
            f'JS 가 {url} 을 직접 안다 — 원천이 둘로 갈라진다'


# ─────────────────────────────────────────────────────────────
# ④ 메뉴 배지 — READY 메뉴 줄마다 '폰 전용'이 실제로 그려진다
# ─────────────────────────────────────────────────────────────

def test_READY_메뉴줄에_폰전용_배지가_그려진다(client):
    """배치1(/alerts·/trash) + 배치2(카탈로그·가이드·실전송·노션) 전부 —
    집합을 그대로 돌므로 배치3 이후에 추가되는 줄도 자동으로 지켜진다."""
    from webapp.routes.mobile_shell import MOBILE_READY_MENU_URLS
    r = client.get('/mobile/menu')
    assert r.status_code == 200
    p = _MenuRows()
    p.feed(r.get_data(as_text=True))
    by_url = {row['url']: row for row in p.rows}
    for url in sorted(MOBILE_READY_MENU_URLS):
        assert url in by_url, f'{url} 줄이 메뉴에 없다'
        assert by_url[url]['badge'] == '폰 전용', \
            f'{url} 배지가 {by_url[url]["badge"]!r} — 폰 대응했는데 PC 화면으로 뜬다'
        assert 'native' in by_url[url]['badge_class'], \
            f'{url} 배지 색이 PC 배지와 같다(native 없음)'


def test_배지의_사이드바_대조가_이제_헛돌지_않는다():
    """test_배지집합에_넣은_PC주소는_사이드바에_실제로_있다 는 배치1 전까지 0건(vacuous)
    이었다 — 이제 /mobile 아닌 주소가 진짜 들어갔는지를 여기서 못 박는다."""
    from webapp.routes.mobile_shell import PHONE_NATIVE_BADGE_URLS
    non_mobile = [u for u in PHONE_NATIVE_BADGE_URLS if not u.startswith('/mobile')]
    assert non_mobile, 'PC 주소가 배지 집합에 하나도 없다 — 사이드바 대조가 다시 헛돈다'


# ─────────────────────────────────────────────────────────────
# ⑤ 화면들 — @media 가 실려 있고, 실재하는 선택자만 가리킨다
# ─────────────────────────────────────────────────────────────

#: url → 템플릿 경로(templates/ 기준). 카탈로그는 탭마다 partial 이 다르다 —
#  탭 주소로 열면 그 partial 의 @media 만 실리므로 탭별로 따로 못 박는다.
_SCREENS = {
    '/alerts': 'alerts/index.html',
    '/trash':  'trash/index.html',
    '/audit':  'trash/audit.html',
    '/catalog/': 'catalog/index.html',
    '/catalog/?tab=dashboard': 'catalog/partials/_dashboard.html',
    '/catalog/?tab=pick': 'catalog/partials/_pick.html',
    '/catalog/?tab=detail': 'catalog/partials/_detail.html',
    '/data-guide': 'data_guide.html',
    '/live-send-test': 'live_send_test/index.html',
}

#: 템플릿이 아니라 라우트 파일 안(_CSS 문자열)에 사는 화면 — base.html 밖 독립 화면.
#  경로는 저장소(PROJECT_ROOT) 기준.
_PY_SCREENS = {
    '/reports/notion-todo': 'webapp/routes/notion_report.py',
}

_ALL_SCREENS = {**_SCREENS, **_PY_SCREENS}

_MEDIA_HEAD = '@media (max-width: 768px) {'


def _src_of(url: str) -> str:
    """화면의 소스 원문 — 템플릿 파일 또는(노션) 라우트 .py 파일."""
    if url in _PY_SCREENS:
        import config
        return (Path(config.PROJECT_ROOT) / _PY_SCREENS[url]).read_text(encoding='utf-8')
    return _template(_SCREENS[url])


def _media_body(src: str) -> str:
    """소스의 @media 블록 본문 — 중괄호 짝으로 끝을 찾는다(정규식 탐욕 함정 회피)."""
    start = src.index(_MEDIA_HEAD)
    depth, i = 1, start + len(_MEDIA_HEAD)
    while depth and i < len(src):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
        i += 1
    return src[start + len(_MEDIA_HEAD):i - 1]


def _style_blocks(src: str) -> list[str]:
    return re.findall(r'<style>(.*?)</style>', src, re.S)


def _markup_of(src: str, url: str) -> str:
    """선택자 실재 대조의 검사 대상 — CSS 를 걷어낸 나머지 전부.

    배치1은 「<style> 앞부분」만 봤는데, 배치2 화면들은 표·줄을 **JS 가 문자열로
    조립**한다(예: _dashboard 의 <table>). 그래서 <style> 블록들만 빼고
    마크업+JS 문자열을 통째로 본다 — CSS 정의는 빠지므로 「스타일에만 있고
    아무 데도 안 쓰는 클래스」는 여전히 잡힌다.
    .py 화면은 <style> 태그가 없다 — @media 본문만 걷어낸다(남는 _CSS 의 PC 규칙엔
    class="…" 모양이 없어 대조를 오염시키지 않는다).
    """
    if url in _PY_SCREENS:
        return src.replace(_MEDIA_HEAD + _media_body(src) + '}', '')
    out = src
    for block in _style_blocks(src):
        out = out.replace('<style>' + block + '</style>', '')
    return out


@pytest.mark.parametrize('url,rel', sorted(_ALL_SCREENS.items()))
def test_화면마다_media_블록이_있다(url, rel):
    src = _src_of(url)
    assert _MEDIA_HEAD in src, f'{rel} 에 폰(≤768px) @media 블록이 없다'
    if url in _PY_SCREENS:
        # _CSS 는 PC 규칙과 한 문자열이라 「블록 밖 규칙 0」 검사가 성립하지 않는다.
        # PC 렌더 불변은 @media 안에만 덧붙였다는 코드리뷰 + tests/design 회귀가 지킨다.
        return
    # 블록 밖 규칙 금지 — @media 를 담은 <style> 은 그 블록만 담아야 PC 렌더가 안 바뀐다
    # (스펙 §1: 덧붙임은 「@media 만 담은 새 <style> 블록」으로).
    holder = next((b for b in _style_blocks(src) if _MEDIA_HEAD in b), None)
    assert holder is not None, f'{rel}: @media 가 <style> 밖에 있다'
    outside = holder.replace(_MEDIA_HEAD + _media_body(src) + '}', '')
    assert not re.search(r'[^\s]\s*\{', re.sub(r'/\*.*?\*/', '', outside, flags=re.S)), \
        f'{rel} 의 @media <style> 에 블록 밖 규칙이 있다 — PC 렌더가 바뀐다(스펙 §1 위반)'


_TOKEN = re.compile(r'([.#])([A-Za-z0-9_-]+)|\[([a-z-]+)="([^"]+)"\]|(?<![\w.#:-])([a-z]{2,})(?![\w-])')


@pytest.mark.parametrize('url,rel', sorted(_ALL_SCREENS.items()))
def test_media_규칙이_실재하는_선택자만_가리킨다(url, rel):
    """🔴 「기능은 맞는데 화면엔 아무 일도 없는」 함정 — 규칙이 가리키는 클래스·id·
    요소·속성이 그 화면 마크업(JS 조립 문자열 포함)에 실제로 있는지 전수 대조한다."""
    src = _src_of(url)
    body = _media_body(src)
    css_only = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
    selectors = re.findall(r'([^{}]+)\{', css_only)
    assert selectors, f'{rel} 의 @media 블록에 규칙이 하나도 없다'
    markup = _markup_of(src, url)
    # class 표기 세 벌 전부 본다 — 템플릿 class="…"·파이썬 class='…'·JS el.className='…'
    def has_class(name: str) -> bool:
        return bool(re.search(r'class=["\'][^"\']*\b' + re.escape(name), markup)
                    or re.search(r'className\s*=\s*["\'][^"\']*\b' + re.escape(name), markup))
    checked = 0
    for group in selectors:
        for sel in group.split(','):
            sel = re.sub(r'::?[a-z-]+(\([^)]*\))?', '', sel).strip()   # :first-child 등 제거
            for m in _TOKEN.finditer(sel):
                kind_id, name, attr, val, elem = m.groups()
                if kind_id == '#':
                    assert f'id="{name}"' in markup or f"id='{name}'" in markup, \
                        f'{rel}: #{name} 이 마크업에 없다'
                elif kind_id == '.':
                    assert has_class(name), f'{rel}: .{name} 이 마크업에 없다'
                elif attr:
                    assert f'{attr}="{val}"' in markup or f"{attr}='{val}'" in markup, \
                        f'{rel}: [{attr}="{val}"] 이 마크업에 없다'
                elif elem and elem not in ('and', 'max-width'):
                    assert f'<{elem}' in markup, f'{rel}: <{elem}> 요소가 마크업에 없다'
                checked += 1
    assert checked >= 5, f'{rel}: 대조한 선택자 조각이 {checked}개뿐 — 이 시험이 헛돈다'


@pytest.mark.parametrize('url,rel', sorted(_ALL_SCREENS.items()))
def test_화면이_실제로_media_를_싣고_열린다(url, rel, client):
    """파일이 아니라 **서빙된 HTML** 에서 본다 — 죽은 파일이면 여기서 걸린다.

    🔴 헤더 존재만 보면 카탈로그 탭이 헛돈다 — 어느 탭을 열어도 index.html 의
    @media 가 실려 있어, partial 의 블록이 죽어도 통과해 버린다. 그래서
    그 파일의 @media **본문 원문**이 응답에 그대로 실렸는지를 본다."""
    r = client.get(url)
    assert r.status_code == 200, f'{url} 이 안 열린다(status={r.status_code})'
    html = r.get_data(as_text=True)
    assert _media_body(_src_of(url)) in html, \
        f'{url} 응답에 {rel} 의 @media 본문이 없다 — 그 화면 블록이 실제로 안 실린다'


def test_표_처리_구조가_박혀있다():
    """화면별 표 선택(스펙 §1) — 구조 줄을 통째로 못 박는다(낱말 헛통과 방지).

    배치1: 휴지통·이력 = 가로 스크롤 + 첫 열 붙박이 / 알림 = 표 유지(안쪽 스크롤).
    배치2: 현황(10열)·데이터 가이드(코드 지도) = 가로 스크롤 + 첫 열 붙박이 /
           실전송(비교셀 180px) = 표 자체 가로 스크롤 / 담기·상세 = 격자 한 줄 접힘.
    """
    trash = _media_body(_template('trash/index.html'))
    audit = _media_body(_template('trash/audit.html'))
    alerts = _media_body(_template('alerts/index.html'))
    for body, name in ((trash, 'trash'), (audit, 'audit')):
        assert 'position: sticky; left: 0; z-index: 1;' in body, \
            f'{name}: 첫 열 붙박이(sticky)가 없다'
        assert 'background: var(--surface, #fff);' in body, \
            f'{name}: 붙박이 열에 배경이 없다 — 밀린 칸 글자가 비쳐 보인다'
    assert 'overflow-x: auto;' in alerts, 'alerts: 표 안쪽 가로 스크롤이 없다'
    assert 'min-height: 44px' in trash and 'min-height: 44px' in alerts, \
        '손끝 목표 44px 규칙이 빠졌다'

    # ── 배치2 ──
    dash = _media_body(_template('catalog/partials/_dashboard.html'))
    assert 'overflow-x: auto;' in dash and 'min-width: 720px;' in dash, \
        'dashboard: 10열 표의 가로 스크롤(컨테이너+최소폭)이 없다'
    assert 'position: sticky; left: 0; z-index: 1; background: var(--surface, #fff);' in dash, \
        'dashboard: 첫 열(마켓) 붙박이+배경이 없다'
    dg = _media_body(_template('data_guide.html'))
    assert 'display: block; overflow-x: auto;' in dg, \
        'data-guide: 코드 지도 표의 가로 스크롤이 없다'
    assert 'position: sticky; left: 0; z-index: 1; background: var(--page, #fff);' in dg, \
        'data-guide: 첫 열(노드) 붙박이+배경(자기 색 이름 --page)이 없다'
    lst = _media_body(_template('live_send_test/index.html'))
    assert 'display: block; overflow-x: auto;' in lst, \
        'live-send-test: 미리보기·직접값 표의 가로 스크롤이 없다'
    assert 'grid-template-columns: 1fr;' in lst, \
        'live-send-test: 직접 값 지정 두 칸이 한 칸으로 안 접힌다'
    pick = _media_body(_template('catalog/partials/_pick.html'))
    assert '.pk-wrap { grid-template-columns: 1fr; }' in pick, \
        'pick: 좌우 두 판이 세로 한 줄로 안 접힌다'
    assert '.pk-cart { position: static; }' in pick, \
        'pick: 담을 목록 sticky 가 폰에서 안 풀린다 — 스크롤을 가린다'
    detail = _media_body(_template('catalog/partials/_detail.html'))
    assert 'grid-template-columns: 1fr auto;' in detail, \
        'detail: 고정폭 여러 열이 2열 격자로 안 접힌다'
    notion = _media_body(_src_of('/reports/notion-todo'))
    assert 'min-height:44px' in notion and 'font-size:16px' in notion, \
        'notion-todo: 손끝 목표 44px·입력칸 16px(iOS 확대 방지)가 빠졌다'
    # 손끝 목표 44px — 배치2 전 화면
    for body, name in ((dash, 'dashboard'), (dg, 'data-guide'), (lst, 'live-send-test'),
                       (pick, 'pick'), (detail, 'detail')):
        assert 'min-height: 44px' in body, f'{name}: 손끝 목표 44px 규칙이 빠졌다'
    # 16px 입력칸(iOS 포커스 확대 방지) — 입력칸이 있는 화면
    for body, name in ((lst, 'live-send-test'), (pick, 'pick'), (detail, 'detail')):
        assert 'font-size: 16px;' in body, f'{name}: 입력칸 16px 규칙이 빠졌다'
