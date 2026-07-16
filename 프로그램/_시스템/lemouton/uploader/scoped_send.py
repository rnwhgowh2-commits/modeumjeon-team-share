# -*- coding: utf-8 -*-
"""스코프 실전송 코어 — 지정 SKU/구성만 1회 전송(연속 스케줄러와 분리).

이 모듈이 실전송 안전 코어의 단일 진실 원천이다:
  · resolve_send_mode — 실어댑터 사용 3중 게이트(want_live + confirmed + 서버키).
  · run — 스코프 원샷 전송(기본 드라이런, run_uploader 재사용으로 price_guard·DLQ 보존).
  · skus_for_set / preview_for_set — 실전송 테스트 화면(구성 단위)용 헬퍼.

CLI(scripts/live_send_skus.py)와 라우트(webapp/routes/live_send_test.py)가 공용으로 쓴다.
"""
from __future__ import annotations

import os


def resolve_send_mode(*, want_live: bool, confirmed: bool, server_key_on: bool):
    """(use_real: bool, refusal_reason: str|None). real 은 3조건 모두 참일 때만."""
    if not want_live:
        return False, None
    if not confirmed:
        return False, "실전송하려면 --i-understand-live-send 확인 플래그가 필요합니다(드라이런으로 실행)."
    if not server_key_on:
        return False, "서버키 MOUM_LIVE_UPLOAD 가 꺼져 있습니다. 배포 env 설정·재배포(사용자) 후 재시도(드라이런으로 실행)."
    return True, None


def _server_key_on() -> bool:
    from lemouton.uploader.runtime import live_upload_enabled
    return live_upload_enabled()


def scope_c_output_to_markets(c_output: dict, markets) -> dict:
    """C 페이로드를 선택 마켓으로만 스코프(순수). 실제 전송도 선택 마켓에 한정.

    markets 가 비었으면(None/[]) 원본 그대로. 아니면 'alerts' 키는 보존하고,
    각 마켓 키는 markets 에 포함된 것만 payload 를 유지하고 나머지는 빈 dict {} 로
    비운다 — run_uploader 는 c_output.get(market) 를 돌므로 빈 dict = 그 마켓 미전송.
    원본 dict 는 변경하지 않는다(부작용 없음).
    """
    if not markets:
        return c_output
    keep = set(markets)
    out: dict = {}
    for key, val in c_output.items():
        if key == "alerts":
            out[key] = val                 # alerts 보존
        elif key in keep:
            out[key] = val                 # 선택 마켓 payload 유지
        else:
            out[key] = {}                  # 미선택 마켓 → 빈 dict(미전송)
    return out


def run(skus, *, want_live: bool, confirmed: bool, force: bool = False,
        markets=None) -> dict:
    """스코프 원샷 전송. use_real 이면 실어댑터, 아니면 드라이런. 결과 dict 반환.

    지정 skus(canonical_sku)만 build_c_output(only_skus=)로 스코프 → 다른 상품은
    후보에 들어가지 않는다. markets 를 주면(비었으면 전 마켓) 선택 마켓으로도 스코프해
    실제 전송이 미선택 마켓으로 새지 않게 한다. automation=None(변동종류 토글 미적용,
    전량 후보). persist=use_real — 드라이런은 커밋하지 않아 기준선 오염 없음.
    """
    from shared.db import SessionLocal
    from lemouton.uploader.runtime import select_adapters, build_sku_by_option
    from lemouton.uploader.orchestrator import run_uploader
    from scripts.verify_pipeline_dryrun import build_c_output

    use_real, refusal = resolve_send_mode(
        want_live=want_live, confirmed=confirmed, server_key_on=_server_key_on())
    session = SessionLocal()
    try:
        c_output = build_c_output(session, only_skus=list(skus))
        c_output = scope_c_output_to_markets(c_output, markets)   # 선택 마켓으로도 스코프
        sku_by_option = build_sku_by_option(session)
        adapters = select_adapters(live=use_real)
        dlq_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "uploader_dlq.jsonl")
        result = run_uploader(
            session, c_output,
            sku_by_option=sku_by_option, adapters=adapters, dlq_path=dlq_path,
            force=force, persist=use_real, automation=None,
        )
    finally:
        session.close()
    return {"use_real": use_real, "refusal": refusal, "skus": list(skus), "result": result}


# ─────────────────────────────────────────────────────────────────────────────
# 직접 값 지정 전송 — 지정 마켓·옵션 1건에 명시값을 밀어 전송 경로 자체를 검증.
# ─────────────────────────────────────────────────────────────────────────────
def build_explicit_c_output(*, market, model_code_key, product_id,
                            option_id, price, stock) -> dict:
    """명시값 1건만 담은 최소 C 페이로드(순수). 그 마켓·그 옵션 외에는 절대 미포함.

    _extract_uploads 가 마켓별로 읽는 실제 shape 에 맞춘다:
      · smartstore = base_price + 옵션 add_price → base_price=명시가, add_price=0.
      · 그 외(coupang·lotteon·eleven11·auction·gmarket) = 옵션 price 평면값.
    alerts 는 빈 리스트(직접 지정은 크롤 경보 없음).
    """
    if market == "smartstore":
        payload = {
            "product_id": product_id,
            "base_price": price,
            "options": [{"option_id": option_id, "add_price": 0, "stock": stock}],
        }
    else:
        payload = {
            "product_id": product_id,
            "options": [{"option_id": option_id, "price": price, "stock": stock}],
        }
    return {market: {model_code_key: payload}, "alerts": []}


