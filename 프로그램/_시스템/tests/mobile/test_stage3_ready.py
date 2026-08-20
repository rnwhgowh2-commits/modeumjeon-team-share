# -*- coding: utf-8 -*-
"""3단계 배치1·2·3 — 폰 대응 완료(MOBILE_READY) 배선과 화면들의 @media 를 못 박는다.

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

[배치3 · 2026-08-04] 화면 4개 추가 — /templates(가격 정책)·/policies(정책 생성)·
  /policies/apply(상품 정책 적용)·/accounts/upload(판매처 계정 72KB — 최대 retrofit).

[배치4a · 2026-08-04] ① 선택자 대조 파서 보강 — \b 경계 헛통과(up-main→.main) 차단
  + base.html 상속 화면은 base 마크업 합류(서빙 시 실재하므로). ② PATH_ONLY —
  쿼리가 데이터 필터일 뿐인 화면(/policies?brand=)은 경로 일치로 띠 생략(opt-in).
  ③ 화면 3개 — /market-send·/automation(89KB)·/bulk/(탭 9개 = partial 열거).

[배치4b · 2026-08-04 — retrofit 마지막 배치] ① 화면 5벌 — /bundles(60KB)·
  /optgen 탭 3개(index+market 탭 partial)·/inventory/(57KB — 인라인 style 판이라
  id 훅 6개 + !important)·/sourcing-guide/(59KB — 「2배 확대」 화면)·
  /automation/weights(27KB — 4a 이월). ② PATH_ONLY 확장 — /bundles·/inventory/·
  /sourcing-guide/ (전부 쿼리=데이터 필터·같은 템플릿. 🔴 /optgen 은 market 탭이
  _market_pane 조각을 그려 자격이 없다 — 탭 열거 유지). ③ 4a 검토 Minor 반영 —
  PATH_ONLY 기계 문지기(template_rendered 로 「같은 템플릿」 주장 자체를 검사) +
  파서의 base.html Jinja 잔여물({{…}}) 제거(.default 유령 토큰 차단).
"""
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
    # 화면 자체는 셋 다 폰에서 잘 보이게 해 뒀다 — 주소로 열면 그대로 쓴다.
    assert {'/alerts', '/trash', '/audit'} <= MOBILE_READY_URLS
    # 메뉴 배지 줄도 고정 목록으로 못 박는다 — 아래 배지 시험(④)은 집합을 그대로
    # 돌기 때문에, 집합에서 줄이 빠지면 검사도 같이 빠져 조용히 약해진다.
    #   🔴 [2026-08-12 사장님 확정 ㉠] '/trash' 는 뺐다 — PC 메뉴에서 없앴기 때문이다.
    #     배지는 「메뉴 줄이 있는 화면」에만 붙는다. 메뉴에서 없앤 주소를 여기 남기면
    #     「PC 메뉴에 없는 주소」라 짝 시험이 막는다.
    assert {'/alerts'} <= MOBILE_READY_MENU_URLS
    assert '/trash' not in MOBILE_READY_MENU_URLS,         '메뉴에서 없앤 주소가 배지 목록에 남아 있다'


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


def test_배치3_주소가_READY에_있다():
    """배치3 네 화면 — 전부 PC 메뉴에 자기 줄이 있어 배지 집합에도 같이 넣는다.
    ★ /policies 는 ?brand= 로 걸러지는데 값이 임의라 탭처럼 열거할 수 없다 —
      걸러진 주소(/policies?brand=X)에서는 노란 띠가 다시 뜬다(껍데기 설계 한계, 기록)."""
    from webapp.routes.mobile_shell import MOBILE_READY_MENU_URLS, MOBILE_READY_URLS
    batch3 = {'/templates', '/policies', '/policies/apply', '/accounts/upload'}
    assert batch3 <= MOBILE_READY_URLS
    assert batch3 <= MOBILE_READY_MENU_URLS


def test_배치4a_주소가_READY에_있다():
    """배치4a 세 화면 — /bulk/ 는 탭 9개가 물음표 뒤로 갈린다(카탈로그와 같은 이유로
    탭 주소를 열거). 메뉴 줄이 있는 셋은 배지 집합에도 같이 넣는다."""
    from webapp.routes.mobile_shell import MOBILE_READY_MENU_URLS, MOBILE_READY_URLS
    assert {'/market-send', '/automation', '/bulk/'} <= MOBILE_READY_URLS
    assert {'/market-send', '/automation', '/bulk/'} <= MOBILE_READY_MENU_URLS


def test_배치4b_주소가_READY에_있다():
    """배치4b 다섯 화면 — retrofit 마지막 배치. /optgen 은 탭 3개가 물음표 뒤로
    갈린다(원천 optgen.SUBTABS — 아래 열거 시험이 대조). 메뉴 줄이 있는 여섯 주소만
    배지 집합에 넣는다(★/automation/weights 는 /audit 처럼 메뉴 줄 없는 하위 화면·
    맨몸 /optgen 도 메뉴 줄이 없다 — 배지 시험이 사이드바와 대조하다 막는다)."""
    from webapp.routes.mobile_shell import (MOBILE_READY_MENU_URLS,
                                            MOBILE_READY_PATH_ONLY,
                                            MOBILE_READY_URLS)
    b4b = {'/bundles', '/optgen', '/optgen?tab=direct', '/optgen?tab=market',
           '/optgen?tab=product', '/inventory/', '/sourcing-guide/',
           '/automation/weights'}
    assert b4b <= MOBILE_READY_URLS, f'READY 에 없다: {b4b - MOBILE_READY_URLS}'
    assert {'/bundles', '/optgen?tab=direct', '/optgen?tab=market',
            '/optgen?tab=product', '/inventory/',
            '/sourcing-guide/'} <= MOBILE_READY_MENU_URLS
    assert '/automation/weights' not in MOBILE_READY_MENU_URLS, \
        '메뉴 줄이 없는 하위 화면에 배지를 붙였다'
    assert '/optgen' not in MOBILE_READY_MENU_URLS, '맨몸 /optgen 은 메뉴 줄이 없다'
    # 쿼리가 데이터 필터일 뿐인 세 화면 — PATH_ONLY(경로 일치 opt-in).
    # /bundles?status=·brand=·q= / /inventory/?sku=·q= / /sourcing-guide/?guide=1
    # 전부 같은 템플릿 하나를 그린다(아래 기계 문지기가 이 주장 자체를 검사한다).
    assert {'/bundles', '/inventory/',
            '/sourcing-guide/'} <= MOBILE_READY_PATH_ONLY
    # 🔴 /optgen 은 market 탭이 _market_pane.html 조각을 그린다 — PATH_ONLY 금지
    assert '/optgen' not in MOBILE_READY_PATH_ONLY, \
        '/optgen 이 PATH_ONLY 로 새고 있다 — 탭마다 그리는 조각이 다르다'


