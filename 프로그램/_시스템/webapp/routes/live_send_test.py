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
#: 🔴 [2026-08-12] 여기가 3개로 잠겨 있어서 옥션·G마켓·11번가 상품은 화면에서
#:    **고를 수조차 없었다**. `scoped_send._account_adapter` 는 진작 6마켓을 다
#:    만들 수 있었는데 목록만 안 늘린 것 — 「코드가 없다」와 「목록에 안 적었다」는
#:    다른 문제고, 뒤엣것은 에러도 안 나서 있는 기능이 없는 것처럼 굳는다.
#:    같은 날 6마켓 전부 라이브 왕복(가격 +100 · 재고 ±1 → 원복)으로 실측하고 열었다.
SEND_MARKETS = [
    {"key": "smartstore", "label": "스마트스토어"},
    {"key": "coupang", "label": "쿠팡"},
    {"key": "lotteon", "label": "롯데온"},
    {"key": "eleven11", "label": "11번가"},
    {"key": "auction", "label": "옥션"},
    {"key": "gmarket", "label": "G마켓"},
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
    try:
        from lemouton.sourcing.models_v2 import UploadAccount
        _accts = [{"account_key": x.account_key, "display_name": x.display_name,
                   "env_prefix": x.env_prefix}
                  for x in session.query(UploadAccount).filter_by(market=market).all()]
    except Exception:
        _accts = []
    return jsonify({
        "ok": True, "market": market, "market_product_id": product_id,
        "options": options,
        "fetch_ok": bool(fr.success),
        "account_key": ch.account_key,       # 진단: 채널 계정명
        "env_prefix": env_prefix,            # 진단: 해석된 계정 prefix(None=매핑실패)
        "accounts_debug": _accts,            # 진단: 그 마켓의 등록 계정들
        "note": (None if fr.success else
                 f"현재값 조회 미지원/실패 — 값을 직접 입력하세요. ({fr.error or ''})"),
    })


# ─────────────────────────────────────────────────────────────────────────────
# 직접(세트 연동 없이) 진단 — 실제 마켓 상품을 뽑아 조회·전송 검증.
#   세트에 연동되지 않은 마켓(롯데온·11번가)의 실상품으로 전송 경로를 검증하기 위한 도구.
#   pick-orders: 최근 주문에서 실제 (상품번호·단품번호) 후보를 수집.
#   direct-current/direct-send: env_prefix+상품번호로 세트 없이 바로 조회/전송.
# ─────────────────────────────────────────────────────────────────────────────
@bp.get("/api/live-send-test/accounts")
def api_accounts():
    """마켓의 활성 계정 목록 [(env_prefix, 표시명)]. 계정 지정 검증용."""
    market = (request.args.get("market") or "").strip()
    if not market:
        return jsonify({"ok": False, "error": "market 필요"}), 400
    from lemouton.markets import order_export as _oe
    accts = _oe._active_accounts(market) or []
    return jsonify({"ok": True, "market": market,
                    "accounts": [{"env_prefix": ep, "display_name": nm}
                                 for ep, nm in accts]})


@bp.get("/api/live-send-test/pick-orders")
def api_pick_orders():
    """최근 주문에서 실제 상품 후보(상품번호·단품번호)를 수집. 세트 연동 불필요.

    ?market=lotteon|eleven11&days=14&limit=20&env_prefix=... . env_prefix 주면 그 계정만.
    """
    market = (request.args.get("market") or "").strip()
    want_prefix = (request.args.get("env_prefix") or "").strip() or None
    try:
        days = max(1, min(int(request.args.get("days") or 14), 120))
    except (TypeError, ValueError):
        days = 14
    try:
        limit = max(1, min(int(request.args.get("limit") or 20), 100))
    except (TypeError, ValueError):
        limit = 20
    if market not in ("lotteon", "eleven11"):
        return jsonify({"ok": False, "error": "market 은 lotteon·eleven11 만 지원"}), 400

    from datetime import datetime, timedelta
    from lemouton.markets import order_export as _oe
    until = datetime.now()
    since = until - timedelta(days=days)
    accts = _oe._active_accounts(market) or [(None, "대표 계정")]
    if want_prefix:
        accts = [(ep, nm) for ep, nm in accts if ep == want_prefix]
    seen, out, warnings = set(), [], []
    for env_prefix, alias in accts:
        if len(out) >= limit:
            break
        try:
            client = _oe._account_client(market, env_prefix)
            if market == "lotteon":
                from shared.platforms.lotteon.orders import iter_delivery_orders
                for od in iter_delivery_orders(since, until, client=client):
                    pid = str(_oe._g(od, "spdNo", default="") or "")
                    oid = str(_oe._g(od, "sitmNo", default="") or "")
                    if not pid or not oid:
                        continue
                    key = (env_prefix, pid, oid)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"alias": alias, "env_prefix": env_prefix,
                                "product_id": pid, "option_id": oid,
                                "name": str(_oe._g(od, "spdNm", default="") or ""),
                                "option": str(_oe._g(od, "sitmNm", default="") or "")})
                    if len(out) >= limit:
                        break
            else:  # eleven11 — 결제완료뿐 아니라 배송준비·완료·구매확정도 훑어 상품번호 확보
                from shared.platforms.eleven11 import orders as _e11o
                iters = [_e11o.iter_orders, _e11o.iter_preparing,
                         _e11o.iter_delivered, _e11o.iter_completed]
                for _it in iters:
                    if len(out) >= limit:
                        break
                    try:
                        for od in _it(since, until, client=client):
                            pid = str(od.get("prdNo") or od.get("prdNoStr") or "")
                            if not pid:
                                continue
                            oid = str(od.get("mixOptNo") or od.get("optCd") or "")
                            key = (env_prefix, pid, oid)
                            if key in seen:
                                continue
                            seen.add(key)
                            out.append({"alias": alias, "env_prefix": env_prefix,
                                        "product_id": pid, "option_id": oid,
                                        "name": str(od.get("prdNm") or ""),
                                        "option": str(od.get("slctPrdOptNm")
                                                      or od.get("optNm") or "")})
                            if len(out) >= limit:
                                break
                    except Exception as e:  # noqa: BLE001
                        warnings.append(f"{alias}/{_it.__name__}: "
                                        f"{type(e).__name__}: {str(e)[:120]}")
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{alias}: {type(e).__name__}: {str(e)[:150]}")
    return jsonify({"ok": True, "market": market, "count": len(out),
                    "candidates": out, "warnings": warnings})


@bp.get("/api/live-send-test/direct-current")
def api_direct_current():
    """세트 없이 (market, env_prefix, product_id)로 옵션·현재 가격/재고 조회."""
    market = (request.args.get("market") or "").strip()
    env_prefix = (request.args.get("env_prefix") or "").strip() or None
    product_id = (request.args.get("product_id") or "").strip()
    if not market or not product_id:
        return jsonify({"ok": False, "error": "market·product_id 필요"}), 400
    from lemouton.uploader.market_fetch import fetch_market_options
    try:
        fr = fetch_market_options(market, product_id, env_prefix=env_prefix)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 200
    if not fr.success:
        return jsonify({"ok": False, "error": fr.error or "옵션 조회 실패"}), 200
    opts = [{"market_option_id": str(o.option_id), "color": o.color, "size": o.size,
             "cur_price": o.price, "cur_stock": o.stock} for o in fr.options]
    return jsonify({"ok": True, "market": market, "product_id": product_id,
                    "product_name": fr.product_name, "count": len(opts), "options": opts})


@bp.post("/api/live-send-test/direct-send")
def api_direct_send():
    """세트 없이 실제 마켓 상품 옵션 1건에 명시 가격/재고 전송(검증용).

    body: {market, env_prefix, product_id, option_id, price, stock, confirmed}.
    서버키(MOUM_LIVE_UPLOAD)+confirmed 둘 다 참일 때만 실전송, 아니면 드라이런.
    """
    p = request.get_json(silent=True) or {}
    market = str(p.get("market") or "").strip()
    env_prefix = (str(p.get("env_prefix") or "").strip() or None)
    product_id = str(p.get("product_id") or "").strip()
    option_id = str(p.get("option_id") or "").strip()
    confirmed = bool(p.get("confirmed"))
    stock_only = bool(p.get("stock_only"))  # 가격 미확인 마켓(11번가) 재고만 검증
    if not market or not product_id or not option_id:
        return jsonify({"ok": False, "error": "market·product_id·option_id 필요"}), 400
    try:
        stock = int(p.get("stock"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "stock 는 정수"}), 400
    if stock < 0:
        return jsonify({"ok": False, "error": "재고는 0 이상이어야 해요."}), 400
    if not stock_only:
        try:
            price = int(p.get("price"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "price 는 정수"}), 400
        if price <= 0:
            return jsonify({"ok": False, "error": "가격은 양수여야 해요."}), 400

    from lemouton.uploader.scoped_send import _account_adapter, _server_key_on
    use_real = bool(_server_key_on() and confirmed)

    # [2026-07-20] 이 경로는 run_uploader 를 우회해 어댑터를 직접 부른다(검증 화면 특성).
    #   그래서 표준 경로가 갖는 안전장치가 빠져 있었다 — 최소한 **가격 가드**는 여기서도 건다.
    #   scoped_send.run_explicit(:173) 와 같은 함수를 써서 0·음수·비정상 가격을 전송 전에 차단.
    #   (수동 확인 전송이라 confirmed 가 사람 게이트 역할을 하므로 autosend_mode 는 요구하지 않는다.)
    if not stock_only:
        from shared.platforms.price_guard import assert_live_sale_price, UnsafePriceError
        try:
            price = assert_live_sale_price(price, context=f"직접값 {market}/{option_id}")
        except UnsafePriceError as e:
            return jsonify({"ok": False, "use_real": use_real,
                            "error": f"가격 가드: {e}"}), 400
    try:
        if stock_only:
            # 재고만 변경(가격 미접촉). 11번가=재고번호 PUT, 롯데온=옵션 재고.
            if not use_real:
                r = type("R", (), {"success": True, "http_status": None})()
            elif market == "eleven11":
                from lemouton.uploader.market_fetch import _eleven11_client
                from shared.platforms.eleven11.stocks_query import get_stocks
                from shared.platforms.eleven11.inventory import update_stock_by_stock_no
                cli = _eleven11_client(env_prefix)
                cur = [o for o in get_stocks(product_id, client=cli)
                       if str(o.get("prd_stck_no")) == option_id]
                if not cur:
                    return jsonify({"ok": False, "use_real": use_real,
                                    "error": f"재고번호 {option_id} 미발견"}), 200
                sr = update_stock_by_stock_no(product_id, option_id, stock,
                                              cur[0].get("opt_wght"), client=cli)
                r = type("R", (), {"success": sr.success, "http_status": None,
                                   "error": sr.error_message})()
            elif market == "lotteon":
                from lemouton.uploader.market_fetch import _lotteon_client
                from shared.platforms.lotteon.inventory import update_stock
                ok = update_stock(product_id, option_id, stock,
                                  client=_lotteon_client(env_prefix))
                r = type("R", (), {"success": bool(ok), "http_status": None,
                                   "error": None if ok else "재고 변경 실패"})()
            else:
                return jsonify({"ok": False, "error": "stock_only 는 eleven11·lotteon만"}), 400
        else:
            adapter = _account_adapter(market, env_prefix, live=use_real)
            r = adapter.update_price_and_stock(
                canonical_sku=f"DIRECT:{product_id}:{option_id}",
                market_product_id=product_id, market_option_id=option_id,
                new_price=price, new_stock=stock)
    except Exception as e:  # noqa: BLE001
        import traceback
        return jsonify({"ok": False, "use_real": use_real,
                        "error": f"전송 실패: {type(e).__name__}: {e}",
                        "detail": traceback.format_exc()[-1000:]}), 200
    return jsonify({"ok": bool(r.success), "use_real": use_real, "market": market,
                    "product_id": product_id, "option_id": option_id,
                    "http_status": getattr(r, "http_status", None),
                    "error": None if r.success else (r.error or "전송 실패")})