def run_explicit(session, *, canonical_sku, market, market_product_id,
                 market_option_id, new_price, new_stock,
                 want_live: bool, confirmed: bool) -> dict:
    """지정 마켓·옵션 1건에 '명시값'을 전송(변동감지 우회, 게이트는 그대로).

    안전:
      · resolve_send_mode 3중 게이트(want_live+confirmed+서버키) 로 use_real 판정.
        서버키 off 면 use_real=False → 드라이런(외부 호출 0).
      · price_guard(assert_live_sale_price) 로 0/음수/비정수 가격을 전송 전에 차단.
        (드라이런에서도 차단해 화면 검증 시 안전 · 거짓 0원 전송 금지.)
      · 합성 c_output 은 그 마켓·그 옵션만 담는다 — 다른 상품/옵션 절대 미포함.
      · run_uploader(force=True) 재사용 → 명시값이 현재와 같아도 전송(변동감지만 우회),
        price_guard·DLQ·정직한 실패보고(resultCode/UploadResult) 보존. automation=None.
      · 지정 옵션이 matched(등록) 상태가 아니면 정직히 실패 표면화(추측 전송 금지).
    반환: {use_real, refusal, market, option_id, price_error, result}. result 는
    run_uploader 결과(uploaded/failed/held/preview…) 또는 차단 시 None.
    """
    import os
    from shared.platforms.price_guard import assert_live_sale_price, UnsafePriceError
    from lemouton.uploader.runtime import select_adapters, build_sku_by_option
    from lemouton.uploader.orchestrator import run_uploader

    use_real, refusal = resolve_send_mode(
        want_live=want_live, confirmed=confirmed, server_key_on=_server_key_on())

    base = {"use_real": use_real, "refusal": refusal,
            "market": market, "option_id": market_option_id, "price_error": None}

    # 가격 안전 게이트 — 0/음수/비정수는 드라이런에서도 페이로드를 만들지 않는다.
    try:
        price = assert_live_sale_price(new_price, context=f"직접값 {market}/{market_option_id}")
    except UnsafePriceError as e:
        return {**base, "price_error": str(e), "result": None}

    # 지정 옵션이 실제 등록(matched)된 마켓 옵션인지 확인 — 아니면 정직히 실패.
    sku_by_option = build_sku_by_option(session)
    s_opt = str(market_option_id)
    mapped = sku_by_option.get((market, s_opt))
    if mapped is None and s_opt.isdigit():
        mapped = sku_by_option.get((market, int(s_opt)))
    if mapped is None:
        return {**base, "result": None,
                "error": (f"이 옵션({market}/{market_option_id})은 매칭(matched) 상태가 "
                          f"아니어서 전송 대상이 아니에요. 먼저 연동(매칭)이 필요합니다.")}

    c_output = build_explicit_c_output(
        market=market, model_code_key=str(canonical_sku or mapped),
        product_id=market_product_id, option_id=market_option_id,
        price=price, stock=new_stock,
    )
    adapters = select_adapters(live=use_real)
    dlq_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "uploader_dlq.jsonl")
    result = run_uploader(
        session, c_output,
        sku_by_option=sku_by_option, adapters=adapters, dlq_path=dlq_path,
        force=True, persist=use_real, automation=None,
    )
    return {**base, "result": result}


# ─────────────────────────────────────────────────────────────────────────────
# 구성(세트) 단위 헬퍼 — 실전송 테스트 화면.
# ─────────────────────────────────────────────────────────────────────────────
def skus_for_set(session, set_id) -> list[str]:
    """SetProduct(set_id) → SetOption.canonical_sku distinct 목록."""
    from lemouton.sets.models import SetProduct, SetOption

    rows = (
        session.query(SetOption.canonical_sku)
        .join(SetProduct, SetOption.set_product_id == SetProduct.id)
        .filter(SetProduct.set_id == set_id)
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def _keep_market(market: str, markets) -> bool:
    """markets 필터 — 비었으면(또는 None) 전부 통과, 아니면 포함집합만."""
    if not markets:
        return True
    return market in set(markets)


def _preview_row(upload: dict, *, old_price, old_stock, new_price, new_stock) -> dict:
    """미리보기 1행 형태. changed = 가격·재고 중 하나라도 이전값과 다르면 True."""
    return {
        "market": upload["market"],
        "canonical_sku": upload["canonical_sku"],
        "market_option_id": upload["market_option_id"],
        "old_price": old_price,
        "new_price": new_price,
        "old_stock": old_stock,
        "new_stock": new_stock,
        "changed": (old_price != new_price) or (old_stock != new_stock),
    }


def preview_for_set(session, set_id, markets) -> list[dict]:
    """구성의 지정 SKU만 드라이런 산출 → 마켓별 (현재 → 보낼 값) 미리보기 행.

    실어댑터·실전송 없음(집계만). build_c_output 은 저장된 크롤 데이터만 읽고,
    detect_change 는 MarketRegistration 기준선(직전 전송값)만 조회한다.
    """
    from scripts.verify_pipeline_dryrun import build_c_output
    from lemouton.uploader.orchestrator import _extract_uploads
    from lemouton.uploader.runtime import build_sku_by_option
    from lemouton.uploader.changes import detect_change

    skus = skus_for_set(session, set_id)
    if not skus:
        return []
    c_output = build_c_output(session, only_skus=skus)
    sku_by_option = build_sku_by_option(session)
    uploads = _extract_uploads(c_output, sku_by_option)

    rows: list[dict] = []
    for u in uploads:
        if not _keep_market(u["market"], markets):
            continue
        change = detect_change(
            session,
            canonical_sku=u["canonical_sku"], market=u["market"],
            new_price=u["new_price"], new_stock=u["new_stock"],
        )
        rows.append(_preview_row(
            u,
            old_price=change.old_price, old_stock=change.old_stock,
            new_price=change.new_price, new_stock=change.new_stock,
        ))
    return rows