def test_optgen_탭이_전부_READY에_열거됐다():
    """스펙도 썩는다 — 탭 목록의 원천(optgen.SUBTABS)과 대조한다(bulk 와 같은 이유)."""
    from webapp.routes.mobile_shell import MOBILE_READY_URLS
    from webapp.routes.optgen import SUBTABS
    assert SUBTABS, 'optgen 탭 원천이 비었다 — 이 시험이 헛돈다'
    for t in SUBTABS:
        assert f"/optgen?tab={t['key']}" in MOBILE_READY_URLS, \
            f"/optgen?tab={t['key']} 이 READY 에 없다 — 그 탭에서만 노란 띠가 되살아난다"


def test_bulk_탭이_전부_READY에_열거됐다():
    """스펙도 썩는다 — 탭 목록의 원천(bulk.SUBTABS)과 대조한다. 탭이 늘었는데
    READY 에 안 적으면 그 탭에서만 노란 띠가 되살아난다(카탈로그 탭의 그 함정)."""
    from webapp.routes.bulk import SUBTABS
    from webapp.routes.mobile_shell import MOBILE_READY_URLS
    assert SUBTABS, 'bulk 탭 원천이 비었다 — 이 시험이 헛돈다'
    for t in SUBTABS:
        assert f"/bulk/?tab={t['key']}" in MOBILE_READY_URLS, \
            f"/bulk/?tab={t['key']} 이 READY 에 없다 — 그 탭에서만 노란 띠가 되살아난다"


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
# ①-b PATH_ONLY — 쿼리가 「데이터 거르기」일 뿐인 화면 (배치4a)
#     /policies?brand=X 는 값이 임의라 열거가 불가능한데 같은 index.html 을
#     그린다 — 경로만 맞으면 띠를 생략한다(opt-in 부분집합).
# ─────────────────────────────────────────────────────────────

def _would_skip_notice(url: str) -> bool:
    """JS isReadyScreen 과 같은 판정을 서버 원천으로 재현 —
    (정확 일치) OR (PATH_ONLY 경로 일치, 쿼리 무시)."""
    from webapp.routes.mobile_shell import (MOBILE_READY_PATH_ONLY_ROUTES,
                                            MOBILE_READY_SCREENS, same_route,
                                            same_screen)
    return (same_screen(url) in MOBILE_READY_SCREENS
            or same_route(url) in MOBILE_READY_PATH_ONLY_ROUTES)


def test_PATH_ONLY는_READY의_부분집합이고_policies가_들어있다():
    """READY 에 없는 주소를 PATH_ONLY 에만 넣으면 「@media 없는 화면의 띠 생략」
    이라는 거짓 표시가 된다 — 부분집합을 못 박는다."""
    from webapp.routes.mobile_shell import (MOBILE_READY_PATH_ONLY,
                                            MOBILE_READY_URLS)
    assert '/policies' in MOBILE_READY_PATH_ONLY
    assert MOBILE_READY_PATH_ONLY <= MOBILE_READY_URLS, \
        f'READY 에 없는 PATH_ONLY: {MOBILE_READY_PATH_ONLY - MOBILE_READY_URLS}'


def test_policies_임의_brand_주소도_띠를_생략한다():
    """배치3의 「?brand= 는 열거 불가 → 띠가 되살아난다」 한계의 해소."""
    assert _would_skip_notice('/policies?brand=아무값')
    assert _would_skip_notice('/policies?brand=아무거나&q=1')


def test_배치4b_임의_쿼리_주소도_띠를_생략한다():
    """[배치4b] /bundles·/inventory/·/sourcing-guide/ 도 policies 와 같은 부류 —
    걸러진 주소(brand=·sku=…)는 값이 임의라 열거 불가, 같은 템플릿을 그린다.
    ★ /inventory/?sku= 는 목록에서 행을 누르기만 해도 붙는 주소다 — PATH_ONLY 가
      없으면 행을 누르는 순간 노란 띠가 되살아난다."""
    assert _would_skip_notice('/bundles?status=draft&brand=아무값&q=1')
    assert _would_skip_notice('/inventory/?sku=아무SKU&in_stock=1')
    assert _would_skip_notice('/sourcing-guide/?guide=1')
    # /optgen 은 탭 열거 방식 — 열거 안 한 탭이 통과하면 PATH_ONLY 가 새는 것
    assert not _would_skip_notice('/optgen?tab=없는탭'), \
        '/optgen 열거 안 한 탭이 통과한다 — PATH_ONLY 가 전역으로 새고 있다'
    assert _would_skip_notice('/optgen?tab=market'), '열거된 탭이 오히려 막혔다'


