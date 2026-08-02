# -*- coding: utf-8 -*-
"""재고 판정 = 화면과 전송이 **같은 한 곳**을 본다 + 「보내도 되나」 판정.

옮긴 이유 — 라우트 안에 있으면 화면 밖(마켓 전송)에서 자기 판정을 새로 만들게 되고,
그 순간 화면은 「품절」인데 전송은 「있음」으로 나가는 모순이 생긴다.
(이 저장소가 반복해서 겪은 원천 분열의 형태 그대로다.)
"""
from lemouton.sourcing import stock_resolve as SR


# ── 옮겨도 답이 그대로인가 (원천이 하나인가) ────────────────────────────

def test_라우트가_쓰는_함수와_같은_물건이다():
    """`api_pricing._resolve_stock` 이 공용 모듈을 그대로 가리켜야 한다.

    다른 물건이면 두 벌이 갈릴 수 있다 — 그게 바로 옮긴 이유다.
    """
    from webapp.routes import api_pricing as AP
    assert AP._resolve_stock is SR.resolve_stock
    assert AP._stock_state is SR.stock_state
    assert AP._STOCK_CAP == SR.STOCK_CAP
    assert AP._STOCK_UNKNOWN == SR.STOCK_UNKNOWN


# ── 보내도 되나 ─────────────────────────────────────────────────────────

def test_품절0은_보낸다():
    """0 은 확인된 값이다 — 품절도 정확한 정보다. 안 보내면 마켓에 옛 재고가 남는다."""
    ok, qty, why = SR.sendable('musinsa', 0)
    assert ok is True and qty == 0 and why == ''


def test_실수량은_그대로_보낸다():
    ok, qty, _ = SR.sendable('ssg', 7)
    assert ok is True and qty == 7


def test_재고있음은_보내되_수량은_미상이다():
    """999·무신사 CAP 은 「충분」 센티넬이라 실수량이 아니다 — 수량은 호출자가 정한다."""
    ok, qty, _ = SR.sendable('ssg', 999)
    assert ok is True and qty is None
    ok2, qty2, _ = SR.sendable('musinsa', 10)
    assert ok2 is True and qty2 is None


def test_확인불가는_막는다():
    """🔴 -1 = 크롤은 됐는데 신호를 못 읽음. 있다고 단정하면 오버셀이다."""
    ok, qty, why = SR.sendable('musinsa', -1)
    assert ok is False and qty is None
    assert '확인' in why


def test_롯데온_옵션999는_막는다():
    """롯데온 옵션 999 = 품절 사이즈에 꽂히는 「대체상품」 센티넬 — 실재고가 아니다."""
    ok, _, why = SR.sendable('lotteon', 999)
    assert ok is False, '대체상품 센티넬을 재고로 읽었다'
    assert '확인' in why


def test_미크롤과_크롤실패와_미수집은_전부_막는다():
    for status in (None, 'error', 'uncollected'):
        ok, _, why = SR.sendable('ssg', None, status)
        assert ok is False, status
        assert why


def test_소싱처가_안_파는_조합은_품절로_보낸다():
    """(다) not_sold = 목록에 그 색×사이즈가 아예 없음 → 품절. 오버셀 방향이 아니다."""
    ok, qty, _ = SR.sendable('ssg', None, 'not_sold')
    assert ok is True and qty == 0


def test_크롤성공_수량미상은_보낸다():
    ok, qty, _ = SR.sendable('ssg', None, 'ok')
    assert ok is True and qty is None


def test_막는_사유는_사람이_읽을_수_있다():
    """부류만 주면 사장님이 손을 못 쓴다 — 무슨 상태인지 말해야 한다."""
    _, _, why = SR.sendable('musinsa', -1)
    assert '⚠️확인필요' in why or '확인' in why
