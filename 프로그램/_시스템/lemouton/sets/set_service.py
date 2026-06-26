"""[구성 레이어] 구성(세트) CRUD 서비스."""
from __future__ import annotations

from sqlalchemy.orm import Session

from lemouton.sets.models import ProductSet, SetProduct, SetOption


def create_set(session: Session, *, model_code: str, name: str) -> ProductSet:
    s = ProductSet(model_code=model_code, name=name)
    session.add(s)
    session.flush()
    return s


def add_product(session: Session, *, set_id: int, model_code: str,
                quantity: int = 1) -> SetProduct:
    p = SetProduct(set_id=set_id, model_code=model_code, quantity=quantity)
    session.add(p)
    session.flush()
    return p


def set_options(session: Session, *, set_product_id: int,
                canonical_skus: list[str]) -> list[SetOption]:
    """선택 옵션을 통째로 교체(부분집합 재설정)."""
    session.query(SetOption).filter_by(set_product_id=set_product_id).delete()
    rows = []
    for i, sku in enumerate(canonical_skus):
        o = SetOption(set_product_id=set_product_id, canonical_sku=sku, sort_order=i)
        session.add(o)
        rows.append(o)
    session.flush()
    return rows


def list_sets(session: Session, model_code: str) -> list[ProductSet]:
    return list(
        session.query(ProductSet)
        .filter_by(model_code=model_code, is_active=True)
        .order_by(ProductSet.id)
        .all()
    )


def get_set_detail(session: Session, set_id: int) -> dict:
    s = session.get(ProductSet, set_id)
    if s is None:
        return {}
    return {
        "id": s.id, "model_code": s.model_code, "name": s.name,
        "products": [
            {"id": p.id, "model_code": p.model_code, "quantity": p.quantity,
             "options": [o.canonical_sku for o in p.options]}
            for p in s.products
        ],
        "channels": [
            {"id": c.id, "market": c.market, "account_key": c.account_key,
             "market_product_id": c.market_product_id, "status": c.status}
            for c in s.channels
        ],
    }


def delete_set(session: Session, set_id: int) -> bool:
    s = session.get(ProductSet, set_id)
    if s is None:
        return False
    session.delete(s)   # cascade: products → options, channels
    return True
