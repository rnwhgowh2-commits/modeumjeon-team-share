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
from lemouton.sets.models import ProductSet, SetChannel, SetChannelOption
from lemouton.uploader.scoped_send import (
    run, skus_for_set, preview_for_set, run_explicit,
)

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
    markets 는 run 에 전달해 대상 SKU + 선택 마켓 둘 다로 실제 전송을 스코프한다
    (미선택 마켓으로 전송이 새지 않음).
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

    out = run(skus, want_live=True, confirmed=confirmed, markets=markets)

    return jsonify({
        "ok": True,
        "use_real": out["use_real"],
        "refusal": out["refusal"],
        "skus": out["skus"],
        "result": out["result"],
    })


# ─────────────────────────────────────────────────────────────────────────────
# 직접 값 지정 테스트 — 한 옵션에 명시값을 밀어 전송 경로 자체를 검증.
# ─────────────────────────────────────────────────────────────────────────────
def _channel_for(session, set_id, market):
    """(set_id, market) → SetChannel 1개. account_key 여러 개면 상품번호 있는 것 우선."""
    rows = (session.query(SetChannel)
            .filter(SetChannel.set_id == set_id, SetChannel.market == market)
            .all())
    for ch in rows:
        if ch.market_product_id:
            return ch
    return rows[0] if rows else None


@bp.get("/api/live-send-test/current")
def api_current():
    """지정 구성·마켓의 matched 옵션 목록 + 각 옵션의 '현재 마켓 가격·재고'(읽기).

    마켓에 쓰지 않음(GET·fetch_market_options). 현재값 조회를 지원하지 않는 마켓
    (11번가 상세 스펙 미확보 등)은 옵션 목록은 주되 현재값은 null + note 로 안전 표면화
    (크래시·추측값 금지). 사용자는 그 경우 값을 직접 입력한다.
    """
    from lemouton.uploader.market_fetch import fetch_market_options
    from lemouton.sets.set_link_service import _resolve_env_prefix

    try:
        set_id = int(request.args.get("set_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "set_id 필요"}), 400
    market = (request.args.get("market") or "").strip()
    if not market:
        return jsonify({"ok": False, "error": "market 필요"}), 400

    session = SessionLocal()
    try:
        ch = _channel_for(session, set_id, market)
        if ch is None:
            return jsonify({"ok": False, "error": "연동된 판매처 채널이 없어요."}), 404
        product_id = ch.market_product_id
        if not product_id:
            return jsonify({"ok": False, "error": "상품번호가 입력되지 않았어요."}), 400
        matched = (session.query(SetChannelOption)
                   .filter_by(channel_id=ch.id, status="matched")
                   .filter(SetChannelOption.market_option_id.isnot(None))
                   .all())
        opt_meta = [{
            "market_option_id": str(sco.market_option_id),
            "canonical_sku": sco.canonical_sku,
        } for sco in matched]
        env_prefix = _resolve_env_prefix(session, market, ch.account_key)
    finally:
        session.close()

    if not opt_meta:
        return jsonify({"ok": True, "market": market, "market_product_id": product_id,
                        "options": [], "fetch_ok": False,
                        "note": "매칭된 옵션이 없어요(먼저 연동 실행 필요)."})

    fr = fetch_market_options(market, product_id, env_prefix=env_prefix)
    cur = {}
    if fr.success:
        cur = {str(mo.option_id): mo for mo in fr.options}
    options = []
    for m in opt_meta:
        mo = cur.get(m["market_option_id"])
        options.append({
            "market_option_id": m["market_option_id"],
            "canonical_sku": m["canonical_sku"],
            "color": (mo.color if mo else None),
            "size": (mo.size if mo else None),
            # 쿠팡은 옵션 재고 미제공(None). 롯데온 재고미관리도 None → 센티넬 노출 금지.
            "cur_price": (mo.price if mo else None),
            "cur_stock": (mo.stock if mo else None),
        })
    return jsonify({
        "ok": True, "market": market, "market_product_id": product_id,
        "options": options,
        "fetch_ok": bool(fr.success),
        "note": (None if fr.success else
                 f"현재값 조회 미지원/실패 — 값을 직접 입력하세요. ({fr.error or ''})"),
    })


@bp.post("/api/live-send-test/send-explicit")
def api_send_explicit():
    """지정 마켓·옵션 1건에 명시값 전송. want_live=True 고정(화면 성격), confirmed=body.

    3중 게이트 미충족(서버키 off 등)이면 use_real False → 드라이런(외부 호출 0).
    price_guard 로 0/음수 가격은 전송 전에 차단(price_error). 정직한 실패 표면화.
    """
    payload = request.get_json(silent=True) or {}
    set_id = payload.get("set_id")
    market = (payload.get("market") or "").strip()
    market_option_id = payload.get("market_option_id")
    confirmed = bool(payload.get("confirmed"))
    if set_id is None or not market or market_option_id in (None, ""):
        return jsonify({"ok": False,
                        "error": "set_id · market · market_option_id 필요"}), 400
    try:
        price = int(payload.get("price"))
    except (TypeError, ValueError):
        price = payload.get("price")   # run_explicit 의 price_guard 가 정직히 차단
    stock = payload.get("stock")
    try:
        stock = int(stock)
    except (TypeError, ValueError):
        stock = stock

    session = SessionLocal()
    try:
        ch = _channel_for(session, set_id, market)
        if ch is None or not ch.market_product_id:
            return jsonify({"ok": False, "error": "연동된 판매처 채널/상품번호가 없어요."}), 404
        sco = (session.query(SetChannelOption)
               .filter_by(channel_id=ch.id, status="matched")
               .filter(SetChannelOption.market_option_id == str(market_option_id))
               .first())
        if sco is None:
            return jsonify({"ok": False,
                            "error": "이 옵션은 매칭(matched) 상태가 아니에요."}), 400
        canonical_sku = sco.canonical_sku
        product_id = ch.market_product_id
        try:
            out = run_explicit(
                session,
                canonical_sku=canonical_sku, market=market,
                market_product_id=product_id, market_option_id=str(market_option_id),
                new_price=price, new_stock=stock,
                want_live=True, confirmed=confirmed,
            )
        except Exception as e:   # 실전송 경로 예외를 화면에 정직히 표면화(500 팝업 방지)
            import traceback, logging
            logging.getLogger(__name__).exception("send-explicit 실패")
            return jsonify({
                "ok": False,
                "error": f"전송 실패: {type(e).__name__}: {e}",
                "detail": traceback.format_exc()[-1200:],
            }), 200
    finally:
        session.close()

    return jsonify({
        "ok": True,
        "use_real": out["use_real"],
        "refusal": out["refusal"],
        "price_error": out.get("price_error"),
        "error": out.get("error"),
        "market": out["market"],
        "option_id": out["option_id"],
        "result": out["result"],
    })
