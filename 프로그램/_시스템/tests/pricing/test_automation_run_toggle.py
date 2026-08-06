# -*- coding: utf-8 -*-
"""[2026-08-06 사장님 신고] 「실행」을 눌러도 크롤이 안 돈다 — 화면이 거짓말한 자리.

라이브 실측
    사장님 화면엔 「실행」이 켜져 보이는데 서버는 `crawl_auto_enabled=false` 였다
    (`/api/crawl/due-bundles` → `enabled:false, count:0`). `/api/automation/save` 로
    true 를 보내니 곧바로 `enabled:true, count:1` — **저장 경로·크롤 스케줄은 멀쩡**했고
    화면 상태만 서버와 어긋나 있었다.

진범
    `st.crawl_auto_enabled` 은 **페이지 로드 때 `R.dataset.crawlOn` 한 번**으로만 채워진다.
    딴 탭·폰 리모컨·딴 세션이 서버 값을 바꾸면 이 화면만 옛값으로 굳는다. 그 상태에서
    옛 토글 핸들러의 `if(run===st.crawl_auto_enabled) return;` 가 저장을 **아예 안 내보냈다** —
    눌러도 아무 일이 없던 정확한 이유.

여기서 못 박는 것 (셋 다 없으면 같은 사고가 그대로 재발한다)
    ① 이미 도는 폴링(pollLap → /api/crawl/queue)이 서버 enabled 로 화면을 다시 칠한다.
       ★폴링을 새로 만들지 않는다(중복 폴링 = 라이브 마비 전력, api.py:36 참조).
    ② early-return 제거 — 어긋났을 때 사용자가 눌러서 빠져나올 수 있어야 한다.
    ③ 저장 실패를 조용히 삼키지 않는다(옛 코드는 `.catch(function(){})`).

🔴 낱말 grep 이 아니라 **판정 줄을 통째로** 못 박는다 — 이 저장소가 여러 번 당한 함정.
"""
from pathlib import Path

import pytest

TPL = (Path(__file__).resolve().parents[2]
       / 'webapp' / 'templates' / 'automation' / 'index.html')


@pytest.fixture(scope='module')
def html() -> str:
    return TPL.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def lines(html) -> list[str]:
    return [ln.strip() for ln in html.splitlines()]


# ── ① 서버 진실로 다시 칠하기 ────────────────────────────────────────────

def test_폴링이_서버_enabled_를_화면에_되먹인다(lines):
    """`/api/crawl/queue` 응답에 실려 오는 enabled 를 실제로 읽어 쓰는가."""
    assert 'applyServerRun(d, _gen);' in lines, \
        '폴링 응답을 실행/정지 판정에 안 넘긴다 — 화면이 또 옛값으로 굳는다'
    assert 'var _gen=_crawlGen;' in lines, '응답 세대를 안 기록하면 옛 응답을 못 가려낸다'


def test_다르면_다시_칠한다(lines):
    """서버 값이 화면과 다를 때 st 를 갈아끼우고 두 그림 함수를 다시 부른다."""
    assert 'if(d.enabled===st.crawl_auto_enabled) return;' in lines
    assert 'st.crawl_auto_enabled=d.enabled; paintSeg(); paintRun();' in lines


def test_낙관적_표시를_옛_응답이_되돌리지_못한다(lines):
    """방금 누른 표시가 「저장 직전 값」을 든 폴링 응답에 뒤집히면 안 된다.

    ① 내 저장이 도는 중이면 무시 ② 응답이 나간 뒤 또 눌렀으면 그 응답은 버린다.
    """
    assert 'if(_crawlSaving>0 || gen!==_crawlGen) return;' in lines


def test_폴링을_새로_만들지_않았다(html):
    """중복 폴링 금지 — 잦은 폴링이 라이브를 마비시킨 전력이 있다(api.py:36)."""
    assert html.count("fetch('/api/crawl/queue')") == 1, '큐 폴링이 두 곳이 됐다'
    assert html.count('setInterval(') == 3, \
        'setInterval 이 늘었다 — 기존 폴링에 얹으라는 규약을 어겼다'


# ── ② early-return 제거 ─────────────────────────────────────────────────

def _code_lines(lines: list[str]) -> list[str]:
    """주석 줄은 뺀다 — 「옛 코드가 이랬다」는 기록까지 금지하면 이유를 못 적는다."""
    return [ln for ln in lines if not ln.startswith('//') and not ln.startswith('{#')]


def test_같은_값이어도_저장을_보낸다(lines):
    """화면과 서버가 어긋났을 때 사용자가 눌러서 탈출할 수 있어야 한다."""
    assert 'if(run===st.crawl_auto_enabled) return;' not in '\n'.join(_code_lines(lines)), \
        '되살아난 early-return — 어긋난 상태에서 눌러도 저장이 안 나간다(사장님 신고 그대로)'
    assert ("document.querySelectorAll('#crawl-seg button').forEach(function(b){ "
            "b.addEventListener('click',function(){ setRun(this.dataset.run==='1'); }); });") in lines, \
        '토글 핸들러가 setRun 을 그대로 부르지 않는다(중간에 관문이 끼면 또 막힌다)'
    assert 'save({crawl_auto_enabled:run}).then(function(){ _crawlSaving--; });' in lines, \
        '누른 값이 무조건 저장으로 나가야 한다(멱등)'


