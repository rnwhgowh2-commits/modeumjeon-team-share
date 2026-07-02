"""[구성 레이어] 알림 판정 — 저장 안 하고 현재 데이터에서 파생 계산.

유형 5종:
 - market_soldout (danger 위험): 판매처 재고 0(쿠팡 제외 — 쿠팡은 재고 미상)
 - both_zero (critical 심각): 소싱·판매 둘 다 재고 0 (src_stock_map 필요)
 - not_synced (info 정보): 연동됐는데 마켓 현재값 한 번도 수집 안 됨(미동기화)
 - source_changed (warning 주의): 소싱 변동이 마지막 마켓 수집 이후 발생 → 판매처 갱신 필요
 - price_spike (info 정보): 최근 가격 20% 이상 급변

src_stock_map={canonical_sku:src_stock} 주입 시 both_zero 판정. 없으면 market_soldout 으로만
(개수 동일, severity만 보수적). source_changed 는 작업6(source 이벤트 훅) 후 점등.
"""
from __future__ import annotations

from lemouton.sets.models import SetChannel, SetChannelOption, ChannelChangeEvent

PRICE_SPIKE_RATE = 0.2


def alerts_for_set(session, set_id, src_stock_map=None):
    """구성 알림 — [{type, severity, market, canonical_sku, message}]."""
    src = src_stock_map or {}
    out = []
    chans = session.query(SetChannel).filter_by(set_id=set_id).all()
    for ch in chans:
        scos = (session.query(SetChannelOption)
                .filter_by(channel_id=ch.id, status="matched").all())
        # 미동기화: 연동 상태인데 현재값 수집 흔적(mkt_fetched_at) 전무
        if ch.status == "linked" and ch.market_product_id and scos:
            if all(s.mkt_fetched_at is None for s in scos):
                out.append({"type": "not_synced", "severity": "info",
                            "market": ch.market, "canonical_sku": None,
                            "message": "마켓 현재값 미수집(미동기화)"})
        # 수집됐는데 값이 깨진 경우 표면화(조용한 초록 금지)
        fetched_any = any(s.mkt_fetched_at is not None for s in scos)
        if scos and fetched_any:
            # 현재가 0원 = 수집 실패/비정상 → danger(그대로 업로드 시 0원 판매 위험)
            if any(s.mkt_price == 0 for s in scos):
                out.append({"type": "price_zero", "severity": "danger",
                            "market": ch.market, "canonical_sku": None,
                            "message": "현재가 0원(수집 실패·확인 필요)"})
            # 재고 전량 미상(None) = 수집 불가/실패 → warning(초록으로 정상 위장 금지)
            if all(s.mkt_stock is None for s in scos):
                out.append({"type": "stock_unknown", "severity": "warning",
                            "market": ch.market, "canonical_sku": None,
                            "message": "판매처 재고 미상(수집 불가)"})
        # 재고 0 — 소싱도 0이면 심각(both_zero), 아니면 판매재고0(market_soldout)
        for sco in scos:
            if ch.market == "coupang" or sco.mkt_stock != 0:
                continue
            if src.get(sco.canonical_sku) == 0:
                out.append({"type": "both_zero", "severity": "critical",
                            "market": ch.market, "canonical_sku": sco.canonical_sku,
                            "message": "소싱·판매 둘 다 재고 0"})
            else:
                out.append({"type": "market_soldout", "severity": "danger",
                            "market": ch.market, "canonical_sku": sco.canonical_sku,
                            "message": "판매처 재고 0(품절)"})
        # 소싱변동→판매갱신: source 이벤트가 마지막 마켓 수집보다 최신
        last_fetch = max((s.mkt_fetched_at for s in scos if s.mkt_fetched_at is not None),
                         default=None)
        if last_fetch is not None:
            recent_src = (session.query(ChannelChangeEvent)
                          .filter_by(set_id=set_id, market=ch.market, source="source")
                          .filter(ChannelChangeEvent.at > last_fetch).first())
            if recent_src is not None:
                out.append({"type": "source_changed", "severity": "warning",
                            "market": ch.market, "canonical_sku": None,
                            "message": "소싱 변동 — 판매처 갱신 필요"})
        # 가격 급변
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
