# -*- coding: utf-8 -*-
"""F-2 크롤 가이드 폰 화면(/mobile/guide) — 목차(검색+줄) → 절 읽기.

사장님 확정(2026-08-04, 「모음전 폰 화면 일괄 시안 v1.html」 fF2): 검색칸 +
번호 줄(제목+한 줄 요약+›) → 누르면 그 절을 폰 글자 크기로 읽는다. **시안=코드**
(목차 화면의 search·row·rl·rp·rm·rr 부품 구조 그대로).

무엇을 지키나
    ① 화면 200 + 시안 구조(search·번호 줄·›) + 메뉴 등록(admin — PC 게이트와 동일).
    ② 🔴 목차는 정본 md 의 `## ` 헤딩에서 **렌더 시점에** 나온다 — 시험이 md 를
       독자적으로 파싱해 절 키·제목을 화면과 대조한다(목록 하드코딩이면 빨강).
    ③ 🔴 내용 복제 금지 — 본문은 파일에서 실시간으로 온다. 정본 경로를 임시
       파일로 갈아끼우면 화면이 **그 즉시** 새 내용을 그려야 한다(캐시·사본이면
       빨강). 템플릿에는 가이드 본문 글자가 한 줄도 없어야 한다.
    ④ 읽기 규칙 실재 — 본문 ≥14px · 코드 블록/표는 자기 그릇 안에서 가로
       스크롤(overflow-x:auto) · 목차 줄 44px. 렌더러가 코드 펜스·표를 실제로
       그 그릇에 넣는지 임시 md 로 기능 검증(HTML 이스케이프 포함).
    ⑤ 검색 = 목차(제목·요약) 클라이언트 필터 — 서버 호출 0(fetch 없음).
       줄마다 data-text 가 실려 있고 그 안에 제목이 들어 있다.
    ⑥ 폴링 없음 · ISO Date 파싱 없음.

★ '낱말이 어딘가 있나'로 검사하지 않는다 — CSS 는 규칙 본문을, 목차는 (키,
  제목) 짝을, 렌더러는 임시 md 실렌더 결과를 본다(형제 화면 헛통과 함정).
"""
import re
from pathlib import Path

import pytest

# flask_app 픽스처는 tests/mobile/conftest.py 에 있다.

_TPL_DIR = Path(__file__).resolve().parents[2] / 'webapp' / 'templates' / 'mobile'
_TOC_TPL = _TPL_DIR / 'guide_toc.html'
_SEC_TPL = _TPL_DIR / 'guide_section.html'

ADMIN_EMAIL = 'guide-admin@test.local'
MEMBER_EMAIL = 'guide-member@test.local'


def _toc_src() -> str:
    assert _TOC_TPL.exists(), f'템플릿이 없다: {_TOC_TPL}'
    return _TOC_TPL.read_text(encoding='utf-8')


def _sec_src() -> str:
    assert _SEC_TPL.exists(), f'템플릿이 없다: {_SEC_TPL}'
    return _SEC_TPL.read_text(encoding='utf-8')


def _real_md_text() -> str:
    """정본 md — 경로의 단일 원천은 sourcing_guide._GUIDE_MD 하나다."""
    from webapp.routes.sourcing_guide import _GUIDE_MD
    return Path(_GUIDE_MD).read_text(encoding='utf-8')


@pytest.fixture
def users(flask_app):
    """admin·member 하나씩 — 이 화면은 PC 가이드와 같은 admin 게이트 뒤다.

    DISABLE_AUTH=1 은 '첫 admin'으로 자동 로그인한다(test_crawl_remote_api 관례).
    사용자를 만드는 픽스처라 진짜 DB 면 안 돈다.
    """
    from tests.mobile.conftest import require_sqlite
    require_sqlite()

    from shared.db import SessionLocal
    from webapp.auth.models import User
    s = SessionLocal()
    try:
        out = {}
        for email, role in ((ADMIN_EMAIL, 'admin'), (MEMBER_EMAIL, 'member')):
            u = s.query(User).filter(User.email == email).first()
            if u is None:
                u = User(email=email, name=role, password_hash='x',
                         role=role, is_active=True)
                s.add(u)
                s.flush()
            u.is_active = True
            out[role] = u.id
        s.commit()
        return out
    finally:
        s.close()