# ── ③ 저장 실패를 알린다 ────────────────────────────────────────────────

def test_저장_실패를_조용히_삼키지_않는다(html):
    assert '.catch(function(){});' not in _save_line(html), \
        '빈 catch 로 실패를 먹고 있다 — 화면만 바뀐 척한다'


def test_실패하면_기존_토스트를_빨갛게_돌려_쓴다(html, lines):
    line = _save_line(html)
    assert "toastFail((d&&d.error)||'저장 실패'); return false;" in line, '서버가 ok 를 안 줬을 때'
    assert "catch(function(){ toastFail('서버에 닿지 못했어요'); return false; });" in line, '서버에 못 닿았을 때'
    # 새 부품을 발명하지 않았는지 — 성공 토스트와 같은 #saved 를 쓴다.
    assert any(ln.startswith('function toastFail(msg){ savedEl.') for ln in lines), \
        '실패 알림이 기존 토스트(#saved) 부품을 안 쓴다'
    assert '.au-saved.err{color: var(--글자-빨강, var(--red,#c0343f));font-weight:700;}' in lines, \
        '예비값 없는 토큰은 규칙째로 죽는다 — var(--토큰,#원래색) 형태를 지킨다'


def _save_line(html: str) -> str:
    """`save(patch)` 한 줄만 떼어 낸다(다른 곳의 빈 catch 는 이 검사 대상이 아니다)."""
    for ln in html.splitlines():
        if ln.strip().startswith('function save(patch)'):
            return ln
    raise AssertionError('save(patch) 를 못 찾았다 — 이름이 바뀌었으면 이 검사도 같이 고칠 것')


# ── 서버 쪽 계약 ────────────────────────────────────────────────────────

def test_큐_응답이_enabled_를_들고_온다():
    """위 배선의 전제 — `/api/crawl/queue` 페이로드에 enabled 가 실려 있다.

    (값별 동작은 tests/sources/test_crawl_queue_payload.py 가 본다. 여기선 키 존재만.)
    """
    import inspect

    from lemouton.sources import crawl_schedule
    src = inspect.getsource(crawl_schedule.due_crawl_payload)
    assert '"enabled": False' in src and '"enabled": True' in src


# ── 진행 문구 — 실행 중인데 「실행을 켜면」이라 말하지 않는다 ────────────────

def test_실행_중_문구는_켜라고_말하지_않는다(html):
    """[2026-08-06 라이브 실측] 오늘 18바퀴·19번째 진행 중인 화면에서
    「대기 중… 「실행」을 켜면 지금 긁는 소싱처가 여기 흘러요」가 떠 있었다.

    이 갈래는 「지금 이 순간 긁는 창이 없다」는 뜻일 뿐인데(다음 대상으로 넘어가는 사이)
    문구가 「정지 상태」를 말해 이미 켠 사람에게 켜라고 시켰다. 켜짐/꺼짐은 실행 단추의
    실제 표시(paintSeg 가 서버 진실로 칠한다)에서 읽어 두 갈래로 갈라야 한다.
    """
    # 갈림 자체 — 단추 표시에서 켜짐을 읽는다(함수 밖 변수에 기대지 않는다).
    assert "var autoOn=!!document.querySelector('#crawl-seg .run.on');" in html, \
        '실행 여부를 단추 표시에서 읽는 배선이 없다 — 켜짐/꺼짐 문구가 갈리지 않는다'
    assert "? '실행 중 — 다음 소싱처를 기다리는 중이에요'" in html, \
        '실행 중일 때의 문구가 없다(「실행을 켜면」이 그대로 남으면 거짓 화면)'
    assert ": '정지 중… 「실행」을 켜면 지금 긁는 소싱처가 여기 흘러요';" in html, \
        '정지 중일 때의 문구가 없다'
    # 옛 무조건 문구가 JS 에 남아 있으면 안 된다(첫 렌더는 Jinja 갈래가 담당).
    assert "feed.textContent='대기 중… 「실행」을 켜면" not in html, \
        '무조건 「대기 중…」으로 덮는 옛 코드가 남아 있다'


def test_첫_렌더_문구도_서버값으로_갈린다(html):
    """paintRun 이 곧 덮더라도 첫 프레임에 「실행을 켜면」이 보이면 그 순간은 거짓이다."""
    assert '{% if a.crawl_auto_enabled %}실행 중 — 다음 소싱처를 기다리는 중이에요' in html, \
        '첫 렌더 문구가 서버값(a.crawl_auto_enabled)으로 갈리지 않는다'
