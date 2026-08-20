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
    """조정 — **결과 수량(new_qty)을 받아 원장엔 그 차이를 남긴다.**

    🔴 [2026-08-13 사장님 확정] 조정은 **차이값**이다.
       받는 값은 그대로 「실사해 보니 N개」다 — 작업자에게 뺄셈을 안 시킨다.
       차이 계산은 여기서 한다.

       절대값으로 남기면 **위치별 합이 전체와 안 맞는다**(전체는 접어서 세고
       위치별은 더해서 세기 때문). 규칙 정본 = shared/inventory_stock.py 머리말.
       모바일 창구(webapp/routes/mobile.py)도 같은 규칙이어야 한다 —
       한쪽만 바뀌면 같은 표의 행이 두 가지 뜻을 갖는다(오늘 세 번 그랬다).
    """
    opt = session.query(Option).filter(Option.canonical_sku == option_canonical_sku).first()
    if not opt:
        raise ValueError(f"옵션 없음: {option_canonical_sku}")
    if new_qty < 0:
        raise ValueError("조정 수량은 0 이상")

    # 🔴 차이의 기준은 **그 창고**다 — 「세어 보니 8개」는 이 창고가 8개라는 뜻이다.
    #   `location_id` 를 안 넘기면 `get_stock_batch` 가 위치 필터를 안 걸어
    #   **전 창고 합**을 돌려준다(shared/inventory_stock.py 의 location_id 분기).
    #   그러면 창고A(10)·창고B(10) 에서 A 를 8 로 실사할 때 차이가 8−20=−12 가 되어
    #   A 에 박히고, A=−2 · 총합=8 이 된다 — **10개가 에러 없이 증발**한다.
    #   (2026-08-13 감사에서 실행 재현. 기존 시험은 전부 창고 1곳이라 못 봤다.)
    from shared.inventory_stock import get_stock_batch
    before = int(get_stock_batch(session, [option_canonical_sku],
                                 location_id=location_id)
                 .get(option_canonical_sku) or 0)
    delta = int(new_qty) - before

    tx = InventoryTx(
        tx_type='adjust',
        location_id=location_id,
        option_canonical_sku=option_canonical_sku,
        qty=delta,
        memo=(memo.strip() or f'{before} → {new_qty}'),
        created_by=created_by,
        created_at=_now(),
        status='completed',
        source='local',
    )
    session.add(tx)
    session.flush()
    # 🔴 스냅샷(`boxhero_stock_total`)은 **전체** 수량이다. 한 창고 실사 결과를
    #   그대로 박으면 참값과 어긋나고, 그 스냅샷을 기준으로 읽는 화면이 없던 재고를
    #   만든다(조정서 ± 모드 실측: 원장 18인데 스냅샷 20 → +5 → 25, 기대 23).
    #   원장에서 다시 세어 넣는다 — 원장이 진실이다.
    opt.boxhero_stock_total = int(
        get_stock_batch(session, [option_canonical_sku]).get(option_canonical_sku) or 0)
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