@bp.get("/api/live-send-test/current-stock")
def api_current_stock():
    """선택한 옵션 1건의 현재 재고 조회(온디맨드). 쿠팡=vendorItemId inventories.

    옵션 전량 조회는 느려서(상품당 수십~수백), 화면에서 고른 옵션 하나만 조회한다.
    실패/미지원은 stock=null + note 로 안전 표면화(0 날조 금지).
    """
    try:
        set_id = int(request.args.get("set_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "set_id 필요"}), 400
    market = (request.args.get("market") or "").strip()
    option = (request.args.get("option") or "").strip()
    if not market or not option:
        return jsonify({"ok": False, "error": "market·option 필요"}), 400
    session = SessionLocal()
    try:
        ch = _channel_for(session, set_id, market)
        if ch is None:
            return jsonify({"ok": False, "error": "연동된 채널이 없어요."}), 404
        from lemouton.sets.set_link_service import _resolve_env_prefix
        env_prefix = _resolve_env_prefix(session, market, ch.account_key)
        stock, note = None, None
        if market == "coupang":
            try:
                from lemouton.uploader.market_fetch import _coupang_client
                from shared.platforms.coupang.inventory import get_quantity
                stock = get_quantity(int(option), client=_coupang_client(env_prefix))
                if stock is None:
                    note = "재고를 가져오지 못했어요(값을 직접 입력하세요)."
            except Exception as e:  # noqa: BLE001
                note = f"재고 조회 실패: {e}"
        else:
            note = "이 마켓은 옵션 조회에서 이미 재고를 제공합니다."
    finally:
        session.close()
    return jsonify({"ok": True, "market": market, "option": option,
                    "stock": stock, "note": note})


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
        # ★그 상품이 등록된 계정의 키로 전송(다계정) — 조회와 동일한 env_prefix 사용.
        from lemouton.sets.set_link_service import _resolve_env_prefix
        env_prefix = _resolve_env_prefix(session, market, ch.account_key)
        try:
            out = run_explicit(
                session,
                canonical_sku=canonical_sku, market=market,
                market_product_id=product_id, market_option_id=str(market_option_id),
                new_price=price, new_stock=stock,
                want_live=True, confirmed=confirmed, env_prefix=env_prefix,
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

@bp.get("/api/live-send-test/product-list")
def api_product_list():
    """[2026-07-20] 마켓 상품 목록 조회 — **읽기 전용**. 마켓에 아무것도 쓰지 않는다.

    왜: 「판매처 연동」을 하려면 그 마켓의 실제 상품번호를 알아야 하는데, 지금까지는
      사람이 셀러 어드민에서 눈으로 보고 옮겨 적어야 했다. 데이터 코드 지도(상품 조회)에
      각 마켓의 목록 조회 API 가 문서로 확보돼 있어 그대로 연결한다.

    query: market, account(=UploadAccount.account_key), limit
    [주의] 응답 필드 스펙이 지도에 미확보(res 비어 있음) → **원본 응답을 그대로 돌려준다**.
       여기서 상품번호 필드를 추측해 뽑지 않는다(틀린 번호로 연동하면 남의 상품에 가격이 간다).
    """
    market = (request.args.get("market") or "").strip()
    account = (request.args.get("account") or "").strip()
    all_accounts = request.args.get("all") == "1"

    # [2026-07-20] 계정 문제냐 API 문제냐를 가른다.
    #   롯데온 product/list 가 returnCode 9000 인데, 지도상 product/detail 도 '검증대기'라
    #   "상세는 되고 목록만 안 된다"는 근거가 없었다. 계정 전체 × (인증·상세·목록)을 한 번에.
    if market == "lotteon" and all_accounts:
        from lemouton.sourcing.models_v2 import UploadAccount
        from lemouton.uploader import market_fetch as MF
        from shared.platforms.lotteon.client import LotteonClient
        from shared.platforms import LOTTEON
        from datetime import datetime, timedelta
        _s = SessionLocal()
        try:
            accts = (_s.query(UploadAccount)
                     .filter_by(market="lotteon", is_active=True)
                     .order_by(UploadAccount.id).all())
            acct_rows = [(a.display_name, a.env_prefix) for a in accts]
        finally:
            _s.close()
        _now = datetime.now()
        _probe_spd = (request.args.get("spd") or "").strip()
        report = []
        for name, envp in acct_rows:
            base = MF._lotteon_client(envp) or LotteonClient()
            cfg = {**(getattr(base, "_cfg", None) or LOTTEON),
                   "max_retries": 1, "retry_backoff_sec": 0, "request_timeout_sec": 8}
            cli = LotteonClient(config=cfg)
            row = {"계정": name, "trNo있음": bool(cfg.get("tr_no"))}
            for label, path, body in [
                ("인증확인", cfg["paths"].get("identity"),
                 {"trGrpCd": cfg.get("tr_grp_cd", "SR"), "trNo": cfg.get("tr_no", "")}),
                ("목록조회", cfg["paths"].get("list"),
                 {"trGrpCd": cfg.get("tr_grp_cd", "SR"), "trNo": cfg.get("tr_no", ""),
                  "regStrtDttm": (_now - timedelta(days=30)).strftime("%Y%m%d%H%M%S"),
                  "regEndDttm": _now.strftime("%Y%m%d%H%M%S"),
                  "pageNo": 1, "rowsPerPage": 10}),
            ] + ([("상세조회", cfg["paths"].get("detail"),
                   {"trGrpCd": cfg.get("tr_grp_cd", "SR"), "trNo": cfg.get("tr_no", ""),
                    "lrtrNo": cfg.get("lrtr_no", ""), "spdNo": _probe_spd})]
                 if _probe_spd else []):
                if not path:
                    row[label] = "경로없음"
                    continue
                try:
                    resp = cli.request(method="POST", path=path, body=body)
                    row[label] = f"rc={resp.get('returnCode')} {str(resp.get('message') or '')[:24]}"
                except Exception as ex:   # noqa: BLE001
                    row[label] = str(ex)[:90]
            report.append(row)
        return jsonify({"ok": True, "mode": "계정 전수 진단", "report": report})
    limit = min(int(request.args.get("limit") or 20), 100)
    days = int(request.args.get("days") or 365)      # 조회 기간(마켓마다 상한이 다름)
    sale_status = (request.args.get("status") or "").strip() or None
    if not market:
        return jsonify({"ok": False, "error": "market 필요"}), 400

    from lemouton.sourcing.models_v2 import UploadAccount
    s = SessionLocal()
    try:
        q = s.query(UploadAccount).filter_by(market=market, is_active=True)
        if account:
            q = q.filter_by(account_key=account)
        acct = q.order_by(UploadAccount.id).first()
        if acct is None:
            return jsonify({"ok": False, "error": f"{market} 계정을 찾을 수 없어요."}), 404
        env_prefix, acct_name = acct.env_prefix, acct.display_name
    finally:
        s.close()

    try:
        if market == "lotteon":
            # [2026-07-20] 원인 규명 완료(pageNo·rowsPerPage 필수) → 정식 호출로 교체.
            #   q 를 주면 상품명(spdNm)으로 거르고, 없으면 첫 페이지만.
            from lemouton.uploader import market_fetch as MF
            from shared.platforms.lotteon.client import LotteonClient
            from shared.platforms.lotteon.products import list_products
            from shared.platforms import LOTTEON
            from datetime import datetime as _dt, timedelta as _td
            import html as _html
            _base_cli = MF._lotteon_client(env_prefix) or LotteonClient()
            _cfg = {**(getattr(_base_cli, "_cfg", None) or LOTTEON),
                    "max_retries": 1, "retry_backoff_sec": 0, "request_timeout_sec": 15}
            _cli = LotteonClient(config=_cfg)
            q = (request.args.get("q") or "").strip()
            max_pages = min(int(request.args.get("pages") or (20 if q else 1)), 50)
            _now = _dt.now()
            rows, scanned = [], 0
            for pg in range(1, max_pages + 1):
                page = list_products(
                    client=_cli, page_no=pg, rows_per_page=100,
                    reg_start=(_now - _td(days=days)).strftime("%Y%m%d%H%M%S"),
                    reg_end=_now.strftime("%Y%m%d%H%M%S"),
                    sale_status=sale_status)
                if not page:
                    break
                scanned += len(page)
                for r in page:
                    if q and q.lower() not in _html.unescape(
                            str(r.get("spdNm") or "")).lower():
                        continue
                    rows.append(r)
                if len(rows) >= limit or len(page) < 100:
                    break
            return jsonify({"ok": True, "market": market, "account": acct_name,
                            "scanned": scanned, "count": len(rows),
                            "rows": [{"spdNo": r.get("spdNo"),
                                      "spdNm": _html.unescape(str(r.get("spdNm") or "")),
                                      "slStatCd": r.get("slStatCd"),
                                      "items": len(r.get("sitmNoLst") or [])}
                                     for r in rows[:limit]]})
        elif market == "eleven11":
            # [2026-07-20] 「다중 상품 조회」 = 조건 검색. limit 필수, prdNm 으로 이름 검색.
            from lemouton.uploader import market_fetch as MF
            from shared.platforms.eleven11.products import search_products
            q = (request.args.get("q") or "").strip() or None
            rows = search_products(client=MF._eleven11_client(env_prefix),
                                   name=q, limit=min(limit, 100),
                                   sale_status=(sale_status or None))
            return jsonify({"ok": True, "market": market, "account": acct_name,
                            "count": len(rows), "rows": rows[:limit]})
        elif market in ("auction", "gmarket"):
            # [2026-07-20] 실호출 400 진단 — GET/POST·siteId 유무를 한 번에 시험하고 본문을 본다.
            #   (지도=POST / 권한신청서 엑셀=GET 로 메서드가 갈려 있어 실호출로 확정한다)
            if request.args.get("probe") == "1":
                import requests as _rq
                from lemouton.uploader import market_fetch as MF
                from shared.platforms import AUCTION as _CFG
                _cli = MF._esm_client(market, env_prefix)
                _hdr = _cli._headers()
                _base = _cli.base_url + _CFG["paths"]["search"]
                _q = (request.args.get("q") or "").strip() or None
                _sid = "1" if market == "auction" else "2"
                trials = []
                variants = [
                    ("POST body siteId", "POST", None,
                     {"pageIndex": 0, "pageSize": 10, "siteId": _sid, **({"keyword": _q} if _q else {})}),
                    ("POST body no-site", "POST", None,
                     {"pageIndex": 0, "pageSize": 10, **({"keyword": _q} if _q else {})}),
                    ("GET query siteId", "GET",
                     {"pageIndex": 0, "pageSize": 10, "siteId": _sid, **({"keyword": _q} if _q else {})}, None),
                    ("POST body pageSize500", "POST", None,
                     {"pageIndex": 0, "pageSize": 500, "siteId": _sid}),
                ]
                for label, meth, params, jbody in variants:
                    try:
                        r = _rq.request(meth, _base, headers=_hdr, params=params,
                                        json=jbody, timeout=15)
                        trials.append({"변형": label, "status": r.status_code,
                                       "본문": r.text[:280]})
                    except Exception as ex:   # noqa: BLE001
                        trials.append({"변형": label, "실패": str(ex)[:150]})
                return jsonify({"ok": True, "mode": "ESM 400 진단",
                                "market": market, "account": acct_name, "trials": trials})
            from lemouton.uploader import market_fetch as MF
            from shared.platforms.esm.products import search_goods
            q = (request.args.get("q") or "").strip() or None
            _cli = MF._esm_client(market, env_prefix)
            # scan=1 이면 전 페이지 순회 + 서버측 이름 필터. 분당 30회 한도 안에서
            #   최대 10페이지(500×10=5,000건)까지.
            # ★ [2026-07-23 정정] 예전 주석은 "ESM keyword 는 실측상 무시됨" 이라 적고
            #   이 순회를 기본으로 삼았는데, **무시의 원인은 우리 요청 모양이었다** —
            #   조건을 `query` 객체에 넣지 않고 최상위에 보내서 ESM 이 통째로 버린 것.
            #   search_goods 를 고친 뒤 keyword 가 정상 동작한다(실측: "니트" 46건).
            #   그래서 아래 기본 경로(한 번 호출)로 충분하고, scan 은 대조용으로만 남긴다.
            if request.args.get("scan") == "1" and q:
                import time as _t
                items = []
                page = 1
                total = None
                while page <= 10:
                    res = search_goods(client=_cli, market=market, page_index=page,
                                       sell_status=(sale_status or None), page_size=500)
                    batch = res.get("items") or []
                    total = res.get("totalItems")
                    items += [it for it in batch
                              if q in str(it.get("goodsName") or it.get("goodsNm") or "")]
                    if not batch or page * 500 >= int(total or 0):
                        break
                    page += 1
                    _t.sleep(2.2)   # 분당 30회 한도
                return jsonify({"ok": True, "market": market, "account": acct_name,
                                "mode": f"scan {page}p", "total": total,
                                "count": len(items),
                                "rows": [{"goodsNo": it.get("goodsNo"),
                                          "goodsName": it.get("goodsName") or it.get("goodsNm"),
                                          "sellStatus": it.get("sellStatus"),
                                          "siteGoodsNo": it.get("siteGoodsNo") or {}}
                                         for it in items[:50]]})
            res = search_goods(client=_cli,
                               keyword=q, market=market, page_index=1,
                               sell_status=(sale_status or None),
                               page_size=min(limit, 500))
            items = res.get("items") or []
            return jsonify({"ok": True, "market": market, "account": acct_name,
                            "total": res.get("totalItems"), "count": len(items),
                            "rows": [{"goodsNo": it.get("goodsNo"),
                                      "siteGoodsNo": (it.get("siteGoodsNo") or {}),
                                      "goodsName": it.get("goodsName") or it.get("goodsNm"),
                                      "sellStatus": it.get("sellStatus"),
                                      "managedCode": it.get("managedCode")}
                                     for it in items[:limit]]})
        else:
            return jsonify({"ok": False, "market": market, "account": acct_name,
                            "error": f"{market} 목록 조회는 아직 연결 전이에요."}), 200
    except Exception as e:   # noqa: BLE001 — 실패를 성공으로 둔갑시키지 않는다
        import traceback
        return jsonify({"ok": False, "market": market, "account": acct_name,
                        "sent": {"days": days, "status": sale_status},
                        "error": f"{type(e).__name__}: {e}",
                        "detail": traceback.format_exc()[-800:]}), 200

    return jsonify({"ok": True, "market": market, "account": acct_name,
                    "count": len(rows), "rows": rows[:limit]})

@bp.get("/api/live-send-test/product-detail")
def api_product_detail():
    """[2026-07-20] 기존 등록 상품의 콘텐츠를 역으로 읽는다 — 4대 마켓 등록 재료 확보용.

    르무통 메이트가 이미 쿠팡·스스에 올라가 있으니, 그 상세(상품명·옵션·가격·이미지·카테고리)를
    읽어 ProductDraft 를 채우는 근거로 쓴다. 읽기 전용.
    query: market(coupang|smartstore), product_id, account
    """
    market = (request.args.get("market") or "").strip()
    product_id = (request.args.get("product_id") or "").strip()
    account = (request.args.get("account") or "").strip()
    if not market or not product_id:
        return jsonify({"ok": False, "error": "market·product_id 필요"}), 400

    from lemouton.sourcing.models_v2 import UploadAccount
    s = SessionLocal()
    try:
        q = s.query(UploadAccount).filter_by(market=market, is_active=True)
        if account:
            q = q.filter_by(account_key=account)
        acct = q.order_by(UploadAccount.id).first()
        env_prefix = acct.env_prefix if acct else None
        acct_name = acct.display_name if acct else "(기본)"
    finally:
        s.close()

    try:
        from lemouton.uploader import market_fetch as MF
        if market == "coupang":
            from shared.platforms.coupang.products import get_product, extract_vendor_items
            detail = get_product(int(product_id), client=MF._coupang_client(env_prefix))
            items = extract_vendor_items(detail)
            return jsonify({"ok": True, "market": market, "account": acct_name,
                            "name": detail.get("sellerProductName"),
                            "category": detail.get("displayCategoryCode"),
                            "brand": detail.get("brand"),
                            "images_count": len(detail.get("images") or []),
                            "option_count": len(items),
                            "options": items[:20],
                            "top_keys": list(detail.keys())[:25]})
        elif market in ("auction", "gmarket"):
            # [2026-07-20] 옥션 상세 — 등록에 재사용할 선행자원(출하지·발송정책·배송정책·
            #   카테고리·상품정보고시)을 기존 상품에서 확보한다.
            from shared.platforms.esm.products import get_goods_detail
            d = get_goods_detail(product_id, client=MF._esm_client(market, env_prefix))
            ai = d.get("itemAddtionalInfo") or d.get("itemAdditionalInfo") or {}
            bi = d.get("itemBasicInfo") or {}
            ship = ai.get("shipping") or {}
            pol = ship.get("policy") or {}
            return jsonify({"ok": True, "market": market, "account": acct_name,
                            "goodsNo": d.get("goodsNo"),
                            "카테고리": (bi.get("category") or {}),
                            "출하지placeNo": pol.get("placeNo"),
                            "발송정책": ship.get("dispatchPolicyNo"),
                            "묶음배송": (pol.get("bundle") or {}).get("deliveryTmplId"),
                            "배송type": ship.get("type"),
                            "택배사": ship.get("companyNo"),
                            "반품교환": ship.get("returnAndExchange"),
                            "상품고시No": (ai.get("officialNotice") or {}).get("officialNoticeNo"),
                            "상품고시details": (ai.get("officialNotice") or {}).get("details"),
                            "면세": ai.get("isVatFree"),
                            "대표이미지": (ai.get("images") or {}).get("basicImgURL"),
                            "옵션type": (ai.get("recommendedOpts") or {}).get("type"),
                            "top_keys": list(d.keys())[:20],
                            "ai_keys": list(ai.keys())[:30]})
        else:
            return jsonify({"ok": False, "market": market,
                            "error": f"{market} 상세 역읽기는 아직 연결 전이에요."}), 200
    except Exception as e:   # noqa: BLE001
        import traceback
        return jsonify({"ok": False, "market": market, "account": acct_name,
                        "error": f"{type(e).__name__}: {e}",
                        "detail": traceback.format_exc()[-600:]}), 200

@bp.post("/api/live-send-test/register-esm")
def api_register_esm():
    """[2026-07-20] 옥션·G마켓 상품 등록 — dry-run(기본) / 실등록(arm 2중잠금).

    body: {market, account, goods_name, cat_code, site_cat_code, price, stock,
           place_no, dispatch_policy_no, return_addr_no, delivery_company_no,
           official_notice_no, official_notice_details[], image_url, detail_html,
           options[], arm}
     실등록은 arm=='1' AND 서버 MOUM_LIVE_UPLOAD 둘 다 켜야. 아니면 payload만 조립해 돌려준다.
    """
    p = request.get_json(silent=True) or {}
    market = (p.get("market") or "").strip()
    if market not in ("auction", "gmarket"):
        return jsonify({"ok": False, "error": "market 은 auction/gmarket"}), 400
    account = (p.get("account") or "").strip()
    site_type = 1 if market == "auction" else 2

    from shared.platforms.esm.products import build_esm_register_payload, register_goods
    payload = build_esm_register_payload(
        market=market, goods_name=p.get("goods_name") or "",
        cat_code=p.get("cat_code") or "", site_cat_code=p.get("site_cat_code") or "",
        site_type=site_type, price=int(p.get("price") or 0), stock=int(p.get("stock") or 1),
        place_no=int(p.get("place_no") or 0), dispatch_policy_no=int(p.get("dispatch_policy_no") or 0),
        return_addr_no=str(p.get("return_addr_no") or ""),
        delivery_company_no=int(p.get("delivery_company_no") or 0),
        official_notice_no=int(p.get("official_notice_no") or 0),
        official_notice_details=p.get("official_notice_details") or [],
        image_url=p.get("image_url") or "", detail_html=p.get("detail_html") or "",
        options=p.get("options") or None, is_vat_free=bool(p.get("is_vat_free")))

    import os as _os
    armed = (str(p.get("arm")) == "1") and (_os.environ.get("LIVE_REGISTER_ARMED") == "1")
    if not armed:
        return jsonify({"ok": True, "mode": "dry-run(조립만)", "market": market,
                        "armed": False, "payload": payload,
                        "note": "실등록하려면 arm=1 + 서버 LIVE_REGISTER_ARMED=1 둘 다 필요"})

    from lemouton.sourcing.models_v2 import UploadAccount
    from lemouton.uploader import market_fetch as MF
    s2 = SessionLocal()
    try:
        q = s2.query(UploadAccount).filter_by(market=market, is_active=True)
        if account:
            q = q.filter_by(account_key=account)
        acct = q.order_by(UploadAccount.id).first()
        env_prefix = acct.env_prefix if acct else None
        acct_name = acct.display_name if acct else "(기본)"
    finally:
        s2.close()
    try:
        result = register_goods(payload, client=MF._esm_client(market, env_prefix))
        return jsonify({"ok": True, "mode": "실등록", "market": market, "account": acct_name,
                        "armed": True, "result": result})
    except Exception as e:  # noqa: BLE001
        import traceback
        # ESM 4xx 사유 표면화 — requests.HTTPError 는 .response.text 에 거부 사유를 담고 있다
        _resp = getattr(e, "response", None)
        esm_body = None
        if _resp is not None:
            try:
                esm_body = (_resp.text or "")[:800]
            except Exception:  # noqa: BLE001
                esm_body = None
        return jsonify({"ok": False, "mode": "실등록", "market": market,
                        "error": f"{type(e).__name__}: {e}",
                        "esm_body": esm_body,
                        "detail": traceback.format_exc()[-800:]}), 200


@bp.post("/api/live-send-test/suspend-esm")
def api_suspend_esm():
    """[2026-07-21] 옥션·G마켓 상품 판매중지 — set_sold_out(isSell=false) 호출.

    판매를 **내리는** 안전한 방향이라 arm 게이트 없이 항상 동작한다(오버셀 차단이
    목적이므로 등록 게이트가 꺼져 있어도 언제든 내릴 수 있어야 함).
    body: {market, account, goodsNo}
    성공 판정: set_sold_out True + 재조회 isSell 의 해당 사이트 값이 false.
    """
    p = request.get_json(silent=True) or {}
    market = (p.get("market") or "").strip()
    if market not in ("auction", "gmarket"):
        return jsonify({"ok": False, "error": "market 은 auction/gmarket"}), 400
    goods_no = str(p.get("goodsNo") or p.get("goods_no") or "").strip()
    if not goods_no:
        return jsonify({"ok": False, "error": "goodsNo 필수 — 없으면 상품을 못 내림"}), 400
    account = (p.get("account") or "").strip()

    from lemouton.sourcing.models_v2 import UploadAccount
    from lemouton.uploader import market_fetch as MF
    from shared.platforms.esm.inventory import set_sold_out, get_sell_status
    s2 = SessionLocal()
    try:
        q = s2.query(UploadAccount).filter_by(market=market, is_active=True)
        if account:
            q = q.filter_by(account_key=account)
        acct = q.order_by(UploadAccount.id).first()
        env_prefix = acct.env_prefix if acct else None
        acct_name = acct.display_name if acct else "(기본)"
    finally:
        s2.close()

    def _ci(container, key):
        for kk, vv in (container or {}).items():
            if str(kk).lower() == str(key).lower():
                return vv
        return None

    try:
        client = MF._esm_client(market, env_prefix)
        ok = set_sold_out(goods_no, market, client=client)
        # 검증 — isSell 재조회(대소문자 무시). auction=iac, gmarket=gmkt
        is_sell_after = None
        site_key = "iac" if market == "auction" else "gmkt"
        try:
            cur = get_sell_status(goods_no, client=client)
            is_sell = _ci(cur, "isSell") or {}
            is_sell_after = {"gmkt": _ci(is_sell, "gmkt"), "iac": _ci(is_sell, "iac")}
        except Exception as ve:  # noqa: BLE001
            is_sell_after = f"(재조회 실패: {type(ve).__name__})"
        suspended = bool(ok) and isinstance(is_sell_after, dict) \
            and (is_sell_after.get(site_key) is False)
        return jsonify({"ok": bool(ok), "mode": "판매중지", "market": market,
                        "account": acct_name, "goodsNo": goods_no,
                        "sold_out_ok": bool(ok), "site_key": site_key,
                        "isSell_after": is_sell_after, "suspended_verified": suspended})
    except Exception as e:  # noqa: BLE001
        import traceback
        return jsonify({"ok": False, "mode": "판매중지", "market": market,
                        "goodsNo": goods_no, "error": f"{type(e).__name__}: {e}",
                        "detail": traceback.format_exc()[-800:]}), 200


def _first_account_env(market: str, account: str = ""):
    """market 의 활성 UploadAccount(account 지정 시 그 키) → (env_prefix, 표시명)."""
    from lemouton.sourcing.models_v2 import UploadAccount
    s2 = SessionLocal()
    try:
        q = s2.query(UploadAccount).filter_by(market=market, is_active=True)
        if account:
            q = q.filter_by(account_key=account)
        acct = q.order_by(UploadAccount.id).first()
        return (acct.env_prefix if acct else None,
                acct.display_name if acct else "(기본)")
    finally:
        s2.close()


@bp.get("/api/live-send-test/eleven11-prereq")
def api_eleven11_prereq():
    """[2026-07-21] 11번가 등록 선행자원 프로브(읽기 전용).

    출고지/반품지 주소 조회(outboundarea) 응답 **원문 XML** + (q= 주면) 기존상품 참고행.
    응답 스펙이 지도에 미확보라 원문을 그대로 보여주고 사람이 addrSeq 를 정한다.
    """
    from lemouton.uploader import market_fetch as MF
    env_prefix, acct_name = _first_account_env(
        "eleven11", (request.args.get("account") or "").strip())
    client = MF._eleven11_client(env_prefix)
    out = {"ok": True, "account": acct_name}
    try:
        from shared.platforms.eleven11.products import get_outbound_areas_xml
        out["outbound_xml"] = (get_outbound_areas_xml(client=client) or "")[:4000]
    except Exception as e:  # noqa: BLE001
        out["outbound_error"] = f"{type(e).__name__}: {e}"
    # 반품/교환지 — outboundarea(루트 inOutAddresss)와 대칭 경로를 실측 프로브(읽기 GET).
    #   등록 실측 에러 "반품/교환지 정보를 찾을수가 없습니다" → 반품지 addrSeq 는 별도.
    try:
        out["inbound_xml"] = (client or __import__(
            "shared.platforms.eleven11.client", fromlist=["Eleven11Client"]
        ).Eleven11Client()).request("GET", "/rest/areaservice/inboundarea")[:4000]
    except Exception as e:  # noqa: BLE001
        out["inbound_error"] = f"{type(e).__name__}: {str(e)[:300]}"
    q = (request.args.get("q") or "").strip()
    if q:
        try:
            from shared.platforms.eleven11.products import search_products
            out["rows"] = search_products(client=client, name=q, limit=5)[:5]
        except Exception as e:  # noqa: BLE001
            out["rows_error"] = f"{type(e).__name__}: {e}"
    # 단품(옵션)별 재고 조회 — stocks=prdNo (읽기 전용 POST·중첩 ProductStock 규격)
    stocks_prd = (request.args.get("stocks") or "").strip()
    if stocks_prd:
        try:
            from shared.platforms.eleven11.stocks_query import get_stocks
            out["stocks_prdNo"] = stocks_prd
            out["stocks"] = get_stocks(stocks_prd, client=client)
        except Exception as e:  # noqa: BLE001
            out["stocks_error"] = f"{type(e).__name__}: {str(e)[:300]}"
    # 범용 읽기 프로브 — 카테고리/주소/고시 등 **조회성 경로만** 화이트리스트로 허용.
    #   (지도에 응답 스펙이 안 펼쳐진 조회 API 를 실측하기 위한 통로. 주문/정산 경로 불허)
    probe = (request.args.get("probe") or "").strip()
    if probe:
        _ALLOWED = ("/rest/cateservice", "/rest/areaservice",
                    "/rest/prodservices/notification", "/rest/commonservices",
                    "/rest/prodservices/product/details",   # 단일상품 전체조회(읽기) — 고시 실값 수확
                    "/rest/prodmarketservice/prodmarket")   # 상품 조회(읽기)
        if probe.startswith(_ALLOWED):
            try:
                out["probe_path"] = probe
                out["probe_xml"] = (client.request("GET", probe) or "")[:60000] if client \
                    else None
            except Exception as e:  # noqa: BLE001
                out["probe_error"] = f"{type(e).__name__}: {str(e)[:400]}"
        else:
            out["probe_error"] = "허용되지 않은 경로(조회성 화이트리스트만)"
    return jsonify(out)


@bp.get("/api/live-send-test/esm-options-probe")
def api_esm_options_probe():
    """[2026-07-21] ESM 옵션 봉투 실측 프로브(읽기 전용) — GET recommended-options 원문.

    query: market=auction|gmarket, goodsNo=. 옵션 등록(조합형 미러링) 구조 확인용.
    """
    market = (request.args.get("market") or "auction").strip()
    goods_no = (request.args.get("goodsNo") or "").strip()
    cat_code = (request.args.get("catCode") or "").strip()   # 카테고리별 옵션코드 조회
    opt_no = (request.args.get("optNo") or "").strip()       # 옵션별 선택항목 조회
    if market not in ("auction", "gmarket") or not (goods_no or cat_code or opt_no):
        return jsonify({"ok": False,
                        "error": "market=auction|gmarket + goodsNo|catCode|optNo 중 하나"}), 400
    from lemouton.uploader import market_fetch as MF
    env_prefix, acct_name = _first_account_env(market, (request.args.get("account") or "").strip())
    try:
        client = MF._esm_client(market, env_prefix)
        if cat_code:
            path = f"/item/v1/options/recommended-opts?catCode={cat_code}"
        elif opt_no:
            path = f"/item/v1/options/recommended-opts/{opt_no}"
        else:
            path = f"/item/v1/goods/{goods_no}/recommended-options"
        resp = client.request(method="GET", path=path)
        return jsonify({"ok": True, "market": market, "account": acct_name,
                        "path": path, "envelope": resp})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:400]}"}), 200


@bp.get("/api/live-send-test/lotteon-prereq")
def api_lotteon_prereq():
    """[2026-07-21] 롯데온 등록 선행자원 프로브(읽기 전용).

    ①3계약 조회(출고지/반품지·하위거래처·배송비정책 — 등록 전 필수 계약)
    ②판매중 상품 1건 detail(등록 body 는 detail 응답과 동일 구조 — 본보기 수확).
    spd_no= 주면 그 상품 detail. 전부 조회 API 만 호출한다.
    """
    from lemouton.uploader import market_fetch as MF
    env_prefix, acct_name = _first_account_env(
        "lotteon", (request.args.get("account") or "").strip())
    client = MF._lotteon_client(env_prefix)
    if client is None:
        from shared.platforms.lotteon.client import LotteonClient
        client = LotteonClient()
    cfg = getattr(client, "_cfg", {}) or {}
    tr_no = cfg.get("tr_no")
    out = {"ok": True, "account": acct_name, "trNo": tr_no,
           "trGrpCd": cfg.get("tr_grp_cd"), "lrtrNo": cfg.get("lrtr_no")}
    cbody = {"afflTrCd": tr_no}
    if cfg.get("lrtr_no"):
        cbody["afflLrtrCd"] = cfg.get("lrtr_no")
    for key, path in (("dvp_출고지반품지", "/v1/openapi/contract/v1/dvp/getDvpListSr"),
                      ("lrtr_하위거래처", "/v1/openapi/contract/v1/lrtr/selectLrTraderSr"),
                      ("dvl_배송비정책", "/v1/openapi/contract/v1/dvl/getDvCstListSr")):
        try:
            out[key] = client.request("POST", path, body=cbody)
        except Exception as e:  # noqa: BLE001
            out[key + "_error"] = f"{type(e).__name__}: {str(e)[:300]}"
    spd_no = (request.args.get("spd_no") or "").strip()
    status = (request.args.get("status") or "SALE").strip()   # 'ALL'=상태 미지정(전체)
    name_q = (request.args.get("name") or "").strip()          # spdNm 부분일치 검색
    try:
        from shared.platforms.lotteon.products import list_products, get_product_detail
        if not spd_no:
            _kw = {}
            _days = (request.args.get("days") or "").strip()   # 최근 N일 등록분만
            if _days:
                from datetime import datetime as _dt2, timedelta as _td2
                _now2 = _dt2.now()
                _kw["reg_start"] = (_now2 - _td2(days=int(_days))).strftime("%Y%m%d%H%M%S")
                _kw["reg_end"] = _now2.strftime("%Y%m%d%H%M%S")
            rows = list_products(client=client,
                                 sale_status=None if status == "ALL" else status,
                                 rows_per_page=100, **_kw)
            if name_q:
                rows = [r for r in rows if isinstance(r, dict)
                        and name_q in str(r.get("spdNm") or "")]
            out["rows_count"] = len(rows)
            out["sample_rows"] = [{k: r.get(k) for k in list(r.keys())[:10]}
                                  for r in rows[:10] if isinstance(r, dict)]
            spd_no = str((rows[0] or {}).get("spdNo") or "") if rows else ""
        if spd_no:
            out["detail_spdNo"] = spd_no
            out["detail"] = get_product_detail(spd_no, client=client)
    except Exception as e:  # noqa: BLE001
        out["detail_error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return jsonify(out)


@bp.post("/api/live-send-test/register-lotteon")
def api_register_lotteon():
    """[2026-07-21] 롯데온 상품 등록 — raw payload 통과형. dry-run(기본)/실등록(arm 2중잠금).

    body: {payload:{...등록 body 전체 — detail 응답과 동일 구조}, account, arm}
    trGrpCd/trNo 는 계정 cfg 로 강제 주입(다계정 trNo 함정 — 전역 config 쓰면 8888).
    성공판정 = returnCode 0000 + spdNo 수령(거짓 성공 금지).
    """
    p = request.get_json(silent=True) or {}
    payload = p.get("payload") or {}
    if not isinstance(payload, dict) or not payload:
        return jsonify({"ok": False, "error": "payload(등록 body) 필수"}), 400
    from lemouton.uploader import market_fetch as MF
    env_prefix, acct_name = _first_account_env("lotteon", (p.get("account") or "").strip())
    client = MF._lotteon_client(env_prefix)
    if client is None:
        from shared.platforms.lotteon.client import LotteonClient
        client = LotteonClient()
    cfg = getattr(client, "_cfg", {}) or {}
    payload = dict(payload)
    payload["trGrpCd"] = cfg.get("tr_grp_cd", "SR")
    payload["trNo"] = cfg.get("tr_no")

    import os as _os
    armed = (str(p.get("arm")) == "1") and (_os.environ.get("LIVE_REGISTER_ARMED") == "1")
    if not armed:
        return jsonify({"ok": True, "mode": "dry-run(조립만)", "armed": False,
                        "trNo": payload.get("trNo"),
                        "payload_keys": sorted(payload.keys()),
                        "note": "실등록하려면 arm=1 + 서버 LIVE_REGISTER_ARMED=1 둘 다 필요"})
    # 등록 경로 — 정본 yaml(apiNo=87)=/product/regist, 지도=/registration/request(접수형?).
    #   실측 이력: registration/request 는 returnCode 9999+data[] 로 상품이 안 생겼다.
    #   등록 계열 경로만 허용(오픈 릴레이 방지).
    reg_path = (p.get("path") or "/v1/openapi/product/v1/product/regist").strip()
    if not reg_path.startswith("/v1/openapi/product/v1/product/regist"):
        return jsonify({"ok": False, "error": "path 는 등록 계열만 허용"}), 400
    try:
        resp = client.request("POST", reg_path, body=payload)
        rc = str(resp.get("returnCode"))
        data = resp.get("data")
        spd_no = None
        if isinstance(data, dict):
            spd_no = data.get("spdNo")
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            spd_no = data[0].get("spdNo")
        ok = rc in ("0000", "SUCCESS") and bool(spd_no)
        return jsonify({"ok": ok, "mode": "실등록", "armed": True, "account": acct_name,
                        "returnCode": rc, "spdNo": spd_no,
                        "message": str(resp.get("message"))[:300],
                        "subMessages": str(resp.get("subMessages"))[:500],
                        "data_head": str(data)[:600]})
    except Exception as e:  # noqa: BLE001
        import traceback
        return jsonify({"ok": False, "mode": "실등록", "armed": True,
                        "error": f"{type(e).__name__}: {str(e)[:800]}",
                        "detail": traceback.format_exc()[-600:]}), 200


@bp.post("/api/live-send-test/suspend-lotteon")
def api_suspend_lotteon():
    """[2026-07-21] 롯데온 판매종료/품절 — status/change + detail 재조회 검증. 게이트 없음.

    body: {spdNo, slStatCd(기본 END), account}
    """
    p = request.get_json(silent=True) or {}
    spd_no = str(p.get("spdNo") or "").strip()
    if not spd_no:
        return jsonify({"ok": False, "error": "spdNo 필수 — 없으면 상품을 못 내림"}), 400
    stat = (p.get("slStatCd") or "END").strip()
    from lemouton.uploader import market_fetch as MF
    env_prefix, acct_name = _first_account_env("lotteon", (p.get("account") or "").strip())
    client = MF._lotteon_client(env_prefix)
    if client is None:
        from shared.platforms.lotteon.client import LotteonClient
        client = LotteonClient()
    cfg = getattr(client, "_cfg", {}) or {}
    try:
        body = {"spdLst": [{"trGrpCd": cfg.get("tr_grp_cd", "SR"),
                            "trNo": cfg.get("tr_no"),
                            "spdNo": spd_no, "slStatCd": stat}]}
        resp = client.request(
            "POST", "/v1/openapi/product/v1/product/status/change", body=body)
        from shared.platforms.lotteon.products import get_product_detail
        try:
            after = get_product_detail(spd_no, client=client)
            after_stat = after.get("slStatCd")
        except Exception as ve:  # noqa: BLE001
            after_stat = f"(재조회 실패: {type(ve).__name__})"
        return jsonify({"ok": str(resp.get("returnCode")) in ("0000", "SUCCESS"),
                        "mode": "판매상태변경", "account": acct_name, "spdNo": spd_no,
                        "요청상태": stat, "returnCode": resp.get("returnCode"),
                        "message": str(resp.get("message"))[:200],
                        "slStatCd_after": after_stat,
                        "suspended_verified": str(after_stat) == stat})
    except Exception as e:  # noqa: BLE001
        import traceback
        return jsonify({"ok": False, "mode": "판매상태변경", "spdNo": spd_no,
                        "error": f"{type(e).__name__}: {str(e)[:600]}",
                        "detail": traceback.format_exc()[-600:]}), 200


@bp.post("/api/live-send-test/register-eleven11")
def api_register_eleven11():
    """[2026-07-21] 11번가 신규 상품 등록 — dry-run(기본) / 실등록(arm 2중잠금).

    body: {disp_ctgr_no, prd_nm, brand, image_url, detail_html, price, stock,
           as_detail, addr_seq_out, addr_seq_in, return_cost, exchange_cost,
           account, arm}
     실등록은 arm=='1' AND 서버 LIVE_REGISTER_ARMED=1 둘 다(ESM 과 같은 게이트).
    """
    p = request.get_json(silent=True) or {}
    from shared.platforms.eleven11.products import build_register_xml, register_product
    try:
        xml_body = build_register_xml(p)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 400

    import os as _os
    armed = (str(p.get("arm")) == "1") and (_os.environ.get("LIVE_REGISTER_ARMED") == "1")
    if not armed:
        return jsonify({"ok": True, "mode": "dry-run(조립만)", "armed": False,
                        "xml": xml_body,
                        "note": "실등록하려면 arm=1 + 서버 LIVE_REGISTER_ARMED=1 둘 다 필요"})

    from lemouton.uploader import market_fetch as MF
    env_prefix, acct_name = _first_account_env("eleven11", (p.get("account") or "").strip())
    try:
        result = register_product(xml_body, client=MF._eleven11_client(env_prefix))
        return jsonify({"ok": True, "mode": "실등록", "armed": True,
                        "account": acct_name, "result": result})
    except Exception as e:  # noqa: BLE001
        import traceback
        return jsonify({"ok": False, "mode": "실등록", "armed": True,
                        "error": f"{type(e).__name__}: {str(e)[:800]}",
                        "detail": traceback.format_exc()[-800:]}), 200


@bp.post("/api/live-send-test/suspend-eleven11")
def api_suspend_eleven11():
    """[2026-07-21] 11번가 전시중지(판매중단) — 게이트 없음(내리는 안전 방향).

    body: {prdNo, account}
    stop_display(PUT stopdisplay/{prdNo}) 후 get_product_detail 로 selStatCd==105 검증.
    """
    p = request.get_json(silent=True) or {}
    prd_no = str(p.get("prdNo") or p.get("productNo") or "").strip()
    if not prd_no:
        return jsonify({"ok": False, "error": "prdNo 필수 — 없으면 상품을 못 내림"}), 400
    from lemouton.uploader import market_fetch as MF
    from shared.platforms.eleven11.products import stop_display, get_product_detail
    env_prefix, acct_name = _first_account_env("eleven11", (p.get("account") or "").strip())
    client = MF._eleven11_client(env_prefix)
    try:
        res = stop_display(prd_no, client=client)
        try:
            after = get_product_detail(prd_no, client=client)
        except Exception as ve:  # noqa: BLE001
            after = {"error": f"{type(ve).__name__}: {ve}"}
        suspended = str((after or {}).get("sel_stat_cd") or "") == "105"
        return jsonify({"ok": True, "mode": "전시중지", "account": acct_name,
                        "prdNo": prd_no, "stop_resp": res, "detail_after": after,
                        "suspended_verified": suspended})
    except Exception as e:  # noqa: BLE001
        import traceback
        return jsonify({"ok": False, "mode": "전시중지", "prdNo": prd_no,
                        "error": f"{type(e).__name__}: {str(e)[:800]}",
                        "detail": traceback.format_exc()[-800:]}), 200


# ═════════════════════════════════════════════════════════════════════════════
# [2026-08-06] 5축 왕복 실전송 검증 — 바꿔 보내고 · 되읽어 확인하고 · 되돌린다.
#
#   정본 설계: docs/superpowers/specs/2026-08-06-마켓-5축-왕복-실전송-검증-design.md
#   코어:      lemouton/uploader/roundtrip/ (runner·journal·snapshot·markets·probe_image)
#
#   안전 불변식(코어에서 테스트로 못 박음 — 여기선 잠금만 건다):
#     · 2중 잠금 — arm=1 AND 서버키 MOUM_LIVE_UPLOAD 둘 다여야 전송.
#     · 판매중지 상품만. 판매중이면 코어가 거부한다.
#     · 저널(원복 보험)을 못 쓰면 전송하지 않는다.
#     · 원복은 finally — 검증이 깨져도, 예외가 나도 반드시 돈다.
#
#   마켓별 근거(데이터 코드 지도):
#     · smartstore  PUT origin-products/{no}      st=ok   — 5축 · 즉시 반영
#     · auction/gmarket PUT /item/v1/goods/{no}   st=ok   — 5축 · 즉시 반영
#         🔴 isEditableGoodsName=false 면 상품명이 에러 없이 무시된다(조회로 미리 거른다)
#     · coupang / lotteon / eleven11 — 아래 주석 참조(아직 미지원)
# ═════════════════════════════════════════════════════════════════════════════
#: 🔴 [2026-08-07 사고 2건] ESM 상품수정 PUT **자체**가 재심사를 유발해 상품이 잠긴다.
#:    옥션 6390703083(5축) · G마켓 6390711573(**가격 한 축만**) 둘 다 같은 결과 —
#:    첫 전송은 성공하고 몇 초 뒤 원복이 「지식재산권침해 우려(1250/1251) 노출 제한」으로
#:    거부됐다. 저널 손복구도 거부. **되돌릴 수 없는 변경이 남았다.**
#:    처음엔 상품명·브랜드가 방아쇠라고 봤는데, 가격 한 축만 보낸 G마켓도 같아서
#:    **PUT 자체가 원인**임이 드러났다. 원인 규명 전까지 전송을 막는다(조회는 계속 된다).
#: 🟢 [2026-08-12 해소] 원인은 마켓이 아니라 **어느 API 를 쓰느냐**였다.
#:    전체 상품수정 PUT(esm.20)이 재심사를 부른 것이고, 가격·재고 **전용 API**
#:    (esm.186 / esm.26)로 보내면 브랜드 상품도 멀쩡히 왕복한다 — 라이브 실측:
#:      · 옥션  6495431339  59,300→59,400→59,300 · 재고 10→11→10  (잠김 없음)
#:      · G마켓 6495432102  35,300→35,400→35,300 · 재고 10→11→10  (잠김 없음)
#:    그래서 차단을 **마켓 단위에서 축 단위로** 좁힌다. 아직 막는 건 아래 3축뿐이다.
#: 무거운 3축 — 상품명·상세·이미지. 가격·재고와 달리 **손님 화면에 그대로 보이고**,
#: 마켓마다 되돌리기 실패 시 손복구가 어려운 축이다.
HEAVY_AXES = ("name", "detail_html", "image_urls")
_ESM_HEAVY_AXES = HEAVY_AXES        # 옛 이름 유지(참조가 남아 있다)

#: 마켓별 무거운 축 잠금 사유. 값이 있으면 그 마켓의 3축은 막힌다.
#: 🔴 [2026-08-13 전수 조사] 「옥션·G마켓만 막으면 된다」가 **틀렸다.**
#:    쿠팡이 무방비로 열려 있었고, 그쪽이 오히려 돈에 직결된다.
HEAVY_BLOCKED: dict[str, str] = {
    "auction": (
        "옥션의 상품명·상세·이미지 왕복은 아직 막혀 있습니다 — 지금 배선된 경로가 "
        "**전체 상품수정 PUT** 이고, 그 전송 자체가 재심사를 유발해 상품이 잠기고 "
        "원복도 손복구도 거부됩니다(2026-08-07 실측 2건). "
        "가격·재고는 전용 API 라 정상 왕복합니다(2026-08-12 실측)."),
    "coupang": (
        "쿠팡의 상품명·상세·이미지 왕복은 막혀 있습니다 — 이 3축을 보내면 "
        "**가격과 재고가 옛 값으로 되감깁니다**. 전송 시작 시점에 뜬 상품 사본을 그대로 "
        "다시 올리는 구조라, 그 사본 안에 바꾸기 전 가격·재고가 들어 있고 승인이 나는 "
        "순간 그 값으로 돌아갑니다(2026-08-13 코드 확인). "
        "가격·재고는 전용 경로라 정상 왕복합니다(2026-08-12 실측)."),
}
HEAVY_BLOCKED["gmarket"] = HEAVY_BLOCKED["auction"].replace("옥션의", "G마켓의")
_ESM_HEAVY_BLOCKED = HEAVY_BLOCKED["auction"]


def _heavy_axis_refusal(market: str, axes, *, unblocked: bool = False):
    """무거운 축 요청이면 (사유, 막힌축) 을 준다. 통과면 None.

    [중요] 축을 안 주면 5축 전부라 **그때도 막아야 한다** — 기본값이 위험한 쪽으로
       열리면 안 된다.
    """
    if unblocked:
        return None
    why = HEAVY_BLOCKED.get(market)
    if not why:
        return None
    want = tuple(axes or ()) or HEAVY_AXES
    hit = [a for a in HEAVY_AXES if a in want]
    return (why, hit) if hit else None

#: **전송**이 허용된 마켓.
#: 🟢 11번가 — 가격·재고 **전용 API 가 이미 우리 코드에 있었다**(2026-08-08).
#:    「지도에 없다」던 건 상품수정(5축) 얘기고, 가격·재고는 별도 엔드포인트다.
ROUNDTRIP_MARKETS = ("smartstore", "coupang", "lotteon", "eleven11",
                     "auction", "gmarket")

#: **조회**가 허용된 마켓 — 마켓에 아무것도 안 쓰므로 차단과 무관하게 열어 둔다.
#: 🔴 차단을 조회에까지 걸었더니 원인 진단조차 못 했다(2026-08-07).
ROUNDTRIP_READ_MARKETS = ROUNDTRIP_MARKETS

#: 아직 못 붙인 마켓 — **없는 것을 있는 척 하지 않는다.** 거부할 때 이유를 그대로 말한다.
ROUNDTRIP_NOT_YET: dict[str, str] = {}


def _roundtrip_client(market: str, env_prefix):
    from lemouton.uploader import market_fetch as MF
    if market == "smartstore":
        return MF._smartstore_client(env_prefix)
    if market in ("auction", "gmarket"):
        return MF._esm_client(market, env_prefix)
    if market == "coupang":
        return MF._coupang_client(env_prefix)
    if market == "lotteon":
        return MF._lotteon_client(env_prefix)
    if market == "eleven11":
        return MF._eleven11_client(env_prefix)
    raise ValueError(f"왕복 시험 미지원 마켓: {market}")


@bp.get("/api/live-send-test/roundtrip-candidates")
def api_roundtrip_candidates():
    """왕복 시험에 쓸 **판매중지** 상품 후보 (읽기 전용 — 마켓에 아무것도 안 쓴다).

    계정 지정: `env_prefix=SMARTSTORE_2` 를 권장한다. `account` 는 UploadAccount.account_key
    인데 표시명과 달라 화면에서 알 수 없다(표시명을 넣으면 조용히 대표 계정으로 떨어진다
    — 2026-07-25 「대표계정 폴백」 이력과 같은 부류라 여기서 원천 차단).
    `all=1` 이면 활성 계정을 **전부** 훑되 계정을 섞지 않고 계정별로 따로 보고한다.
    """
    market = (request.args.get("market") or "smartstore").strip()
    account = (request.args.get("account") or "").strip()
    want_prefix = (request.args.get("env_prefix") or "").strip()
    scan_all = request.args.get("all") == "1"
    # 사장님 확정(2026-08-07) — 판매중 상품으로 시험한다. on_sale=1 이면 판매중만 고른다.
    want_on_sale = request.args.get("on_sale") == "1"
    pages = min(int(request.args.get("pages") or 3), 20)

    if market not in ROUNDTRIP_READ_MARKETS:
        return jsonify({"ok": False, "market": market, "env_prefix": want_prefix or None,
                        "accounts": [],
                        "error": f"{market} 은 아직 왕복 시험을 지원하지 않아요."}), 400

    def _scan(env_prefix, acct_name):
        row = {"account": acct_name, "env_prefix": env_prefix,
               "scanned_total": None, "candidates": [], "candidate_count": 0,
               "error": None}
        try:
            client = _roundtrip_client(market, env_prefix)
            found = []
            if market == "smartstore":
                from lemouton.uploader.roundtrip.candidates import suspended_from_search
                for page in range(1, pages + 1):
                    resp = client.request("POST", "/external/v1/products/search",
                                          body={"page": page, "size": 100})
                    if row["scanned_total"] is None:
                        row["scanned_total"] = (resp or {}).get("totalElements")
                    found.extend(suspended_from_search(resp or {},
                                                      want="sale" if want_on_sale else "stopped"))
                    if not ((resp or {}).get("contents")):
                        break
            elif market == "lotteon":
                # 롯데온 — **검증된 기존 list_products** 를 쓴다.
                #   손으로 body 를 조립하면 pageNo·rowsPerPage 누락(returnCode 9000)이나
                #   응답 형태 차이(data 가 list/dict 양쪽)를 또 밟는다 — 이미 겪은 이력이다.
                from shared.platforms.lotteon.products import list_products
                from lemouton.uploader.roundtrip.sale_status import is_on_sale, is_stopped
                _lo_check = is_on_sale if want_on_sale else is_stopped
                total = 0
                for page in range(1, pages + 1):
                    rows = list_products(
                        client=client, page_no=page, rows_per_page=100,
                        sale_status=("SALE" if want_on_sale else "STP"))
                    total += len(rows)
                    for r in rows:
                        if not _lo_check("lotteon", (r or {}).get("slStatCd")):
                            continue
                        spd = (r or {}).get("spdNo")
                        if not spd:
                            continue
                        found.append({"origin_product_no": str(spd),
                                      "channel_product_no": None,
                                      "name": r.get("pdNm"),
                                      # 마켓 원값 그대로 — 무엇을 보고 골랐는지 보이게
                                      "status": str(r.get("slStatCd") or "").upper()})
                    if not rows:
                        break
                row["scanned_total"] = total
            elif market == "coupang":
                # 쿠팡 — 상품 목록(seller-products)에서 판매중지만 고른다.
                #   커서(nextToken) 방식이라 페이지 번호가 아니다.
                from shared.platforms import COUPANG
                vid = (getattr(client, "vendor_id", None)
                       or (getattr(client, "_cfg", None) or {}).get("vendor_id"))
                token, total = "", 0
                for _ in range(pages):
                    q = f"vendorId={vid}&maxPerPage=100"
                    if token:
                        q += f"&nextToken={token}"
                    resp = client.request(method="GET",
                                          path=COUPANG["paths"]["create_product"], query=q)
                    rows = (resp or {}).get("data") or []
                    total += len(rows)
                    from lemouton.uploader.roundtrip.sale_status import is_on_sale, is_stopped
                    _cp_check = is_on_sale if want_on_sale else is_stopped
                    for r in rows:
                        st = (r or {}).get("statusName")
                        # 🔴 쿠팡 판매중지는 「부분승인완료·승인반려·상품삭제」다
                        #    (「중지」라는 낱말이 안 들어간다 — 낱말 판정은 0건이 났다).
                        if not _cp_check("coupang", st):
                            continue
                        pid = (r or {}).get("sellerProductId")
                        if not pid:
                            continue
                        found.append({"origin_product_no": str(pid),
                                      "channel_product_no": None,
                                      "name": r.get("sellerProductName"),
                                      "status": st})
                    token = (resp or {}).get("nextToken") or ""
                    if not token or not rows:
                        break
                row["scanned_total"] = total
            elif market == "eleven11":
                # 11번가 — 다중 상품 조회. 판매상태 103=판매중 / 105·106·108=중지.
                #   🔴 요청 필터를 믿지 않고 **응답 행의 selStatCd** 로 다시 거른다
                #      (ESM 이 요청 필터를 무시했던 부류를 선제 차단).
                from shared.platforms.eleven11.products import search_products
                from lemouton.uploader.roundtrip.sale_status import is_on_sale, is_stopped
                _e_check = is_on_sale if want_on_sale else is_stopped
                total = 0
                for page in range(pages):
                    rows = search_products(
                        client=client, limit=100,
                        start=page * 100 + 1, end=(page + 1) * 100,
                        sale_status=("103" if want_on_sale else "105"))
                    total += len(rows)
                    for r in rows:
                        st = (r or {}).get("selStatCd")
                        if not _e_check("eleven11", st):
                            continue
                        prd = (r or {}).get("prdNo")
                        if not prd:
                            continue
                        found.append({"origin_product_no": str(prd),
                                      "channel_product_no": None,
                                      "name": r.get("prdNm"),
                                      "status": str(st or "")})
                    if not rows:
                        break
                row["scanned_total"] = total
            else:
                # ESM — 🔴 sellStatus 요청 필터는 **무시된다**(지도 2026-08-02 실측).
                #   응답 **행의 sellStatus 가 진실**이라 클라이언트에서 걸러야 한다.
                #   22(직권중지)는 마켓이 강제로 세운 상품이라 수정이 거부된다 —
                #   이걸 안 걸러서 2026-08-07 사고 2건이 났다.
                from shared.platforms.esm.products import search_goods
                from lemouton.uploader.roundtrip.candidates import esm_suspended_from_search
                import collections as _c
                dist = _c.Counter()
                site_key = "iac" if market == "auction" else "gmkt"
                for page in range(1, pages + 1):
                    resp = search_goods(client=client, market=market,
                                        sell_status=("11" if want_on_sale else "21"),
                                        page_index=page, page_size=100)
                    if row["scanned_total"] is None:
                        row["scanned_total"] = (resp or {}).get("totalItems")
                    items = (resp or {}).get("items") or []
                    for it in items:
                        st = (it or {}).get("sellStatus")
                        dist[str((st or {}).get(site_key) or "?")] += 1
                    found.extend(esm_suspended_from_search(
                        items, market=market,
                        want="sale" if want_on_sale else "stopped"))
                    if not items:
                        break
                # 진단 — 요청 필터가 무시되는 게 눈에 보이게 상태 분포를 함께 준다.
                row["상태분포"] = dict(dist)
            row["candidates"] = found[:50]
            row["candidate_count"] = len(found)
        except Exception as e:  # noqa: BLE001
            row["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        return row

    if scan_all:
        from lemouton.markets import order_export as _oe
        accts = _oe._active_accounts(market) or []
        rows = [_scan(ep, nm) for ep, nm in accts]
        return jsonify({"ok": True, "market": market, "mode": "전계정",
                        "env_prefix": want_prefix or None, "accounts": rows,
                        "candidate_count": sum(r["candidate_count"] for r in rows)})

    if want_prefix:
        env_prefix, acct_name = want_prefix, want_prefix
        from lemouton.markets import order_export as _oe
        for ep, nm in (_oe._active_accounts(market) or []):
            if ep == want_prefix:
                acct_name = nm
                break
    else:
        env_prefix, acct_name = _first_account_env(market, account)

    row = _scan(env_prefix, acct_name)
    return jsonify({"ok": row["error"] is None, "market": market,
                    "env_prefix": env_prefix, "accounts": [row], **row})


@bp.post("/api/live-send-test/roundtrip")
def api_roundtrip():
    """5축 왕복 1회. body: {market, origin_product_no, account, axes[], arm}"""
    p = request.get_json(silent=True) or {}
    market = (p.get("market") or "smartstore").strip()
    account = (p.get("account") or "").strip()
    raw_no = p.get("origin_product_no") or p.get("product_id")

    def _refuse(msg, **extra):
        return jsonify({"ok": False, "armed": False, "sent": 0,
                        "market": market, "refusal": msg, **extra})

    # 차단은 **실수 방지**용이다 — 원인을 규명하려면 의도적으로 풀 수 있어야 한다.
    #   unblock=1 은 사람이 사유를 알고 켜는 스위치(기본은 계속 막힘).
    unblocked = str(p.get("unblock") or "") == "1"
    allowed = ROUNDTRIP_MARKETS + (ROUNDTRIP_READ_MARKETS if unblocked else ())
    if market not in allowed:
        return _refuse(ROUNDTRIP_NOT_YET.get(
            market, f"{market} 은 아직 왕복 시험을 지원하지 않아요."))
    if not raw_no:
        return _refuse("상품번호(origin_product_no)가 필요해요.")

    # 🔴 무거운 3축(상품명·상세·이미지)은 **마켓별로** 막는다 — 가격·재고는 열려 있다.
    #    축을 안 주면 5축 전부라 그때도 막힌다(기본값이 위험 쪽으로 열리면 안 된다).
    _blk = _heavy_axis_refusal(market, p.get("axes"), unblocked=unblocked)
    if _blk:
        return _refuse(_blk[0], 막힌축=_blk[1])

    # 🔴 [2026-08-13] **판매중 상품 + 무거운 3축**은 같이 켤 수 없다.
    #    사장님이 판매중 상품에 허락한 것은 가격 +100원·재고 +1 뿐이다(2026-08-07).
    #    상품명·상세·사진은 손님과 검색 목록에 그대로 보이고, 몇 초 만에 되돌려도
    #    검색 목록 사진은 한동안 남는다.
    if str(p.get("allow_on_sale") or "") == "1":
        _want = tuple(p.get("axes") or ()) or HEAVY_AXES
        _hit = [a for a in HEAVY_AXES if a in _want]
        if _hit:
            return _refuse(
                "판매중 상품에는 상품명·상세·이미지를 보내지 않습니다 — 손님과 검색 목록에 "
                "그대로 보이고, 되돌려도 검색 목록 사진은 한동안 남습니다. "
                "판매중 상품은 가격·재고만, 무거운 축은 판매중지 상품에서 시험하세요.",
                막힌축=_hit)

    # ── 2중 잠금 ────────────────────────────────────────────────────────────
    armed_req = str(p.get("arm") or "") == "1"
    # 서버키 판정은 시스템 정본(live_upload_enabled)을 그대로 쓴다 — 여기서만 '1' 만
    # 인정하면 서버가 MOUM_LIVE_UPLOAD=true 로 무장됐는데 이 화면만 거부한다.
    from lemouton.uploader.runtime import live_upload_enabled
    server_key = live_upload_enabled()
    if not armed_req:
        return _refuse("실전송하려면 arm=1 이 필요해요(지금은 아무것도 보내지 않았습니다).")
    if not server_key:
        return _refuse("서버키 MOUM_LIVE_UPLOAD 가 꺼져 있어요 — "
                       "배포 env 설정·재배포 후 다시 시도하세요.")

    axes = tuple(p.get("axes") or ()) or None
    # 계정은 env_prefix 우선 — account_key 는 표시명과 달라, 표시명을 넣으면 조용히
    # 대표 계정으로 떨어져 「남의 계정 상품을 못 찾음」이 된다(2026-07-25 이력).
    want_prefix = (p.get("env_prefix") or "").strip()
    if want_prefix:
        env_prefix, acct_name = want_prefix, want_prefix
        from lemouton.markets import order_export as _oe
        for ep, nm in (_oe._active_accounts(market) or []):
            if ep == want_prefix:
                acct_name = nm
                break
    else:
        env_prefix, acct_name = _first_account_env(market, account)

    from lemouton.uploader.roundtrip.journal import RoundtripJournal
    from lemouton.uploader.roundtrip.probe_image import (
        upload_probe_image, upload_probe_image_public,
    )
    from lemouton.uploader.roundtrip.runner import run_roundtrip
    from lemouton.uploader.roundtrip.snapshot import AXES

    ids = {}
    approval_axes = ()
    try:
        client = _roundtrip_client(market, env_prefix)

        if market == "smartstore":
            # 수정 API 는 originProductNo 를 요구한다 — 어느 번호를 줘도 변환해서 쓴다
            # (2026-07-17 과거이력: channelProductNo 로 수정 시도 → 실패).
            from shared.platforms.smartstore.get_channel_no import resolve_product_ids
            from lemouton.uploader.roundtrip.markets.smartstore import make_smartstore_ops
            ids = resolve_product_ids(int(raw_no), client=client) or {}
            if not ids:
                return _refuse(f"상품번호 {raw_no} 를 이 계정({acct_name})에서 찾지 못했어요.")
            product_no = str(ids["origin_product_no"])
            ops = make_smartstore_ops(int(product_no), client=client)
            # 스스는 자기 CDN(shop-phinf) URL 만 받는다 — 외부 URL 은 400.
            image_fn = lambda: upload_probe_image(client=client)   # noqa: E731
        elif market == "coupang":
            from lemouton.uploader.roundtrip.markets.coupang import (
                APPROVAL_AXES, make_coupang_ops,
            )
            product_no = str(raw_no)
            ops = make_coupang_ops(int(product_no), client=client)
            approval_axes = APPROVAL_AXES
            image_fn = lambda: upload_probe_image_public(tag=market)   # noqa: E731
        elif market == "lotteon":
            from lemouton.uploader.roundtrip.markets.lotteon import make_lotteon_ops
            product_no = str(raw_no)
            ops = make_lotteon_ops(product_no, client=client)
            image_fn = lambda: upload_probe_image_public(tag=market)   # noqa: E731
        elif market == "eleven11":
            # 11번가 — 가격·재고 **전용 API**(GET price/{prdNo}/{selPrc} ·
            #   PUT stockqty/{prdStckNo}). 상품명·상세·이미지는 수정 스펙 미확보라
            #   어댑터가 스스로 missing 으로 내놓는다(지어내지 않는다).
            from lemouton.uploader.roundtrip.markets.eleven11 import make_eleven11_ops
            product_no = str(raw_no)
            ops = make_eleven11_ops(product_no, client=client)
            image_fn = lambda: upload_probe_image_public(tag=market)   # noqa: E731
        else:
            # ESM — 수정은 **마스터 goodsNo** 로만. 사이트 상품번호를 줘도 변환해서 쓰고,
            #   이미 마스터번호면 변환 실패를 삼키고 그대로 쓴다(후보 조회가 주는 게 마스터번호).
            from lemouton.uploader.roundtrip.markets.esm import (
                make_esm_ops, resolve_master_goods_no,
            )
            product_no = resolve_master_goods_no(raw_no, client=client)
            ops = make_esm_ops(product_no, market=market, client=client)
            ids = {"channel_product_no": str(raw_no) if str(raw_no) != product_no else None}
            # ESM 은 공개 URL 을 그대로 받는다 → 우리 R2 에 올려 그 주소를 쓴다.
            image_fn = lambda: upload_probe_image_public(tag=market)   # noqa: E731

        journal = RoundtripJournal(market=market, product_id=str(product_no))
        report = run_roundtrip(
            snapshot_fn=ops.snapshot, apply_fn=ops.apply, journal=journal,
            axes=axes or AXES, on_sale_fn=ops.on_sale,
            image_url_fn=image_fn, approval_axes=approval_axes,
            allow_on_sale=(str(p.get("allow_on_sale") or "") == "1"),
            # 마켓이 정한 재고 범위 — 상한이면 +1 대신 -1 로 흔든다(2026-08-12 11번가).
            stock_bounds=getattr(ops, "STOCK_BOUNDS", None),
        )
    except Exception as e:  # noqa: BLE001
        import traceback
        return jsonify({"ok": False, "armed": True, "market": market,
                        "error": f"{type(e).__name__}: {str(e)[:400]}",
                        "detail": traceback.format_exc()[-800:]}), 200

    return jsonify({
        "ok": report.ok,
        "armed": True,
        "market": market,
        "account": acct_name,
        "origin_product_no": product_no,
        "channel_product_no": ids.get("channel_product_no"),
        "product_name": ids.get("product_name") or (
            report.before.name if report.before else None),
        "refusal": report.refusal,
        "send_error": report.send_error,
        "reverted": report.reverted,
        "revert_error": report.revert_error,
        "recovery_hint": report.recovery_hint,
        "journal": report.journal_path,
        "axes": [{
            "축": a.label, "axis": a.axis,
            "원래값": a.before, "보낸값": a.sent, "보낸뒤": a.after,
            "바뀜": a.changed_ok, "원복뒤": a.restored, "되돌아옴": a.restored_ok,
            "비고": a.note,
        } for a in report.axes],
    })


#: 프로브가 조사할 수 있는 마켓 — 어댑터가 아직 없어도 **조회는** 해 본다.
PROBE_MARKETS = ("smartstore", "auction", "gmarket", "coupang", "lotteon", "eleven11")


@bp.get("/api/live-send-test/roundtrip-probe")
def api_roundtrip_probe():
    """축 조회 프로브 — **읽기 전용**. 이 마켓이 5축 중 무엇을 실제로 주는가.

    왜: 롯데온 상세조회는 지도에 필드가 10개뿐이고 `res.note="전체 스펙 롯데ON apiNo=94"`
      (미확보)다. 11번가는 상품 수정 API 자체가 지도에 없다. 문서로 모르는 것을
      **추측해서 어댑터를 짜면** 「없는 필드를 읽어 None → 확인불가」로 조용히 굳는다.
      consult-market-map §3(갭 선순환): 실호출로 확보 → 지도에 되채움.

    마켓에 **아무것도 쓰지 않는다.**
    """
    market = (request.args.get("market") or "").strip()
    product_id = (request.args.get("product_id") or "").strip()
    want_prefix = (request.args.get("env_prefix") or "").strip()

    if market not in PROBE_MARKETS:
        return jsonify({"ok": False, "market": market,
                        "error": f"모르는 마켓: {market!r}"}), 400
    if not product_id:
        return jsonify({"ok": False, "market": market,
                        "error": "상품번호(product_id)가 필요해요."}), 400

    env_prefix = want_prefix or (_first_account_env(market, "")[0])

    def _flat_keys(node, prefix="", out=None, depth=0):
        """중첩 dict/list 의 열쇠 이름을 평평하게 — 어떤 필드가 오는지 눈으로 보려고."""
        out = [] if out is None else out
        if depth > 4 or len(out) > 400:
            return out
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{prefix}.{k}" if prefix else str(k)
                out.append(p)
                _flat_keys(v, p, out, depth + 1)
        elif isinstance(node, list) and node:
            _flat_keys(node[0], f"{prefix}[]", out, depth + 1)
        return out

    result = {"ok": True, "market": market, "product_id": product_id,
              "env_prefix": env_prefix, "axes": None, "raw_keys": [], "error": None}
    try:
        if market in ROUNDTRIP_READ_MARKETS:
            # 어댑터가 있는 마켓 — 그 어댑터가 읽는 그대로 보여준다.
            client = _roundtrip_client(market, env_prefix)
            if market == "smartstore":
                from lemouton.uploader.roundtrip.markets.smartstore import make_smartstore_ops
                ops = make_smartstore_ops(int(product_id), client=client)
            elif market == "coupang":
                from lemouton.uploader.roundtrip.markets.coupang import make_coupang_ops
                ops = make_coupang_ops(int(product_id), client=client)
            elif market == "lotteon":
                from lemouton.uploader.roundtrip.markets.lotteon import make_lotteon_ops
                ops = make_lotteon_ops(str(product_id), client=client)
            elif market == "eleven11":
                from lemouton.uploader.roundtrip.markets.eleven11 import make_eleven11_ops
                ops = make_eleven11_ops(str(product_id), client=client)
            else:
                from lemouton.uploader.roundtrip.markets.esm import make_esm_ops
                ops = make_esm_ops(product_id, market=market, client=client)
            snap = ops.snapshot()
            result["axes"] = {
                "상품명": snap.name, "가격": snap.sale_price,
                "재고": snap.value_of("stock"),
                "상세길이": len(snap.detail_html or "") if snap.detail_html else None,
                "이미지수": len(snap.image_urls) if snap.image_urls else None,
            }
            result["missing"] = list(snap.missing)
            result["raw_keys"] = _flat_keys(snap.raw)[:400]
        elif market == "lotteon":
            from lemouton.uploader import market_fetch as MF
            from shared.platforms.lotteon.products import get_product_detail
            cli = MF._lotteon_client(env_prefix)
            data = get_product_detail(str(product_id), client=cli)
            result["raw_keys"] = _flat_keys(data)[:400]
            result["axes"] = {"상품명": data.get("pdNm"), "판매상태": data.get("slStatCd")}
        else:   # eleven11
            from lemouton.uploader import market_fetch as MF
            from shared.platforms.eleven11.stocks_query import get_stocks
            cli = MF._eleven11_client(env_prefix)
            data = get_stocks(str(product_id), client=cli)
            result["raw_keys"] = _flat_keys(
                data if isinstance(data, dict) else {"rows": data})[:400]
            result["axes"] = {"재고행수": len(data) if isinstance(data, list) else None}
    except Exception as e:  # noqa: BLE001
        import traceback
        result["ok"] = False
        result["error"] = f"{type(e).__name__}: {str(e)[:400]}"
        result["detail"] = traceback.format_exc()[-700:]
    return jsonify(result)


@bp.get("/api/live-send-test/roundtrip-journals")
def api_roundtrip_journals():
    """남아 있는 왕복 저널 목록 — **원복 실패한 것부터** 보여준다(읽기 전용)."""
    from shared.state_store import state_dir
    import json as _json
    from pathlib import Path
    d = Path(state_dir()) / "roundtrip"
    rows = []
    if d.exists():
        for f in sorted(d.glob("*.json"), reverse=True)[:60]:
            try:
                j = _json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            # 🔴 원복실패는 결국 **사람이 손으로 되돌린다** — 그때 필요한 건 "실패했다"가
            #    아니라 「원래 얼마였나」다. 저널엔 있는데 목록이 안 줘서 파일을 못 열면
            #    복구를 못 한다(2026-08-08). 무거운 축(상세·이미지)은 길이만 준다.
            def _brief(node):
                out = {}
                for k, v in (node or {}).items():
                    if isinstance(v, str) and len(v) > 120:
                        out[k] = f"({len(v)}자) {v[:80]}…"
                    elif isinstance(v, (list, tuple)):
                        out[k] = f"({len(v)}개) {list(v)[:2]}"
                    else:
                        out[k] = v
                return out

            rows.append({"file": f.name, "path": str(f), "market": j.get("market"),
                         "product_id": j.get("product_id"), "status": j.get("status"),
                         "note": j.get("note"), "written_at": j.get("written_at"),
                         "원래값": _brief(j.get("before"))})
    bad = [r for r in rows if "실패" in str(r.get("status") or "")]
    return jsonify({"ok": True, "총": len(rows), "원복실패": len(bad),
                    "실패목록": bad, "전체": rows})


@bp.post("/api/live-send-test/roundtrip-restore")
def api_roundtrip_restore():
    """저널로 되돌리기 — **원복이 실패했을 때의 손복구**. body: {journal, arm}

    [중요] 왜 따로 있나: 원복이 실패하면 마켓에 시험값이 남는데, 왕복을 다시 부르면
       **지금 값(시험값)을 원래값으로 삼아** 더 나빠진다. 되돌리기 전용 경로가 필요하다.
    """
    p = request.get_json(silent=True) or {}
    journal = (p.get("journal") or "").strip()
    if not journal:
        return jsonify({"ok": False, "error": "journal(저널 파일 경로)이 필요해요."}), 400
    if str(p.get("arm") or "") != "1":
        return jsonify({"ok": False, "armed": False,
                        "refusal": "되돌리려면 arm=1 이 필요해요."})
    from lemouton.uploader.runtime import live_upload_enabled
    if not live_upload_enabled():
        return jsonify({"ok": False, "armed": False,
                        "refusal": "서버키 MOUM_LIVE_UPLOAD 가 꺼져 있어요."})

    import json as _json
    from pathlib import Path
    try:
        meta = _json.loads(Path(journal).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"저널을 읽지 못했어요: {e}"}), 400

    market = str(meta.get("market") or "")
    product_no = str(meta.get("product_id") or "")
    env_prefix = (p.get("env_prefix") or "").strip() or _first_account_env(market, "")[0]

    # 🔴 [2026-08-13] **전송만 막고 되돌리기를 안 막고 있었다.**
    #    되돌리려다 2026-08-07 에 상품을 잠근 그 전송이 그대로 나간다.
    #    저널엔 5축이 다 들어 있으므로 축 지정 없이 부르면 무거운 축까지 나간다.
    _blk = _heavy_axis_refusal(market, p.get("axes"),
                               unblocked=(str(p.get("unblock") or "") == "1"))
    if _blk:
        return jsonify({"ok": False, "armed": True, "market": market,
                        "product_id": product_no, "막힌축": _blk[1],
                        "refusal": _blk[0] + " (손복구도 같은 전송을 씁니다 — "
                                             "셀러오피스에서 손으로 고쳐 주세요)"})

    from lemouton.uploader.roundtrip.restore import restore_from_journal
    try:
        client = _roundtrip_client(market, env_prefix)
        if market == "smartstore":
            from lemouton.uploader.roundtrip.markets.smartstore import make_smartstore_ops
            ops = make_smartstore_ops(int(product_no), client=client)
        elif market == "coupang":
            from lemouton.uploader.roundtrip.markets.coupang import make_coupang_ops
            ops = make_coupang_ops(int(product_no), client=client)
        elif market == "lotteon":
            from lemouton.uploader.roundtrip.markets.lotteon import make_lotteon_ops
            ops = make_lotteon_ops(product_no, client=client)
        elif market == "eleven11":
            from lemouton.uploader.roundtrip.markets.eleven11 import make_eleven11_ops
            ops = make_eleven11_ops(product_no, client=client)
        else:
            from lemouton.uploader.roundtrip.markets.esm import make_esm_ops
            # 🔴 손복구는 **원래 이름으로 되돌리는** 일이다 — 상품명 축을 막아 두면
            #    시험 표식 " (시험중)" 이 붙은 채로 영영 남는다(2026-08-12 발견).
            #    시험할 때 상품명을 끄는 것과, 되돌릴 때 켜는 것은 다른 문제다.
            ops = make_esm_ops(product_no, market=market, client=client, allow_name=True)
        rep = restore_from_journal(journal, apply_fn=ops.apply, snapshot_fn=ops.snapshot)
    except Exception as e:  # noqa: BLE001
        import traceback
        return jsonify({"ok": False, "armed": True, "market": market,
                        "error": f"{type(e).__name__}: {str(e)[:400]}",
                        "detail": traceback.format_exc()[-700:]}), 200

    # 확인이 끝났으면 저널 상태를 바꾼다 — 안 그러면 목록에 「원복실패」로 영영 남아
    # 다음 사람이 또 손복구를 돌리고, 진짜 남은 문제가 소음에 묻힌다(2026-08-12).
    # 🔴 판별 못 한 축이 하나라도 있으면 도장을 찍지 않는다 — 「흔적 없음」이 거짓이 된다.
    if rep.ok and rep.verified and not rep.unknown:
        from lemouton.uploader.roundtrip.journal import mark_resolved
        skipped = ", ".join(rep.skipped or {})
        mark_resolved(journal, note=(
            "손복구 확인 — 마켓에 시험 흔적 없음"
            + (f" (시험 뒤 정상 변경이라 안 건드린 축: {skipped})" if skipped else "")))

    return jsonify({"ok": rep.ok, "armed": True, "market": rep.market,
                    "product_id": rep.product_id, "error": rep.error,
                    "되돌린값": {k: (list(v) if isinstance(v, tuple) else v)
                              for k, v in rep.sent.items()},
                    "확인됨": rep.verified, "안맞는축": list(rep.mismatched),
                    # 시험 흔적이 아니라 그 뒤에 정상적으로 바뀐 값이라 안 건드린 축.
                    # 조용히 건너뛰면 「되돌렸다」는 보고가 거짓이 된다.
                    "안건드린축": {k: (list(v) if isinstance(v, tuple) else v)
                               for k, v in (rep.skipped or {}).items()},
                    # 우리 시험값인지 **판별조차 못 한** 축 — 사람이 마켓 화면에서 봐야 한다.
                    "판별불가축": {k: (list(v) if isinstance(v, tuple) else v)
                               for k, v in (rep.unknown or {}).items()},
                    "journal": rep.journal_path})
