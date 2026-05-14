"""[I] attributes.py — 사용자 정의 속성 (5종: text/number/date/barcode/file).

박스히어로 도움말 data-center/attributes 1:1.
ai-workflow STEP 7 Sprint 1A Task 1.4
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from lemouton.inventory.models import ItemAttribute

VALID_TYPES = ('text', 'number', 'date', 'barcode', 'file')


def list_active(session: Session) -> list[ItemAttribute]:
    return (
        session.query(ItemAttribute)
        .filter(ItemAttribute.deleted_at.is_(None))
        .order_by(ItemAttribute.sort_order, ItemAttribute.id)
        .all()
    )


def create(session: Session, name: str, type_: str) -> ItemAttribute:
    name = (name or '').strip()
    if not name:
        raise ValueError("속성 이름은 필수입니다.")
    if type_ not in VALID_TYPES:
        raise ValueError(f"잘못된 type — {type_}. 가능: {VALID_TYPES}")

    existing = session.query(ItemAttribute).filter(
        ItemAttribute.name == name,
        ItemAttribute.deleted_at.is_(None)
    ).first()
    if existing:
        raise ValueError(f"이미 존재하는 속성: {name}")

    max_order = session.query(ItemAttribute.sort_order).order_by(
        ItemAttribute.sort_order.desc()).first()
    sort_order = (max_order[0] if max_order else 0) + 1

    attr = ItemAttribute(name=name, type=type_, sort_order=sort_order)
    session.add(attr)
    session.flush()
    return attr


def delete(session: Session, attr_id: int) -> None:
    attr = session.query(ItemAttribute).filter(ItemAttribute.id == attr_id).first()
    if not attr or attr.deleted_at is not None:
        raise ValueError(f"속성 없음: id={attr_id}")
    attr.deleted_at = datetime.now(timezone.utc)
