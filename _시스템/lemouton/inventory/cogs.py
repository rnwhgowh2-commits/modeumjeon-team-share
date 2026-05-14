"""[I] cogs.py — 이동평균 매입가 + 매출 snapshot + 마진 계산.

ADR-002 (이동평균 + 출고 시점 매입가 snapshot) 핵심 구현.

핵심 함수 4종:
  - update_moving_avg(option, qty_in, price_in) → int  (입고 시 이동평균 갱신)
  - snapshot_at_outbound(option) → int                  (출고 시점 평균 매입가 박제)
  - compute_margin(unit_purchase_at_tx, unit_sale, qty) → dict  (매출·이익·마진율)
  - recalc_stock_total(option_sku, session) → int       (Tx history 기반 위치별 재고 합산)

ai-workflow STEP 7 Sprint 1A Task 1.1
"""
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from lemouton.sourcing.models import Option
from lemouton.inventory.models import InventoryTx


def _now():
    return datetime.now(timezone.utc)


def update_moving_avg(option: Option, qty_in: int, price_in: int) -> int:
    """입고 시 이동평균 매입가 갱신 (ADR-002).

    new_avg = (old_avg × old_qty + price_in × qty_in) / (old_qty + qty_in)

    재고 0 → 재입고: 새 매입가가 곧바로 평균 (분기 로직 ❌, 0×0+price×qty / qty 자연스러움).

    Args:
        option: SQLAlchemy Option 인스턴스 (수정 대상).
        qty_in: 입고 수량 (양수).
        price_in: 입고 단가.

    Returns:
        new_avg: 갱신된 이동평균.

    Side effects:
        option.boxhero_avg_purchase_price 갱신
        option.boxhero_avg_updated_at 갱신
        option.boxhero_stock_total += qty_in
    """
    if qty_in <= 0:
        raise ValueError(f"qty_in must be positive, got {qty_in}")

    old_avg = option.boxhero_avg_purchase_price or 0
    old_qty = option.boxhero_stock_total or 0
    new_total = old_qty + qty_in

    if new_total == 0:
        # 가능성 ❌ (qty_in > 0이라), 안전 장치
        return old_avg

    new_avg = round((old_avg * old_qty + price_in * qty_in) / new_total)
    option.boxhero_avg_purchase_price = new_avg
    option.boxhero_avg_updated_at = _now()
    option.boxhero_stock_total = new_total
    return new_avg


def snapshot_at_outbound(option: Option) -> int:
    """출고 직전 평균 매입가를 박제 (ADR-002 매출 snapshot).

    Tx row의 unit_purchase_price_at_tx 에 저장될 값.
    출고 후 입고로 평균이 변해도 이 값은 영원히 변경 ❌.
    """
    return option.boxhero_avg_purchase_price or 0


def compute_margin(unit_purchase_at_tx: int | None, unit_sale: int | None, qty: int) -> dict:
    """매출·매출원가·이익·마진율 계산.

    Args:
        unit_purchase_at_tx: 출고 시점 박제된 평균 매입가 (Tx.unit_purchase_price_at_tx)
        unit_sale: 실제 판매가 (Tx.unit_sale_price)
        qty: 출고 수량

    Returns:
        {
            'revenue': 매출 (qty × unit_sale),
            'cogs': 매출원가 (qty × unit_purchase_at_tx),
            'profit': 매출이익 (revenue - cogs),
            'rate': 마진율 (profit / revenue, 소수점 4자리),
            'has_data': 매입가·판매가 둘 다 있을 때만 True
        }
    """
    pp = unit_purchase_at_tx or 0
    sp = unit_sale or 0
    has_data = pp > 0 and sp > 0
    revenue = qty * sp
    cogs = qty * pp
    profit = revenue - cogs
    rate = round(profit / revenue, 4) if revenue > 0 else 0.0
    return {
        'revenue': revenue,
        'cogs': cogs,
        'profit': profit,
        'rate': rate,
        'has_data': has_data,
    }


def recalc_stock_total(option_canonical_sku: str, session: Session) -> int:
    """옵션의 위치별 재고 합산을 Tx history 기반으로 재계산.

    무결성 검증·복구용. 정상 운영 시 update_moving_avg + Tx 발생 시 동기화되지만
    데이터 손상·import 후 검증에 사용.

    Args:
        option_canonical_sku: 모음전 옵션 PK.
        session: SQLAlchemy 세션.

    Returns:
        total: 모든 위치의 재고 합계.
        - 입고(in): +qty
        - 출고(out): -qty
        - 조정(adjust): 절대값으로 set (이전 합산 무관)
        - 이동(move): 0 (위치 간만 이동, 총합 영향 ❌)
    """
    txs = (
        session.query(InventoryTx)
        .filter(InventoryTx.option_canonical_sku == option_canonical_sku)
        .filter(InventoryTx.status == 'completed')
        .order_by(InventoryTx.created_at)
        .all()
    )

    total = 0
    for tx in txs:
        if tx.tx_type == 'in':
            total += tx.qty or 0
        elif tx.tx_type == 'out':
            total -= tx.qty or 0
        elif tx.tx_type == 'adjust':
            # 조정은 절대값 — 그 시점의 시스템 재고를 직접 set
            total = tx.qty or 0
        elif tx.tx_type == 'move':
            pass  # 위치 간 이동만, 총합 영향 ❌
    return total
