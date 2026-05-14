"""변동 감지 — 직전 동기화 값과 비교."""
from dataclasses import dataclass
from sqlalchemy.orm import Session

from .repository import get_registration


@dataclass
class Change:
    canonical_sku: str
    market: str
    old_price: int | None
    old_stock: int | None
    new_price: int
    new_stock: int
    price_changed: bool
    stock_changed: bool

    @property
    def has_change(self) -> bool:
        return self.price_changed or self.stock_changed


def detect_change(
    session: Session,
    *,
    canonical_sku: str,
    market: str,
    new_price: int,
    new_stock: int,
) -> Change:
    r = get_registration(session, canonical_sku, market)
    if r is None:
        return Change(
            canonical_sku=canonical_sku, market=market,
            old_price=None, old_stock=None,
            new_price=new_price, new_stock=new_stock,
            price_changed=True, stock_changed=True,
        )
    return Change(
        canonical_sku=canonical_sku, market=market,
        old_price=r.last_synced_price, old_stock=r.last_synced_stock,
        new_price=new_price, new_stock=new_stock,
        price_changed=(r.last_synced_price != new_price),
        stock_changed=(r.last_synced_stock != new_stock),
    )
