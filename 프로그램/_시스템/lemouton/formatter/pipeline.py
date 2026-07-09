"""[C] 메인 포매터 — [A]+[B] 출력 → 마켓별 페이로드 dict."""
from collections import defaultdict
from sqlalchemy.orm import Session

from lemouton.sourcing.master import get_model, get_option_by_canonical
from .smartstore import build_smartstore_payload
from .coupang import build_coupang_payload
from .lotteon import build_lotteon_payload
from .esm import build_auction_payload, build_gmarket_payload


def run_formatter(
    session: Session,
    a_output: dict[str, dict],
    b_output: dict,
) -> dict:
    """[A] 옵션 dict + [B] 결정 dict → 마켓별 페이로드 dict.

    반환 형식:
      {
        "smartstore": {model_code: payload},
        "coupang": {model_code: payload},
        "alerts": [...]   # [B] alerts 그대로 전달 + 옵션/모델 미매핑 알림 추가
      }
    """
    decisions_by_sku = b_output.get("decisions", {})
    alerts = list(b_output.get("alerts", []))

    # 옵션 단위 데이터 합치기 + 모델 단위 그룹화
    decisions_by_model: dict[str, list[dict]] = defaultdict(list)
    boxhero_by_sku: dict[str, int] = {}

    for sku, opt_data in a_output.items():
        decision = decisions_by_sku.get(sku, {})
        opt = get_option_by_canonical(session, sku)
        if opt is None:
            # 옵션 매핑 없으면 알림 + 스킵
            alerts.append({
                "type": "option_not_mapped",
                "level": "warning",
                "canonical_sku": sku,
                "message": "옵션 매핑 없음 — 마스터 매핑 필요",
            })
            continue

        merged = {
            "canonical_sku": sku,
            "model_code": opt.model_code,
            "color_code": opt.color_code,
            "color_display": opt.color_display,
            "size_code": opt.size_code,
            "size_display": opt.size_display,
            "lemouton_only": bool(opt.lemouton_only),
            "naver_option_id": opt.naver_option_id,
            "coupang_option_id": opt.coupang_option_id,
            "lotteon_option_id": opt.lotteon_option_id,
            "auction_option_id": opt.auction_option_id,
            "gmarket_option_id": opt.gmarket_option_id,
            "ss": decision.get("ss", {}),
            "coupang": decision.get("coupang", {}),
            "lotteon": decision.get("lotteon", {}),
            "auction": decision.get("auction", {}),
            "gmarket": decision.get("gmarket", {}),
        }
        decisions_by_model[opt.model_code].append(merged)
        boxhero_by_sku[sku] = opt_data.get("boxhero_stock", 0)

    smartstore_payloads: dict[str, dict] = {}
    coupang_payloads: dict[str, dict] = {}
    lotteon_payloads: dict[str, dict] = {}
    auction_payloads: dict[str, dict] = {}
    gmarket_payloads: dict[str, dict] = {}

    for model_code, model_decisions in decisions_by_model.items():
        m = get_model(session, model_code)
        if m is None:
            alerts.append({
                "type": "model_not_mapped",
                "level": "warning",
                "model_code": model_code,
                "message": "모델 마스터 없음",
            })
            continue
        model_dict = {
            "model_code": m.model_code,
            "model_name_display": m.model_name_display,
            "naver_product_id": m.naver_product_id,
            "coupang_product_id": m.coupang_product_id,
            "lotteon_product_id": m.lotteon_product_id,
            "auction_product_id": m.auction_product_id,
            "gmarket_product_id": m.gmarket_product_id,
            "naver_product_name_override": m.naver_product_name_override,
            "coupang_product_name_override": m.coupang_product_name_override,
        }

        ss_payload = build_smartstore_payload(model_decisions, model_dict, boxhero_by_sku)
        if ss_payload is not None:
            smartstore_payloads[model_code] = ss_payload
        else:
            alerts.append({
                "type": "naver_product_not_registered",
                "level": "info",
                "model_code": model_code,
                "message": "네이버 신상품 미등록",
            })

        cp_payload = build_coupang_payload(model_decisions, model_dict, boxhero_by_sku)
        if cp_payload is not None:
            coupang_payloads[model_code] = cp_payload
        else:
            alerts.append({
                "type": "coupang_product_not_registered",
                "level": "info",
                "model_code": model_code,
                "message": "쿠팡 신상품 미등록",
            })

        # 롯데온 — lotteon_product_id 매핑된 모델만(미매핑이면 None → 방출 안 함, 자동전송 0).
        lo_payload = build_lotteon_payload(model_decisions, model_dict, boxhero_by_sku)
        if lo_payload is not None:
            lotteon_payloads[model_code] = lo_payload

        # 옥션·G마켓(ESM) — {market}_product_id 매핑된 모델만(미매핑이면 None → 자동전송 0).
        au_payload = build_auction_payload(model_decisions, model_dict, boxhero_by_sku)
        if au_payload is not None:
            auction_payloads[model_code] = au_payload
        gm_payload = build_gmarket_payload(model_decisions, model_dict, boxhero_by_sku)
        if gm_payload is not None:
            gmarket_payloads[model_code] = gm_payload

    return {
        "smartstore": smartstore_payloads,
        "coupang": coupang_payloads,
        "lotteon": lotteon_payloads,
        "auction": auction_payloads,
        "gmarket": gmarket_payloads,
        "alerts": alerts,
    }
