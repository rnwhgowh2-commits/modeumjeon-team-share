"""[구성 레이어] 알림 판정 — 저장 안 하고 현재 데이터에서 파생 계산.

현재 판정(저장값 기반): 판매 재고 0(market_soldout), 가격 급변(price_spike).
소싱·판매 대조형(소싱변동→판매갱신·둘다0·미동기화)은 소싱 매트릭스 통합 시 추가(P4).
"""
from __future__ import annotations

from lemouton.sets.models import SetChannel, SetChannelOption, ChannelChangeEvent

PRICE_SPIKE_RATE = 0.2


def alerts_for_set(session, set_id):
    """구성의 알림 목록 — [{type, severity, market, canonical_sku, message}]."""
    out = []
    chans = session.query(SetChannel).filter_by(set_id=set_id).all()
    for ch in chans:
        scos = (session.query(SetChannelOption)
                .filter_by(channel_id=ch.id, status="matched").all())
        for sco in scos:
            if ch.market != "coupang" and sco.mkt_stock == 0:
                out.append({"type": "market_soldout", "severity": "danger",
                            "market": ch.market, "canonical_sku": sco.canonical_sku,
                            "message": "판매처 재고 0(품절)"})
        last = (session.query(ChannelChangeEvent)
                .filter_by(set_id=set_id, market=ch.market, field="price")
                .order_by(ChannelChangeEvent.at.desc()).first())
        if last and last.prev_value and last.next_value is not None:
            rate = abs(last.next_value - last.prev_value) / last.prev_value
            if rate >= PRICE_SPIKE_RATE:
                out.append({"type": "price_spike", "severity": "info",
                            "market": ch.market, "canonical_sku": last.canonical_sku,
                            "message": "가격 급변 %d%%" % round(rate * 100)})
    return out
