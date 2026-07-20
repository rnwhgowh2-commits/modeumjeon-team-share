"""롯데온 페이로드 빌더 (자동전송 formatter 경로).
build_coupang_payload 와 동형. 옵션별 가격 직접 매핑.

⚠️ 안전: 모델에 lotteon_product_id 가 없으면(미매핑) None 반환 → 오케스트레이터가
이 모델을 건너뜀 → 자동 전송 0. 현재 모든 모델의 lotteon_product_id 는 NULL 이므로
이 빌더는 아무 것도 방출하지 않는다(배선만 준비 상태). 실제 자동 전송은
MOUM_LIVE_UPLOAD ON + 롯데온 상품/옵션 ID 매핑 후에만 발생.
"""

import logging

logger = logging.getLogger(__name__)


def build_lotteon_payload(
    decisions: list[dict],
    model: dict,
    boxhero_stock_by_sku: dict[str, int],
    external_stock_by_sku: dict[str, int] | None = None,
) -> dict | None:
    """단일 모델의 롯데온 페이로드 생성.

    decisions: 같은 model_code 의 옵션별 [B] 결과 (각각 lotteon 결정 포함, 현재는 빈 dict)
    model: 모델 마스터 dict (lotteon_product_id 등)
    boxhero_stock_by_sku: 사입품 재고 매핑
    external_stock_by_sku: (선택) 외부 소싱 재고 매핑

    NOT-매핑 모델 (lotteon_product_id=NULL) → None 반환(자동전송 대상 아님).
    """
    product_id = model.get("lotteon_product_id")
    if not product_id:
        return None

    options = []
    for d in decisions:
        option_id = d.get("lotteon_option_id")
        if not option_id:
            continue

        sku = d["canonical_sku"]
        c = d.get("lotteon", {})
        # [2026-07-20] 시한폭탄 차단 — 가격 엔진이 이 마켓 결정을 아직 안 만든다
        #   (pricing/engine.py 는 ss·coupang 키만 생성). 그래서 c 는 늘 {} 이고
        #   is_displayed=False → price=0 이 된다. 지금은 lotteon_product_id 가 NULL 이라
        #   방출 자체가 없지만, 나중에 ID 를 채우는 순간 **0원이 그대로 마켓에 나간다**.
        #   0원은 폴백으로 메울 값이 아니므로(정합성 원칙) 방출에서 제외한다.
        is_displayed = c.get("displayed", False)
        price = c.get("price", 0) if is_displayed else 0
        if is_displayed and (not price or int(price) <= 0):
            logger.warning("[lotteon] 판매가 0/미상 — 옵션 제외 sku=%s", sku)
            continue

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
        "market": "lotteon",
        "product_id": product_id,
        "product_name": model.get("model_name_display", ""),
        "options": options,
    }