def _rendered_templates(flask_app, client, url):
    """이 주소가 그리는 최상위 템플릿 이름들 — Flask template_rendered 신호로 잡는다.
    ({% include %}·{% extends %} 는 별도 신호가 없다 — 「어느 라우트 분기가 어느
    render_template 을 탔나」 수준의 문지기다. /optgen 처럼 같은 템플릿 안에서
    조각({% include %})이 갈리는 화면까지는 못 본다 — 그건 위 열거 시험들의 몫.)"""
    from flask import template_rendered
    names: list[str] = []

    def _rec(sender, template, context, **extra):
        names.append(template.name)

    template_rendered.connect(_rec, flask_app)
    try:
        r = client.get(url)
        assert r.status_code == 200, f'{url} 이 안 열린다(status={r.status_code})'
    finally:
        template_rendered.disconnect(_rec, flask_app)
    return names


def test_PATH_ONLY_주소는_엉뚱한_쿼리에도_같은_템플릿을_그린다(client, flask_app):
    """[배치4b·4a 검토 Minor] PATH_ONLY 의 기계 문지기 — 앞으로 늘어나는 항목도
    자동으로 지킨다. 경로 일치로 띠를 생략한다는 건 「쿼리는 데이터 필터일 뿐,
    같은 템플릿」이라는 주장이다 — 엉뚱한 쿼리(?zzz=1)를 붙여도 같은 템플릿이
    그려져야 그 주장이 참이다(라우트가 쿼리로 템플릿을 갈면 여기서 빨갛게 된다)."""
    from webapp.routes.mobile_shell import MOBILE_READY_PATH_ONLY
    assert MOBILE_READY_PATH_ONLY, 'PATH_ONLY 가 비었다 — 이 시험이 헛돈다'
    for url in sorted(MOBILE_READY_PATH_ONLY):
        plain = _rendered_templates(flask_app, client, url)
        assert plain, f'{url} 이 템플릿을 하나도 안 그렸다 — 이 대조가 헛돈다'
        noisy = _rendered_templates(
            flask_app, client, url + ('&' if '?' in url else '?') + 'zzz=1')
        assert plain == noisy, (
            f'{url} 이 쿼리에 따라 다른 템플릿을 그린다 — PATH_ONLY 자격이 없다: '
            f'{plain} vs {noisy}')


def test_PATH_ONLY가_전역이_아니다():
    """🔴 경로 일치를 전역으로 하면 /orders 처럼 탭(?tab=)마다 **다른 템플릿**을
    그리는 화면에서, 한 탭만 전환해도 네 탭 전부 띠가 사라진다 — opt-in 만 허용.
    /catalog 는 탭이 partial 로 갈리므로 열거 방식을 유지한다."""
    from webapp.routes.mobile_shell import MOBILE_READY_PATH_ONLY
    assert '/catalog/' not in MOBILE_READY_PATH_ONLY
    assert '/catalog' not in MOBILE_READY_PATH_ONLY
    assert not _would_skip_notice('/catalog/?tab=없는탭'), \
        '열거 안 한 카탈로그 탭이 통과한다 — PATH_ONLY 가 전역으로 새고 있다'
    assert _would_skip_notice('/catalog/?tab=pick'), '열거된 탭이 오히려 막혔다'
    assert not _would_skip_notice('/orders/?tab=list')


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


def test_JSON_블롭에_readyPaths가_실린다(client):
    """[배치4a] PATH_ONLY 도 같은 블록으로 내려간다 — JS 가 읽을 두 번째 칸."""
    from webapp.routes.mobile_shell import MOBILE_READY_PATH_ONLY_ROUTES
    r = client.get('/')
    assert r.status_code == 200
    blob = shell_blob_of(r.get_data(as_text=True))
    assert 'readyPaths' in blob, 'JSON 에 readyPaths 칸이 없다 — 경로 일치 판정이 죽는다'
    assert blob['readyPaths'] == sorted(MOBILE_READY_PATH_ONLY_ROUTES), \
        '화면의 readyPaths 가 서버 원천(MOBILE_READY_PATH_ONLY_ROUTES)과 다르다'
    assert blob['readyPaths'], 'readyPaths 가 빈 목록이다 — 이 시험이 헛돈다'


# ─────────────────────────────────────────────────────────────
# ③ JS — 판정 줄을 통째로 못 박는다
# ─────────────────────────────────────────────────────────────

