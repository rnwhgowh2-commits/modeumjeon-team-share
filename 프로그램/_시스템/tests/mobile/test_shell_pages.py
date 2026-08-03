# -*- coding: utf-8 -*-
"""1단계에서 새로 생기는 폰 화면들이 실제로 열리는지."""
import re
from html.parser import HTMLParser

import pytest

from tests.mobile.conftest import require_sqlite

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


# flask_app 픽스처는 tests/mobile/conftest.py 에 있다(세 파일이 쓴다).


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
    # (사유·원리는 conftest.require_sqlite 의 주석에 한 번만 적어 뒀다).
    require_sqlite()

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
    # ★ 갈래 자체를 줄 통째로 못 박는다. 낱말만 보면 `if (false)` 로 바꿔 갈래를
    #   죽여도 `const ct = …` 줄이 죽은 코드로 남아 낱말을 대 주고 통과한다(실측).
    #   member 403 은 r.ok 가 먼저 거르지만, **세션 만료는 302 → 로그인 페이지
    #   200 OK HTML** 이라 r.ok 를 통과한다. 이 갈래가 죽으면 r.json() 이 HTML 에서
    #   터져 「연결이 안 됩니다」로 뜬다 — I-2 에서 고친 증상이 그대로 되살아난다.
    assert "if (!ct.includes('application/json'))" in html, \
        'content-type 갈래가 사라졌다 — 세션 만료가 「연결이 안 됩니다」로 안내된다'
    # JSON 을 푸는 자리는 askServer 안 **한 곳**뿐이어야 하고, 그것도 되돌려보내기
    #   (throw) 뒤라야 한다. 곳곳에서 풀면 그중 하나가 검사를 건너뛰어도 안 걸린다.
    assert low.count('.json()') == 1, \
        'JSON 을 푸는 곳이 여러 곳이다 — askServer 를 거치지 않는 길이 생겼다'
    # ★ rindex(=마지막) 여야 한다. index(첫 등장)로 보면 위쪽 r.ok 갈래의 throw 가
    #   먼저 잡혀, 정작 content-type 갈래에 대해선 **아무 말도 하지 않는다**.
    #   실제로 그렇게 새서 content-type 검사를 통째로 지워도 34개가 다 통과했다.
    assert low.rindex('throw e') < low.index('.json()'), \
        'JSON 이 아닐 때 되돌려보내기 전에 이미 파싱한다'


def test_리셋_건수는_화면에_쓰지_않는다(client):
    """run-lap 의 reset 은 '리셋된 건수'가 아니라 랩 대상 전체 개수다."""
    html = crawl_html(client)
    assert '건 리셋' not in html


def test_잠긴_버튼은_잠겨_보인다(client):
    """🔴 기능만 잠그고 **보이는 게 그대로**면 이 화면 최악의 결과가 남는다.

    실측으로 드러난 구멍: `.m-action-btn.primary` 가 background 와 color:white 를
    명시해 브라우저 기본 회색 처리를 덮는다. 그래서 disabled 를 걸어도
    「▶ 지금 한 바퀴 돌리기」가 **선명한 파란 버튼 그대로** 떴고, PC 가 꺼져 있는데도
    누를 수 있어 보였다(눌러도 무반응).

    ★ 속성(disabled)만 보는 시험은 이 결함을 그대로 통과시킨다 — 실제로 통과시켰다.
      그래서 화면에 실린 CSS 에 흐리게 만드는 규칙이 **있는지**까지 본다.
      (_base.html 이 style 을 인라인으로 싣기 때문에 브라우저 없이 확인된다.)
    """
    html = crawl_html(client)
    m = re.search(r'\.m-action-btn:disabled\s*\{([^}]*)\}', html)
    assert m, '잠긴 큰 버튼을 흐리게 하는 규칙(.m-action-btn:disabled)이 없다 — ' \
              'PC 가 꺼져도 버튼이 멀쩡해 보인다'
    body = m.group(1)
    o = re.search(r'opacity\s*:\s*([0-9.]+)', body)
    assert o and float(o.group(1)) < 1, f'흐려지지 않는다: {body!r}'
    assert 'not-allowed' in body, '누를 수 없다는 커서 표시가 없다'


