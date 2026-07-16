# -*- coding: utf-8 -*-
"""[실전송 테스트] 한 상품(구성)만 안전하게 실제 판매처로 가격·재고를 밀어보는 화면.

안전 불변식:
  · 기본 드라이런. 실제 전송은 3중 게이트(want_live + confirmed + 서버키 MOUM_LIVE_UPLOAD).
  · 지정 구성의 canonical_sku 만 대상 — scoped_send.run(skus_for_set(...)) 로 스코프.
  · 라우트는 어댑터를 임의로 무장하지 않는다. select_adapters(live=use_real)는 run 내부에서만.
  · run_uploader 재사용 → price_guard·DLQ·정직한 실패보고 보존. automation=None.
"""
from flask import Blueprint, render_template, request, jsonify

from shared.db import SessionLocal
from lemouton.sets.models import ProductSet, SetChannel
from lemouton.uploader.scoped_send import run, skus_for_set, preview_for_set

bp = Blueprint("live_send_test", __name__)

# 이 화면이 다루는 마켓(실전송 검증 대상). 표시·필터용 정본.
SEND_MARKETS = [
    {"key": "smartstore", "label": "스마트스토어"},
    {"key": "coupang", "label": "쿠팡"},
    {"key": "lotteon", "label": "롯데온"},
]


def _channels_for_set(session, set_id: int) -> list[dict]:
    rows = (
        session.query(SetChannel.market, SetChannel.account_key,
                      SetChannel.market_product_id, SetChannel.status)
        .filter(SetChannel.set_id == set_id)
        .all()
    )
    return [{
        "market": m, "account_key": ak,
        "market_product_id": mpid, "status": st,
    } for (m, ak, mpid, st) in rows]


@bp.get("/live-send-test")
def index():
    return render_template(
        "live_send_test/index.html",
        active="live_send_test",
        send_markets=SEND_MARKETS,
    )


@bp.get("/api/live-send-test/search")
def api_search():
    """구성(ProductSet) name/model_code LIKE 검색 + 각 구성의 판매처 채널."""
    q = (request.args.get("q") or "").strip()
    session = SessionLocal()
    try:
        query = session.query(ProductSet)
        if q:
            like = f"%{q}%"
            query = query.filter(
                (ProductSet.name.like(like)) | (ProductSet.model_code.like(like)))
        sets = query.order_by(ProductSet.id.desc()).limit(30).all()
        results = [{
            "set_id": ps.id,
            "name": ps.name,
            "model_code": ps.model_code,
            "channels": _channels_for_set(session, ps.id),
        } for ps in sets]
    finally:
        session.close()
    return jsonify({"results": results})


@bp.post("/api/live-send-test/preview")
def api_preview():
    """지정 구성·마켓의 (현재 → 보낼 값) 미리보기. 실전송 없음(드라이런 집계만)."""
    payload = request.get_json(silent=True) or {}
    set_id = payload.get("set_id")
    markets = payload.get("markets") or []
    if set_id is None:
        return jsonify({"ok": False, "error": "set_id 필요"}), 400
    session = SessionLocal()
    try:
        rows = preview_for_set(session, set_id, markets)
    finally:
        session.close()
    return jsonify({"ok": True, "rows": rows})


@bp.post("/api/live-send-test/send")
def api_send():
    """지정 구성만 실제 전송 시도. 3중 게이트 미충족이면 드라이런(use_real False).

    want_live 은 이 화면 성격상 항상 True(실전송 의도). confirmed 는 사용자 확인 체크,
    서버키는 배포 env — 셋 다 참일 때만 실어댑터. 그 외엔 안전하게 드라이런.
    markets 는 결과 표시 필터(대상 SKU 스코프는 run 이 보장).
    """
    payload = request.get_json(silent=True) or {}
    set_id = payload.get("set_id")
    markets = payload.get("markets") or []
    confirmed = bool(payload.get("confirmed"))
    if set_id is None:
        return jsonify({"ok": False, "error": "set_id 필요"}), 400

    session = SessionLocal()
    try:
        skus = skus_for_set(session, set_id)
    finally:
        session.close()

    out = run(skus, want_live=True, confirmed=confirmed)

    # 결과 preview 를 선택 마켓으로만 필터(표시용). 대상 SKU 스코프는 run 이 이미 보장.
    result = out["result"]
    preview = result.get("preview") or {}
    if markets:
        preview = {m: v for m, v in preview.items() if m in set(markets)}
    result = {**result, "preview": preview}

    return jsonify({
        "ok": True,
        "use_real": out["use_real"],
        "refusal": out["refusal"],
        "skus": out["skus"],
        "result": result,
    })
