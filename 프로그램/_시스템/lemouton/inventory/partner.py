"""[I] partner.py — 거래처 텍스트 보존만 (ADR-003).

ai-workflow STEP 7 Sprint 1A Task 1.5
"""
from sqlalchemy import func
from sqlalchemy.orm import Session
from lemouton.inventory.models import InventoryTx


def recent_labels(session: Session, limit: int = 50) -> list[dict]:
    """최근 사용한 거래처 라벨 + 사용 횟수 + 최근 사용일 + tx_type 사용 (in/out).

    박스히어로 multi-type 1:1 — 같은 label 이 in/out 둘 다 사용된 경우 두 type 모두 표기.
    """
    rows = (
        session.query(
            InventoryTx.partner_label,
            func.count(InventoryTx.id),
            func.max(InventoryTx.created_at),
        )
        .filter(InventoryTx.partner_label.isnot(None))
        .filter(InventoryTx.partner_label != '')
        .group_by(InventoryTx.partner_label)
        .order_by(func.max(InventoryTx.created_at).desc())
        .limit(limit)
        .all()
    )
    type_rows = (
        session.query(InventoryTx.partner_label, InventoryTx.tx_type)
        .filter(InventoryTx.partner_label.isnot(None))
        .filter(InventoryTx.partner_label != '')
        .distinct()
        .all()
    )
    types_by_label: dict[str, set] = {}
    for label, tx_type in type_rows:
        types_by_label.setdefault(label, set()).add(tx_type)
    return [
        {'label': label, 'count': cnt, 'last_used': last,
         'types': sorted(types_by_label.get(label, set()))}
        for (label, cnt, last) in rows
    ]