def test_지어내지_않게_막는_장치가_스크립트에_남아있다(client):
    """서버가 답을 못 준 것을 '알아낸 사실'로 바꿔 쓰지 않게 하는 장치들.

    ⚠️ 정직하게 적어 둔다 — 이건 **원문 검사**다. 이 저장소엔 JS 를 돌릴 하니스가
      없어(형제 시험도 전부 파이썬) 동작까지는 확인하지 못한다. 그래도 누가 조용히
      지웠을 때 걸리게는 해 둔다. 각 줄이 막는 사고는 아래에 적었다.
    """
    html = crawl_html(client)

    # 상태코드를 안 보면 JSON 모양의 에러가 render() 로 들어가 d.pc 가 undefined
    # → 화면이 「PC 꺼져 있음」이라고 단정한다(서버 침묵을 PC 상태로 지어냄).
    assert 'if (!r.ok)' in html, '상태코드를 안 본다 — 서버 오류가 「PC 꺼짐」으로 둔갑한다'

    # setInterval + await 는 느린 망에서 요청이 겹치고 늦은 응답이 나중에 그려진다.
    # 게다가 화면이 숨겨져도 계속 돌아 하루 8,640회가 DB 를 친다.
    # 낱말이 아니라 **부르는 것**을 본다 — 왜 안 쓰는지 적어 둔 주석에도 그 낱말이 있다.
    #   (그래도 누가 주석에 `setInterval()` 이라 적으면 헛터진다 → 원하는 모양을 같이 못 박아
    #    의도를 분명히 한다.)
    assert 'setInterval(' not in html, 'setInterval 로 되돌아갔다 — 요청이 겹치고 숨겨도 계속 돈다'
    assert 'setTimeout(tick' in html, "'끝난 뒤에 다시 예약' 방식이 사라졌다"

    # 겹침은 예약 방식이 아니라 **세대 번호**가 처리한다(요청을 막는 게 아니라
    #   늦게 온 옛 응답을 버린다). 요청 자체를 막으면 명령 직후 새로고침까지 막혀
    #   토글이 옛 자리에 남는다 — 원래 문제만큼 나쁜 부작용이라 그 방식은 안 쓴다.
    #   ⚠️ 이 두 줄은 **있는지만** 본다. 실제로 순서가 뒤바뀐 응답이 버려지는지는
    #     JS 를 돌려야 알 수 있고, 이 저장소엔 그 하니스가 없다.
    assert 'const mySeq = ++loadSeq;' in html, \
        '세대 번호가 없다 — 늦은 응답이 새 값을 덮고 토글이 되돌아간 것처럼 보인다'
    assert html.count('if (mySeq !== loadSeq) return;') == 2, \
        '세대 검사가 두 갈래(실패·그리기) 모두에 있어야 한다'
    # 검사가 그리기보다 늦으면 아무 의미가 없다 — 순서까지 못 박는다.
    assert html.rindex('if (mySeq !== loadSeq) return;') < html.index('render(d);'), \
        '세대 검사가 render() 뒤에 있다 — 옛 응답을 이미 그린 뒤라 소용없다'
    assert 'Date.now() - lastLoadAt < 3000' in html, \
        '앱 전환 연타에 상한이 없다 — 복귀할 때마다 전체 조회가 나간다'
    # 기록하는 쪽이 없으면 lastLoadAt 이 0 에 머물러 위 상한이 **영원히 안 걸린다**
    #   — 검사는 남아 있는데 죽은 장치가 된다(실측으로 이 변이가 안 잡혔다).
    assert 'lastLoadAt = Date.now();' in html, \
        '나간 시각을 기록하지 않는다 — 3초 상한이 죽은 장치가 된다'

    # ★ 낱말이 '어딘가 있나'로는 못 막는다(실측) — visibilityState 는 복귀 리스너에도,
    #   lastAuto 는 선언·기록 자리에도 있어서, 정작 **쓰는 자리**를 지워도 통과했다.
    #   그래서 그 두 줄을 통째로 못 박는다. 원문에 밀착하는 대신 실제로 잡힌다.
    assert "if (document.visibilityState === 'visible') await load();" in html, \
        '화면이 안 보여도 계속 서버를 친다 — 폰 한 대가 하루 8,640회를 친다'
    assert '$auto.checked = lastAuto;' in html, \
        '실패해도 토글이 민 자리에 남는다 — 서버 값과 어긋난 걸 보여 준다'
    assert 'lastAuto = !!d.auto_enabled;' in html, \
        '서버가 확인해 준 값을 기억하지 않는다 — 되돌릴 곳이 없어진다'
    assert 'visibilitychange' in html, \
        '다시 켰을 때 오래된 화면이 그대로 남는다'

    # render() 안에서 난 TypeError 가 통신 실패와 같은 갈래로 떨어지면 「연결이
    # 안 됩니다」로 뜬다 — 망 문제가 아닌데 사장님이 와이파이를 보러 가시게 된다.
    assert '화면을 그릴 수 없습니다' in html, \
        '그리다 난 오류를 통신 실패로 안내한다 — 엉뚱한 곳을 고치시게 된다'


def test_화면이_읽는_칸_이름이_서버_응답에_다_있다(client):
    """🔴 템플릿이 손으로 적은 `d.<이름>` 과 서버 응답을 묶는 유일한 검사.

    이게 없으면 서버에서 칸 이름 하나만 바꿔도 화면이 undefined/NaN 을 그리는데
    시험은 전부 통과한다(초록불인데 화면은 깨진 상태). 사람이 두 파일을 눈으로
    맞추는 수밖에 없어지는데, Task 4·5 로 화면이 늘면 곧 못 한다.

    ⚠️ 한계 — **읽기를 지우는 변경은 이 검사 밖이다.** 방향이 한쪽뿐이라서다
      (화면이 읽는 이름 → 서버에 있나). 화면에서 `d.laps_today` 를 아예 안 읽게
      바꾸면 검사 대상에서 사라져 그냥 통과한다. 반대 방향(서버 칸을 다 읽는지)은
      만들 수 없다 — `ok`·`last_lap_today_at` 은 일부러 안 읽는 칸이다.
      만능으로 믿지 말 것.
    """
    html = crawl_html(client)
    payload = client.get('/mobile/crawl/api/status').get_json()

    # `d.pc.online` 같은 두 단계까지 잡는다.
    used = set(re.findall(r'\bd\.([a-z_]+)(?:\.([a-z_]+))?', html))
    assert used, '템플릿에서 d.<이름> 을 하나도 못 찾았다 — 이 시험이 헛돈다'

    for top, sub in sorted(used):
        assert top in payload, \
            f"화면은 d.{top} 을 읽는데 서버 응답엔 '{top}' 칸이 없다"
        if sub:
            inner = payload[top]
            assert isinstance(inner, dict), \
                f'화면은 d.{top}.{sub} 를 읽는데 서버의 {top} 은 {type(inner).__name__} 이다'
            assert sub in inner, \
                f"화면은 d.{top}.{sub} 를 읽는데 서버 {top} 안에 '{sub}' 칸이 없다"