@pytest.fixture
def client(flask_app, users):
    """admin 으로 로그인된 클라이언트 (DISABLE_AUTH 가 첫 admin 을 집는다)."""
    return flask_app.test_client()


def _fake_md(monkeypatch, tmp_path, text: str) -> None:
    """정본 경로를 임시 md 로 갈아끼운다 — 실파일은 건드리지 않는다.

    경로 원천은 sourcing_guide._GUIDE_MD 하나(폰 라우트가 그걸 렌더 시점에
    읽어 간다) — 여기를 갈아끼웠는데 화면이 안 바뀌면 어딘가 사본이 있다는 뜻.
    """
    p = tmp_path / 'guide.md'
    p.write_text(text, encoding='utf-8')
    import webapp.routes.sourcing_guide as sg
    monkeypatch.setattr(sg, '_GUIDE_MD', str(p))


# ════════════════════════════════════════════════════════════
#  ① 화면 · 시안 구조 · 메뉴
# ════════════════════════════════════════════════════════════

def test_목차_화면이_뜨고_시안_구조가_있다(client):
    r = client.get('/mobile/guide')
    assert r.status_code == 200, f'크롤 가이드 목차가 안 열린다(status={r.status_code})'
    html = r.get_data(as_text=True)
    # fF2 구조 — 검색칸 + 번호 줄(제목+요약+›).
    assert re.search(r'class="search"', html), '검색칸(.search)이 없다'
    rows = re.findall(r'href="/mobile/guide/s/([^"]+)"[^>]*data-text=', html)
    assert len(rows) >= 5, f'목차 줄이 {len(rows)}개뿐이다 — md 헤딩 수만큼 있어야 한다'
    nums = re.findall(r'class="rp">(\d+)\.', html)
    assert nums, '번호 줄(N. 제목)이 없다 — 시안 fF2 구조가 아니다'
    assert '›' in html, '오른쪽 화살표(›)가 없다'
    # 시안 부품 CSS 가 규칙 본문으로 실재한다(낱말 아님).
    src = _toc_src()
    for cls, needle in (('.search', 'border'), ('.row', 'display'),
                        ('.rp', 'font-size'), ('.rm', 'color')):
        m = re.search(re.escape(cls) + r'[^{]*\{([^}]*)\}', src)
        assert m, f'시안 부품 {cls} 규칙이 없다'
        assert needle in m.group(1), f'{cls} 규칙에 {needle} 이 없다'


def test_메뉴_목록에_실렸고_게이트와_묶였다(flask_app):
    """admin_only 표시는 실게이트(blueprint before_request)의 사본이다 — 묶어 본다."""
    from types import SimpleNamespace

    import flask_login

    from webapp.routes import mobile_guide
    from webapp.routes.mobile_shell import PHONE_NATIVE_ROWS
    rows = [it for it in PHONE_NATIVE_ROWS if it['url'] == '/mobile/guide']
    assert rows, '/mobile/guide 가 PHONE_NATIVE_ROWS 에 없다 — 메뉴에서 못 들어간다'
    assert rows[0]['name'] == '크롤 가이드'
    # PC 원천(/sourcing-guide/*)이 team-share-dev 에서 admin 게이트다
    # (sourcing_guide._admin_only) — 폰만 열면 두 화면이 다른 답을 낸다.
    assert rows[0].get('admin_only') is True, \
        'PC 가이드는 admin 전용인데 폰 줄이 안 잠겨 있다'
    gates = flask_app.before_request_funcs.get(mobile_guide.bp.name) or []
    assert gates, '폰 가이드에 blueprint 게이트가 없다 — 메뉴 표시만 잠겨 있다'
    orig = flask_login.current_user
    try:
        flask_login.current_user = SimpleNamespace(is_authenticated=True,
                                                   is_admin=False)
        with flask_app.test_request_context('/mobile/guide'):
            blocked = [g for g in gates if g() is not None]
    finally:
        flask_login.current_user = orig
    assert blocked, 'member 인데 폰 가이드 게이트가 통과시킨다 — 표시와 게이트가 어긋났다'


