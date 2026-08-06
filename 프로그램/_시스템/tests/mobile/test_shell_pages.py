# -*- coding: utf-8 -*-
"""1단계에서 새로 생기는 폰 화면들이 실제로 열리는지."""
import re
from html.parser import HTMLParser
from types import SimpleNamespace

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


# 닫는 태그가 없는 것들 — 깊이를 세는 데 끼면 셈이 영영 안 맞는다(<br> 이 실제로 있다).
_VOID = {'br', 'img', 'input', 'hr', 'meta', 'link', 'source',
         'area', 'base', 'col', 'embed', 'param', 'track', 'wbr'}


class _TextInside(HTMLParser):
    """id 로 요소 하나를 찾아 **그 안에 실제로 보이는 글자**만 모은다.

    ★ 왜 문자열 검색(`'사파리' in html`)을 안 쓰나 — 이 저장소가 이미 네 번 당한 함정이다.
      낱말이 주석·변수명·죽은 코드·엉뚱한 칸에 남아 있으면, 정작 안내 문구를
      통째로 지워도 시험이 그대로 통과한다. 여기서는
        1) HTML 주석(<!-- -->)은 handle_data 로 안 오니 저절로 빠지고
        2) <script>·<style> 안의 글자는 손으로 뺀다
        3) 무엇보다 **아이폰 칸 / 안드로이드 칸 안쪽만** 본다
      그래서 '사파리'가 안드로이드 칸이나 스크립트에 있어도 통과하지 않는다.
    """

    def __init__(self, want_id):
        super().__init__(convert_charrefs=True)
        self.want_id = want_id
        self.depth = 0      # 대상 요소 안에서의 깊이 (0 = 아직 밖)
        self.skip = 0       # script/style 안이면 > 0
        self.buf = []
        self.found = False

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            return
        if self.depth:
            self.depth += 1
            if tag in ('script', 'style'):
                self.skip += 1
        elif not self.found and dict(attrs).get('id') == self.want_id:
            self.found = True
            self.depth = 1

    def handle_endtag(self, tag):
        if tag in _VOID or not self.depth:
            return
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1
        self.depth -= 1

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.buf.append(data)


def text_in(html, elem_id):
    p = _TextInside(elem_id)
    p.feed(html)
    assert p.found, f'id={elem_id!r} 인 요소가 화면에 없다'
    # 줄바꿈·들여쓰기 때문에 낱말이 갈라지지 않게 공백을 한 칸으로 눕힌다
    return re.sub(r'\s+', ' ', ''.join(p.buf)).strip()


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


# ─────────────────────────────────────────────────────────────
# Task 5 — 설치 안내 화면 (/mobile/install)
# ─────────────────────────────────────────────────────────────

def install_html(client):
    """설치 안내 화면의 HTML — 200 이 아니면 거기서 세운다.

    ★ 리모컨 쪽에서 겪은 그대로다: 본문이 비면 '없는 쪽'을 보는 시험이 저절로
      통과한다. 아래 시험들이 의미를 가지려면 본문이 진짜 그 화면이어야 한다.
    """
    r = client.get('/mobile/install')
    assert r.status_code == 200, \
        f'설치 안내 화면이 안 열린다(status={r.status_code}) — 아래 시험은 의미가 없다'
    return r.get_data(as_text=True)


def test_설치안내_화면이_열린다(client):
    r = client.get('/mobile/install')
    assert r.status_code == 200
    # 200 만으로는 '무언가 200'인지 이 화면인지 구분이 안 된다 → 뼈대를 확인한다.
    assert attrs_of(r.get_data(as_text=True), 'mobile-install')


def test_아이폰은_사파리로만_된다는_것이_적혀있다(client):
    """크롬으로 시도하면 헤맨다 — 그런데 이 안내가 **따라 하는 단계 안에** 있어야 한다.

    두 번 좁혔고, 두 번 다 이유가 실측이다.
      1) 화면 전체가 아니라 아이폰 칸 — '홈 화면에 추가'는 안드로이드 칸에도 나온다.
      2) 칸이 아니라 **단계 목록(ol)** — 칸에는 보충 설명이 붙어 있어서, 1단계를
         「크롬으로 접속」으로 바꿔도 보충 설명의 '사파리'가 낱말을 대 주고 통과했다
         (변이 M1·M2·M3 을 실제로 놓쳤다). 그러면 서로 어긋난 안내가 그대로 나간다.
    """
    html = install_html(client)
    assert '아이폰' in text_in(html, 'mi-iphone'), '어느 기계용 안내인지 제목이 없다'
    steps = text_in(html, 'mi-iphone-steps')
    assert '사파리' in steps, f'따라 하는 단계에 사파리가 없다: {steps[:120]!r}'
    assert '홈 화면에 추가' in steps
    assert '공유' in steps, '공유 버튼을 누르라는 단계가 빠졌다 — 이게 유일한 설치 경로다'