def test_JS가_ready를_읽고_안내띠를_생략한다():
    src = _static('mobile_shell.js')
    # ready·readyPaths 를 실제로 파싱하는 줄
    assert 'ready: Array.isArray(d.ready) ? d.ready : []' in src, \
        'JSON 의 ready 칸을 안 읽는다'
    assert 'readyPaths: Array.isArray(d.readyPaths) ? d.readyPaths : []' in src, \
        'JSON 의 readyPaths 칸을 안 읽는다 — PATH_ONLY 판정이 죽는다'
    # 생략 판정이 입구(mount)에서 실제로 쓰이는 줄 — 함수만 있으면 죽은 장식이다
    assert ('if (!isReadyScreen(data.ready, data.readyPaths)) '
            'body.insertBefore(buildNotice(), body.firstChild);') in src, \
        'ready 판정이 안내 띠 부착을 실제로 거르지 않는다'
    # 판정 두 갈래를 통째로 못 박는다 — ① 정확 일치 ② PATH_ONLY 경로 일치(쿼리 무시)
    assert ('if (ready.indexOf(sameScreen(window.location.pathname, '
            'window.location.search)) !== -1) return true;') in src, \
        '지금 주소를 ready 목록과 비교하는 줄이 없다'
    assert ("return readyPaths.indexOf(sameScreen(window.location.pathname, '')) !== -1;") in src, \
        '경로만으로 readyPaths 와 비교하는 줄이 없다 — /policies?brand= 에서 띠가 되살아난다'


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
    # ── 배치3 ──
    '/templates': 'templates_page/index.html',
    '/policies': 'policy/index.html',
    '/policies/apply': 'policy/apply.html',
    '/accounts/upload': 'accounts/upload.html',
    # ── 배치4a — bulk 는 탭마다 partial 이 다르다(카탈로그와 같은 구조) ──
    '/market-send': 'market_send/index.html',
    '/automation': 'automation/index.html',
    '/bulk/': 'bulk/index.html',
    '/bulk/?tab=collect': 'bulk/partials/_collect.html',
    '/bulk/?tab=process': 'bulk/partials/_process.html',
    '/bulk/?tab=send': 'bulk/partials/_send.html',
    '/bulk/?tab=manual': 'bulk/partials/_manual.html',
    '/bulk/?tab=products': 'bulk/partials/_products.html',
    '/bulk/?tab=orders': 'bulk/partials/_shared_screen.html',
    '/bulk/?tab=cs': 'bulk/partials/_shared_screen.html',
    '/bulk/?tab=stats': 'bulk/partials/_shared_screen.html',
    '/bulk/?tab=settings': 'bulk/partials/_settings.html',
    # ── 배치4b — optgen 은 market 탭만 partial 이 다르다(direct·product = index) ──
    #   GET 주소는 빗금 포함(/optgen/…) — 라우트가 '/optgen'+'/' 라 맨몸은 308 이 난다.
    #   READY 의 열거는 메뉴 줄 그대로(/optgen?tab=…) — same_screen 이 빗금을 흡수한다.
    # [2026-08-06 컨트롤타워] /bundles 는 tower.html 로 재구현(시안 v8) — list.html 은
    #   라우팅되지 않는 옛 화면이라 여기서 빠진다(파일은 참조용으로 남아 있음).
    '/bundles': 'bundles/tower.html',
    '/optgen/': 'optgen/index.html',
    '/optgen/?tab=direct': 'optgen/index.html',
    '/optgen/?tab=market': 'optgen/_market_pane.html',
    '/optgen/?tab=product': 'optgen/index.html',
    '/inventory/': 'inventory/home.html',
    '/sourcing-guide/': 'sourcing_guide/overview.html',
    '/automation/weights': 'automation/weights.html',
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


def _strip_styles(src: str) -> str:
    out = src
    for block in _style_blocks(src):
        out = out.replace('<style>' + block + '</style>', '')
    return out


def _markup_of(src: str, url: str) -> str:
    """선택자 실재 대조의 검사 대상 — CSS 를 걷어낸 나머지 전부.

    배치1은 「<style> 앞부분」만 봤는데, 배치2 화면들은 표·줄을 **JS 가 문자열로
    조립**한다(예: _dashboard 의 <table>). 그래서 <style> 블록들만 빼고
    마크업+JS 문자열을 통째로 본다 — CSS 정의는 빠지므로 「스타일에만 있고
    아무 데도 안 쓰는 클래스」는 여전히 잡힌다.
    .py 화면은 <style> 태그가 없다 — @media 본문만 걷어낸다(남는 _CSS 의 PC 규칙엔
    class="…" 모양이 없어 대조를 오염시키지 않는다).

    [배치4a] base.html 을 물려받는 화면은 base 의 마크업도 검사 대상에 합친다 —
    서빙 시 그 화면 몸에 base 의 `.main`(내용 판) 등이 실제로 함께 그려지므로,
    @media 가 base 수준 선택자를 만지는 건 정당하다(upload 의 `.main` 이 그 예).
    ⚠️ 이 합치기가 없으면 아래 경계 강화(①)가 그 정당한 규칙을 빨갛게 만든다 —
    ①과 ②는 한 몸이다.
    """
    if url in _PY_SCREENS:
        return src.replace(_MEDIA_HEAD + _media_body(src) + '}', '')
    out = _strip_styles(src)
    # [배치4b] 따옴표 두 벌 다 본다 — sourcing_guide/overview 는 "base.html" 이다.
    #   (한 벌만 보면 그 화면은 base 합류가 조용히 빠져 base 수준 선택자가 빨갛다.)
    if "{% extends 'base.html' %}" in src or '{% extends "base.html" %}' in src:
        # [배치4b·4a 검토 Minor] base 마크업의 {{…}} 는 합류 전에 걷어낸다 —
        #   class="{{ design_body_class|default('') }}" 가 그대로 남으면
        #   .default·.design_body_class 이 유령 토큰으로 **헛통과**한다
        #   (규칙이 아무 데도 안 걸리는데 시험은 초록 — 이 시험의 존재 이유와 정반대).
        out += re.sub(r'\{\{.*?\}\}', ' ', _strip_styles(_template('base.html')),
                      flags=re.S)
    return out


