"""[I] locations.py — 위치(Location) CRUD.

Q1 결정: A + CRUD (그로스/기본 위치/판매불가 + 사용자 자유 추가/수정/삭제).
박스히어로 도움말 data-center/locations 1:1.

ai-workflow STEP 7 Sprint 1A Task 1.2
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from lemouton.inventory.models import InventoryLocation


def _now():
    return datetime.now(timezone.utc)


def list_active(session: Session) -> list[InventoryLocation]:
    """삭제 안 된 위치 목록 (sort_order ASC, name ASC)."""
    return (
        session.query(InventoryLocation)
        .filter(InventoryLocation.deleted_at.is_(None))
        .order_by(InventoryLocation.sort_order, InventoryLocation.name)
        .all()
    )


def create(session: Session, name: str, is_default: bool = False) -> InventoryLocation:
    """신규 위치 추가 — 박스히어로식 자유 추가."""
    name = (name or '').strip()
    if not name:
        raise ValueError("위치 이름은 필수입니다.")

    existing = (
        session.query(InventoryLocation)
        .filter(InventoryLocation.name == name)
        .filter(InventoryLocation.deleted_at.is_(None))
        .first()
    )
    if existing:
        raise ValueError(f"이미 존재하는 위치: {name}")

    # 새 위치는 마지막 sort_order + 1
    max_order = (
        session.query(InventoryLocation.sort_order)
        .order_by(InventoryLocation.sort_order.desc())
        .first()
    )
    sort_order = (max_order[0] if max_order else 0) + 1

    loc = InventoryLocation(
        name=name,
        sort_order=sort_order,
        is_default=is_default,
    )
    session.add(loc)
    session.flush()
    return loc


def update(session: Session, loc_id: int, name: Optional[str] = None,
           sort_order: Optional[int] = None, is_default: Optional[bool] = None) -> InventoryLocation:
    """위치 수정 (name·sort_order·is_default)."""
    loc = session.query(InventoryLocation).filter(InventoryLocation.id == loc_id).first()
    if not loc or loc.deleted_at is not None:
        raise ValueError(f"위치 없음: id={loc_id}")

    if name is not None:
        new_name = name.strip()
        if not new_name:
            raise ValueError("위치 이름은 필수입니다.")
        # 중복 검사 (자기 자신 제외)
        dup = (
            session.query(InventoryLocation)
            .filter(InventoryLocation.name == new_name)
            .filter(InventoryLocation.id != loc_id)
            .filter(InventoryLocation.deleted_at.is_(None))
            .first()
        )
        if dup:
            raise ValueError(f"이미 존재하는 위치: {new_name}")
        loc.name = new_name

    if sort_order is not None:
        loc.sort_order = sort_order
    if is_default is not None:
        loc.is_default = is_default

    loc.updated_at = _now()
    return loc


def delete(session: Session, loc_id: int) -> None:
    """위치 soft-delete. 재고 있으면 ValueError (사용자 확인 후 강제 삭제 가능)."""
    loc = session.query(InventoryLocation).filter(InventoryLocation.id == loc_id).first()
    if not loc or loc.deleted_at is not None:
        raise ValueError(f"위치 없음: id={loc_id}")
    if loc.is_default:
        raise ValueError("기본 위치는 삭제 불가합니다.")

    # 재고 보유 확인
    from lemouton.inventory.models import InventoryTx
    has_tx = (
        session.query(InventoryTx)
        .filter(InventoryTx.location_id == loc_id)
        .filter(InventoryTx.status == 'completed')
        .first()
    )
    if has_tx:
        raise ValueError("거래 내역이 있는 위치는 삭제 불가합니다. 먼저 다른 위치로 이동해주세요.")

    loc.deleted_at = _now()


def seed_defaults(session: Session) -> list[InventoryLocation]:
    """박스히어로 기본 3 위치 (그로스 / 기본 위치 / 판매불가) 시드.

    이미 존재하면 skip. 비즈니스 플랜의 99LAB 운영 환경 미러.
    """
    seeds = [
        ('기본 위치', True, 1),
        ('그로스', False, 2),
        ('판매불가', False, 3),
    ]
    created = []
    for name, is_default, sort_order in seeds:
        existing = (
            session.query(InventoryLocation)
            .filter(InventoryLocation.name == name)
            .filter(InventoryLocation.deleted_at.is_(None))
            .first()
        )
        if existing:
            continue
        loc = InventoryLocation(name=name, sort_order=sort_order, is_default=is_default)
        session.add(loc)
        created.append(loc)
    if created:
        session.flush()
    return created
