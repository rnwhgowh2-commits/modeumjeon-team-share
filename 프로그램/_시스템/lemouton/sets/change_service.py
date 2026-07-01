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