@pytest.mark.parametrize('url,rel', sorted(_ALL_SCREENS.items()))
def test_화면마다_media_블록이_있다(url, rel):
    src = _src_of(url)
    assert _MEDIA_HEAD in src, f'{rel} 에 폰(≤768px) @media 블록이 없다'
    if url in _PY_SCREENS:
        # _CSS 는 PC 규칙과 한 문자열이라 「블록 밖 규칙 0」 검사가 성립하지 않는다.
        # ★ tests/design 은 routes/*.py 의 _CSS 문자열을 **안 훑는다**(배치2 검토에서
        #   확인) — PC 렌더 불변은 아래 「768 블록이 _CSS 의 마지막 조각」 시험이 지킨다:
        #   덧붙임이 블록 뒤에 새 PC 규칙을 흘리면 거기서 걸린다.
        return
    # 블록 밖 규칙 금지 — @media 를 담은 <style> 은 그 블록만 담아야 PC 렌더가 안 바뀐다
    # (스펙 §1: 덧붙임은 「@media 만 담은 새 <style> 블록」으로).
    holder = next((b for b in _style_blocks(src) if _MEDIA_HEAD in b), None)
    assert holder is not None, f'{rel}: @media 가 <style> 밖에 있다'
    outside = holder.replace(_MEDIA_HEAD + _media_body(src) + '}', '')
    assert not re.search(r'[^\s]\s*\{', re.sub(r'/\*.*?\*/', '', outside, flags=re.S)), \
        f'{rel} 의 @media <style> 에 블록 밖 규칙이 있다 — PC 렌더가 바뀐다(스펙 §1 위반)'


def test_notion_CSS는_768블록이_마지막_조각이다():
    """🔴 배치2 검토 Important#1 — tests/design 이 notion_report.py 의 _CSS 를 안 훑어
    「블록 뒤에 PC 규칙을 흘려도」 아무도 못 잡던 구멍. 768 블록이 _CSS 의 **맨 끝**
    조각임을 못 박는다(실측: 오늘 기준 뒤에 남는 글자 0)."""
    src = _src_of('/reports/notion-todo')
    css = re.search(r'_CSS = """(.*?)"""', src, re.S).group(1)
    start = css.index(_MEDIA_HEAD)
    tail = css[start + len(_MEDIA_HEAD) + len(_media_body(css)) + 1:]
    assert tail.strip() == '', \
        f'_CSS 의 768 블록 뒤에 규칙이 흘렀다(PC 렌더가 바뀔 수 있다): {tail[:80]!r}'


