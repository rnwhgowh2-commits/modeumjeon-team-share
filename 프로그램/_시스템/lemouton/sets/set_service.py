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


def _rep_source_url(smap, name):
    """대표 소싱처명(name)에 대응하는 상품 URL — 그 이름을 가진 옵션 중 URL 있는 첫 항목.

    카드 「소」 줄 바로가기(↗)가 가리킬 곳. 사입(URL 없음)·미매칭은 None.
    """
    if not name:
        return None
    for v in smap.values():
        if v.get("source_name") == name and v.get("source_url"):
            return v.get("source_url")
    return None


def _rep_price(smap):
    """카드 「소」 대표 가격 — (표면노출가, 최종매입가) 코히런트 쌍.

    표면이 있는 옵션 중 최저 표면가의 (표면, 최종)을 취한다(같은 옵션이라 최종=표면−혜택 일관).
    표면 없는 사입-only 세트는 (None, 최저 최종매입가). 값 없으면 (None, None).
    """
    with_surf = [v for v in smap.values() if v.get("surface") is not None]
    if with_surf:
        rep = min(with_surf, key=lambda v: v["surface"])
        return rep.get("surface"), rep.get("final")
    finals = [v.get("final") for v in smap.values() if v.get("final") is not None]
    return None, (min(finals) if finals else None)


def _src_summary(src_provider, model_codes, skus):
    """카드 「재고 소」용 소싱처 요약 — {src_stock_total, source_name, source_url, surface, final}.

    소싱 재고/소싱처명은 무거운 매트릭스 경로(_option_matrix_data)라, 서비스는
    순수하게 두고 라우트가 주입(src_provider)한다. 미주입 시 None(지연 표시).
    src_provider(model_codes, skus) -> {sku: {"stock", "source_name", "source_url",
        "surface"(표면노출가), "final"(최종매입가)}}.
    source_url = 대표 소싱처 바로가기(↗)용 상품 URL. surface/final = 대표 「소」 가격 2값.
    """
    empty = {"src_stock_total": None, "source_name": None, "source_url": None,
             "surface": None, "final": None}
    if src_provider is None or not skus:
        return empty
    smap = src_provider(model_codes, skus) or {}
    stocks = [v.get("stock") for v in smap.values() if v.get("stock") is not None]
    names = [v.get("source_name") for v in smap.values() if v.get("source_name")]
    name = None
    if names:
        # 대표 소싱처 = 최다 등장
        name = max(set(names), key=names.count)
    surface, final = _rep_price(smap)
    return {"src_stock_total": sum(stocks) if stocks else None,
            "source_name": name, "source_url": _rep_source_url(smap, name),
            "surface": surface, "final": final}


def _enrich_from_provider(row, src_provider):
    """q 필터 통과 세트에 소싱 요약(재고·소싱처명) + 채널별 판매예정가를 채운다.

    provider 한 번 호출(무거운 _option_matrix_data 재사용)로 소싱 요약·판매예정가·
    「소」 2값(표면노출가·최종매입가)을 모두 파생. 판매예정가 = 매칭 옵션들의 마켓별
    값 중 대표(최저). 표면·최종은 대표(최저 표면가) 옵션의 코히런트 쌍(_rep_price).
    """
    mcs = row.pop("_mcs", set())
    skus = row.pop("_skus", set())
    row["src_summary"] = {"src_stock_total": None, "source_name": None,
                          "source_url": None, "surface": None, "final": None}
    smap = {}
    if src_provider is not None and skus:
        smap = src_provider(mcs, skus) or {}
        stocks = [v.get("stock") for v in smap.values() if v.get("stock") is not None]
        names = [v.get("source_name") for v in smap.values() if v.get("source_name")]
        name = max(set(names), key=names.count) if names else None
        surface, final = _rep_price(smap)
        row["src_summary"] = {"src_stock_total": sum(stocks) if stocks else None,
                              "source_name": name,
                              "source_url": _rep_source_url(smap, name),
                              "surface": surface, "final": final}
    for ch in row["channels"]:
        ch_skus = ch.pop("_skus", [])
        pk = ("ss_price" if ch["market"] == "smartstore"
              else "cp_price" if ch["market"] == "coupang" else None)
        pp = None
        if pk and smap:
            vals = [smap[s].get(pk) for s in ch_skus
                    if s in smap and smap[s].get(pk) is not None]
            pp = min(vals) if vals else None
        ch["planned_price"] = pp


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
                "id": c.id,
                "market": c.market, "market_product_id": c.market_product_id,
                "status": c.status, "matched": matched, "total": total,
                "mkt_fetched_at": mkt_fetched.isoformat() if mkt_fetched else None,
                "mkt_stock_total": sum(stocks) if stocks else None,
                "mkt_price": min(prices) if prices else None,
                "planned_price": None,   # 마켓별 판매예정가 — provider 파생(아래)
                "signals": _signals(mk_alerts, has_send=last_sent is not None),
                "_skus": [s.canonical_sku for s in scos],
            })
        out.append({
            "set_id": ps.id, "name": ps.name, "model_code": ps.model_code,
            "products": products, "channels": channels,
            "src_summary": {"src_stock_total": None, "source_name": None},
            "_mcs": model_codes, "_skus": skus,
            "last_collected_at": last_collected.isoformat() if last_collected else None,
            "last_sent_at": last_sent,
            "alerts": alerts,
            "auto_mode": getattr(ps, "auto_mode", "on"),
            "manual_crawl_hours": getattr(ps, "manual_crawl_hours", 1),
            "manual_crawl_minutes": getattr(ps, "manual_crawl_minutes", 0),
            "manual_upload_hours": getattr(ps, "manual_upload_hours", 3),
            "manual_upload_minutes": getattr(ps, "manual_upload_minutes", 0),
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
    # 무거운 provider(소싱 요약 + 채널별 판매예정가)는 q 필터 통과 세트에만 — 검색 핫패스 부하 방지
    for r in out:
        _enrich_from_provider(r, src_provider)
    return out


def delete_set(session: Session, set_id: int) -> bool:
    s = session.get(ProductSet, set_id)
    if s is None:
        return False
    session.delete(s)   # cascade: products → options, channels
    return True


_AUTO_MODES = ("on", "off", "manual")


def _auto_dict(s: ProductSet) -> dict:
    return {
        "auto_mode": getattr(s, "auto_mode", "on"),
        "manual_crawl_hours": getattr(s, "manual_crawl_hours", 1),
        "manual_crawl_minutes": getattr(s, "manual_crawl_minutes", 0),
        "manual_upload_hours": getattr(s, "manual_upload_hours", 3),
        "manual_upload_minutes": getattr(s, "manual_upload_minutes", 0),
    }


def save_set_automation(session: Session, set_id: int, data: dict) -> dict | None:
    """구성별 자동 저장 — auto_mode(on|off|manual) + 수동설정 주기(시:분).
    전달된 항목만 갱신·검증(모드 화이트리스트·분 0~59·음수 방지). 호출자가 commit."""
    s = session.get(ProductSet, set_id)
    if s is None:
        return None
    if "auto_mode" in data and data["auto_mode"] in _AUTO_MODES:
        s.auto_mode = data["auto_mode"]
    for k, cap in (("manual_crawl_hours", None), ("manual_crawl_minutes", 59),
                   ("manual_upload_hours", None), ("manual_upload_minutes", 59)):
        if k in data:
            try:
                v = max(0, int(data[k]))
            except (TypeError, ValueError):
                continue
            if cap is not None:
                v = min(cap, v)
            setattr(s, k, v)
    session.flush()
    return _auto_dict(s)
