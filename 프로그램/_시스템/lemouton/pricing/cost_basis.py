# -*- coding: utf-8 -*-
"""옵션별 원가 기준 선택 — 소싱 vs 사입.

【사장님 확정 규칙 · 2026-07-20】
  옵션 하나하나마다:
    (1) 그 옵션에 **사입한 상품이 있으면** → 사입 매입가 기준으로 마진 계산·판매가 설정
    (2) 사입한 상품이 없으면        → 100% 소싱처 크롤 최종매입가 기준
    (3) 단, 소싱처 최종매입가가 사입 매입가보다 **낮으면** → 소싱처 최종매입가 기준
  ⇒ 둘 다 있으면 **낮은 쪽**. 그리고 마진 설정(side)은 **고른 원가를 따라간다**
     ("○○ 기준으로 마진 계산" = 그 쪽 정책 세트를 쓴다는 뜻).

【"사입한 상품이 있다" 의 판정 — 여기가 사고 지점이라 못 박는다】
  · 재고가 실제로 있어야 한다 (InventoryTx 합산 SSOT).
  · 매입가는 **그 옵션의 실측 이동평균**(Option.boxhero_avg_purchase_price)이어야 한다.
  · PriceTemplate.boxhero_purchase_price(사람이 손으로 적은 한 숫자)는 **후보가 아니다**.
    그 값은 전 옵션에 똑같이 깔리므로, 후보로 넣으면 "사입한 적 없는 옵션"까지
    그 값으로 원가가 깎여 판매가가 통째로 떨어진다.
    (라이브 실측 2026-07-19: 템플릿 95,000 vs 실제 소싱 107,700~113,500)

이 모듈은 화면(api_pricing) · 미리보기(uploader.preview) · 실업로드(uploader.reconcile)
세 경로가 **모두 여기만** 부르게 해서 "화면값 ≠ 업로드값" 을 구조적으로 막는다.
"""
from typing import NamedTuple, Optional


class CostBasis(NamedTuple):
    cost: Optional[int]     # 판매가 계산에 쓸 원가. None = 원가를 모름 → 판매 막아야 함
    side: Optional[str]     # 'sourcing' | 'purchase' — 마진 정책도 이걸 따라간다
    sourcing_cost: Optional[int]
    purchase_cost: Optional[int]   # 후보로 인정된 사입 매입가(없으면 None)
    reason: str


def has_purchased_stock(purchase_stock, purchase_avg) -> bool:
    """'그 옵션에 사입한 상품이 있다' 판정. 재고와 실측 매입가가 **둘 다** 있어야 한다."""
    try:
        stock_ok = int(purchase_stock or 0) >= 1
    except (TypeError, ValueError):
        stock_ok = False
    try:
        avg_ok = int(purchase_avg or 0) > 0
    except (TypeError, ValueError):
        avg_ok = False
    return stock_ok and avg_ok


def resolve_cost_basis(sourcing_cost, purchase_avg, purchase_stock) -> CostBasis:
    """옵션 하나의 원가·마진정책 기준을 정한다.

    Args:
        sourcing_cost: 소싱처 최종매입가(혜택 차감 후). 못 구했으면 None.
        purchase_avg:  그 옵션의 실측 사입 매입가(이동평균). 템플릿 값을 넣지 말 것.
        purchase_stock: 그 옵션의 사입 재고 수량(InventoryTx 합산).

    Returns:
        CostBasis(cost, side, ...) — cost 가 None 이면 원가 불명(판매 막아야 함).
    """
    try:
        s = int(sourcing_cost) if sourcing_cost and int(sourcing_cost) > 0 else None
    except (TypeError, ValueError):
        s = None
    p = int(purchase_avg) if has_purchased_stock(purchase_stock, purchase_avg) else None

    if s is None and p is None:
        return CostBasis(None, None, None, None, '원가 없음 — 소싱 크롤가도 사입 이력도 없어요.')
    if p is None:
        return CostBasis(s, 'sourcing', s, None, '사입한 상품이 없어 소싱처 최종매입가로 계산해요.')
    if s is None:
        return CostBasis(p, 'purchase', None, p, '소싱 크롤가가 없어 사입 매입가로 계산해요.')
    if s < p:
        return CostBasis(s, 'sourcing', s, p,
                         f'소싱처가 더 싸요 ({s:,}원 < 사입 {p:,}원) — 소싱처 기준으로 계산해요.')
    return CostBasis(p, 'purchase', s, p,
                     f'사입한 상품이 있어요 (사입 {p:,}원 ≤ 소싱 {s:,}원) — 사입 기준으로 계산해요.')