def test_파서가_base의_Jinja표현을_클래스로_오인하지_않는다():
    """[배치4b·4a 검토 Minor] base.html 의 {{ design_body_class|default('') }} 가
    class="…" 안에 그대로 남아 `.default` 같은 유령 선택자가 헛통과하던 구멍 —
    합류 전에 {{…}} 를 걷어내는 fix 를 못 박는다(자동화 화면 = base 합류 화면)."""
    markup = _markup_of(_src_of('/automation'), '/automation')
    for ghost in ('default', 'design_body_class'):
        token = r'(?<![\w-])' + ghost + r'(?![\w-])'
        assert not re.search(r'class=["\'][^"\']*?' + token, markup), \
            f'base 의 Jinja 잔여물이 클래스 {ghost} 로 남아 있다 — 유령 토큰 헛통과'


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
    # 🔴 [배치4a 검토 Important#1] \b 는 '-' 앞뒤를 낱말 경계로 세서 `up-main` 이
    #   `.main` 으로 헛통과했다(경계 헛통과 — 이 저장소가 네 번 당한 그 함정의 변종).
    #   앞뒤를 (?<![\w-])·(?![\w-]) 로 막아 클래스 이름 전체가 일치할 때만 통과시킨다.
    def has_class(name: str) -> bool:
        token = r'(?<![\w-])' + re.escape(name) + r'(?![\w-])'
        return bool(re.search(r'class=["\'][^"\']*?' + token, markup)
                    or re.search(r'className\s*=\s*["\'][^"\']*?' + token, markup))
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

    # ── 배치3 ──
    # 가격 정책: 사전 표 = 가로 스크롤 + 첫 열 붙박이. 감싼 .card-tight 가 인라인
    # overflow:hidden 이라 !important 없이는 스크롤이 조용히 안 먹는다.
    tpl = _media_body(_template('templates_page/index.html'))
    assert 'overflow-x: auto !important;' in tpl, \
        'templates: 사전 표 가로 스크롤이 없다(인라인 hidden 을 못 이긴다)'
    assert 'position: sticky; left: 0; z-index: 1; background: var(--surface, #fff);' in tpl, \
        'templates: 첫 열 붙박이+배경이 없다'
    # 정책 생성: 줄 목록 표 가로 스크롤 + 사이드바 위로 접힘 + 마켓 격자 2열
    #   (「가격 정책에서 옮겨오기」 대조 표는 2026-08-04 사장님 확정으로 화면에서 삭제 —
    #    옛 가격 템플릿 2개가 이미 전부 정책으로 이사 완료라 남은 대상 0.
    #    카드 격자(.pl-grid)는 2026-08-04 카드형→격자 B1 확정으로 표(.gl-wrap)가 됐다)
    pol = _media_body(_template('policy/index.html'))
    assert '.gl-wrap { overflow-x: auto; }' in pol, \
        'policies: 줄 목록 표의 가로 스크롤이 없다'
    assert '.layout { grid-template-columns: 1fr; }' in pol, \
        'policies: 사이드바가 폰에서 본문 위로 안 접힌다'
    assert '.pl-sb { position: static; }' in pol, \
        'policies: 사이드바 붙박이가 폰에서 안 풀린다 — 스크롤을 가린다'
    # [2026-08-19] 3열 max-content 격자(고치기 눌러야 펼침) → 바로 누르는 알약으로
    #   바뀌면서 격자 자체가 없어졌다. 알약은 .pl-mk 의 flex-wrap 으로 이미 접혀
    #   폰 폭을 넘지 않는다 — 여기서는 손끝 목표(32px)만 확인한다.
    assert '.v2d-pill { min-height: 32px; font-size: 13px; }' in pol, \
        'policies: 내보낼 마켓 알약이 폰에서 손끝 목표를 안 키운다'
    # 정책 매칭: 좌우 두 판이 세로 한 줄로
    ap = _media_body(_template('policy/apply.html'))
    assert '.ap-two { grid-template-columns: 1fr; }' in ap, \
        'apply: 좌우 두 판이 세로 한 줄로 안 접힌다'
    # [배치4a 검토] 체크칸 22px 은 화면 뿌리로 스코프 — 맨몸 input[type=checkbox] 이면
    # 껍데기가 나중에 갖게 될 체크박스까지 22px 을 물려받는다.
    assert '#screen-policy-apply input[type="checkbox"]' in ap, \
        'apply: 체크칸 22px 규칙이 화면 뿌리로 스코프되지 않았다'
    ap_sels = [s.strip()
               for grp in re.findall(r'([^{}]+)\{', re.sub(r'/\*.*?\*/', '', ap, flags=re.S))
               for s in grp.split(',')]
    for s in ap_sels:
        if 'input[type="checkbox"]' in s or 'input[type="radio"]' in s:
            assert s.startswith('#screen-policy-apply'), \
                f'apply: 스코프 안 된 체크칸 선택자 {s!r} — 껍데기로 샌다'
    # 판매처 계정: 사이드바 접힘 + 표 가로 스크롤 + 첫 열 붙박이 + colgroup 폭 이김
    up = _media_body(_template('accounts/upload.html'))
    assert '.up-shell { grid-template-columns: 1fr; min-height: 0; }' in up, \
        'upload: 좌측 사이드바가 위로 안 접힌다'
    assert '.up-table { display: block; overflow-x: auto; }' in up, \
        'upload: 계정 표의 가로 스크롤이 없다'
    assert '.up-table colgroup col { width: auto !important; }' in up, \
        'upload: colgroup 고정폭(인라인+JS 복원값)을 못 이긴다 — 표가 폰 폭을 넘는다'
    assert 'position: sticky; left: 0; z-index: 1; background: var(--surface, #fff);' in up, \
        'upload: 첫 열(마켓) 붙박이+배경이 없다'
    # 손끝 목표 44px — 배치3 전 화면
    for body, name in ((tpl, 'templates'), (pol, 'policies'), (ap, 'apply'), (up, 'upload')):
        assert 'min-height: 44px' in body, f'{name}: 손끝 목표 44px 규칙이 빠졌다'
    # 16px 입력칸 — upload 는 인라인 12.5~13px 을 이겨야 해서 !important 판이다
    for body, name in ((tpl, 'templates'), (pol, 'policies'), (ap, 'apply')):
        assert 'font-size: 16px;' in body, f'{name}: 입력칸 16px 규칙이 빠졌다'
    assert 'font-size: 16px !important;' in up, \
        'upload: 입력칸 16px(!important — 인라인을 이겨야 함) 규칙이 빠졌다'

    # ── 배치4a ──
    # 마켓 전송: 필터 이름표 고정폭 해제 + 목록 표 가로 스크롤 + 첫 열 붙박이
    ms = _media_body(_template('market_send/index.html'))
    assert '#msList { overflow-x: auto; }' in ms, \
        'market-send: 목록 표의 가로 스크롤 컨테이너가 없다'
    assert 'table.lst { min-width: 720px;' in ms, \
        'market-send: 표 최소폭이 없다 — 5열이 375px 에 짓눌린다'
    assert 'position: sticky; left: 0; z-index: 1;' in ms, \
        'market-send: 첫 열(소싱처) 붙박이가 없다'
    assert 'background: var(--surface, #fff);' in ms, \
        'market-send: 붙박이 열에 밑칠이 없다 — 밀린 칸 글자가 비쳐 보인다'
    # 2026-08-19 조건검색 3분류 개편 — 옛 .flb(단일줄 이름표) 대신 .g3-row 가
    # 폰에서 세로 라벨+줄 구조를 1단으로 접는다(같은 목적: 고정폭이 폰을 안 짓누름).
    assert '.g3-row { grid-template-columns: 1fr; }' in ms, \
        'market-send: 조건검색 이름표 칸(104px 고정)이 폰에서 안 풀린다'
    # 자동화: zoom 해제 + 두 카드 세로 접힘 + 표 4벌 스크롤 + 보고서 팝업 폭
    au = _media_body(_template('automation/index.html'))
    assert '.au-wrap { zoom: 1; }' in au, \
        'automation: PC 확대(zoom:1.3)가 폰에서 안 풀린다 — 375px 이 288px 처럼 좁아진다'
    assert '.au-pair { grid-template-columns: 1fr; }' in au, \
        'automation: 소싱처·판매처 두 카드가 세로 한 줄로 안 접힌다'
    assert '.locks { grid-template-columns: 1fr; }' in au, \
        'automation: 두 겹 잠금 상자가 세로로 안 접힌다'
    assert ('table.km, table.spd-t, table.pv-t, table.rpt-t {\n'
            '    display: block; overflow-x: auto;') in au, \
        'automation: 표 4벌의 가로 스크롤이 없다'
    assert '.lrbox { zoom: 1; width: calc(100vw - 16px);' in au, \
        'automation: 회차 보고서 팝업(PC zoom:1.4·1200px)이 폰 폭으로 안 줄어든다'
    # 대량등록 껍데기: .app 세로 전환(본문) — 사이드바 접힘은 아래 사이드바 시험이 본다
    bk = _media_body(_template('bulk/index.html'))
    assert '.app { flex-direction: column; }' in bk, \
        'bulk: 사이드바+본문 가로 배치가 세로로 안 접힌다'
    # 탭별 partial — 표 화면 3곳(가공·상품·설정)은 가로 스크롤 + 첫 열 붙박이
    for rel, wrap in (('bulk/partials/_process.html', '.pp-tbl'),
                      ('bulk/partials/_products.html', '.pr-tbl'),
                      ('bulk/partials/_settings.html', '.st-tbl')):
        b = _media_body(_template(rel))
        assert f'{wrap} {{ overflow-x: auto; }}' in b, f'{rel}: 표 가로 스크롤이 없다'
        assert 'position: sticky; left: 0; z-index: 1;' in b, f'{rel}: 첫 열 붙박이가 없다'
        assert 'background: var(--surface, #fff);' in b, f'{rel}: 붙박이 밑칠이 없다'
    man = _media_body(_template('bulk/partials/_manual.html'))
    assert '#bd-opt-table, #bd-list { display: block; overflow-x: auto;' in man, \
        'manual: 옵션·저장상품 표의 가로 스크롤이 없다'
    col = _media_body(_template('bulk/partials/_collect.html'))
    assert '.col-wrap { grid-template-columns: 1fr; }' in col, \
        'collect: 좌(목록)+우(상세) 두 판이 세로로 안 접힌다'
    sd4 = _media_body(_template('bulk/partials/_send.html'))
    assert '.sd-gate { grid-template-columns: 1fr; }' in sd4 \
        and '.sd-mkts { grid-template-columns: 1fr; }' in sd4, \
        'send: 게이트 2단·마켓 4단 격자가 세로로 안 접힌다'
    ss = _media_body(_template('bulk/partials/_shared_screen.html'))
    assert '.ss-go { min-height: 44px;' in ss, 'shared: 이동 단추가 44px 이 안 된다'
    # 손끝 44px — 배치4a 전 화면(부품 하나 이상)
    for body, name in ((ms, 'market-send'), (au, 'automation'), (man, 'manual'),
                       (col, 'collect'), (sd4, 'send'), (ss, 'shared')):
        assert 'min-height: 44px' in body, f'{name}: 손끝 목표 44px 규칙이 빠졌다'
    # 16px 입력칸 — 입력칸이 있는 화면
    for body, name in ((ms, 'market-send'), (au, 'automation'), (man, 'manual')):
        assert 'font-size: 16px;' in body, f'{name}: 입력칸 16px 규칙이 빠졌다'


