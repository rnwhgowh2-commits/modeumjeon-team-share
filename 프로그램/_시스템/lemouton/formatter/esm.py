"""옥션·G마켓(ESM 2.0) 페이로드 빌더 (자동전송 formatter 경로).

build_lotteon_payload 와 동형. 옵션별 가격·재고 직접 매핑. 옥션·G마켓은 같은 구조라
market 인자로 구분(auction_product_id/auction_option_id vs gmarket_*).

⚠️ 안전: 모델에 {market}_product_id 가 없으면(미매핑) None 반환 → 오케스트레이터가 이 모델을
건너뜀 → 자동 전송 0. 현재 모든 모델의 auction/gmarket product_id 는 NULL 이므로 이 빌더는
아무 것도 방출하지 않는다(배선만 준비 상태). 실제 자동 전송은 LEMOUTON_LIVE_UPLOAD ON +
옥션/G마켓 상품/옵션 ID 매핑(기존 상품 연동) 후에만 발생.
"""

_MARKETS = ("auction", "gmarket")


def build_esm_payload(
    market: str,
    decisions: list[dict],
    model: dict,
    boxhero_stock_by_sku: dict[str, int],
    external_stock_by_sku: dict[str, int] | None = None,
) -> dict | None:
    """단일 모델의 옥션 또는 G마켓 페이로드 생성. market=auction|gmarket.

    NOT-매핑 모델 ({market}_product_id=NULL) → None 반환(자동전송 대상 아님).
    """
    if market not in _MARKETS:
        raise ValueError(f"ESM 마켓 아님: {market}")
    product_id = model.get(f"{market}_product_id")
    if not product_id:
        return None

    options = []
    for d in decisions:
        option_id = d.get(f"{market}_option_id")
        if not option_id:
            continue

        sku = d["canonical_sku"]
        c = d.get(market, {})
        is_displayed = c.get("displayed", False)
        price = c.get("price", 0) if is_displayed else 0

        stock = 0
        if is_displayed:
            stock = boxhero_stock_by_sku.get(sku, 0)
            if external_stock_by_sku:
                stock += external_stock_by_sku.get(sku, 0)

        color = d.get("color_display", d.get("color_code", ""))
        size = d.get("size_display", d.get("size_code", ""))
        option_name = f"{color} {size}".strip()

        options.append({
            "option_id": option_id,
            "option_name": option_name,
            "price": price,
            "stock": stock,
        })

    return {
        "market": market,
        "product_id": product_id,
        "product_name": model.get("model_name_display", ""),
        "options": options,
    }


def build_auction_payload(decisions, model, boxhero_stock_by_sku, external_stock_by_sku=None):
    return build_esm_payload("auction", decisions, model, boxhero_stock_by_sku, external_stock_by_sku)


def build_gmarket_payload(decisions, model, boxhero_stock_by_sku, external_stock_by_sku=None):
    return build_esm_payload("gmarket", decisions, model, boxhero_stock_by_sku, external_stock_by_sku)