# ════════════════════════════════════════════════════════════
#  ② 목차 = md 헤딩 (렌더 시점 유도)
# ════════════════════════════════════════════════════════════

def test_목차는_정본_md_헤딩에서_나온다(client):
    """시험이 md 를 **독자적으로** 파싱해 화면과 대조한다 — 목록 하드코딩이면 빨강."""
    md = _real_md_text()
    heads = re.findall(r'^## +(.+?)\s*$', md, re.M)
    assert len(heads) >= 5, 'md 의 ## 헤딩을 못 찾았다 — 이 시험이 헛돈다'
    want_keys = set()
    for h in heads:
        m = re.search(r'§\s*([0-9][0-9a-zA-Z\-]*)', h)
        assert m, f'## 헤딩에 § 키가 없다(파서 가정 붕괴): {h!r}'
        want_keys.add(m.group(1))

    html = client.get('/mobile/guide').get_data(as_text=True)
    have_keys = set(re.findall(r'href="/mobile/guide/s/([^"]+)"', html))
    # 머리말(intro)은 # 제목에서 온 추가 줄 — ## 키 집합과는 별도로 허용.
    assert have_keys - {'intro'} == want_keys, \
        f'목차 키가 md 헤딩과 다르다: 화면에만 {sorted((have_keys - {"intro"}) - want_keys)}, ' \
        f'md 에만 {sorted(want_keys - have_keys)}'
    # 제목 글자도 md 에서 온다 — § 접두를 뗀 제목이 줄에 있어야 한다.
    #   (Jinja 자동 이스케이프와 같은 모양으로 대조 — `>`·`"` 가 든 제목이 실재한다)
    from markupsafe import escape
    for h in heads:
        title = re.sub(r'^§\s*[0-9][0-9a-zA-Z\-]*\.?\s*', '', h).strip()
        assert str(escape(title)) in html, f'md 헤딩 제목이 목차에 없다: {title!r}'


def test_없는_절은_404(client):
    assert client.get('/mobile/guide/s/no-such-key').status_code == 404


# ════════════════════════════════════════════════════════════
#  ③ 내용 복제 금지 — 파일에서 실시간
# ════════════════════════════════════════════════════════════

def test_내용은_파일에서_실시간으로_온다(client, monkeypatch, tmp_path):
    """정본 경로를 갈아끼우면 화면이 **그 즉시** 바뀐다 — 사본·캐시면 빨강."""
    _fake_md(monkeypatch, tmp_path, (
        '# 시험 정본\n머리말 표식 MARKER-INTRO-77\n\n'
        '## §77. 시험 절\n본문 표식 MARKER-BODY-77\n'
    ))
    toc = client.get('/mobile/guide').get_data(as_text=True)
    assert '시험 절' in toc, '갈아끼운 md 의 헤딩이 목차에 안 뜬다 — 어딘가 사본이 있다'
    assert '/mobile/guide/s/77' in toc
    sec = client.get('/mobile/guide/s/77').get_data(as_text=True)
    assert 'MARKER-BODY-77' in sec, '갈아끼운 md 의 본문이 안 뜬다 — 렌더 시점 읽기가 아니다'
    intro = client.get('/mobile/guide/s/intro').get_data(as_text=True)
    assert 'MARKER-INTRO-77' in intro, '머리말이 파일에서 오지 않는다'