def test_배치4b_표_처리_구조가_박혀있다():
    """화면별 표 선택(스펙 §1) — 구조 줄을 통째로 못 박는다(낱말 헛통과 방지).

    배치4b: 모음전(12열)·옵션 묶음·마켓 찾기·소싱처(7열)·랩 보고서 = 가로 스크롤 +
    붙박이 열 + 밑칠 / 재고관리·소싱처 가이드는 인라인 style 판이라 !important 로만
    이긴다(배치3 upload 의 결정) / 계수 밀러 컬럼(5열)은 세로 1열로 쌓는다.
    """
    # 모음전: 첫 열은 체크칸이라 **이름 열**(2번째)을 붙박는다 + 브랜드 nav 가로 줄
    bl = _media_body(_template('bundles/list.html'))
    assert '.bl-table { min-width: 860px; }' in bl, \
        'bundles: 표 최소폭이 없다 — 12열이 375px 에 짓눌린다'
    # 앵커 = data-sort-key(열의 신원) — nth-child(순서)면 열 추가 때 조용히 어긋난다
    assert ('.bl-table th[data-sort-key="name"], .bl-table td.bl-c-name {\n'
            '    position: sticky; left: 0; z-index: 1;') in bl, \
        'bundles: 이름 열 붙박이가 없다(앵커는 data-sort-key — 순서 아님)'
    assert 'background: var(--surface, #fff);' in bl, \
        'bundles: 붙박이 밑칠이 없다 — 밀린 칸 글자가 비쳐 보인다'
    assert '.brand-nav { position: static; display: flex;' in bl, \
        'bundles: 브랜드 nav 가 위쪽 가로 스크롤 줄로 안 접힌다(sticky 가 스크롤을 가린다)'
    assert 'mask-image: linear-gradient(to right, #000 calc(100% - 28px), transparent);' in bl, \
        'bundles: 브랜드 줄 오른쪽 끝 흐림 힌트(더 있음)가 없다'
    # 옵션생성: 탭 줄 가로 스크롤 + 흐림 힌트 + 묶음 표 붙박이
    og = _media_body(_template('optgen/index.html'))
    assert '.og-tb { display: block; overflow-x: auto; white-space: nowrap; }' in og, \
        'optgen: 옵션 묶음 표의 가로 스크롤이 없다'
    assert 'position: sticky; left: 0; z-index: 1;' in og, 'optgen: 첫 열 붙박이가 없다'
    assert 'mask-image: linear-gradient(to right, #000 calc(100% - 28px), transparent);' in og, \
        'optgen: 탭 줄 오른쪽 끝 흐림 힌트가 없다'
    im = _media_body(_template('optgen/_market_pane.html'))
    assert '.im-tb { display: block; overflow-x: auto; white-space: nowrap; min-width: 0; }' in im, \
        'market_pane: 찾은 상품 표(7열)의 가로 스크롤이 없다'
    assert 'position: sticky; left: 0; z-index: 1;' in im, 'market_pane: 첫 열 붙박이가 없다'
    assert '.im-bigrow { flex-wrap: wrap; }' in im, \
        'market_pane: 큰 찾기 줄이 폰 폭에서 안 접힌다'
    # 재고관리: 전부 인라인 style — id 훅 + !important 로만 이긴다
    iv = _media_body(_template('inventory/home.html'))
    assert '#iv-split { grid-template-columns: 1fr !important; }' in iv, \
        'inventory: 좌(목록)+우(상세) 두 판이 세로 한 줄로 안 접힌다'
    assert '#iv-detail { position: static !important; }' in iv, \
        'inventory: 상세 판 sticky 가 폰에서 안 풀린다 — 스크롤을 가린다'
    assert '#iv-stats { grid-template-columns: 1fr !important; }' in iv, \
        'inventory: 통계 3장이 세로로 안 접힌다'
    assert '#iv-actions { grid-template-columns: 1fr 1fr !important; }' in iv, \
        'inventory: 입고·출고·조정·이동 4칸이 2×2 로 안 접힌다'
    # 소싱처 가이드: 감싼 카드의 인라인 overflow:hidden 이 스크롤을 조용히 죽인다
    sg = _media_body(_template('sourcing_guide/overview.html'))
    assert '.sg-ov { padding: 12px 10px !important; }' in sg, \
        'sourcing: 인라인 48px 패딩이 폰에서 안 줄어든다'
    assert '.sg-ov .sg-card { overflow-x: auto !important; }' in sg, \
        'sourcing: 소싱처 표의 가로 스크롤이 없다(인라인 hidden 을 못 이긴다)'
    assert '.sg-ov table.sg-atbl { min-width: 760px; }' in sg, \
        'sourcing: 표 최소폭이 없다 — 7열이 375px 에 짓눌린다'
    assert 'position: sticky; left: 0; z-index: 1;' in sg, 'sourcing: 첫 열 붙박이가 없다'
    # 계수: 밀러 컬럼 세로 1열(#cw-finder = id 라 .c5/.c4/.c3 를 이긴다) + 랩 표 붙박이
    cw = _media_body(_template('automation/weights.html'))
    assert '#cw-finder { grid-template-columns: 1fr; max-width: none; }' in cw, \
        'weights: 5열 밀러 컬럼이 세로 1열로 안 쌓인다'
    assert '.cw-step button { width: 44px; height: 44px; }' in cw, \
        'weights: 계수 ±단추가 44px 이 안 된다'
    assert ('.lr th:first-child, .lr td:first-child {\n'
            '    position: sticky; left: 0; z-index: 1;') in cw, \
        'weights: 랩 보고서 첫 열(소싱처) 붙박이가 없다'
    # 손끝 44px — 배치4b 전 화면
    for body, name in ((bl, 'bundles'), (og, 'optgen'), (im, 'market_pane'),
                       (iv, 'inventory'), (sg, 'sourcing'), (cw, 'weights')):
        assert 'min-height: 44px' in body, f'{name}: 손끝 목표 44px 규칙이 빠졌다'
    # 붙박이 밑칠 — 붙박이 열이 있는 화면 전부. inventory 는 카드 줄(가로 표 없음)이라
    # 붙박이 자체가 없다 — 제외(밑칠 규칙을 넣으면 죽은 장식이 된다).
    for body, name in ((bl, 'bundles'), (og, 'optgen'), (im, 'market_pane'),
                       (sg, 'sourcing'), (cw, 'weights')):
        assert 'background: var(--surface, #fff);' in body, f'{name}: 붙박이 밑칠이 없다'
    # 16px 입력칸(iOS 확대 방지) — 입력칸 있는 화면. sourcing 은 입력칸이 없다
    # (이름·로고는 prompt 대화상자) — 제외. inventory 는 인라인 14px 을 이겨야 해서 !important.
    for body, name in ((bl, 'bundles'), (og, 'optgen'), (im, 'market_pane'),
                       (cw, 'weights')):
        assert 'font-size: 16px;' in body, f'{name}: 입력칸 16px 규칙이 빠졌다'
    assert 'font-size: 16px !important;' in iv, \
        'inventory: 입력칸 16px(!important — 인라인을 이겨야 함) 규칙이 빠졌다'


