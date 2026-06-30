"""[구성 레이어] 판매처 현재값 수집 — fetch_market_options 로 당겨와 mkt_* 저장 + 변동 기록.

마켓에 쓰지 않음(읽기+로컬). 쿠팡 재고는 미상이므로 mkt_stock=None. 폴백 금지(조회 실패 시 미갱신).
"""
from __future__ import annotations

from datetime import datetime, timezone

from lemouton.sets.models import SetChannel, SetChannelOption
from lemouton.sets.change_service import record_change
from lemouton.sets.set_link_service import _resolve_env_prefix
from lemouton.uploader.market_fetch import fetch_market_options


def collect_channel(session, channel_id, fetcher=fetch_market_options):
    """채널의 현재 재고/가격을 마켓 API로 당겨와 mkt_* 갱신 + 변동 이벤트 기록."""
    ch = session.get(SetChannel, channel_id)
    if ch is None:
        return {"ok": False, "error": "채널 없음"}
    if not ch.market_product_id:
        return {"ok": False, "error": "상품번호 미입력"}
    env_prefix = _resolve_env_prefix(session, ch.market, ch.account_key)
    fr = fetcher(ch.market, ch.market_product_id, env_prefix=env_prefix)
    if not fr.success:
        return {"ok": False, "error": fr.error or "조회 실패"}
    mo_map = {str(o.option_id): o for o in fr.options}
    now = datetime.now(timezone.utc)
    fetched = changed = 0
    rows = (session.query(SetChannelOption)
            .filter_by(channel_id=channel_id, status="matched").all())
    for sco in rows:
        if not sco.market_option_id:
            continue
        mo = mo_map.get(str(sco.market_option_id))
        if mo is None:
            continue
        fetched += 1
        new_stock = None if ch.market == "coupang" else mo.stock
        new_price = mo.price
        if record_change(session, set_id=ch.set_id, market=ch.market,
                         canonical_sku=sco.canonical_sku, field="stock",
                         source="market", prev_value=sco.mkt_stock, next_value=new_stock):
            changed += 1
        if record_change(session, set_id=ch.set_id, market=ch.market,
                         canonical_sku=sco.canonical_sku, field="price",
                         source="market", prev_value=sco.mkt_price, next_value=new_price):
            changed += 1
        sco.mkt_stock = new_stock
        sco.mkt_price = new_price
        sco.mkt_fetched_at = now
    return {"ok": True, "fetched": fetched, "changed": changed}


def collect_set(session, set_id, fetcher=fetch_market_options):
    """구성의 모든 채널(상품번호 있는) 일괄 수집."""
    chans = (session.query(SetChannel)
             .filter(SetChannel.set_id == set_id,
                     SetChannel.market_product_id.isnot(None)).all())
    out = []
    for ch in chans:
        r = collect_channel(session, ch.id, fetcher=fetcher)
        out.append({"channel_id": ch.id, "market": ch.market, **r})
    return {"ok": True, "channels": out}


def collect_all_linked_sets(session, fetcher=fetch_market_options):
    """연동된 모든 구성의 판매처 현재값 일괄 수집(주기 작업용). 마켓 쓰기 0(읽기+로컬)."""
    from lemouton.sets.models import SetChannel
    set_ids = [r[0] for r in session.query(SetChannel.set_id).distinct().all()]
    done = 0
    for sid in set_ids:
        try:
            collect_set(session, sid, fetcher=fetcher)
            done += 1
        except Exception:
            session.rollback()
    return {"ok": True, "sets": done}
