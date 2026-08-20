"""변동 기록 서비스 — 판매처 채널 옵션의 stock/price 변동을 이력 테이블에 기록한다."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from lemouton.sets.models import ChannelChangeEvent


def record_change(
    session: Session,
    *,
    set_id: int,
    market: str,
    canonical_sku: str,
    field: str,
    source: str,
    prev_value: Optional[int],
    next_value: Optional[int],
    at: Optional[datetime] = None,
) -> bool:
    """prev_value == next_value 면 아무것도 하지 않고 False 반환.

    다르면 ChannelChangeEvent 를 session 에 추가하고 True 반환.
    호출자가 commit 해야 영속된다.
    """
    if prev_value == next_value:
        return False

    event = ChannelChangeEvent(
        set_id=set_id,
        market=market,
        canonical_sku=canonical_sku,
        field=field,
        source=source,
        prev_value=prev_value,
        next_value=next_value,
        at=at or datetime.now(timezone.utc),
    )
    session.add(event)
    return True


def list_changes(session, *, set_id, market=None, field=None, limit=200):
    """구성의 변동 이벤트를 최신순(at desc)으로 반환. market/field 선택 필터.

    source 필드로 소싱처('source')·판매처('market') 변동을 구분해 호출자가 2열 표시.
    """
    q = session.query(ChannelChangeEvent).filter(ChannelChangeEvent.set_id == set_id)
    if market:
        q = q.filter(ChannelChangeEvent.market == market)
    if field == "price":
        # 가격 이력 = 3단계(소싱표면가 surface·최종매입가 cost·판매예정가 planned) + 레거시 price
        q = q.filter(ChannelChangeEvent.field.in_(
            ["surface", "cost", "planned", "price"]))
    elif field:
        q = q.filter(ChannelChangeEvent.field == field)
    q = q.order_by(ChannelChangeEvent.at.desc(), ChannelChangeEvent.id.desc()).limit(limit)
    out = []
    for e in q.all():
        out.append({
            "at": e.at.isoformat() if e.at else None,
            "source": e.source,
            "market": e.market,
            "canonical_sku": e.canonical_sku,
            "field": e.field,
            "prev_value": e.prev_value,
            "next_value": e.next_value,
        })
    return out


def list_automation_log(session, *, limit=200):
    """전체 구성의 자동 감지 변동을 상품단위(모음전 × 마켓)로 묶어 반환.

    각 그룹 = {set_name, brand, market, latest_at, stock_count, price_count, options[]}.
    options[] = {name, parts[{kind:'s'|'p', label, value}]} — 옵션 한 줄에 필드 합침.
    현재 실데이터 = source 변동. '자동 크롤'·'판매처 전송'은 5단계 엔진이 추가.
    """
    from lemouton.sets.models import ProductSet, SetProduct
    from lemouton.sourcing.models import Model, Option

    events = (session.query(ChannelChangeEvent)
              .order_by(ChannelChangeEvent.at.desc(), ChannelChangeEvent.id.desc())
              .limit(limit).all())
    brand_cache: dict = {}
    name_cache: dict = {}
    opt_cache: dict = {}

    def _set_info(set_id):
        if set_id in brand_cache:
            return brand_cache[set_id], name_cache[set_id]
        ps = session.get(ProductSet, set_id)
        brand, name = None, None
        if ps is not None:
            name = ps.name
            sp = (session.query(SetProduct).filter_by(set_id=set_id)
                  .order_by(SetProduct.sort_order).first())
            if sp is not None:
                m = session.get(Model, sp.model_code)
                brand = getattr(m, "brand", None) if m else None
        brand = brand or name or "—"
        name = name or "—"
        brand_cache[set_id] = brand
        name_cache[set_id] = name
        return brand, name

    def _opt(sku):
        if sku in opt_cache:
            return opt_cache[sku]
        o = session.get(Option, sku)
        if o is not None:
            c = o.color_display or o.color_code or ""
            s = o.size_display or o.size_code or ""
            lbl = ("%s %s" % (c, s)).strip() or sku
        else:
            lbl = sku
        opt_cache[sku] = lbl
        return lbl

    mk = {"coupang": "쿠팡", "smartstore": "스마트스토어"}
    # 배지 스타일: 소=소싱(표면·매입) / 판=판매(예정) / 재=재고(별도). label=짧은 라벨
    side_map = {"surface": "소", "cost": "소", "planned": "판",
                "price": "판", "stock": "재"}
    short_map = {"surface": "표면", "cost": "매입", "planned": "예정",
                 "price": "가격", "stock": "재고"}
    order_map = {"surface": 0, "cost": 1, "planned": 2, "price": 3}

    def _num(v):
        if v is None:
            return None
        try:
            return format(int(v), ",")
        except (TypeError, ValueError):
            return str(v)

    def _change(prev, nxt, field):
        # 단위(개·원)는 끝에 한 번만: '2→26개' · '→126,200원' · '111,510→113,630원'
        unit = "개" if field == "stock" else "원"
        p, n = _num(prev), _num(nxt)
        n = n if n is not None else "—"
        body = ("→%s" % n) if p is None else ("%s→%s" % (p, n))
        return body + (unit if n != "—" else "")

    groups: dict = {}
    order: list = []
    for e in events:
        key = (e.set_id, e.market)
        g = groups.get(key)
        if g is None:
            brand, name = _set_info(e.set_id)
            g = {
                "set_id": e.set_id, "set_name": name, "brand": brand,
                "market": mk.get(e.market, e.market or "—"),
                "market_key": e.market if e.market in ("coupang", "smartstore") else "",
                "latest_at": e.at.isoformat() if e.at else None,
                "stock_count": 0, "price_count": 0,
                "options": [], "_oi": {}, "_seen": set(),
            }
            groups[key] = g
            order.append(key)
        sig = (e.canonical_sku, e.field)   # 같은 옵션·필드는 최신 1건만 (desc → 첫 등장 유지)
        if sig in g["_seen"]:
            continue
        g["_seen"].add(sig)
        oi = g["_oi"].get(e.canonical_sku)
        if oi is None:
            oi = len(g["options"])
            g["_oi"][e.canonical_sku] = oi
            g["options"].append({"name": _opt(e.canonical_sku), "parts": []})
        g["options"][oi]["parts"].append({
            "field": e.field,
            "side": side_map.get(e.field, "판"),
            "label": short_map.get(e.field, e.field),
            "value": _change(e.prev_value, e.next_value, e.field),
            "empty": e.prev_value is None,          # 이전값 없음 → '빈데이터 → 값'
        })

    out = []
    for key in order:
        g = groups[key]
        g.pop("_oi", None)
        g.pop("_seen", None)
        for o in g["options"]:
            o["parts"].sort(key=lambda p: (0 if p["field"] == "stock" else 1,
                                           order_map.get(p["field"], 9)))
        # 요약 = '옵션 수'(한 옵션은 한 번만): 재고 바뀐 옵션 수 · 가격 바뀐 옵션 수
        g["stock_count"] = sum(
            1 for o in g["options"] if any(p["field"] == "stock" for p in o["parts"]))
        g["price_count"] = sum(
            1 for o in g["options"] if any(p["field"] != "stock" for p in o["parts"]))
        g["option_count"] = len(g["options"])
        out.append(g)
    return out


def snapshot_source_values(session, *, set_id, value_map):
    """구성 옵션의 현재 소싱 값(value_map={sku:{stock,price}})을 직전 source 이벤트와
    비교해 변동만 ChannelChangeEvent(source='source')로 기록. 기록 건수 반환(호출자 commit).

    소싱 변동을 머니-크리티컬 글로벌 크롤 핫패스 대신 세트 단위에서 스냅샷으로 포착.
    H2 변동이력 소싱열·source_changed 알림이 이 기록으로 점등된다.
    """
    from lemouton.sets.models import SetChannel, SetChannelOption
    n = 0
    chans = session.query(SetChannel).filter_by(set_id=set_id).all()
    for ch in chans:
        scos = (session.query(SetChannelOption)
                .filter_by(channel_id=ch.id, status="matched").all())
        for sco in scos:
            vals = value_map.get(sco.canonical_sku)
            if not vals:
                continue
            # 기록 필드: 재고 + 기존 price + 가격 3단계(surface 소싱표면가 / cost 최종매입가)
            fields = {f: vals[f] for f in ("stock", "price", "surface", "cost")
                      if vals.get(f) is not None}
            # planned 판매예정가 = 마켓별(스스=ss / 쿠팡=cp)
            pk = ("ss_price" if ch.market == "smartstore"
                  else "cp_price" if ch.market == "coupang" else None)
            if pk and vals.get(pk) is not None:
                fields["planned"] = vals[pk]
            for field, new in fields.items():
                last = (session.query(ChannelChangeEvent)
                        .filter_by(set_id=set_id, market=ch.market,
                                   canonical_sku=sco.canonical_sku, field=field,
                                   source="source")
                        .order_by(ChannelChangeEvent.at.desc()).first())
                prev = last.next_value if last else None
                if record_change(session, set_id=set_id, market=ch.market,
                                 canonical_sku=sco.canonical_sku, field=field,
                                 source="source", prev_value=prev, next_value=new):
                    n += 1
    return n
