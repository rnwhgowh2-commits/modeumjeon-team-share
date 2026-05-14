"""스마트스토어 페이로드 빌더.

[B] 결정 + 모델 메타 → 네이버 커머스 API 형식.
색상 단위 기준가 + 가산금액 표현.
"""


def build_smartstore_payload(
    decisions: list[dict],
    model: dict,
    boxhero_stock_by_sku: dict[str, int],
    external_stock_by_sku: dict[str, int] | None = None,
) -> dict | None:
    """단일 모델의 스마트스토어 페이로드 생성.

    decisions: 같은 model_code의 옵션별 [B] 결과 (각각 ss 결정 포함)
    model: 모델 마스터 dict (naver_product_id, naver_product_name_override 등)
    boxhero_stock_by_sku: 사입품 재고 매핑
    external_stock_by_sku: (선택) 외부 소싱 재고 매핑

    NOT-등록 모델 (naver_product_id=NULL) → None 반환.
    """
    product_id = model.get("naver_product_id")
    if not product_id:
        return None

    # lemouton_only 제외
    visible = [d for d in decisions if not d.get("lemouton_only", False)]
    if not visible:
        return {
            "market": "smartstore",
            "product_id": product_id,
            "product_name": model.get("naver_product_name_override")
                            or model.get("model_name_display", ""),
            "base_price": 0,
            "options": [],
        }

    # 기준가 = 표시되는 옵션 중 SS 가격 MIN
    displayed_prices = [d["ss"]["price"] for d in visible
                        if d["ss"].get("displayed", False) and d["ss"].get("price", 0) > 0]
    base_price = min(displayed_prices) if displayed_prices else 0

    options = []
    for d in visible:
        option_id = d.get("naver_option_id")
        if not option_id:
            # 미등록 옵션은 페이로드에서 제외 (옵션 매핑 필요)
            continue

        sku = d["canonical_sku"]
        ss = d.get("ss", {})
        is_displayed = ss.get("displayed", False)
        price = ss.get("price", 0) if is_displayed else 0

        add_price = max(0, price - base_price) if is_displayed and price > 0 else 0

        # 재고: 사입품 + 외부 (활용된 부분), displayed=False면 0
        stock = 0
        if is_displayed:
            stock = boxhero_stock_by_sku.get(sku, 0)
            if external_stock_by_sku:
                stock += external_stock_by_sku.get(sku, 0)

        options.append({
            "option_id": option_id,
            "option_name": f"{d.get('color_display', d.get('color_code', ''))} / {d.get('size_display', d.get('size_code', ''))}",
            "add_price": add_price,
            "stock": stock,
        })

    return {
        "market": "smartstore",
        "product_id": product_id,
        "product_name": model.get("naver_product_name_override")
                        or model.get("model_name_display", ""),
        "base_price": base_price,
        "options": options,
    }
