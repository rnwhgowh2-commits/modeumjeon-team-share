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
@bp.get("/api/live-send-test/pick-orders")
def api_pick_orders():
    """최근 주문에서 실제 상품 후보(상품번호·단품번호)를 수집. 세트 연동 불필요.

    ?market=lotteon|eleven11&days=14&limit=20 . 계정별로 순회하며 중복(상품·옵션) 제거.
    """
    market = (request.args.get("market") or "").strip()
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


@bp.get("/api/live-send-test/e11-raw")
def api_e11_raw():
    """[진단] 11번가 재고조회 원시 요청/응답 XML 확인(파싱 매핑 확정용). 임시."""
    env_prefix = (request.args.get("env_prefix") or "").strip() or None
    product_id = (request.args.get("product_id") or "").strip()
    if not product_id:
        return jsonify({"ok": False, "error": "product_id 필요"}), 400
    from lemouton.uploader.market_fetch import _eleven11_client
    from shared.platforms.eleven11 import stocks_query as SQ
    pid = str(product_id)
    hdr = '<?xml version="1.0" encoding="euc-kr"?>'
    # 요청 XML 형식 후보(응답 래퍼 ProductStockss·오류메시지 기반 추정)
    variants = {
        "ProductStocks":  f"{hdr}<ProductStocks><prdNo>{pid}</prdNo></ProductStocks>",
        "ProductStockss": f"{hdr}<ProductStockss><prdNo>{pid}</prdNo></ProductStockss>",
        "ProductStock":   f"{hdr}<ProductStock><prdNo>{pid}</prdNo></ProductStock>",
        "Product":        f"{hdr}<Product><prdNo>{pid}</prdNo></Product>",
        "bare_prdNo":     f"{hdr}<prdNo>{pid}</prdNo>",
    }
    out = {}
    try:
        client = _eleven11_client(env_prefix)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"client: {type(e).__name__}: {e}"}), 200
    # POST 변형들
    for name, body in variants.items():
        try:
            resp = client.request("POST", SQ._PATH_STOCKS, body)
            out[f"POST:{name}"] = (resp or "")[:700]
        except Exception as e:  # noqa: BLE001
            out[f"POST:{name}"] = f"ERR {type(e).__name__}: {str(e)[:200]}"
    # GET 변형(prdNo 쿼리)
    try:
        resp = client.request("GET", SQ._PATH_STOCKS + f"?prdNo={pid}")
        out["GET:query"] = (resp or "")[:700]
    except Exception as e:  # noqa: BLE001
        out["GET:query"] = f"ERR {type(e).__name__}: {str(e)[:200]}"
    return jsonify({"ok": True, "product_id": pid, "results": out})


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
    if not market or not product_id or not option_id:
        return jsonify({"ok": False, "error": "market·product_id·option_id 필요"}), 400
    try:
        price = int(p.get("price"))
        stock = int(p.get("stock"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "price·stock 는 정수"}), 400
    # 머니세이프티: 가격 양수·재고 0 이상(품절 허용). 폴백·추측 없음.
    if price <= 0 or stock < 0:
        return jsonify({"ok": False, "error": "가격은 양수, 재고는 0 이상이어야 해요."}), 400

    from lemouton.uploader.scoped_send import _account_adapter, _server_key_on
    use_real = bool(_server_key_on() and confirmed)
    adapter = _account_adapter(market, env_prefix, live=use_real)
    try:
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
