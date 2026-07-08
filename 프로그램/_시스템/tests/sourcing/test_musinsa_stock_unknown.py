"""[2026-07-08] 무신사 ⓪ 수집 성공 게이트 — 재고 API 전체 실패를 '충분(999)'으로 둔갑 금지.

무신사는 양의 재고 수량이 없어(outOfStock=false + remainQuantity 없음 = 충분 '추론') 재고
API(prioritized-inventories)가 통째로 비면 모든 옵션이 999(충분)로 둔갑 → 실제 품절도 팔림.
→ 재고 API 전체 실패 시 -1(_STOCK_UNKNOWN=확인불가). API 성공+신호없음일 때만 999.

순수 함수 _musinsa_option_stock(out_of_stock, remain_i, inv_read_ok) 를 직접 검증
(fetch() 는 회원가·인증 DB 의존이라 유닛 대상에서 제외).
"""
from lemouton.sourcing.crawlers.musinsa import _musinsa_option_stock, _STOCK_UNKNOWN


def test_inventory_api_empty_is_unknown_not_sufficient():
    """재고 API 전체 실패(inv_read_ok=False) + 신호 없음 → -1(확인불가). 999 둔갑 금지 = 오버셀 방지."""
    s = _musinsa_option_stock(out_of_stock=False, remain_i=None, inv_read_ok=False)
    assert s == _STOCK_UNKNOWN, f"재고 API 전체 실패는 확인불가(-1)여야 하는데 {s}"
    assert s != 999, "충분 둔갑 금지"


def test_present_no_remain_is_sufficient_999():
    """재고 API 성공(inv_read_ok=True) + remainQuantity 없음 → 999(충분). (정상 추론)"""
    assert _musinsa_option_stock(out_of_stock=False, remain_i=None, inv_read_ok=True) == 999


def test_out_of_stock_is_zero_regardless_of_api():
    """outOfStock=true → 0(품절). API 성공/실패 무관."""
    assert _musinsa_option_stock(out_of_stock=True, remain_i=None, inv_read_ok=True) == 0
    assert _musinsa_option_stock(out_of_stock=True, remain_i=None, inv_read_ok=False) == 0


def test_remain_qty_passthrough():
    """remainQuantity=N → N(한정). 음수는 0."""
    assert _musinsa_option_stock(out_of_stock=False, remain_i=3, inv_read_ok=True) == 3
    assert _musinsa_option_stock(out_of_stock=False, remain_i=0, inv_read_ok=True) == 0
    assert _musinsa_option_stock(out_of_stock=False, remain_i=-2, inv_read_ok=True) == 0
