"""[구성 레이어] 구성(세트) CRUD 서비스."""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from lemouton.sets.models import (
    ProductSet, SetProduct, SetOption, SetChannel, SetChannelOption,
)
from lemouton.sourcing.models import Model
from lemouton.sets.alert_service import alerts_for_set as _alerts_for_set


def _signals(market_alerts, *, has_send):
    """카드 상태 신호등(재고·가격·전송) — 기존 알림(P3) + 전송상태에서 파생.

    ok | warn(주의 주황) | sev(심각 빨강). 알림 재사용(중복 판정 금지).
    소≠판 재고 안 맞음(warn)은 소싱 재고수 배선(P4-1b) 후 보강.
    """
    types = {a.get("type") for a in (market_alerts or [])}
    stock = "sev" if (types & {"market_soldout", "both_zero"}) else "ok"
    price = "warn" if "price_spike" in types else "ok"
    needs_sync = (not has_send) or bool(types & {"not_synced", "source_changed"})
    send = "warn" if needs_sync else "ok"
    return {"stock": stock, "price": price, "send": send}


def _src_summary(src_provider, model_codes, skus):
    """카드 「재고 소」용 소싱처 요약 — {src_stock_total, source_name}.

    소싱 재고/소싱처명은 무거운 매트릭스 경로(_option_matrix_data)라, 서비스는
    순수하게 두고 라우트가 주입(src_provider)한다. 미주입 시 None(지연 표시).
    src_provider(model_codes, skus) -> {sku: {"stock": int|None, "source_name": str|None}}.
    """
    empty = {"src_stock_total": None, "source_name": None}
    if src_provider is None or not skus:
        return empty
    smap = src_provider(model_codes, skus) or {}
    stocks = [v.get("stock") for v in smap.values() if v.get("stock") is not None]
    names = [v.get("source_name") for v in smap.values() if v.get("source_name")]
    name = None
    if names:
        # 대표 소싱처 = 최다 등장
        name = max(set(names), key=names.count)
    return {"src_stock_total": sum(stocks) if stocks else None, "source_name": name}


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


def list_linked_sets(session: Session, q: str | None = None,
                     src_provider=None) -> list[dict]:
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
        model_codes: set[str] = set()
        skus: set[str] = set()
        for sp in ps.products:
            m = session.get(Model, sp.model_code)
            name = (m.model_name_display or m.model_name_raw) if m else sp.model_code
            sp_opts = session.query(SetOption).filter_by(set_product_id=sp.id).all()
            model_codes.add(sp.model_code)
            for o in sp_opts:
                skus.add(o.canonical_sku)
            products.append({
                "model_code": sp.model_code, "model_name": name,
                "quantity": sp.quantity, "option_count": len(sp_opts),
                "brand": getattr(m, "brand", None) if m else None,
            })
            crawled = getattr(m, "last_crawled_at", None) if m else None
            if crawled is not None and (last_collected is None or crawled > last_collected):
                last_collected = crawled
        src_summary = _src_summary(src_provider, model_codes, skus)
        alerts = _alerts_for_set(session, ps.id)
        last_sent = None   # 전송 기능(2단계) 도입 시 채워짐 — 현재 항상 미전송
        channels = []
        for c in ps.channels:
            scos = (session.query(SetChannelOption)
                    .filter_by(channel_id=c.id, status="matched").all())
            total = session.query(SetChannelOption).filter_by(channel_id=c.id).count()
            matched = len(scos)
            mkt_fetched = (session.query(func.max(SetChannelOption.mkt_fetched_at))
                           .filter_by(channel_id=c.id).scalar())
            stocks = [s.mkt_stock for s in scos if s.mkt_stock is not None]
            prices = [s.mkt_price for s in scos if s.mkt_price is not None]
            mk_alerts = [a for a in alerts if a.get("market") == c.market]
            channels.append({
                "market": c.market, "market_product_id": c.market_product_id,
                "status": c.status, "matched": matched, "total": total,
                "mkt_fetched_at": mkt_fetched.isoformat() if mkt_fetched else None,
                "mkt_stock_total": sum(stocks) if stocks else None,
                "mkt_price": min(prices) if prices else None,
                "signals": _signals(mk_alerts, has_send=last_sent is not None),
            })
        out.append({
            "set_id": ps.id, "name": ps.name, "model_code": ps.model_code,
            "products": products, "channels": channels,
            "src_summary": src_summary,
            "last_collected_at": last_collected.isoformat() if last_collected else None,
            "last_sent_at": last_sent,
            "alerts": alerts,
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
