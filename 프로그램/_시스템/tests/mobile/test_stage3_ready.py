# -*- coding: utf-8 -*-
"""3단계 배치1 — 폰 대응 완료(MOBILE_READY) 배선과 화면 3개(@media)를 못 박는다.

무엇을 지키나
    ① MOBILE_READY_URLS 는 진짜 라우트다(오타 나면 띠 생략이 조용히 안 먹는다).
    ② base.html JSON(ms-tabs-data)에 ready 가 실려 내려간다.
    ③ mobile_shell.js 가 ready 를 읽고 그 화면에서 안내 띠를 생략한다 —
       판정 줄을 **통째로** 못 박는다(낱말 검사는 이 저장소가 네 번 당한 함정).
    ④ 배치1 화면(알림·휴지통·변경이력)의 @media 규칙이 실제 존재하는 선택자를
       가리킨다 — 「기능은 맞는데 화면엔 아무 일도 없는」 함정(1단계 실사고)의 방지.

★ /source-registry 는 배치1 계획에 있었으나 **라우트 자체가 없다** —
  2026-06-30 소싱처 사전 블루프린트 제거(webapp/routes/__init__.py:84,
  크롤링 가이드 전체보기로 통합). 그래서 배치1은 /alerts·/trash(+짝 화면 /audit).
"""
import json
import re
from pathlib import Path

import pytest

# 같은 폴더의 형제 모듈 — 메뉴 줄(주소, 배지) 파서를 재사용한다(사본 금지).
from test_menu_single_source import _MenuRows
from tests.mobile.conftest import require_sqlite

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
    from webapp.routes.mobile_shell import MOBILE_READY_URLS
    assert {'/alerts', '/trash', '/audit'} <= MOBILE_READY_URLS


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
# ─────────────────────────────────────────────────────────────

def _blob_of(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="ms-tabs-data">(.*?)</script>',
                  html, re.S)
    assert m, '탭 JSON 블록(ms-tabs-data)이 화면에 없다'
    return json.loads(m.group(1))


def test_JSON_블롭에_ready가_실린다(client):
    """JS 는 이 칸만 읽는다 — 서버 집합과 **완전히 같아야** 원천이 하나로 남는다."""
    from webapp.routes.mobile_shell import MOBILE_READY_SCREENS
    r = client.get('/')
    assert r.status_code == 200
    blob = _blob_of(r.get_data(as_text=True))
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
# ④ 메뉴 배지 — 배치1 줄에 '폰 전용'이 실제로 그려진다
# ─────────────────────────────────────────────────────────────

def test_배치1_메뉴줄에_폰전용_배지가_그려진다(client):
    r = client.get('/mobile/menu')
    assert r.status_code == 200
    p = _MenuRows()
    p.feed(r.get_data(as_text=True))
    by_url = {row['url']: row for row in p.rows}
    for url in ('/alerts', '/trash'):
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
# ⑤ 화면 3개 — @media 가 실려 있고, 실재하는 선택자만 가리킨다
# ─────────────────────────────────────────────────────────────

_SCREENS = {
    '/alerts': 'alerts/index.html',
    '/trash':  'trash/index.html',
    '/audit':  'trash/audit.html',
}

_MEDIA_HEAD = '@media (max-width: 768px) {'


def _media_body(tpl_src: str) -> str:
    """템플릿의 @media 블록 본문 — 중괄호 짝으로 끝을 찾는다(정규식 탐욕 함정 회피)."""
    start = tpl_src.index(_MEDIA_HEAD)
    depth, i = 1, start + len(_MEDIA_HEAD)
    while depth and i < len(tpl_src):
        if tpl_src[i] == '{':
            depth += 1
        elif tpl_src[i] == '}':
            depth -= 1
        i += 1
    return tpl_src[start + len(_MEDIA_HEAD):i - 1]


@pytest.mark.parametrize('url,rel', sorted(_SCREENS.items()))
def test_화면마다_media_블록이_있다(url, rel):
    src = _template(rel)
    assert _MEDIA_HEAD in src, f'{rel} 에 폰(≤768px) @media 블록이 없다'
    # 블록 밖 규칙 금지 — <style> 안에서 @media 앞뒤에 선언이 없어야 PC 렌더가 안 바뀐다.
    style = re.search(r'<style>(.*?)</style>', src, re.S).group(1)
    outside = style.replace(_MEDIA_HEAD + _media_body(src) + '}', '')
    assert not re.search(r'[^\s]\s*\{', re.sub(r'/\*.*?\*/', '', outside, flags=re.S)), \
        f'{rel} 의 <style> 에 @media 밖 규칙이 있다 — PC 렌더가 바뀐다(스펙 §1 위반)'


_TOKEN = re.compile(r'([.#])([A-Za-z0-9_-]+)|\[([a-z-]+)="([^"]+)"\]|(?<![\w.#:-])([a-z]{2,})(?![\w-])')


@pytest.mark.parametrize('url,rel', sorted(_SCREENS.items()))
def test_media_규칙이_실재하는_선택자만_가리킨다(url, rel):
    """🔴 「기능은 맞는데 화면엔 아무 일도 없는」 함정 — 규칙이 가리키는 클래스·id·
    요소·속성이 그 템플릿 마크업에 실제로 있는지 전수 대조한다."""
    src = _template(rel)
    body = _media_body(src)
    css_only = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
    selectors = re.findall(r'([^{}]+)\{', css_only)
    assert selectors, f'{rel} 의 @media 블록에 규칙이 하나도 없다'
    markup = src[:src.index('<style>')]          # 검사 대상은 마크업 쪽만
    checked = 0
    for group in selectors:
        for sel in group.split(','):
            sel = re.sub(r'::?[a-z-]+(\([^)]*\))?', '', sel).strip()   # :first-child 등 제거
            for m in _TOKEN.finditer(sel):
                kind_id, name, attr, val, elem = m.groups()
                if kind_id == '#':
                    assert f'id="{name}"' in markup, f'{rel}: #{name} 이 마크업에 없다'
                elif kind_id == '.':
                    assert re.search(r'class="[^"]*\b' + re.escape(name), markup), \
                        f'{rel}: .{name} 이 마크업에 없다'
                elif attr:
                    assert f'{attr}="{val}"' in markup, \
                        f'{rel}: [{attr}="{val}"] 이 마크업에 없다'
                elif elem and elem not in ('and', 'max-width'):
                    assert f'<{elem}' in markup, f'{rel}: <{elem}> 요소가 마크업에 없다'
                checked += 1
    assert checked >= 5, f'{rel}: 대조한 선택자 조각이 {checked}개뿐 — 이 시험이 헛돈다'


@pytest.mark.parametrize('url,rel', sorted(_SCREENS.items()))
def test_화면이_실제로_media_를_싣고_열린다(url, rel, client):
    """파일이 아니라 **서빙된 HTML** 에서 본다 — 죽은 파일이면 여기서 걸린다."""
    r = client.get(url)
    assert r.status_code == 200, f'{url} 이 안 열린다(status={r.status_code})'
    assert _MEDIA_HEAD in r.get_data(as_text=True), \
        f'{url} 응답에 @media 블록이 없다 — 템플릿이 실제로 안 쓰이고 있다'


def test_표_처리_구조가_박혀있다():
    """화면별 표 선택 — 휴지통·이력=가로 스크롤+첫 열 붙박이, 알림=표 유지(안쪽 스크롤).
    구조 줄을 통째로 못 박는다(낱말 헛통과 방지)."""
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