def test_정본에_실재하는_글자가_화면에_뜬다(client):
    """진짜 md 기준 한 번 더 — 첫 ## 절의 첫 문단 표식이 절 화면에 있다."""
    md = _real_md_text()
    m = re.search(r'^## +(.+?)\s*$', md, re.M)
    key = re.search(r'§\s*([0-9][0-9a-zA-Z\-]*)', m.group(1)).group(1)
    r = client.get(f'/mobile/guide/s/{key}')
    assert r.status_code == 200
    # 그 절 본문에서 마크업 없는 글자 표식 하나를 집는다.
    body = md[m.end():]
    nxt = re.search(r'^## ', body, re.M)
    body = body[:nxt.start()] if nxt else body
    plain = re.findall(r'[가-힣]{4,}', body)
    assert plain, 'md 절 본문에서 표식을 못 집었다 — 이 시험이 헛돈다'
    assert plain[0] in r.get_data(as_text=True), \
        f'정본 본문 표식 {plain[0]!r} 이 절 화면에 없다'


def test_템플릿엔_가이드_본문이_한_줄도_없다():
    """md 가 바뀌면 화면도 0수정으로 바뀌어야 한다 — 템플릿 복제가 있으면 빨강."""
    md = _real_md_text()
    tpls = _toc_src() + _sec_src()
    for h in re.findall(r'^## +(.+?)\s*$', md, re.M):
        title = re.sub(r'^§\s*[0-9][0-9a-zA-Z\-]*\.?\s*', '', h).strip()
        assert title not in tpls, f'가이드 절 제목이 템플릿에 박혀 있다: {title!r}'
    # 본문 문장 표본도 몇 개 — 제목만 피해 가는 복제를 막는다.
    for probe in re.findall(r'[가-힣]{6,}', md)[:20]:
        assert probe not in tpls, f'가이드 본문 글자가 템플릿에 박혀 있다: {probe!r}'


# ════════════════════════════════════════════════════════════
#  ④ 읽기 규칙 — 글자 크기 · 가로 스크롤 그릇 · 이스케이프
# ════════════════════════════════════════════════════════════

def test_읽기_규칙이_실재한다():
    src = _sec_src()
    m = re.search(r'\.mg-doc[^{]*\{([^}]*)\}', src)
    assert m, '본문 그릇(.mg-doc) 규칙이 없다'
    fs = re.search(r'font-size\s*:\s*(\d+)px', m.group(1))
    assert fs and int(fs.group(1)) >= 14, '본문 글자가 14px 미만이다'
    for cls in ('.mg-code', '.mg-tblwrap'):
        m = re.search(re.escape(cls) + r'[^{]*\{([^}]*)\}', src)
        assert m, f'{cls} 규칙이 없다'
        assert 'overflow-x' in m.group(1) and 'auto' in m.group(1), \
            f'{cls} 가 자기 그릇 안에서 가로 스크롤하지 않는다 — 몸통이 가로로 넘친다'
    # 목차 줄 = 터치 목표 44px.
    m = re.search(r'\.mg-row[^{]*\{([^}]*)\}', _toc_src())
    assert m, '목차 줄(.mg-row) 규칙이 없다'
    mh = re.search(r'min-height\s*:\s*(\d+)px', m.group(1))
    assert mh and int(mh.group(1)) >= 44, '목차 줄 터치 목표가 44px 미만이다'


