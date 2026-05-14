"""SS 가격 결정 래퍼 — 옵션 리스트를 색상별 그룹으로 분리해 처리."""
from collections import defaultdict
from .color_group import decide_ss_color_group
from .models import Decision


def decide_ss(
    options: list[dict],
    *,
    fee_rate: float = 0.06,
    delivery_fee: int = 3000,
    rounding_unit: int = 100,
) -> list[Decision]:
    """옵션 리스트 → SS 가격 결정 리스트.
    옵션을 (model_code, color_code) 그룹으로 분리해 색상 단위 통일 적용.
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for opt in options:
        sku = opt["canonical_sku"]
        # canonical_sku format: 모델-색상-사이즈 (한글 가능)
        # color_code 가 명시되어 있으면 그것 사용, 아니면 sku 파싱
        color_code = opt.get("color_code")
        model_code = opt.get("model_code")
        if not (color_code and model_code):
            parts = sku.rsplit("-", 2)  # 끝에서 2번 split
            if len(parts) == 3:
                model_code, color_code, _ = parts
        groups[(model_code, color_code)].append(opt)

    results = []
    for (mc, cc), grp_options in groups.items():
        results.extend(decide_ss_color_group(
            grp_options,
            fee_rate=fee_rate,
            delivery_fee=delivery_fee,
            rounding_unit=rounding_unit,
        ))
    return results
