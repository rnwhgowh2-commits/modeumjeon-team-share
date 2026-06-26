"""[연결] 모음전 옵션 추출 → 마켓 옵션 매칭 → MarketRegistration upsert."""
from __future__ import annotations

from sqlalchemy.orm import Session

from lemouton.sourcing.models import Option
from lemouton.uploader.linker import match_market_options_to_skus
from lemouton.uploader.market_fetch import fetch_market_options
from lemouton.uploader.repository import upsert_registration


def link_bundle_market(
    session: Session,
    *,
    model_code: str,
    market: str,
    market_product_id: str,
    fetcher=fetch_market_options,
) -> dict:
    """모음전 상품(model_code)을 마켓 상품(product_id)에 연결.

    fetcher: (market, product_id) -> FetchResult. 테스트는 가짜 주입.
    matched 옵션만 MarketRegistration 에 status='linked' 로 저장. 마켓에 쓰지 않음.
    """
    options = session.query(Option).filter_by(model_code=model_code).all()
    bundle_options = [
        {
            "canonical_sku": o.canonical_sku,
            "color_code": o.color_code,
            "color_display": o.color_display,
            "size_code": o.size_code,
            "size_display": o.size_display,
        }
        for o in options
    ]

    fr = fetcher(market, market_product_id)
    if not fr.success:
        return {"ok": False, "error": fr.error, "product_name": None,
                "linked": 0, "unmatched": 0, "ambiguous": 0, "rows": []}

    rows = match_market_options_to_skus(bundle_options, fr.options)

    linked = unmatched = ambiguous = 0
    for r in rows:
        if r.status == "matched":
            upsert_registration(
                session,
                canonical_sku=r.canonical_sku, market=market,
                market_product_id=str(market_product_id),
                market_option_id=r.market_option_id,
                status="linked",
            )
            linked += 1
        elif r.status == "ambiguous":
            ambiguous += 1
        else:
            unmatched += 1
    session.commit()

    return {
        "ok": True, "error": None, "product_name": fr.product_name,
        "linked": linked, "unmatched": unmatched, "ambiguous": ambiguous,
        "rows": [r.__dict__ for r in rows],
    }
