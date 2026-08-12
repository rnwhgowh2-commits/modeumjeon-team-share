"""[I] 입고/출고/조정/이동 통합 거래 서비스.

LIGHT_SPEC §4 + cogs.py 활용. 4 거래 동일 패턴.

ai-workflow STEP 7 Sprint 2 Task 2.1~2.4
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from lemouton.sourcing.models import Option
from lemouton.inventory.models import InventoryTx
from lemouton.inventory.cogs import update_moving_avg, snapshot_at_outbound


def _now():
    return datetime.now(timezone.utc)


def list_txs(session: Session, tx_type: str, page: int = 1, page_size: int = 50) -> tuple[list, int]:
    q = (
        session.query(InventoryTx)
        .filter(InventoryTx.tx_type == tx_type)
        .filter(InventoryTx.status == 'completed')
        .order_by(InventoryTx.created_at.desc())
    )
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def create_inbound(session: Session, location_id: int, option_canonical_sku: str,
                    qty: int, unit_purchase_price: int = 0,
                    partner_label: str = '', memo: str = '',
                    created_by: str = '') -> InventoryTx:
    """입고 — 재고 + 평균매입가 갱신 (이동평균법, ADR-002)."""
    if qty <= 0:
        raise ValueError("입고 수량은 양수여야 합니다.")

    opt = session.query(Option).filter(Option.canonical_sku == option_canonical_sku).first()
    if not opt:
        raise ValueError(f"옵션 없음: {option_canonical_sku}")

    update_moving_avg(opt, qty_in=qty, price_in=unit_purchase_price)

    tx = InventoryTx(
        tx_type='in',
        location_id=location_id,
        option_canonical_sku=option_canonical_sku,
        qty=qty,
        unit_purchase_price_at_tx=unit_purchase_price,
        partner_label=partner_label.strip() or None,
        memo=memo.strip() or None,
        created_by=created_by,
        created_at=_now(),
        status='completed',
        source='local',
    )
    session.add(tx)
    session.flush()
    return tx


def create_outbound(session: Session, location_id: int, option_canonical_sku: str,
                     qty: int, unit_sale_price: int = 0,
                     partner_label: str = '', memo: str = '',
                     created_by: str = '') -> InventoryTx:
    """출고 — 재고 차감 + 매출 snapshot 박제 (ADR-002)."""
    if qty <= 0:
        raise ValueError("출고 수량은 양수여야 합니다.")

    opt = session.query(Option).filter(Option.canonical_sku == option_canonical_sku).first()
    if not opt:
        raise ValueError(f"옵션 없음: {option_canonical_sku}")
    if (opt.boxhero_stock_total or 0) < qty:
        raise ValueError(f"재고 부족: 보유 {opt.boxhero_stock_total or 0}, 요청 {qty}")

    snap = snapshot_at_outbound(opt)  # 출고 직전 평균매입가 박제
    opt.boxhero_stock_total = (opt.boxhero_stock_total or 0) - qty

    tx = InventoryTx(
        tx_type='out',
        location_id=location_id,
        option_canonical_sku=option_canonical_sku,
        qty=qty,
        unit_purchase_price_at_tx=snap,
        unit_sale_price=unit_sale_price,
        partner_label=partner_label.strip() or None,
        memo=memo.strip() or None,
        created_by=created_by,
        created_at=_now(),
        status='completed',
        source='local',
    )
    session.add(tx)
    session.flush()
    return tx


def create_adjustment(session: Session, location_id: int, option_canonical_sku: str,
                       new_qty: int, memo: str = '', created_by: str = '') -> InventoryTx:
    """조정 — 시스템 재고를 절대값으로 set (ADR-002, recalc_stock_total adjust 처리)."""
    opt = session.query(Option).filter(Option.canonical_sku == option_canonical_sku).first()
    if not opt:
        raise ValueError(f"옵션 없음: {option_canonical_sku}")
    if new_qty < 0:
        raise ValueError("조정 수량은 0 이상")

    opt.boxhero_stock_total = new_qty

    tx = InventoryTx(
        tx_type='adjust',
        location_id=location_id,
        option_canonical_sku=option_canonical_sku,
        qty=new_qty,
        memo=memo.strip() or None,
        created_by=created_by,
        created_at=_now(),
        status='completed',
        source='local',
    )
    session.add(tx)
    session.flush()
    return tx


def create_move(session: Session, from_location_id: int, to_location_id: int,
                 option_canonical_sku: str, qty: int, memo: str = '',
                 created_by: str = '') -> InventoryTx:
    """이동 — 위치 간만 이동, 총합 영향 ❌."""
    if qty <= 0:
        raise ValueError("이동 수량은 양수")
    if from_location_id == to_location_id:
        raise ValueError("동일 위치로 이동 불가")

    tx = InventoryTx(
        tx_type='move',
        location_id=from_location_id,
        location_to_id=to_location_id,
        option_canonical_sku=option_canonical_sku,
        qty=qty,
        memo=memo.strip() or None,
        created_by=created_by,
        created_at=_now(),
        status='completed',
        source='local',
    )
    session.add(tx)
    session.flush()
    return tx
