"""[C] 메인 포매터 — [A]+[B] 출력 → 마켓별 페이로드 dict."""
from collections import defaultdict
from sqlalchemy.orm import Session

from lemouton.sourcing.master import get_model, get_option_by_canonical
from .smartstore import build_smartstore_payload
from .coupang import build_coupang_payload
from .lotteon import build_lotteon_payload
from .esm import build_auction_payload, build_gmarket_payload
from .stock_policy import resolve_send_stock


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
    # 마켓에 실제로 보낼 최종 재고 (내 재고 + 소싱처 크롤 재고, 상한 100).
    #   payload 빌더의 첫 재고 인자로 넘긴다 — 이미 합산했으므로
    #   external_stock_by_sku 는 넘기지 않는다(이중 합산 방지).
    send_stock_by_sku: dict[str, int] = {}

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
        # ── 보낼 재고 = 내 창고 재고 + 소싱처 크롤 재고 (상한 100) ──
        # 🔴 [2026-08-06] 이전엔 boxhero_stock 만 썼다. 그런데 보내기 경로의
        #   a_output 은 boxhero_stock 을 0 으로 고정해 오므로(산출 불가), 소싱처
        #   크롤 재고를 갖고 있으면서도 **전 옵션에 재고 0(품절)** 을 보내고 있었다.
        #   sources 의 재고를 합산해 그 사고를 끊는다. 상세 = formatter/stock_policy.py
        src_stocks = [s.get("stock") for s in (opt_data.get("sources") or [])]
        resolved, reason = resolve_send_stock(
            opt_data.get("boxhero_stock", 0), src_stocks)
        if resolved is None:
            # 확인 불가 — 0(품절)으로 단정하지 않고 이 옵션만 전송에서 뺀다
            alerts.append({
                "type": "stock_unknown_hold",
                "level": "warning",
                "canonical_sku": sku,
                "message": "재고 확인 불가 — 품절 오전송 방지를 위해 전송 보류",
            })
            continue

        decisions_by_model[opt.model_code].append(merged)
        send_stock_by_sku[sku] = resolved

    # 🔴 [2026-08-13] 여기 있던 `option_name_collision` 막이를 **걷어냈다.**
    #
    #   왜 넣었었나 — 모델모음전 3축은 옵션 이름(색상+사이즈)이 겹치니 보류하자.
    #   왜 걷어내나 — **두 가지가 다 틀렸다.**
    #
    #   ① 겹쳐도 사고가 안 난다. 이 경로가 만드는 `option_name` 을 **읽는 코드가 0곳**이다.
    #      전송은 `uploader/orchestrator._extract_uploads` 가 하는데 그건
    #      `option_id`·`add_price`·`stock` 만 읽는다. 마켓 옵션 **이름은 안 보낸다** —
    #      `platforms/smartstore/edit_product.py` 가 「None 인 인자는 손대지 않는다」라
    #      마켓에 있던 이름이 그대로 보존된다.
    #
    #   ② 막이가 되레 **라이브 전송을 통째로 멈출 수 있었다.**
    #      `uploader/dryrun.py:34` 가
    #        warnings = len(level != 'info' 인 것) + len(alerts)
    #      로 **warning 을 두 번 센다.** 임계는 `orchestrator.py` 의 5.
    #      → 겹치는 묶음 3개면 6 > 5 → `should_hold` → **전 마켓·전 상품 uploaded=0.**
    #      틀린 값을 막으려다 맞는 값까지 못 나가게 하는 막이였다.
    #
    #   진짜 막힘은 **연동(linker)** 에 있다 — 3축으로 등록한 상품은
    #   `platforms/smartstore/get_options.py` 가 `optionName3` 을 버려서
    #   `uploader/linker.py` 가 못 짝지어 `unmatched` 가 되고, 그래서 가격·재고가
    #   **에러 없이 영영 안 나간다.** 거기를 고쳐야 한다(별건).
    #   시험 = tests/test_formatter_axis_collision.py 가 이 사실을 못 박는다.

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

        ss_payload = build_smartstore_payload(model_decisions, model_dict, send_stock_by_sku)
        if ss_payload is not None:
            smartstore_payloads[model_code] = ss_payload
        else:
            alerts.append({
                "type": "naver_product_not_registered",
                "level": "info",
                "model_code": model_code,
                "message": "네이버 신상품 미등록",
            })

        cp_payload = build_coupang_payload(model_decisions, model_dict, send_stock_by_sku)
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
        lo_payload = build_lotteon_payload(model_decisions, model_dict, send_stock_by_sku)
        if lo_payload is not None:
            lotteon_payloads[model_code] = lo_payload

        # 옥션·G마켓(ESM) — {market}_product_id 매핑된 모델만(미매핑이면 None → 자동전송 0).
        au_payload = build_auction_payload(model_decisions, model_dict, send_stock_by_sku)
        if au_payload is not None:
            auction_payloads[model_code] = au_payload
        gm_payload = build_gmarket_payload(model_decisions, model_dict, send_stock_by_sku)
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