def test_안드로이드_안내도_같이_있다(client):
    """사장님이 아이폰·안드로이드 둘 다 쓰신다 — 한쪽만 있으면 반쪽이다."""
    card = text_in(install_html(client), 'mi-android')
    assert '안드로이드' in card
    steps = text_in(install_html(client), 'mi-android-steps')
    assert '앱 설치' in steps
    # ★ '앱 설치'는 단계 안에 두 번 나온다(저절로 뜨는 배너 / ⋮ 메뉴) → 그 낱말만
    #   보면 한쪽을 지워도 안 걸린다(변이 M7 을 실제로 놓쳤다). 손으로 찾아 들어가는
    #   길이 사라지는 게 진짜 사고라, 그 표시를 따로 못 박는다.
    #   안드로이드 크롬 배너는 조건이 안 맞으면 그냥 안 뜬다 — 그때 이 줄이 유일한 길이다.
    assert '⋮' in steps, '배너가 안 뜰 때 손으로 찾아 들어가는 길이 없다'


def test_설치버튼은_안내가_뜨기_전에는_보이지_않는다(client):
    """🔴 아이폰에서는 beforeinstallprompt 가 **영영 안 온다**.

    그래서 이 버튼이 처음부터 보이면, 아이폰 사장님께는 눌러도 아무 일 없는 파란
    버튼이 남는다 — Task 3 에서 한 번 낸 사고와 같은 부류다.
    감춰 두는 것과 되살릴 때 쓰는 값을 둘 다 못 박는다.
    """
    html = install_html(client)
    style = attrs_of(html, 'mi-prompt').get('style', '')
    assert re.search(r'display\s*:\s*none', style), \
        f'설치 버튼이 처음부터 보인다 — 아이폰에선 눌러도 무반응이다: {style!r}'

    # 되살릴 때 쓰는 값이 그 버튼의 실제 display 와 달라야 할 이유가 없다.
    #   .m-action-btn 은 세로 flex 라 'block' 으로 되살리면 가운데 정렬이 깨진다.
    m = re.search(r'\.m-action-btn\s*\{([^}]*)\}', html)
    assert m, '.m-action-btn 규칙이 화면에 없다 — 이 검사가 헛돈다'
    css_display = re.search(r'display\s*:\s*([a-z-]+)', m.group(1))
    assert css_display, '.m-action-btn 에 display 가 없다'
    assert f"style.display = '{css_display.group(1)}'" in html, \
        f'되살릴 때 쓰는 값이 .m-action-btn 의 display({css_display.group(1)}) 와 다르다'


def test_이미_앱으로_실행중_배너는_기본으로_숨어있다(client):
    """평범하게 웹으로 보는 사람에게 '이미 설치됐다'고 말하면 안내가 통째로 무의미해진다.

    ⚠️ 정직하게 — 이건 **원문 검사**다. 이 저장소엔 JS 를 돌릴 하니스가 없어
      matchMedia 판정이 실제로 맞는지는 확인하지 못한다. 확인하는 건 두 가지뿐이다:
      (1) 기본값이 숨김이라 판정이 죽으면 '안 보이는' 쪽으로 넘어진다는 것,
      (2) 아이폰 전용 옛 신호(navigator.standalone)를 같이 본다는 것.
    """
    html = install_html(client)
    style = attrs_of(html, 'mi-done').get('style', '')
    assert re.search(r'display\s*:\s*none', style), \
        '판정 전에 「이미 앱으로 실행 중」이 먼저 보인다'
    assert "matchMedia('(display-mode: standalone)')" in html, \
        '안드로이드·최신 아이폰에서 설치 여부를 못 알아본다'
    assert 'navigator.standalone === true' in html, \
        '아이폰 옛 신호를 안 본다(=== true 로 못 박아야 undefined 가 참으로 새지 않는다)'


# ─────────────────────────────────────────────────────────────
# Task 6 — 하단 탭 (mobile/_tabbar.html · static/mobile_shell.css)
# ─────────────────────────────────────────────────────────────

