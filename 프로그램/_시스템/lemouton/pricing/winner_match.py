"""쿠팡 위너매치 우선순위 처리.

사용자 결정 (spec §5.4):
- 1b: 옵션 고정가 + WM → WM 우선
- 2b: 사입품 + WM → WM 우선
- 3c: 외부 소싱 + WM → MAX(공식가, WM)
- 4: 재고 0 → 품절 (WM 무시)
"""
from dataclasses import dataclass


@dataclass
class WinnerMatchResult:
    price: int
    reason: str


def apply_winner_match(
    *,
    primary_price: int,
    primary_reason: str,
    winner_price: int,
    competitor_status: str | None,
) -> WinnerMatchResult:
    if competitor_status != "winner_match":
        return WinnerMatchResult(price=primary_price, reason=primary_reason)

    if primary_reason == "out_of_stock":
        return WinnerMatchResult(price=0, reason="out_of_stock")

    if primary_reason in ("external_fixed", "external_formula"):
        if primary_price > winner_price:
            return WinnerMatchResult(price=primary_price, reason=primary_reason)
        return WinnerMatchResult(price=winner_price, reason="winner_match")

    return WinnerMatchResult(price=winner_price, reason="winner_match")
