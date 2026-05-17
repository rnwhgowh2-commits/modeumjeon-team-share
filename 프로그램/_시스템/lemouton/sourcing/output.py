"""[A] → [B] 출력 빌더.

aggregated 데이터에 모델 마스터·옵션 매핑·글로벌 설정을 머지해서
spec §4 형식의 JSON 객체를 생성한다.

머지 우선순위 (effective):
  옵션 단위 override > 모델 단위 override > 글로벌 default
"""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from .master import get_option_by_canonical, get_model


def _effective(option_value, model_value, global_value):
    """옵션 → 모델 → 글로벌 순으로 None 아닌 첫 값 반환."""
    if option_value is not None:
        return option_value
    if model_value is not None:
        return model_value
    return global_value


def build_output_for_b(
    session: Session,
    aggregated: dict[str, dict],
    global_config: dict,
) -> dict[str, dict]:
    """canonical_sku 별로 [B]가 받을 객체 dict 생성."""
    out: dict[str, dict] = {}
    now_iso = datetime.now(timezone.utc).isoformat()

    for sku, agg in aggregated.items():
        opt = get_option_by_canonical(session, sku)
        if opt is None:
            continue  # 마스터에 없는 SKU는 출력 스킵
        model = get_model(session, opt.model_code)
        if model is None:
            continue

        pricing = {
            "boxhero_ss_price_effective": _effective(
                None, model.boxhero_ss_price_override,
                global_config.get("boxhero_ss_price_default")),
            "boxhero_coupang_price_effective": _effective(
                None, model.boxhero_coupang_price_override,
                global_config.get("boxhero_coupang_price_default")),
            "external_ss_price_effective": _effective(
                None, model.external_ss_price_override,
                global_config.get("external_ss_price_default")),
            "external_coupang_price_effective": _effective(
                None, model.external_coupang_price_override,
                global_config.get("external_coupang_price_default")),
            "coupang_winner_premium_effective": _effective(
                None, model.coupang_winner_premium_override,
                global_config.get("coupang_winner_premium_price")),
            "guardrail_lower_effective": _effective(
                None, model.guardrail_lower_override,
                global_config.get("guardrail_lower")),
            "guardrail_upper_effective": _effective(
                None, model.guardrail_upper_override,
                global_config.get("guardrail_upper")),
            "external_ss_margin_effective": {
                "mode": _effective(
                    None, model.external_margin_mode_override,
                    global_config.get("external_ss_margin_mode")),
                "value": _effective(
                    None, model.external_ss_margin_value_override,
                    global_config.get("external_ss_margin_value")),
            },
            "external_coupang_margin_effective": {
                "mode": _effective(
                    None, model.external_margin_mode_override,
                    global_config.get("external_coupang_margin_mode")),
                "value": _effective(
                    None, model.external_coupang_margin_value_override,
                    global_config.get("external_coupang_margin_value")),
            },
            "use_margin_formula_for_external_effective": bool(
                opt.use_margin_formula_option or model.use_margin_formula_for_external),
            "option_ss_price_override": opt.option_ss_price_override,
            "option_coupang_price_override": opt.option_coupang_price_override,
            "boxhero_purchase_price_effective": _effective(
                None, model.boxhero_purchase_price_override,
                global_config.get("boxhero_purchase_price_default")),
        }

        out[sku] = {
            "canonical_sku": sku,
            "model_code": opt.model_code,
            "model_display": model.model_name_display or model.model_name_raw,
            "color_display": opt.color_display or opt.color_code,
            "size_display": opt.size_display or opt.size_code,
            "lemouton_only": bool(opt.lemouton_only),

            "boxhero_stock": agg.get("boxhero_stock", 0),
            "boxhero_purchase_price": agg.get("boxhero_purchase_price"),

            "sources": list(agg.get("sources", [])),

            "pricing": pricing,

            "competitor_status": {"ss": None, "coupang": None},

            "last_updated": now_iso,
        }

    return out
