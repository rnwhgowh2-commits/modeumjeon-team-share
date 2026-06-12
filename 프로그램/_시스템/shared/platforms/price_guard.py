"""마켓 송신 직전 가격 안전 게이트 (2026-06-13).

라이브 마켓(스마트스토어/쿠팡)에 PUT/POST 되기 직전, 0·음수·None·비정상 가격이
실제로 전송되는 것을 '마지막 단계'에서 차단한다(송신 abort).

배경: 쿠팡 송신부(shared/platforms/coupang/prices.py)엔 `price<=0 raise` 가드가
있었으나 스마트스토어 송신부(edit_product/create_product)엔 양수 가드가 전혀 없어,
상위 폴백(대표가·95000·정가대체 등)으로 0/비정상 가격이 생기면 그대로 네이버에
올라갈 수 있었다. 이 모듈이 전 마켓 공통 마지막 방어선이다.

주의: 이 게이트는 '명백히 위험한' 값(None/0/음수/비정수)만 막는다. '양수지만 틀린
폴백가'(예: 매입원가 95000 둔갑)는 상위에서 대체 자체를 금지해야 하며(정책
feedback_no_fallback_price_on_match_fail), 여기서는 catastrophic 만 차단한다.
"""
from __future__ import annotations


class UnsafePriceError(ValueError):
    """라이브 마켓에 보내면 안 되는 가격 — 송신 중단용 예외."""


def assert_live_sale_price(price, *, context: str = "") -> int:
    """라이브 마켓 PUT/POST 직전 판매가 검증. 위반 시 UnsafePriceError → 송신 abort.

    return: 검증 통과한 int 가격.
    """
    where = f" ({context})" if context else ""
    if price is None:
        raise UnsafePriceError(f"판매가가 None — 라이브 전송 차단{where}")
    try:
        p = int(price)
    except (TypeError, ValueError):
        raise UnsafePriceError(f"판매가가 정수가 아님: {price!r} — 라이브 전송 차단{where}")
    if p <= 0:
        raise UnsafePriceError(
            f"판매가는 양의 정수여야 함 (입력: {p}) — 0/음수 라이브 전송 차단{where}")
    return p
