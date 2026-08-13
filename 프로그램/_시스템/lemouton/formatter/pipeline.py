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

    # 🔴 [2026-08-13] 마켓 옵션 이름은 `색상 + 사이즈` 두 칸으로만 만든다
    #   (formatter/esm.py·coupang.py·lotteon.py). 모델모음전 3축은 모델 값이 그 두 칸
    #   어디에도 안 들어가므로, **모델이 달라도 (색상,사이즈)가 같으면 이름이 겹친다.**
    #     메이트 블랙 250 → 「블랙 250」 / 스위트 블랙 250 → 「블랙 250」
    #   그대로 보내면 손님이 못 고르고, 들어온 주문이 어느 모델인지 알 수 없다.
    #
    #   만드는 단계는 멀쩡하다(축 값·SKU·옵션명 전부 다르다) — **전송에서만** 겹친다.
    #   그래서 만들기를 막지 않고 여기서 막는다. 재고 확인 불가와 같은 처방:
    #   틀린 값을 보내느니 그 옵션만 보류하고 **왜인지 말한다.**
    #   「마켓별 옵션 1/2/3축 구성 정책」(상품가공)이 생기면 이 막이는 풀 수 있다.
    for _mc, _decs in list(decisions_by_model.items()):
        _seen: dict[tuple, list] = {}
        for _d in _decs:
            _seen.setdefault((_d.get('color_display') or _d.get('color_code') or '',
                              _d.get('size_display') or _d.get('size_code') or ''),
                             []).append(_d)
        _dupe = [g for g in _seen.values() if len(g) > 1]
        if not _dupe:
            continue
        _hold = {d['canonical_sku'] for g in _dupe for d in g}
        for _k, _g in _seen.items():
            if len(_g) > 1:
                alerts.append({
                    'type': 'option_name_collision',
                    'level': 'warning',
                    'model_code': _mc,
                    'canonical_sku': sorted(d['canonical_sku'] for d in _g),
                    # 🔴 마켓 탓으로 적지 말 것. 스마트스토어는 조합형 3축을 받는다
                    #   (개발자센터 원문: 「최대 등록 가능한 옵션 개수는 조합형은 3개」).
                    #
                    # 🔴 [2026-08-13] 안내를 사실대로 고쳤다. 전송 경로가 **두 갈래**인데
                    #   한쪽만 3축이 된다 —
                    #     · 등록 경로(ProductDraft → compile_smartstore.py:110)
                    #       는 `process_option_axis` 를 읽어 3갈래로 나간다. ✅
                    #     · **이 경로**(모음전 전송 → formatter/smartstore.py:69)는
                    #       옵션 이름을 `color + size` 로만 만든다. 축 설정을 **안 읽는다.**
                    #   그래서 「상품가공에서 3갈래로 바꾸면 풀립니다」는 여기서는 **거짓**이다.
                    #   그렇게 적었다가 사장님이 설정을 바꿔도 아무 일이 안 일어난다.
                    #   formatter 를 3축으로 잇기 전까지는 **없는 해법을 말하지 않는다.**
                    'message': ('마켓 옵션 이름이 겹쳐 전송 보류 — 「%s」 이(가) %d줄입니다. '
                                '모델이 다른 옵션인데, 모음전 전송은 옵션 이름을 '
                                '색상·사이즈로만 만들어서 같은 이름이 됩니다. '
                                '지금은 모델을 나눠서 올리셔야 합니다 '
                                '(모음전 전송의 3갈래는 아직 준비 중입니다).'
                                % (' '.join(x for x in _k if x) or '(빈 이름)', len(_g))),
                })
        decisions_by_model[_mc] = [d for d in _decs
                                   if d['canonical_sku'] not in _hold]
        if not decisions_by_model[_mc]:
            del decisions_by_model[_mc]

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
