# -*- coding: utf-8 -*-
"""1단계에서 새로 생기는 폰 화면들이 실제로 열리는지."""
from html.parser import HTMLParser

import pytest

ADMIN_EMAIL = 'shell-admin@test.local'


class _TagById(HTMLParser):
    """id 로 태그 하나를 찾아 그 속성을 돌려준다.

    ★ 왜 문자열 검색을 안 쓰나 — 「disabled 가 화면 어딘가에 있다」는 검사는
      아무것도 못 막는다. 실측으로 확인했다: 버튼에서 disabled 를 떼도
      체크박스와 JS(`$run.disabled = ...`)에 그 낱말이 남아 시험이 그대로 통과했다.
      막으려는 건 '버튼이 처음부터 잠겨 있나'라 **그 태그의 속성**을 봐야 한다.
    """

    def __init__(self, want_id):
        super().__init__()
        self.want_id = want_id
        self.attrs = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get('id') == self.want_id and self.attrs is None:
            self.attrs = d


def attrs_of(html, elem_id):
    p = _TagById(elem_id)
    p.feed(html)
    assert p.attrs is not None, f'id={elem_id!r} 인 요소가 화면에 없다'
    return p.attrs


@pytest.fixture
def flask_app(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    # 🔴 /mobile/* 라우트는 app.py 의 ENVIRONMENT 게이트 안에서만 등록된다.
    #   pytest 에선 이 값이 없어 라우트가 0개 → 안 넣으면 전부 404 로 실패한다.
    monkeypatch.setenv('ENVIRONMENT', 'team-share-dev')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app


@pytest.fixture
def client(flask_app):
    """admin 으로 로그인된 클라이언트.

    ★ admin 을 **직접 만든다** — 이게 없으면 이 파일은 실행 순서에 기댄다.
      리모컨은 admin 전용(mobile_crawl._admin_only)이고, DISABLE_AUTH 자동 로그인은
      '첫 admin, 없으면 첫 활성 사용자'를 집는다(webapp/auth/__init__.py:82-87).
      빈 DB 면 집을 사람이 없어 익명 → enforce_admin 이 **302 로그인 리다이렉트**를 준다.
      실측: 이 파일만 돌리면 5 failed, tests/mobile 전체로 돌리면 31 passed 였다.
      앞서 도는 test_crawl_remote_api.py 가 공용 임시 SQLite 에 admin 을 남겨 둔
      덕에 우연히 통과한 것이라, 그 파일이 바뀌면 조용히 무너진다.
    """
    # 사용자를 새로 만드는 fixture 라 진짜 DB 에선 돌리지 않는다
    # (config.py:10 의 load_dotenv(override=True) 가 conftest 의 임시 DATABASE_URL 을
    #  덮어써 라이브 팀 DB 를 칠 수 있다 — test_crawl_remote_api.py 의 가드와 같은 이유).
    from shared.db import engine
    if engine.url.get_backend_name() != "sqlite":
        pytest.skip("사용자를 만드는 시험이라 진짜 DB 에선 안 돈다")

    from shared.db import SessionLocal
    from webapp.auth.models import User
    s = SessionLocal()
    try:
        u = s.query(User).filter(User.email == ADMIN_EMAIL).first()
        if u is None:
            # 비밀번호는 안 쓴다 — 로그인은 DISABLE_AUTH 자동 로그인이 해 준다.
            u = User(email=ADMIN_EMAIL, name='admin', password_hash='x',
                     role='admin', is_active=True)
            s.add(u)
        u.is_active = True      # 앞 시험(member_client)이 감춰 뒀을 수 있다
        s.commit()
    finally:
        s.close()
    return flask_app.test_client()


def crawl_html(client):
    """리모컨 화면의 HTML — 200 이 아니면 거기서 세운다.

    ★ 아래 시험들은 대부분 '문자열이 있나/없나'라, 본문이 비면 **없는 쪽 시험이
      저절로 통과**한다. 실제로 302 리다이렉트(본문 30자)일 때
      test_리셋_건수는_화면에_쓰지_않는다 가 아무것도 검증하지 못한 채 통과했다.
      그래서 본문을 읽기 전에 200 인지부터 못 박는다.
    """
    r = client.get('/mobile/crawl/')
    assert r.status_code == 200, \
        f'리모컨 화면이 안 열린다(status={r.status_code}) — 아래 시험은 의미가 없다'
    return r.get_data(as_text=True)


def test_크롤_리모컨_화면이_열린다(client):
    r = client.get('/mobile/crawl/')
    assert r.status_code == 200
    assert 'mobile-crawl' in r.get_data(as_text=True)


def test_PC가_꺼져있으면_누를_수_없다는_것이_화면에_박혀있다(client):
    """누르면 되는 줄 알고 눌렀는데 아무 일도 안 일어나는 게 제일 나쁘다.

    화면이 처음 뜰 때는 PC 가 켜졌는지 **아직 모른다**. 그러니 서버 답을 받기 전까지는
    둘 다 잠겨 있어야 한다 — 열어 두면 그 사이 누른 게 조용히 사라진다.
    """
    html = crawl_html(client)
    assert 'disabled' in html
    assert 'PC' in html
    # 낱말이 어딘가 있는지가 아니라 **그 두 조작칸이** 잠겨 나오는지를 본다.
    for elem_id in ('mc-run', 'mc-auto'):
        assert 'disabled' in attrs_of(html, elem_id), \
            f'{elem_id} 이 잠기지 않은 채 나온다 — PC 상태를 모르는 동안 눌린다'


def test_화면은_시각문자열이_아니라_초를_쓴다(client):
    """서버가 주는 ISO 에는 시간대가 없어 폰에서 9시간 어긋난다."""
    html = crawl_html(client)
    assert 'seconds_ago' in html
    assert 'last_lap_today_at' not in html, '시간대 없는 문자열을 화면이 직접 쓴다'


def test_통계를_못_읽으면_0이_아니라_모름으로_그린다(client):
    html = crawl_html(client)
    assert 'stats_ok' in html, '통계 실패를 구분하지 않는다'


def test_인증_실패가_HTML로_와도_안_터진다(client):
    """리모컨은 admin 전용 — member 는 403 HTML, 세션 만료면 로그인 HTML 이 온다.

    ★ 「content-type 이란 낱말이 있나」로는 못 막는다 — POST 가 보내는
      `'Content-Type': 'application/json'` 헤더에도 그 낱말이 있어, 검사를 통째로
      지워도 시험이 통과했다(실측). 그래서 두 가지를 본다:
        1) **응답의** 헤더를 읽는가 (보내는 헤더 말고)
        2) 그 검사가 첫 `.json()` **앞에** 오는가 — 순서가 핵심이라 그렇다.
    """
    html = crawl_html(client)
    low = html.lower()
    assert "headers.get('content-type')" in low, \
        '응답의 content-type 을 읽지 않는다 — 인증 HTML 을 JSON 으로 파싱하다 터진다'
    assert low.index("headers.get('content-type')") < low.index('.json()'), \
        'content-type 을 보기 전에 .json() 을 먼저 부른다'
    # JSON 을 푸는 자리는 askServer 안 **한 곳**뿐이어야 하고, 그것도 되돌려보내기
    #   (throw) 뒤라야 한다. 곳곳에서 풀면 그중 하나가 검사를 건너뛰어도 안 걸린다.
    assert low.count('.json()') == 1, \
        'JSON 을 푸는 곳이 여러 곳이다 — askServer 를 거치지 않는 길이 생겼다'
    assert low.index('throw e') < low.index('.json()'), \
        'JSON 이 아닐 때 되돌려보내기 전에 이미 파싱한다'


def test_리셋_건수는_화면에_쓰지_않는다(client):
    """run-lap 의 reset 은 '리셋된 건수'가 아니라 랩 대상 전체 개수다."""
    html = crawl_html(client)
    assert '건 리셋' not in html