class _Tabs(HTMLParser):
    """nav.ms-tabbar 안의 a.ms-tab 만 (주소, class 목록, 글자) 로 모은다.

    ★ 왜 문자열 검색을 안 쓰나 — 형제 시험들이 네 번 당한 그 함정이다.
      '크롤' 낱말은 주석·CSS·JS 어디에나 남을 수 있어, 탭 칸을 통째로 지워도
      `'크롤' in html` 은 통과한다. 여기서 보려는 건 '탭바 안에 어떤 칸이
      몇 개 실렸나'라 **그 태그들**을 세야 한다.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bar_found = False
        self._depth = 0          # 탭바 안 깊이 (0 = 밖)
        self.tabs: list[dict] = []
        self._cur: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            return
        d = dict(attrs)
        cls = (d.get('class') or '').split()
        if self._depth:
            self._depth += 1
            if tag == 'a' and 'ms-tab' in cls:
                self._cur = {'href': d.get('href'), 'classes': cls, 'text': ''}
        elif 'ms-tabbar' in cls:
            self.bar_found = True
            self._depth = 1

    def handle_data(self, data):
        if self._cur is not None:
            self._cur['text'] += data.strip()

    def handle_endtag(self, tag):
        if tag in _VOID or not self._depth:
            return
        if tag == 'a' and self._cur is not None:
            self.tabs.append(self._cur)
            self._cur = None
        self._depth -= 1


def tabs_of(html):
    p = _Tabs()
    p.feed(html)
    assert p.bar_found, '하단 탭바(ms-tabbar)가 화면에 없다'
    assert p.tabs, '탭바는 있는데 칸(ms-tab)이 하나도 없다'
    return p.tabs


def page_html(client, path):
    """★ 본문이 비면(302·404) '없는 쪽' 시험이 저절로 통과한다 — 먼저 200 을 못 박는다."""
    r = client.get(path)
    assert r.status_code == 200, \
        f'{path} 이 안 열린다(status={r.status_code}) — 탭 시험이 의미가 없다'
    return r.get_data(as_text=True)


# 폰 전용 화면 전부 — admin(client 픽스처)으로 본다(/mobile/crawl/ 은 admin 전용).
PHONE_PAGES = ['/mobile', '/mobile/scan', '/mobile/scan-batch?mode=in',
               '/mobile/inventory', '/mobile/menu', '/mobile/crawl/',
               '/mobile/install']


@pytest.mark.parametrize('path', PHONE_PAGES)
def test_모든_폰_화면에_하단_탭이_있다(client, path):
    """어디에 있든 홈·작업·전체로 한 번에 돌아올 수 있어야 한다."""
    hrefs = {t['href'] for t in tabs_of(page_html(client, path))}
    for want in ('/mobile', '/mobile/scan', '/mobile/menu'):
        assert want in hrefs, f'{path} 의 탭에 {want} 칸이 없다: {sorted(hrefs)}'


def _tabs_as(flask_app, monkeypatch, is_admin):
    """라우트가 스스로 계산한 is_admin 경로로 탭을 받는다.

    (test_리모컨_줄은_admin_에게만_보인다 와 같은 방식 — tab_rows(True/False) 만
    시험하면 렌더 쪽이 True 를 박아 넣어도 통과한다.)
    """
    import flask_login
    from webapp.routes.mobile_shell import menu as menu_view
    monkeypatch.setattr(flask_login, 'current_user',
                        SimpleNamespace(is_admin=is_admin))
    with flask_app.test_request_context('/mobile/menu'):
        return tabs_of(menu_view())


def test_크롤_탭은_admin_에게만_보인다(flask_app, monkeypatch):
    """member 에게 크롤 탭을 보여 주면 누르는 순간 403 —
    이 프로젝트가 제일 나쁘게 치는 '눌러도 아무 일 없는 버튼'이다."""
    member = {t['href'] for t in _tabs_as(flask_app, monkeypatch, False)}
    admin = {t['href'] for t in _tabs_as(flask_app, monkeypatch, True)}
    assert '/mobile/crawl/' not in member, 'member 에게 크롤 탭이 보인다 — 누르면 403'
    assert '/mobile/crawl/' in admin, 'admin 에게도 크롤 탭이 없다'


def test_member_는_정확히_4칸_admin_은_5칸이다(flask_app, monkeypatch):
    """빈 자리 없이 칸 수 자체가 줄어야 한다(.ms-tab 이 flex:1 이라 4칸이면 4등분).

    [2026-08-06 사장님 확정 A1] 주문 칸이 생겨 member 3→4·admin 4→5.
    주문은 admin 전용이 아니므로 **양쪽 다** 한 칸씩 는다.
    """
    assert len(_tabs_as(flask_app, monkeypatch, False)) == 4
    assert len(_tabs_as(flask_app, monkeypatch, True)) == 5


def test_주문_탭은_member_에게도_보인다(flask_app, monkeypatch):
    """주문은 member 의 일이다 — admin 전용으로 잠그면 PC /orders 와 답이 갈린다."""
    member = {t['href'] for t in _tabs_as(flask_app, monkeypatch, False)}
    admin = {t['href'] for t in _tabs_as(flask_app, monkeypatch, True)}
    assert '/mobile/orders' in member, 'member 에게 주문 탭이 없다'
    assert '/mobile/orders' in admin, 'admin 에게 주문 탭이 없다'


def test_주문_화면에서는_주문_탭이_켜진다():
    """남의 탭(홈·작업)을 켜 두면 「지금 거기 있다」는 거짓말이 된다."""
    from webapp.routes.mobile_shell import active_tab_key
    assert active_tab_key('/mobile/orders') == 'orders'
    assert active_tab_key('/mobile') == 'home'


def test_탭_주소는_전부_폰전용_목록에서_왔다(client):
    """🔴 탭 목록을 따로 적으면 「같은 사실 두 곳에 적기」가 폰 안에서 재발한다.

    3단계에서 화면이 늘 때 메뉴엔 뜨는데 탭엔 없거나 그 반대가 되는 사고 —
    렌더된 탭 주소가 PHONE_NATIVE_ROWS 밖이면 여기서 잡힌다.
    """
    from webapp.routes.mobile_shell import PHONE_NATIVE_ROWS, same_route
    allowed = {same_route(it['url']) for it in PHONE_NATIVE_ROWS}
    tabs = tabs_of(page_html(client, '/mobile'))
    stray = [t['href'] for t in tabs if same_route(t['href']) not in allowed]
    assert not stray, f'폰 전용 목록(PHONE_NATIVE_ROWS)에 없는 탭 주소: {stray}'


def test_탭은_주소를_템플릿에_직접_적지_않는다():
    """위 ⊆ 검사만으로는 '목록과 우연히 같은 값을 하드코딩'한 것을 못 잡는다 —
    원천을 쓰는지 템플릿 원문에서 못 박는다(메뉴 쪽 형제 시험과 같은 방식)."""
    from pathlib import Path
    import config
    tpl = (Path(config.PROJECT_ROOT) / 'webapp' / 'templates' / 'mobile'
           / '_tabbar.html')
    src = tpl.read_text(encoding='utf-8')
    assert 'ms_tab_rows' in src, '탭 원천 헬퍼(ms_tab_rows)를 안 쓰고 있다'
    assert 'href="/mobile' not in src, '탭 주소를 템플릿에 직접 적어뒀다 — 원천이 둘로 갈라진다'


def test_지금_화면의_탭이_켜져_보인다(client):
    """🔴 기능만 맞고 보이는 게 그대로인 부류(Task 3 실사고) — 두 가지를 같이 본다:
    (1) 지금 화면의 탭에 on 이 붙나, (2) on 을 다르게 그리는 CSS 규칙이 실려 있나."""
    tabs = tabs_of(page_html(client, '/mobile/menu'))
    on = [t for t in tabs if 'on' in t['classes']]
    assert [t['href'] for t in on] == ['/mobile/menu'], \
        f'/mobile/menu 화면인데 켜진 탭이 {[t["href"] for t in on]} 이다'

    r = client.get('/static/mobile_shell.css')
    assert r.status_code == 200, 'mobile_shell.css 가 안 실린다'
    css = r.get_data(as_text=True)
    m = re.search(r'\.ms-tab\.on\s*\{([^}]*)\}', css)
    assert m, '켜진 탭을 다르게 그리는 규칙(.ms-tab.on)이 없다 — 어느 탭에 있는지 안 보인다'
    assert 'color' in m.group(1), '.ms-tab.on 이 색을 안 바꾼다'


def test_소속_화면은_부모_탭이_켜지고_소속_없는_화면은_안_켠다(client):
    """연속 스캔(/mobile/scan-batch)은 작업(스캔)의 하위 흐름이라 작업 탭을 켠다.
    재고 목록·설치 안내는 어느 탭의 화면도 아니다 — 홈을 켜 두면
    「지금 홈에 있다」는 거짓말이라 아무것도 안 켠다."""
    tabs = tabs_of(page_html(client, '/mobile/scan-batch?mode=in'))
    on = [t['href'] for t in tabs if 'on' in t['classes']]
    assert on == ['/mobile/scan'], f'연속 스캔인데 켜진 탭이 {on} 이다'

    for path in ('/mobile/inventory', '/mobile/install'):
        on = [t['href'] for t in tabs_of(page_html(client, path))
              if 'on' in t['classes']]
        assert not on, f'{path} 은 어느 탭 화면도 아닌데 {on} 이 켜져 있다'


def test_소속_표시가_실제_탭을_가리킨다():
    """under_tab 이 오타면 에러 없이 그 화면만 조용히 탭이 안 켜진다 — 여기서 잡는다."""
    from webapp.routes.mobile_shell import PHONE_NATIVE_ROWS
    keys = {it['tab']['key'] for it in PHONE_NATIVE_ROWS if it.get('tab')}
    assert keys, '탭이 하나도 정의돼 있지 않다 — 이 시험이 헛돈다'
    for it in PHONE_NATIVE_ROWS:
        under = it.get('under_tab')
        if under:
            assert under in keys, \
                f"{it['url']} 의 under_tab={under!r} 은 없는 탭이다 — 켜지지 않는다"


def test_탭바가_내용을_가리지_않는다(client):
    """탭바는 fixed 라 흐름 밖 — 바닥 여백이 없으면 마지막 줄이 탭 뒤에 숨는다.

    여백은 body.m-body 로 좁혀야 한다: Task 7 에서 이 CSS 가 PC 화면에도 실리는데,
    맨몸 body 규칙이면 PC 바닥에 이유 없는 빈 띠가 생긴다."""
    css = client.get('/static/mobile_shell.css').get_data(as_text=True)
    m = re.search(r'body\.m-body\s*\{([^}]*)\}', css)
    assert m, '바닥 여백 규칙(body.m-body)이 없다 — 내용 끝줄이 탭 뒤에 숨는다'
    assert 'padding-bottom' in m.group(1) and '--ms-tabbar-h' in m.group(1), \
        f'바닥 여백이 탭 높이와 안 묶여 있다: {m.group(1)!r}'
    bare = css.replace('body.m-body', '')     # 좁힌 규칙을 지우고 맨몸 body 만 찾는다
    assert re.search(r'(?<![\w.\-#])body\s*\{', bare) is None, \
        '맨몸 body 규칙이 있다 — Task 7 에서 PC 화면 바닥에 빈 띠가 생긴다'

    html = page_html(client, '/mobile')
    bm = re.search(r'<body[^>]*class="([^"]*)"', html)
    assert bm and 'm-body' in bm.group(1).split(), \
        '폰 화면 body 에 m-body 가 없다 — 바닥 여백 규칙이 안 걸린다'
    assert 'mobile_shell.css' in html, '폰 화면이 mobile_shell.css 를 안 싣는다'


def test_탭_손끝_목표가_충분히_크다(client):
    """탭 높이 56px(≥44px 손끝 목표)이 변수로 못 박혀 있고, 칸이 그 변수를 쓴다."""
    css = client.get('/static/mobile_shell.css').get_data(as_text=True)
    h = re.search(r'--ms-tabbar-h\s*:\s*(\d+)px', css)
    assert h, '탭 높이 변수(--ms-tabbar-h)가 없다'
    assert int(h.group(1)) >= 44, f'탭 높이 {h.group(1)}px — 손끝 목표 44px 미달'
    tab = re.search(r'\.ms-tab\s*\{([^}]*)\}', css)
    assert tab and 'min-height' in tab.group(1) and '--ms-tabbar-h' in tab.group(1), \
        '탭 칸이 높이 변수를 안 쓴다 — 변수만 있고 죽은 장치다'


# ─────────────────────────────────────────────────────────────
# Task 7 — PC 화면 위 껍데기 주입 (base.html · static/mobile_shell.js)
# ─────────────────────────────────────────────────────────────

def shell_js_src():
    from pathlib import Path
    import config
    return (Path(config.PROJECT_ROOT) / 'webapp' / 'static'
            / 'mobile_shell.js').read_text(encoding='utf-8')


# 탭 JSON 파서 — 배치2에서 conftest 로 한 벌만 남겼다(test_stage3_ready 와 공용).
from tests.mobile.conftest import shell_blob_of as tabs_json_of  # noqa: E402


def test_PC_화면에도_껍데기가_실려있다(client):
    """169개 화면 중 157개가 PC 화면이다 — 여기에 뒤로가기·탭이 붙어야 길을 안 잃는다."""
    html = page_html(client, '/')
    assert 'mobile_shell.js' in html
    assert 'mobile_shell.css' in html


def test_PC_탭_JSON은_서버_단일원천과_같다(client):
    """🔴 JS 에 탭 목록을 따로 적으면 「같은 사실 두 곳에 적기」가 재발한다 —
    화면에 심긴 JSON 이 서버 tab_rows(단일 원천) 출력과 **완전히 같아야** 한다.

    [3단계] JSON 이 {tabs, ready} 한 덩어리가 됐다 — 탭은 tabs 칸으로 들어간다.
    ready(폰 대응 완료 주소) 검증은 tests/mobile/test_stage3_ready.py 가 맡는다."""
    from webapp.routes.mobile_shell import tab_rows
    got = tabs_json_of(page_html(client, '/'))
    # client 픽스처는 admin — DISABLE_AUTH 자동 로그인이 그 admin 을 집는다.
    assert got['tabs'] == tab_rows(True), \
        '화면의 탭 JSON 이 서버 원천(tab_rows)과 다르다 — 원천이 둘로 갈라졌다'


def test_ENVIRONMENT_없이도_PC_화면이_안_죽는다(monkeypatch):
    """🔴 이 단계 최고 위험 — base.html 은 PC 화면 157개 전부가 물려받는데,
    ms_tab_rows 는 ENVIRONMENT=team-share-dev 에서만 정의된다(app.py 게이트).
    가드({% if ms_tab_rows is defined %}) 없이 부르면 게이트 꺼진 배포에서
    **모든 화면이 500** 난다. 껍데기 흔적도 0 이어야 한다(설계: 통째로 안 싣는다)."""
    monkeypatch.delenv('ENVIRONMENT', raising=False)
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    a = appmod.create_app()
    a.config['TESTING'] = True
    r = a.test_client().get('/')
    assert r.status_code == 200, \
        f'게이트 꺼진 배포에서 PC 홈이 안 뜬다(status={r.status_code}) — 157개 화면 전멸'
    html = r.get_data(as_text=True)
    assert 'ms-tabs-data' not in html, '게이트가 꺼졌는데 탭 JSON 이 실렸다'
    assert 'mobile_shell.js' not in html, '게이트가 꺼졌는데 껍데기 스크립트가 실렸다'


def test_껍데기는_설치된_앱_좁은화면에서만_켜진다():
    """PC 브라우저에서 켜지면 잘 돌아가던 화면 157개를 망친다.

    ★ 낱말이 아니라 판정 줄을 통째로 못 박는다 — 낱말만 보면 주석에 남아도
      통과한다(이 저장소가 네 번 당한 함정)."""
    src = shell_js_src()
    assert "window.matchMedia('(display-mode: standalone)').matches" in src, \
        '설치 여부(display-mode: standalone)를 안 본다'
    assert 'window.navigator.standalone === true' in src, \
        '아이폰 옛 신호를 안 본다(=== true 라야 undefined 가 참으로 안 샌다)'
    assert "window.matchMedia('(max-width: 768px)').matches" in src, '화면 폭을 안 본다'
    # 세 판정이 실제로 입구를 지키는 줄 — 이게 없으면 판정 함수는 죽은 장식이다.
    assert 'if (!isInstalledApp() || !isNarrow() || isPhoneNativePage()) return;' in src, \
        '판정 함수는 있는데 입구에서 안 쓴다'


def test_폰전용_화면에는_주입하지_않는다():
    """/mobile/* 는 자기 탭(_tabbar.html)을 이미 갖고 있다 — 탭이 두 개 생기면 안 된다."""
    src = shell_js_src()
    assert "window.location.pathname.indexOf('/mobile') === 0" in src


def test_탭_주소는_JS에_직접_적지_않는다():
    """🔴 탭 원천은 PHONE_NATIVE_ROWS 하나 — JS 는 서버가 심은 JSON 만 읽는다.

    허용되는 '/mobile' 리터럴은 딱 두 줄(폰 화면 판정·뒤로가기 폴백)이고,
    그 두 줄을 통째로 못 박은 뒤 개수까지 센다 — 탭 주소를 하나라도 하드코딩하면
    개수가 늘거나 '/mobile/ 부분경로가 생겨 여기서 잡힌다."""
    src = shell_js_src()
    assert "'/mobile/" not in src, 'JS 가 탭 주소를 직접 안다 — 원천이 둘로 갈라진다'
    n = src.count("'/mobile'")
    assert n == 2, f"'/mobile' 리터럴이 {n}곳 — 허용은 판정·폴백 두 줄뿐"
    assert "window.location.pathname.indexOf('/mobile') === 0" in src
    assert "else window.location.href = '/mobile';" in src
    # 탭은 서버가 심은 JSON 에서만 온다.
    assert "document.getElementById('ms-tabs-data')" in src, '심어 둔 탭 JSON 을 안 읽는다'
    assert 'JSON.parse' in src


def test_주입되는_DOM이_CSS_스코프와_맞물린다(client):
    """🔴 기능만 맞고 안 보이는 부류(Task 3 실사고) — 상단바 CSS 는 전부
    `.ms-on ` 접두라, JS 가 <html> 에 ms-on 을 안 붙이면 규칙이 통째로 죽은 채
    맨몸 DOM 이 뜬다. 바닥 여백도 body.m-body 규칙 하나뿐이라 그 클래스를
    붙여야 마지막 줄이 탭 뒤에 안 숨는다.

    ⚠️ 정직하게 — JS 를 돌릴 하니스가 없어(형제 시험 전부 동일) 원문 검사다.
      브라우저 실검증은 Task 10 실폰에서 한다."""
    src = shell_js_src()
    assert "document.documentElement.classList.add('ms-on');" in src, \
        'html 에 ms-on 을 안 붙인다 — .ms-on 접두 CSS 가 전부 죽는다'
    assert "body.classList.add('m-body');" in src, \
        'body 에 m-body 를 안 붙인다 — 바닥 여백이 없어 끝줄이 탭 뒤에 숨는다'
    assert "if (document.querySelector('.ms-tabbar')) return;" in src, \
        '두 번 붙는 것을 안 막는다'
    assert 'if (tb) body.appendChild(tb);' in src, '탭바를 실제로 붙이는 줄이 없다'
    # 주입 DOM 이 입는 CSS 가 진짜 실려 있는지 — 클래스만 맞고 규칙이 없으면 헛일이다.
    css = client.get('/static/mobile_shell.css').get_data(as_text=True)
    for sel in ('.ms-on .ms-topbar', '.ms-on .ms-back',
                '.ms-on .ms-title', '.ms-on .ms-notice'):
        assert re.search(re.escape(sel) + r'\s*\{', css), \
            f'{sel} 규칙이 없다 — 주입 DOM 이 맨몸으로 뜬다'


def test_안내띠_문구가_그대로_있다():
    """PC용 화면임을 알리고 눕히면 낫다는 안내 — 문구를 통째로 못 박는다."""
    assert "'ⓘ PC용 화면입니다 · 폰을 옆으로 눕히면 보기 편합니다'" in shell_js_src()


# ─────────────────────────────────────────────────────────────
# Task 7B — 홈: 크롤 한 줄(admin 전용) + 최근 본 화면(폰 저장)
# ─────────────────────────────────────────────────────────────

def home_tpl_src():
    from pathlib import Path
    import config
    return (Path(config.PROJECT_ROOT) / 'webapp' / 'templates' / 'mobile'
            / 'home.html').read_text(encoding='utf-8')


def _home_as(flask_app, monkeypatch, is_admin):
    """라우트가 스스로 계산한 is_admin 경로로 홈을 렌더한다.

    (_tabs_as·test_리모컨_줄은_admin_에게만_보인다 와 같은 방식 — 템플릿에 True 를
    박아 넣어도 통과하지 않게, 뷰 함수를 직접 부른다.)
    """
    import flask_login
    from webapp.routes.mobile import home as home_view
    monkeypatch.setattr(flask_login, 'current_user',
                        SimpleNamespace(is_admin=is_admin))
    with flask_app.test_request_context('/mobile/'):
        return home_view()


def test_홈_크롤줄은_admin_에게만_있다(flask_app, monkeypatch):
    """member 는 /mobile/crawl/* 이 403(blueprint 게이트, Task 2) — 줄을 그리면
    매번 「불러오지 못했습니다」만 뜨는, 고칠 수도 없는 오류 줄이 된다.
    그래서 서버에서 아예 안 그린다(빈 자리도 안 남는다). 하단 탭의 크롤 칸도
    같은 판정으로 member 에겐 안 실린다(test_크롤_탭은_admin_에게만_보인다) — 홈과
    탭이 같은 방향이어야 한 쪽만 보이는 어긋남이 안 생긴다."""
    admin_html = _home_as(flask_app, monkeypatch, True)
    a = attrs_of(admin_html, 'mh-crawl')
    assert a.get('href') == '/mobile/crawl/', '크롤 줄을 눌러도 크롤 탭으로 안 간다'
    # 기능만 맞고 안 보이는 부류(Task 3 실사고) — 줄이 실제로 카드 모양으로 뜨는지.
    assert 'flex' in a.get('style', ''), '크롤 줄에 모양이 없다 — 맨몸 글자로 뜬다'
    assert "'/mobile/crawl/api/status'" in admin_html, 'admin 홈이 크롤 상태를 안 물어본다'

    member_html = _home_as(flask_app, monkeypatch, False)
    assert attrs_of(member_html, 'recent-list'), \
        'member 홈이 통째로 안 뜬다 — 이 시험이 헛돈다'
    p = _TagById('mh-crawl')
    p.feed(member_html)
    assert p.attrs is None, 'member 에게 크롤 줄이 보인다 — 눌러도 403 인 줄이다'
    # 줄만 숨기고 fetch 가 남으면 member 폰이 30초마다 403 을 받는다 — 스크립트째 뺀다.
    assert '/mobile/crawl/api/status' not in member_html, \
        'member 홈이 크롤 상태를 물어본다 — 매번 403 이 돌아온다'


def test_홈_크롤줄도_인증_HTML을_JSON으로_파싱하지_않는다(client):
    """crawl.html 과 같은 함정(사유·실측은 test_인증_실패가_HTML로_와도_안_터진다 주석) —
    인증 실패는 403 HTML, 세션 만료는 로그인 200 HTML 로 온다. 같은 방식으로 못 박는다."""
    html = page_html(client, '/mobile/')
    low = html.lower()
    assert "headers.get('content-type')" in low, \
        '응답의 content-type 을 읽지 않는다 — 인증 HTML 을 JSON 으로 파싱하다 터진다'
    assert low.index("headers.get('content-type')") < low.index('.json()'), \
        'content-type 을 보기 전에 .json() 을 먼저 부른다'
    assert "if (!ct.includes('application/json'))" in html, \
        'content-type 갈래가 사라졌다 — 세션 만료 HTML 이 파싱 에러로 터진다'
    # 홈의 JSON 풀기는 askServer 한 곳뿐 — loadRecent(최근 활동)도 이 길을 지난다.
    assert low.count('.json()') == 1, \
        'JSON 을 푸는 곳이 여러 곳이다 — askServer 를 거치지 않는 길이 생겼다'
    assert low.rindex('throw e') < low.index('.json()'), \
        'JSON 이 아닐 때 되돌려보내기 전에 이미 파싱한다'


def test_홈_크롤줄이_읽는_칸이_서버_응답에_다_있다(client):
    """홈이 손으로 적은 `cs.<이름>` 을 서버 응답과 묶는다.

    crawl.html 형제 시험(test_화면이_읽는_칸_이름이_서버_응답에_다_있다)과 같은 이유·
    같은 한계(읽기를 지우는 변경은 못 잡는다). 홈은 바퀴 수(laps_today)를 안 그리므로
    stats_ok=false → '-' 처리는 여기 없다 — 그건 크롤 탭(crawl.html)의 일이다."""
    html = page_html(client, '/mobile/')
    payload = client.get('/mobile/crawl/api/status').get_json()
    used = set(re.findall(r'\bcs\.([a-z_]+)(?:\.([a-z_]+))?', html))
    assert used, '홈에서 cs.<이름> 을 하나도 못 찾았다 — 이 시험이 헛돈다'
    for top, sub in sorted(used):
        assert top in payload, f"홈은 cs.{top} 을 읽는데 서버 응답엔 '{top}' 칸이 없다"
        if sub:
            assert isinstance(payload[top], dict) and sub in payload[top], \
                f"홈은 cs.{top}.{sub} 를 읽는데 서버 {top} 안에 '{sub}' 칸이 없다"
    # ISO 시각 문자열 금지 — 시간대가 없어 폰에서 9시간 어긋난다(크롤 탭과 같은 규칙).
    assert 'last_lap_today_at' not in html, '시간대 없는 문자열을 화면이 직접 쓴다'


def test_홈_최근본화면은_비면_통째로_숨는다(client):
    """빈 목록인데 「최근 본 화면」 제목만 뜨면 빈 칸이 남는다 — 통째로 숨긴다."""
    html = page_html(client, '/mobile/')
    wrap = attrs_of(html, 'mh-recent-wrap')
    assert re.search(r'display\s*:\s*none', wrap.get('style', '')), \
        '비어 있을 때도 「최근 본 화면」 제목이 뜬다 — 빈 칸이 남는다'
    assert attrs_of(html, 'mh-recent-pages')
    assert "localStorage.getItem('ms-recent')" in html, \
        '최근 본 화면을 폰(localStorage)에서 안 읽는다'
    # 채워졌을 때 되살리는 줄 — 없으면 기본 숨김이라 영영 안 보이는 죽은 기능이 된다.
    assert "wrap.style.display = ''" in html, '항목이 있어도 안 보인다 — 되살리는 줄이 없다'
    # 폰 저장값은 검증 없이 링크로 만들지 않는다 — 상대주소(/)만 허용.
    assert "charAt(0) !== '/'" in html, '저장값 검증이 없다 — 밖으로 나가는 링크가 생긴다'


def test_홈_폴링은_보일_때만_돈다(flask_app, monkeypatch, client):
    """🔴 crawl.html 이 **일부러 버린** 상시 반복(화면이 안 보여도 서버·DB 를 침)으로
    홈이 되돌아가지 않게 못 박는다 — 크롤 줄·최근 활동 폴링 둘 다 같은 관례를 쓴다.

    ★ Task 3 이 밟은 함정 회피 — 낱말 검사가 아니라 **부르는 것**을 본다:
      (1) 반복 예약 함수 호출 `setInterval(` 이 화면에 0곳(주석엔 그 낱말을 안 적었고,
          홈·_base 에 다른 정당한 사용처가 없음을 이 시험이 전제로 못 박는다),
      (2) 원하는 모양('끝난 뒤 재예약'·보일 때만·복귀 시 즉시)을 줄 통째로 같이 박아
          의도를 분명히 한다(crawl.html 형제 시험과 같은 방식)."""
    html = page_html(client, '/mobile/')
    assert 'setInterval(' not in html, \
        '상시 반복으로 되돌아갔다 — 화면이 안 보여도 서버·DB 를 계속 친다'
    assert 'setTimeout(tick' in html, "'끝난 뒤에 다시 예약' 방식이 사라졌다"
    assert "if (document.visibilityState === 'visible') await refreshAll();" in html, \
        '화면이 안 보여도 계속 서버를 친다'
    assert 'visibilitychange' in html, '다시 켰을 때 오래된 화면이 그대로 남는다'
    # 앱 전환 연타 상한 — 연타는 주기가 아니라 visibilitychange 빈도에서 온다
    # (앱 전환·알림창·잠금해제마다 발생). 기록하는 쪽이 없으면 상한이 죽은 장치다.
    assert 'Date.now() - lastLoadAt < 3000' in html, '앱 전환 연타에 상한이 없다'
    assert 'lastLoadAt = Date.now();' in html, \
        '나간 시각을 기록하지 않는다 — 3초 상한이 죽은 장치가 된다'
    # 크롤 줄이 주기 목록에 실제로 들어가는지 — 안 들어가면 첫 1회만 그리고 영영 낡는다.
    assert 'pollFns.push(loadCrawlLine);' in html, \
        '크롤 줄이 주기 갱신 목록에 없다 — 첫 화면 이후 영영 안 새로고침된다'

    # member 홈도 같은 관례여야 한다(최근 활동 폴링) — admin 전용 블록이 아니라
    # 공용 블록에 있는지, member 렌더에서도 확인한다.
    member_html = _home_as(flask_app, monkeypatch, False)
    assert 'setInterval(' not in member_html
    assert 'setTimeout(tick' in member_html


def test_최근본화면_키는_쓰는쪽과_읽는쪽이_같다():
    """🔴 키 이름 'ms-recent' 가 **두 파일**에 산다 — 쓰기=mobile_shell.js·읽기=home.html.

    한쪽만 바꾸면 에러 없이 목록이 영영 빈다(조용한 실패). 그래서 글자 그대로 묶는다."""
    reads = set(re.findall(r"localStorage\.getItem\('([^']+)'\)", home_tpl_src()))
    writes = set(re.findall(r"localStorage\.setItem\('([^']+)'", shell_js_src()))
    assert reads, '홈이 localStorage 를 안 읽는다 — 이 시험이 헛돈다'
    assert writes, 'mobile_shell.js 가 localStorage 에 안 쓴다 — 기록이 없다'
    assert reads == writes, \
        f'저장 키가 어긋난다: 읽기={sorted(reads)} 쓰기={sorted(writes)} — 목록이 영영 빈다'


def test_최근본화면은_폰에만_기록하고_서버로_안_보낸다():
    """어느 화면을 봤는지는 서버로 보내지 않는다 — 그 주장을 원문에서 검증한다.

    기록은 mount() 안에서만 = PC 대체 화면에서만. 폰 전용 화면(홈·스캔·재고)은
    하단 탭 한 번이면 가니, 기록하면 5칸이 늘 그 화면들로 차서 정작 다시 찾기 어려운
    PC 화면이 밀려난다."""
    src = shell_js_src()
    assert 'function rememberPage()' in src, '기록 함수가 없다'
    mount_body = src.split('function mount()')[1].split('function start()')[0]
    assert 'rememberPage();' in mount_body, 'mount() 가 기록을 안 부른다 — 죽은 함수다'
    assert '.slice(0, 5)' in src, '상한이 없다 — 목록이 한없이 자란다'
    assert 'it.url !== url' in src, '같은 화면이 여러 줄로 쌓인다'
    # '폰에만 저장한다'는 주장 — 이 파일은 서버로 아무것도 안 보낸다.
    assert 'fetch(' not in src and 'XMLHttpRequest' not in src, \
        '껍데기 JS 가 서버로 보낸다 — 어느 화면을 봤는지는 폰 밖으로 안 나간다'
