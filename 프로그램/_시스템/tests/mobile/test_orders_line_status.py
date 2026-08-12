# -*- coding: utf-8 -*-
"""폰 주문 화면의 「주문 관리」 상태 — PC 와 **같은 저장소·같은 엔드포인트**인지 못 박는다.

무엇을 지키나
 ① 🔴 새 엔드포인트 발명 금지 — 폰이 부르는 주소가 PC 가 쓰는 그 라우트여야 한다.
    (폰 전용 API 를 만들면 항목·기본값·저장 규칙이 두 벌이 되어 반드시 갈라진다.)
 ② 🔴 열쇠는 `_line_uid` — 주문번호(`오픈마켓주문번호`)로 저장하면 다품목 주문의
    형제 줄까지 같이 바뀐다.
 ③ 🔴 기본 항목은 **표시만** — `is_fallback` 을 그려 「아직 안 봄」을 구분해야 한다.
 ④ 항목 만들기·고치기·지우기는 폰에 없다(PC 전용) — 폰이 그 라우트를 부르면 안 된다.
 ⑤ 조회 실패 시 옛 상태를 남기지 않는다(`ostMap={}` 로 비운다).
"""
import re
from pathlib import Path

_SYS = Path(__file__).resolve().parents[2]
_MOB = _SYS / 'webapp' / 'templates' / 'mobile' / 'orders.html'
_ROUTES = _SYS / 'webapp' / 'routes' / 'orders.py'


def _src() -> str:
    return _MOB.read_text(encoding='utf-8')


def _routes() -> str:
    return _ROUTES.read_text(encoding='utf-8')


# ── ① 새 엔드포인트 발명 금지 ─────────────────────────────────────────

def test_상태_조회는_PC_와_같은_resolve_라우트다():
    src = _src()
    assert "'/orders/api/line-status/resolve'" in src, \
        '폰이 상태를 PC 와 다른 곳에서 읽으면 항목·기본값이 갈라진다'
    assert "@bp.post('/api/line-status/resolve')" in _routes()


def test_상태_저장은_PC_와_같은_라우트다():
    src = _src()
    assert "'/orders/api/line-status'" in src
    assert "@bp.post('/api/line-status')" in _routes()


def test_폰_전용_상태_API_를_만들지_않았다():
    src = _src()
    바른주소 = {'/orders/api/line-status', '/orders/api/line-status/resolve'}
    쓴주소 = set(re.findall(r"'(/[\w\-./]*line-status[\w\-./]*)'", src))
    assert 쓴주소 <= 바른주소, f'폰 전용 상태 주소가 생겼다: {쓴주소 - 바른주소}'


# ── ② 열쇠는 line_uid ────────────────────────────────────────────────

def test_열쇠는_line_uid_다():
    src = _src()
    m = re.search(r'function ostUid\(r\)\{[^}]*\}', src)
    assert m, 'ostUid() 가 사라졌다 — 상태 배선이 없어졌다'
    assert "_line_uid" in m.group(0)
    assert '오픈마켓주문번호' not in m.group(0), \
        '주문번호를 열쇠로 쓰면 다품목 주문의 형제 줄까지 같이 바뀐다'


def test_저장이_line_uid_를_보낸다():
    assert re.search(r'line_uid:\s*uid', _src()), \
        '저장 payload 가 line_uid 를 안 보내면 서버가 400 을 낸다'


# ── ③ 기본 항목은 표시만 ─────────────────────────────────────────────

def test_기본_항목은_점선으로_구분해_그린다():
    src = _src()
    assert 'is_fallback' in src, '기본 항목을 저장된 값처럼 그리면 「이미 봤다」는 거짓이 된다'
    assert '.mo-ost.fb{' in src and 'border-style:dashed' in src


def test_기본_표시된_줄은_고르기_시트에서_선택으로_안_보인다():
    """`is_fallback` 인 줄은 아직 고른 게 아니다 — 시트에서 체크로 보이면 안 된다."""
    src = _src()
    m = re.search(r'var cur=\(ostMap\[uid\][^;]*;', src)
    assert m and '!ostMap[uid].is_fallback' in m.group(0)


# ── ④ 항목 관리(만들기·고치기·지우기)는 PC 전용 ─────────────────────

def test_폰은_항목을_만들거나_지우지_않는다():
    """항목 관리 라우트(`/api/status-options*`)를 폰이 부르면 안 된다.

    작은 화면에서 실수로 항목을 지우면 **팀 전체 주문의 상태가 한꺼번에 날아간다**
    (`delete_option(force=True)` 가 딸린 줄을 지운다). 그래서 폰은 고르기 전용이다.
    """
    src = _src()
    assert 'status-options' not in src, '폰에 항목 관리(만들기·고치기·지우기)가 생겼다'
    assert "'DELETE'" not in src and "'PATCH'" not in src


def test_항목이_없으면_어디서_만드는지_말한다():
    """고르라고만 하고 만들 길을 안 알려주면 막다른 길이 된다."""
    src = _src()
    assert '아직 만든 상태 항목이 없어요' in src
    assert '항목 관리' in src and 'PC' in src


# ── ⑤ 실패하면 비운다 ────────────────────────────────────────────────

def test_조회_실패면_옛_상태를_지운다():
    src = _src()
    m = re.search(r'function loadLineStatus\(seq\)\{.*?\n  \}', src, re.S)
    assert m, 'loadLineStatus() 가 사라졌다'
    body = m.group(0)
    assert 'ostMap={}' in body, \
        '실패했는데 옛 상태를 그대로 두면 사장님이 이미 처리한 줄로 믿는다'
    assert 'ostOpts=[]' in body


def test_알약이_목록_줄에_실제로_그려진다():
    assert 'ostCell(r)+meta' in _src(), '함수만 있고 줄에 안 붙으면 화면엔 아무것도 없다'


def test_알약_탭이_줄_펼침을_가로채고_시트를_연다():
    src = _src()
    assert "closest('[data-ost]')" in src and 'ostSheetOpen(' in src