def test_bulk_사이드바가_위로_접히고_실제로_실린다(client):
    """bulk 만 base.html 이 왼쪽 사이드바(sidebar_bulk.html)를 끼운다 — 이 파일은
    _SCREENS(화면=탭 partial) 대조 밖이라 여기서 따로 못 박는다: ① @media 가 있고
    ② 접힘 규칙이 있고 ③ 서빙된 HTML 에 실리고 ④ 블록 밖 규칙이 없다(PC 불변)."""
    side = _template('bulk/partials/sidebar_bulk.html')
    assert _MEDIA_HEAD in side, 'sidebar_bulk 에 폰 @media 블록이 없다'
    body = _media_body(side)
    assert '.sidebar { position: static; width: auto;' in body, \
        'sidebar_bulk: 240px 붙박이 사이드바가 위쪽 줄로 안 접힌다'
    assert '.sidebar .nav { display: flex; overflow-x: auto;' in body, \
        'sidebar_bulk: 탭 줄이 가로 스크롤이 아니다'
    # [배치4b·4a 검토 Minor] 오른쪽 끝 흐림 — 탭이 더 있음을 알리는 CSS 힌트(JS 0줄)
    assert 'mask-image: linear-gradient(to right, #000 calc(100% - 28px), transparent);' in body, \
        'sidebar_bulk: 탭 줄 오른쪽 끝 흐림 힌트(더 있음)가 없다'
    assert 'min-height: 44px' in body, 'sidebar_bulk: 손끝 목표 44px 이 없다'
    r = client.get('/bulk/')
    assert r.status_code == 200
    assert body in r.get_data(as_text=True), \
        '/bulk/ 응답에 sidebar_bulk 의 @media 본문이 없다'
    holder = next((b for b in _style_blocks(side) if _MEDIA_HEAD in b), None)
    assert holder is not None, 'sidebar_bulk: @media 가 <style> 밖에 있다'
    outside = holder.replace(_MEDIA_HEAD + body + '}', '')
    assert not re.search(r'[^\s]\s*\{', re.sub(r'/\*.*?\*/', '', outside, flags=re.S)), \
        'sidebar_bulk 의 @media <style> 에 블록 밖 규칙이 있다 — PC 렌더가 바뀐다'
