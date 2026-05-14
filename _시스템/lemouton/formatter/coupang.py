"""쿠팡 페이로드 빌더.

옵션별 가격 직접 매핑. SS와 달리 색상 단위 통일 없음.
"""


def build_coupang_payload(
    decisions: list[dict],
    model: dict,
    boxhero_stock_by_sku: dict[str, int],
    external_stock_by_sku: dict[str, int] | None = None,
) -> dict | None:
    """단일 모델의 쿠팡 페이로드 생성.

    decisions: 같은 model_code의 옵션별 [B] 결과 (각각 coupang 결정 포함)
    model: 모델 마스터 dict (coupang_product_id, coupang_product_name_override 등)
    boxhero_stock_by_sku: 사입품 재고 매핑
    external_stock_by_sku: (선택) 외부 소싱 재고 매핑

    NOT-등록 모델 (coupang_product_id=NULL) → None 반환.
    """
    product_id = model.get("coupang_product_id")
    if not product_id:
        return None

    options = []
    for d in decisions:
        option_id = d.get("coupang_option_id")
        if not option_id:
            continue

        sku = d["canonical_sku"]
        c = d.get("coupang", {})
        is_displayed = c.get("displayed", False)
        price = c.get("price", 0) if is_displayed else 0

        stock = 0
        if is_displayed:
            stock = boxhero_stock_by_sku.get(sku, 0)
            if external_stock_by_sku:
                stock += external_stock_by_sku.get(sku, 0)

        # 쿠팡은 단일 텍스트 옵션명
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
        "market": "coupang",
        "product_id": product_id,
        "product_name": model.get("coupang_product_name_override")
                        or model.get("model_name_display", ""),
        "options": options,
    }
