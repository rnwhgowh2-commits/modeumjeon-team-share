"""[구성 레이어] 구성(세트) CRUD 서비스."""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from lemouton.sets.models import (
    ProductSet, SetProduct, SetOption, SetChannel, SetChannelOption,
)
from lemouton.sourcing.models import Model


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


def list_linked_sets(session: Session, q: str | None = None) -> list[dict]:
    """판매처에 연동(채널 1개 이상)된 구성 목록 — 연동 현황 대시보드용.

    각 구성: 엮인 상품명들·옵션수(다품 가능), 채널(마켓·상품번호·상태·매칭수),
    엮인 모음전들의 최신 수집일자(last_collected_at).
    전송일자(last_sent_at)는 실제 전송(2단계) 도입 시 채워짐 — 현재는 항상 None.
    폴백 없음: 이름/번호 없는 값은 그대로 빈/None 으로 표면화.
    """
    set_ids = [r[0] for r in session.query(SetChannel.set_id).distinct().all()]
    if not set_ids:
        return []
    sets = list(
        session.query(ProductSet)
        .filter(ProductSet.id.in_(set_ids), ProductSet.is_active.is_(True))
        .order_by(ProductSet.id.desc())
        .all()
    )
    out: list[dict] = []
    for ps in sets:
        products = []
        last_collected = None
        for sp in ps.products:
            m = session.get(Model, sp.model_code)
            name = (m.model_name_display or m.model_name_raw) if m else sp.model_code
            opt_count = (
                session.query(SetOption).filter_by(set_product_id=sp.id).count()
            )
            products.append({
                "model_code": sp.model_code, "model_name": name,
                "quantity": sp.quantity, "option_count": opt_count,
            })
            crawled = getattr(m, "last_crawled_at", None) if m else None
            if crawled is not None and (last_collected is None or crawled > last_collected):
                last_collected = crawled
        channels = []
        for c in ps.channels:
            total = session.query(SetChannelOption).filter_by(channel_id=c.id).count()
            matched = (
                session.query(SetChannelOption)
                .filter_by(channel_id=c.id, status="matched").count()
            )
            mkt_fetched = (session.query(func.max(SetChannelOption.mkt_fetched_at))
                           .filter_by(channel_id=c.id).scalar())
            channels.append({
                "market": c.market, "market_product_id": c.market_product_id,
                "status": c.status, "matched": matched, "total": total,
                "mkt_fetched_at": mkt_fetched.isoformat() if mkt_fetched else None,
            })
        out.append({
            "set_id": ps.id, "name": ps.name, "model_code": ps.model_code,
            "products": products, "channels": channels,
            "last_collected_at": last_collected.isoformat() if last_collected else None,
            "last_sent_at": None,
        })
    if q:
        ql = q.strip().lower()

        def _match(r: dict) -> bool:
            if ql in (r["name"] or "").lower():
                return True
            if any(ql in (p["model_name"] or "").lower()
                   or ql in (p["model_code"] or "").lower() for p in r["products"]):
                return True
            if any(c["market_product_id"] and ql in c["market_product_id"].lower()
                   for c in r["channels"]):
                return True
            return False

        out = [r for r in out if _match(r)]
    return out


def delete_set(session: Session, set_id: int) -> bool:
    s = session.get(ProductSet, set_id)
    if s is None:
        return False
    session.delete(s)   # cascade: products → options, channels
    return True