def test_렌더러가_코드와_표를_그릇에_넣는다(client, monkeypatch, tmp_path):
    """기능 검증 — 코드 펜스는 <pre.mg-code>(이스케이프), 표는 .mg-tblwrap 안."""
    _fake_md(monkeypatch, tmp_path, (
        '# 시험\n\n## §1. 절\n\n'
        '```\nif a < b: <script>alert(1)</script>\n```\n\n'
        '| 열A | 열B |\n|---|---|\n| 값1 | 값2 |\n'
    ))
    html = client.get('/mobile/guide/s/1').get_data(as_text=True)
    m = re.search(r'<pre class="mg-code">(.*?)</pre>', html, re.S)
    assert m, '코드 펜스가 <pre class="mg-code"> 로 안 그려졌다'
    assert '&lt;script&gt;' in m.group(1), '코드 안 HTML 이 이스케이프되지 않았다'
    assert '<script>alert' not in html, '본문 HTML 이 그대로 실행 위치에 박혔다'
    assert re.search(r'<div class="mg-tblwrap"><table', html), \
        '표가 가로 스크롤 그릇(.mg-tblwrap) 없이 그려졌다'
    assert '값1' in html and '<th>열A</th>' in html, '표 내용이 사라졌다'


def test_링크_URL_따옴표가_속성을_탈출하지_못한다(client, monkeypatch, tmp_path):
    """🔴 href 속성 주입 무력화 — md 링크 URL 의 " 가 속성을 탈출해 onclick 같은
    이벤트 속성을 만들면 빨강(최종 검토에서 실행으로 확인된 구멍).

    낱말 검색이 아니다 — HTML 파서로 **전 태그의 속성 이름**을 본다.
    """
    from html.parser import HTMLParser

    _fake_md(monkeypatch, tmp_path, (
        '# 시험\n\n## §1. 절\n\n'
        '함정 링크 [x](http://a"onclick=evil) 다.\n'
    ))
    html = client.get('/mobile/guide/s/1').get_data(as_text=True)

    class _Attrs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags: list[tuple[str, dict]] = []

        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))

    p = _Attrs()
    p.feed(html)
    bad = [(t, k) for t, a in p.tags for k in a if k.startswith('on')]
    assert not bad, f'md 링크 URL 이 속성을 탈출해 이벤트 속성이 생겼다: {bad}'
    # 링크 자체는 살아 있어야 한다 — 통째로 안 그리는 식의 회피면 여기서 잡는다.
    hrefs = [a.get('href', '') for t, a in p.tags if t == 'a']
    assert any(h.startswith('http://a') for h in hrefs), \
        '함정 URL 링크가 아예 안 그려졌다 — 이스케이프가 아니라 삭제로 회피했다'


# ════════════════════════════════════════════════════════════
#  ⑤ 검색 = 목차 클라이언트 필터 · ⑥ 폴링/ISO 금지
# ════════════════════════════════════════════════════════════

def test_검색은_목차_필터고_서버를_부르지_않는다(client):
    """정직한 최소판 — 이미 실린 목차(제목·요약)만 거른다. fetch 0."""
    src = _toc_src()
    assert 'fetch(' not in src and 'askServer' not in src, \
        '목차 검색이 서버를 부른다 — 확정 범위(목차 필터)를 넘었다'
    assert 'data-text' in src, '줄에 필터용 data-text 가 없다'
    # 렌더된 줄의 data-text 에 제목이 실제로 들어 있다(필터가 빈 글자를 거르면 무의미).
    html = client.get('/mobile/guide').get_data(as_text=True)
    row = re.search(r'data-text="([^"]+)"[^>]*>\s*<div class="rl"><div class="rp">'
                    r'\d+\.\s*([^<]+)</div>', html)
    assert row, '줄에서 (data-text, 제목) 짝을 못 찾았다 — 구조가 바뀌었나'
    assert row.group(2).strip().lower() in row.group(1).lower(), \
        'data-text 에 제목이 안 들어 있다 — 검색이 그 줄을 영영 못 찾는다'
    # 결과 0건 갈래 — 아무 줄도 안 남으면 그렇다고 말한다(빈 화면 금지).
    assert 'mg-none' in src, '검색 결과 0건 안내 갈래(mg-none)가 없다'


def test_폴링과_ISO_날짜파싱이_없다():
    for src in (_toc_src(), _sec_src()):
        assert 'setInterval' not in src, '가이드 화면은 폴링하지 않는다'
        assert 'new Date(' not in src, 'ISO 문자열 Date 파싱 금지'
