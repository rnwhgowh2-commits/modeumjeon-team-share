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


def run(skus, *, want_live: bool, confirmed: bool, force: bool = False) -> dict:
    """스코프 원샷 전송. use_real 이면 실어댑터, 아니면 드라이런. 결과 dict 반환.

    지정 skus(canonical_sku)만 build_c_output(only_skus=)로 스코프 → 다른 상품은
    후보에 들어가지 않는다. automation=None(변동종류 토글 미적용, 전량 후보).
    persist=use_real — 드라이런은 커밋하지 않아 기준선 오염 없음.
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
