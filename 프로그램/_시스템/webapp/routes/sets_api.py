"""[구성 레이어 Phase 3a] 검색우선 4단계 흐름 JSON API.

기존 검증된 서비스(set_service·channel_service·set_link_service) 위 얇은 라우트.
패턴은 webapp/routes/api.py 와 동일(SessionLocal→서비스→commit→jsonify).
"""
from flask import Blueprint, jsonify, request, render_template

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, Option
from lemouton.sets import set_service as svc
from lemouton.sets import channel_service as ch
from lemouton.sets import set_link_service as link

bp = Blueprint("sets_api", __name__, url_prefix="/api")


def _err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


@bp.get("/sets/search-bundles")
def search_bundles():
    q = (request.args.get("q") or "").strip()
    s = SessionLocal()
    try:
        query = s.query(Model)
        if q:
            like = f"%{q}%"
            query = query.filter(
                Model.model_code.ilike(like)
                | Model.model_name_raw.ilike(like)
                | Model.model_name_display.ilike(like)
            )
        models = query.order_by(Model.model_code).limit(20).all()
        out = []
        for m in models:
            cnt = s.query(Option).filter_by(model_code=m.model_code).count()
            out.append({
                "code": m.model_code,
                "name": m.model_name_display or m.model_name_raw,
                "option_count": cnt,
            })
        return jsonify({"ok": True, "results": out})
    finally:
        s.close()


@bp.get("/sets/flow")
def sets_flow_page():
    """[Phase 3b] 검색우선 4단계 연동 흐름 페이지(base 레이아웃 — 사이드바 유지)."""
    return render_template("sets/flow.html", active="sets_dashboard")


@bp.get("/sets/dashboard")
def sets_dashboard_page():
    """[연동 현황] 판매처에 연동된 구성 목록·검색 대시보드 (사이드바 진입점)."""
    return render_template("sets/dashboard.html", active="sets_dashboard")


def _card_src_provider(model_codes, skus, session=None):
    """카드용 소싱 요약 provider — 매트릭스 단일 진실 원천(_option_matrix_data) 재사용.
    {sku: {stock, source_name, source_url, surface(표면노출가), final(최종매입가),
           ss_price(스스 판매예정가), cp_price(쿠팡 판매예정가)}}.
    판매예정가 = 매트릭스가 쓰는 값 그대로(compute_market_price). 사입은 '사입'(URL·표면 없음).
    source_url = 대표(최저 표면가) 소싱처의 상품 URL — 카드 「소」 줄 바로가기(↗)용.
    surface = 대표 소싱처 크롤 노출가 / final = 표면−혜택(compute_breakdown, 화면 셀·영수증과 동일).
    사입 final = 평균 매입가(purchase_avg_cost).

    session: 라우트가 자기 세션을 넘겨주면 그걸로 breakdown 계산(중첩 세션 회피 —
      list_linked_sets 이터레이션 도중 새 커넥션을 열지 않는다). 없으면 임시 세션.
    최종매입가 계산은 전체를 try 로 감싸 실패해도 목록을 절대 깨지 않음(final=None → '상세 ▾')."""
    from webapp.routes.api_pricing import _option_matrix_data
    out = {}
    items = []   # 최종매입가 breakdown 대상(사입 아닌 대표 소싱처)
    for mc in model_codes:
        data = _option_matrix_data(mc)
        if not data.get("ok"):
            continue
        for o in data.get("options", []):
            if o.get("sku") not in skus:
                continue
            is_pur = o.get("purchase_priority_resolved") == "purchase"
            stock = o.get("purchase_stock") if is_pur else o.get("src_stock")
            if is_pur:
                sname = "사입"
                surl = None
                surface = None
                final = o.get("purchase_avg_cost")
            else:
                cand = [x for x in (o.get("sources") or [])
                        if x.get("crawled_price") is not None]
                cand.sort(key=lambda x: x["crawled_price"])
                srcs = o.get("sources") or []
                # 대표 소싱처 = 최저 표면가(없으면 첫 소싱처). URL·이름·표면가 동일 승자에서 취함.
                win = cand[0] if cand else (srcs[0] if srcs else None)
                sname = win.get("source_name") if win else None
                surl = win.get("product_url") if win else None
                surface = (win.get("crawled_price") if win else None) or o.get("src_cost")
                final = None   # 아래 breakdown 일괄 계산(실패 시 None → 카드 '상세 ▾' 폴백)
                if (win and win.get("source_id") is not None
                        and win.get("crawled_price") is not None):
                    items.append({"sku": o["sku"], "source_id": win["source_id"],
                                  "sale_price": win["crawled_price"],
                                  "source_product_id": win.get("source_product_id")})
            out[o["sku"]] = {"stock": stock, "source_name": sname,
                             "source_url": surl,
                             "surface": surface, "final": final,
                             "receipt": None,   # 아래 breakdown 에서 채움(상세 영수증)
                             "ss_price": o.get("ss_price"),
                             "cp_price": o.get("cp_price")}
    # 최종매입가(표면−혜택) 일괄 계산 — _cache 로 N+1 제거.
    #   전체를 try 로 감싼다: breakdown 이 어떤 이유로 터져도 목록은 절대 안 깨지고
    #   final=None 으로 남아 카드가 '상세 ▾' 로 안전 폴백(날조 금지·무중단).
    if items:
        from webapp.routes.api_benefits import _build_breakdown_cache, compute_breakdown
        own = session is None
        s = session or SessionLocal()
        try:
            cache = _build_breakdown_cache(s, items)
            for it in items:
                try:
                    bd = compute_breakdown(s, sku=it["sku"], source_id=int(it["source_id"]),
                                           sale_price=float(it["sale_price"]), _cache=cache,
                                           source_product_id=it.get("source_product_id"))
                    if bd and bd.get("final_price") is not None and it["sku"] in out:
                        out[it["sku"]]["final"] = bd["final_price"]
                        # 상세 영수증(표면 노출가 → 혜택 항목별 차감 → 최종 매입가).
                        #   steps = 실제 적용(enabled)된 차감만. 셀·영수증 단일 진실 원천.
                        out[it["sku"]]["receipt"] = {
                            "source_name": out[it["sku"]].get("source_name"),
                            "surface": bd.get("sale_price"),
                            "final": bd["final_price"],
                            "steps": [{"name": st.get("name"), "deduct": st.get("deduct"),
                                       "base_after": st.get("base_after")}
                                      for st in (bd.get("steps") or [])],
                        }
                except Exception:
                    pass
        except Exception:
            pass   # _build_breakdown_cache 실패 등 — 목록 보호(최종매입가만 지연)
        finally:
            if own:
                s.close()
    return out


@bp.get("/sets/linked")
def list_linked():
    """대시보드 데이터 — 연동된 구성 목록(검색어 q 로 구성명·상품명·상품번호 필터)."""
    q = (request.args.get("q") or "").strip()
    s = SessionLocal()
    try:
        # 라우트 세션을 provider 에 넘겨 breakdown 이 중첩 세션을 안 열게 한다(무중단·안전).
        rows = svc.list_linked_sets(
            s, q=q or None,
            src_provider=lambda mcs, sk: _card_src_provider(mcs, sk, session=s))
        return jsonify({"ok": True, "sets": rows})
    finally:
        s.close()


@bp.get("/sets/<int:set_id>/detail-matrix")
def set_detail_matrix(set_id):
    """[상세 1b·1c] 구성 옵션별 출처(사입/소싱)·재고·매입가·소싱처 후보·fx 영수증
    + 채널 매칭 상태. 매트릭스 단일 진실 원천(_option_matrix_data)을 그대로 재사용해
    구성의 옵션(canonical_sku)만 필터링한다. 새 가격/재고 계산 없음(중복·모순 방지).
    """
    from webapp.routes.api_pricing import _option_matrix_data
    from lemouton.sets.models import SetChannel, SetChannelOption
    s = SessionLocal()
    try:
        detail = svc.get_set_detail(s, set_id)
        if not detail:
            return _err("구성을 찾을 수 없어요.", 404)
        skus = set()
        for p in detail["products"]:
            skus.update(p["options"])
        # 채널별 옵션 매칭 맵: {canonical_sku: {market: {status, market_option_id}}}
        match_map: dict = {}
        chans = []
        for c in (s.query(SetChannel).filter_by(set_id=set_id)
                  .order_by(SetChannel.id).all()):
            chans.append({"id": c.id, "market": c.market,
                          "market_product_id": c.market_product_id,
                          "account_key": c.account_key, "status": c.status})
            for sco in s.query(SetChannelOption).filter_by(channel_id=c.id).all():
                match_map.setdefault(sco.canonical_sku, {})[c.market] = {
                    "status": sco.status, "market_option_id": sco.market_option_id}
        model_codes = {p["model_code"] for p in detail["products"]}
        set_meta = {"id": detail["id"], "name": detail["name"]}
    finally:
        s.close()
    # 모델별 매트릭스(각자 세션) 호출 후 구성 옵션만 추려 채널 매칭 병합
    opts_out = []
    for mc in model_codes:
        data = _option_matrix_data(mc)
        if not data.get("ok"):
            continue
        for o in data.get("options", []):
            if o.get("sku") in skus:
                o["channels"] = match_map.get(o["sku"], {})
                opts_out.append(o)
    opts_out.sort(key=lambda o: (o.get("color_code") or "", o.get("size_code") or ""))
    return jsonify({"ok": True, "set": set_meta,
                    "channels": chans, "options": opts_out})


def _new_values_for_options(model_codes, skus, market):
    """구성 옵션의 '보낼 재고/가격'(출처 기반) 맵: {canonical_sku: {...}}.
    매트릭스 단일 진실 원천(_option_matrix_data) 그대로 — 출처(사입/소싱)에 따라
    재고/가격 선택. 새 계산 없음(표시값=전송값 parity)."""
    from webapp.routes.api_pricing import _option_matrix_data
    out = {}
    for mc in model_codes:
        data = _option_matrix_data(mc)
        if not data.get("ok"):
            continue
        for o in data.get("options", []):
            if o.get("sku") not in skus:
                continue
            is_pur = o.get("purchase_priority_resolved") == "purchase"
            out[o["sku"]] = {
                "stock": o.get("purchase_stock") if is_pur else o.get("src_stock"),
                "price": o.get("ss_price") if market == "smartstore" else o.get("cp_price"),
                "color": o.get("color_display") or o.get("color_code"),
                "size": o.get("size_display") or o.get("size_code"),
                "source": "purchase" if is_pur else "source",
                "is_active": o.get("is_active"),
            }
    return out


@bp.get("/sets/channel/<int:channel_id>/preview")
def channel_preview(channel_id):
    """[2단계 미리보기] 채널의 마켓 현재 재고/가격(읽기)을 가져와 '보낼 값'과 대조.
    마켓에 쓰지 않음(GET만). matched 옵션만. 변동·평균 가격변동률 요약으로 위험 표면화.
    """
    from lemouton.uploader.market_fetch import fetch_market_options
    from lemouton.sets.models import SetChannel, SetChannelOption, SetProduct, SetOption
    from lemouton.sets.set_link_service import _resolve_env_prefix
    s = SessionLocal()
    try:
        ch = s.get(SetChannel, channel_id)
        if ch is None:
            return _err("채널을 찾을 수 없어요.", 404)
        if not ch.market_product_id:
            return _err("상품번호가 입력되지 않았어요.")
        rows = (s.query(SetOption.canonical_sku, SetProduct.model_code)
                .join(SetProduct, SetOption.set_product_id == SetProduct.id)
                .filter(SetProduct.set_id == ch.set_id).all())
        skus = {r[0] for r in rows}
        model_codes = {r[1] for r in rows}
        matched = {sco.canonical_sku: sco.market_option_id for sco in
                   s.query(SetChannelOption)
                   .filter_by(channel_id=channel_id, status="matched").all()}
        env_prefix = _resolve_env_prefix(s, ch.market, ch.account_key)
        market = ch.market
        product_id = ch.market_product_id
    finally:
        s.close()
    if not matched:
        return jsonify({"ok": True, "market": market, "rows": [],
                        "summary": {"total": 0, "changed": 0, "avg_price_change_pct": 0},
                        "note": "매칭된 옵션이 없어요(먼저 연동 실행 필요)."})
    newv = _new_values_for_options(model_codes, skus, market)
    fr = fetch_market_options(market, product_id, env_prefix=env_prefix)
    if not fr.success:
        return jsonify({"ok": False, "error": fr.error or "마켓 현재값 조회 실패"})
    cur = {mo.option_id: mo for mo in fr.options}
    out_rows = []
    changed = 0
    pcts = []
    for sku, moid in matched.items():
        nv = newv.get(sku)
        cm = cur.get(str(moid))
        # 쿠팡은 현재 재고를 응답에서 안 주므로(미상) None 처리, 가격만 대조
        cur_stock = (cm.stock if (cm and market != "coupang") else None)
        cur_price = cm.price if cm else None
        new_stock = nv.get("stock") if nv else None
        new_price = nv.get("price") if nv else None
        stock_changed = (new_stock is not None and cur_stock is not None
                         and new_stock != cur_stock)
        price_changed = (new_price is not None and cur_price is not None
                         and new_price != cur_price)
        if stock_changed or price_changed:
            changed += 1
        if cur_price and new_price:
            pcts.append(abs(new_price - cur_price) / cur_price * 100)
        out_rows.append({
            "sku": sku, "market_option_id": moid,
            "color": nv.get("color") if nv else None,
            "size": nv.get("size") if nv else None,
            "source": nv.get("source") if nv else None,
            "is_active": nv.get("is_active") if nv else None,
            "cur_stock": cur_stock, "new_stock": new_stock,
            "cur_price": cur_price, "new_price": new_price,
            "stock_changed": stock_changed, "price_changed": price_changed,
            "usable": cm.usable if cm else None,
        })
    out_rows.sort(key=lambda r: ((r["color"] or ""), (r["size"] or "")))
    avg_pct = round(sum(pcts) / len(pcts), 1) if pcts else 0.0
    # 표시용 위험 경고(전송 게이트는 2b). 임계: 평균 가격변동 30%↑ 또는 변동 다수
    hold = avg_pct >= 30.0
    return jsonify({"ok": True, "market": market, "product_name": fr.product_name,
                    "rows": out_rows,
                    "summary": {"total": len(out_rows), "changed": changed,
                                "avg_price_change_pct": avg_pct, "hold": hold}})


@bp.get("/sets/bundle/<code>/options")
def bundle_options(code):
    """단계② 조합 매트릭스용 — 모음전의 옵션을 색/사이즈로."""
    s = SessionLocal()
    try:
        opts = (s.query(Option).filter_by(model_code=code)
                .order_by(Option.color_code, Option.size_code).all())
        colors, sizes, items = [], [], []
        for o in opts:
            color = o.color_display or o.color_code
            size = o.size_display or o.size_code
            if color not in colors:
                colors.append(color)
            if size not in sizes:
                sizes.append(size)
            items.append({"canonical_sku": o.canonical_sku,
                          "color": color, "size": size,
                          "is_active": bool(o.is_active)})
        return jsonify({"ok": True, "colors": colors, "sizes": sizes,
                        "options": items})
    finally:
        s.close()


@bp.get("/sets/upload-accounts")
def upload_accounts():
    """단계③ 판매처 선택용 — 등록된 업로드 계정 + 키 보유 여부."""
    from lemouton.sourcing.models_v2 import UploadAccount
    from lemouton.auth import secrets as _secrets
    s = SessionLocal()
    try:
        accts = (s.query(UploadAccount).filter_by(is_active=True)
                 .order_by(UploadAccount.market, UploadAccount.id).all())
        out = []
        for a in accts:
            try:
                _secrets.load_credentials(market=a.market, env_prefix=a.env_prefix)
                has_key = True
            except Exception:
                has_key = False
            out.append({"account_key": a.account_key, "display_name": a.display_name,
                        "market": a.market, "has_key": has_key})
        return jsonify({"ok": True, "accounts": out})
    finally:
        s.close()


@bp.post("/sets")
def create_set():
    p = request.get_json(silent=True) or {}
    model_code = (p.get("model_code") or "").strip()
    name = (p.get("name") or "").strip()
    if not model_code or not name:
        return _err("model_code 와 name 이 필요해요.")
    quantity = int(p.get("quantity") or 1)
    s = SessionLocal()
    try:
        ps = svc.create_set(s, model_code=model_code, name=name)
        sp = svc.add_product(s, set_id=ps.id, model_code=model_code, quantity=quantity)
        s.commit()
        return jsonify({"ok": True, "set_id": ps.id, "product_id": sp.id})
    finally:
        s.close()


@bp.get("/sets")
def list_sets():
    model_code = (request.args.get("model_code") or "").strip()
    if not model_code:
        return _err("model_code 가 필요해요.")
    s = SessionLocal()
    try:
        rows = svc.list_sets(s, model_code)
        out = []
        for r in rows:
            opt_count = sum(len(p.options) for p in r.products)
            chans = [{"market": c.market, "linked": bool(c.market_product_id)}
                     for c in r.channels]
            out.append({"id": r.id, "name": r.name,
                        "option_count": opt_count, "channels": chans})
        return jsonify({"ok": True, "sets": out})
    finally:
        s.close()


@bp.get("/sets/<int:set_id>")
def get_set(set_id):
    s = SessionLocal()
    try:
        detail = svc.get_set_detail(s, set_id)
        if not detail:
            return _err("구성을 찾을 수 없어요.", 404)
        return jsonify({"ok": True, "set": detail})
    finally:
        s.close()


@bp.post("/sets/<int:set_id>/options")
def set_set_options(set_id):
    p = request.get_json(silent=True) or {}
    set_product_id = p.get("set_product_id")
    skus = p.get("canonical_skus") or []
    if not set_product_id:
        return _err("set_product_id 가 필요해요.")
    s = SessionLocal()
    try:
        svc.set_options(s, set_product_id=int(set_product_id), canonical_skus=list(skus))
        s.commit()
        return jsonify({"ok": True, "count": len(skus)})
    finally:
        s.close()


@bp.delete("/sets/<int:set_id>")
def delete_set(set_id):
    s = SessionLocal()
    try:
        ok = svc.delete_set(s, set_id)
        s.commit()
        return (jsonify({"ok": True}) if ok else _err("구성을 찾을 수 없어요.", 404))
    finally:
        s.close()


@bp.post("/sets/<int:set_id>/channels")
def add_channel(set_id):
    p = request.get_json(silent=True) or {}
    market = (p.get("market") or "").strip()
    if market not in ("smartstore", "coupang"):
        return _err("market 은 smartstore/coupang 중 하나여야 해요.")
    s = SessionLocal()
    try:
        c = ch.add_channel(s, set_id=set_id, market=market,
                           account_key=(p.get("account_key") or None))
        s.commit()
        return jsonify({"ok": True, "channel_id": c.id})
    finally:
        s.close()


@bp.delete("/channels/<int:channel_id>")
def remove_channel(channel_id):
    s = SessionLocal()
    try:
        ok = ch.remove_channel(s, channel_id)
        s.commit()
        return (jsonify({"ok": True}) if ok else _err("채널을 찾을 수 없어요.", 404))
    finally:
        s.close()


@bp.post("/channels/<int:channel_id>/product")
def set_channel_product(channel_id):
    p = request.get_json(silent=True) or {}
    product_id = str(p.get("market_product_id") or "").strip()
    if not product_id:
        return _err("market_product_id 가 필요해요.")
    s = SessionLocal()
    try:
        c = ch.set_channel_product(s, channel_id=channel_id,
                                   market_product_id=product_id,
                                   api_fields=p.get("api_fields"))
        if c is None:
            return _err("채널을 찾을 수 없어요.", 404)
        s.commit()
        return jsonify({"ok": True, "status": c.status})
    finally:
        s.close()


@bp.post("/channels/<int:channel_id>/link")
def link_channel(channel_id):
    s = SessionLocal()
    try:
        result = link.link_set_channel(s, channel_id)
        if not result.get("ok"):
            s.rollback()
            return _err(result.get("error") or "연동 실패", 400)
        s.commit()
        return jsonify(result)
    finally:
        s.close()


@bp.post("/sets/channel/<int:channel_id>/collect")
def collect_channel_route(channel_id):
    """[P2] 채널 현재값 수동 새로고침 — 마켓 API 읽어 mkt_* 갱신 + 변동기록."""
    from lemouton.sets.collect_service import collect_channel
    s = SessionLocal()
    try:
        r = collect_channel(s, channel_id)
        if not r.get("ok"):
            return _err(r.get("error") or "수집 실패")
        s.commit()
        return jsonify(r)
    finally:
        s.close()


@bp.post("/sets/<int:set_id>/collect")
def collect_set_route(set_id):
    """[P2] 구성 단위 일괄 현재값 새로고침."""
    from lemouton.sets.collect_service import collect_set
    s = SessionLocal()
    try:
        r = collect_set(s, set_id)
        s.commit()
        return jsonify(r)
    finally:
        s.close()


def _current_source_value_map(s, set_id):
    """구성 옵션의 '현재' 소싱 값 맵 {sku: {stock, surface, cost, ss_price, cp_price}}.

    매트릭스 단일 진실 원천(_option_matrix_data) + 혜택 breakdown 으로 계산 — 카드 셀·영수증과
    동일 값. detail 없으면 None. snapshot-sources·이력 첫줄 시드가 공유(단일 진실 원천).
      · surface = 표면 노출가(대표 크롤가) / cost = 최종매입가(혜택 차감) / planned = 판매예정가.
    """
    from webapp.routes.api_pricing import _option_matrix_data
    from webapp.routes.api_benefits import _build_breakdown_cache, compute_breakdown
    detail = svc.get_set_detail(s, set_id)
    if not detail:
        return None
    skus = set()
    for p in detail["products"]:
        skus.update(p["options"])
    opts = []
    for mc in {p["model_code"] for p in detail["products"]}:
        data = _option_matrix_data(mc)
        if not data.get("ok"):
            continue
        for o in data.get("options", []):
            if o.get("sku") in skus:
                opts.append(o)
    # 사입 아닌 옵션의 대표 소싱처(최저 크롤가)로 breakdown 일괄 계산(_cache 로 N+1 제거).
    items = []
    for o in opts:
        if o.get("purchase_priority_resolved") == "purchase":
            continue
        cands = [sc for sc in (o.get("sources") or [])
                 if sc.get("source_id") is not None and sc.get("crawled_price") is not None]
        if not cands:
            continue
        best = min(cands, key=lambda sc: sc["crawled_price"])
        items.append({"sku": o["sku"], "source_id": best["source_id"],
                      "sale_price": best["crawled_price"],
                      "source_product_id": best.get("source_product_id")})
    finals = {}     # sku → 최종매입가(혜택 차감)
    surfaces = {}   # sku → 표면 노출가(대표 크롤가)
    try:
        cache = _build_breakdown_cache(s, items)
        for it in items:
            surfaces[it["sku"]] = it["sale_price"]
            try:
                bd = compute_breakdown(s, sku=it["sku"], source_id=int(it["source_id"]),
                                       sale_price=float(it["sale_price"]), _cache=cache,
                                       source_product_id=it.get("source_product_id"))
                if bd and bd.get("final_price") is not None:
                    finals[it["sku"]] = bd["final_price"]
            except Exception:
                pass
    except Exception:
        pass
    vmap = {}
    for o in opts:
        is_pur = o.get("purchase_priority_resolved") == "purchase"
        sku = o["sku"]
        vmap[sku] = {
            "stock": o.get("purchase_stock") if is_pur else o.get("src_stock"),
            "surface": (None if is_pur else surfaces.get(sku, o.get("src_cost"))),
            "cost": (o.get("purchase_avg_cost") if is_pur else finals.get(sku)),
            "ss_price": o.get("ss_price"),
            "cp_price": o.get("cp_price"),
        }
    return vmap


@bp.get("/sets/<int:set_id>/history")
def set_history_route(set_id):
    """[H2] M3 셀 클릭 — 변동이력 시계열(market·field 선택 필터).

    구성에 이력이 전혀 없으면(첫 조회) 현재값(카드·상세 공유 크롤 데이터)을 '오늘' 기준선 1줄로
    심어 상세와 즉시 일치시킨다. 소싱 side·값 있는 필드만(날조 금지). 이후 크롤은 그 위로 이어 기록."""
    from lemouton.sets import change_service as cs
    market = (request.args.get("market") or "").strip() or None
    field = (request.args.get("field") or "").strip() or None
    s = SessionLocal()
    try:
        rows = cs.list_changes(s, set_id=set_id, market=market, field=field)
        seeded = False
        # 이력 전무(어떤 market·field 도 없음)일 때만 현재값으로 첫 기준선 심기.
        if not rows and not cs.list_changes(s, set_id=set_id, limit=1):
            from lemouton.sets.change_service import snapshot_source_values
            vmap = _current_source_value_map(s, set_id)
            if vmap and snapshot_source_values(s, set_id=set_id, value_map=vmap):
                s.commit()
                seeded = True
                rows = cs.list_changes(s, set_id=set_id, market=market, field=field)
        return jsonify({"ok": True, "events": rows, "seeded": seeded})
    finally:
        s.close()


@bp.get("/sets/<int:set_id>/alerts")
def set_alerts_route(set_id):
    """[알림] 구성 알림 — 소싱(_option_matrix_data src_stock) 대조 포함(both_zero 정밀)."""
    from webapp.routes.api_pricing import _option_matrix_data
    from lemouton.sets import alert_service as al
    s = SessionLocal()
    try:
        detail = svc.get_set_detail(s, set_id)
        if not detail:
            return _err("구성을 찾을 수 없어요.", 404)
        skus = set()
        for p in detail["products"]:
            skus.update(p["options"])
        model_codes = {p["model_code"] for p in detail["products"]}
        src_stock_map = {}
        for mc in model_codes:
            data = _option_matrix_data(mc)
            if not data.get("ok"):
                continue
            for o in data.get("options", []):
                if o.get("sku") in skus:
                    is_pur = o.get("purchase_priority_resolved") == "purchase"
                    src_stock_map[o["sku"]] = (o.get("purchase_stock") if is_pur
                                               else o.get("src_stock"))
        alerts = al.alerts_for_set(s, set_id, src_stock_map)
        return jsonify({"ok": True, "alerts": alerts})
    finally:
        s.close()


@bp.post("/sets/<int:set_id>/recrawl-sources")
def recrawl_sources_route(set_id):
    """[작업3] 구성에 연동된 옵션들의 소싱처 URL을 모델 단위로 재크롤.
    HTTP 소싱처는 서버 즉시 크롤, 무신사·롯데온은 need_extension(확장 크롤 안내)."""
    from lemouton.sets import source_update_service as srv
    s = SessionLocal()
    try:
        r = srv.update_set_sources(s, set_id=set_id)
        if not r.get("ok"):
            return _err(r.get("error") or "소싱처 업데이트 실패", 404)
        s.commit()
        # 재크롤 직후 소싱 변동 스냅샷(H2 소싱열·source_changed 알림 점등). 실패해도 본응답 영향X.
        try:
            from webapp.routes.api_pricing import _option_matrix_data
            from lemouton.sets.change_service import snapshot_source_values
            detail = svc.get_set_detail(s, set_id)
            if detail:
                skus = set()
                for p in detail["products"]:
                    skus.update(p["options"])
                vmap = {}
                for mc in {p["model_code"] for p in detail["products"]}:
                    data = _option_matrix_data(mc)
                    if not data.get("ok"):
                        continue
                    for o in data.get("options", []):
                        if o.get("sku") in skus:
                            is_pur = o.get("purchase_priority_resolved") == "purchase"
                            vmap[o["sku"]] = {
                                "stock": o.get("purchase_stock") if is_pur else o.get("src_stock"),
                                "price": o.get("src_cost"),
                            }
                snapshot_source_values(s, set_id=set_id, value_map=vmap)
                s.commit()
        except Exception:
            s.rollback()
        return jsonify(r)
    finally:
        s.close()


@bp.post("/sets/<int:set_id>/automation")
def set_automation_route(set_id):
    """[구성별 자동 전송 예외] auto_stock_mode / auto_price_mode (follow|on|off) 저장."""
    data = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        r = svc.save_set_automation(s, set_id, data)
        if r is None:
            return _err("구성을 찾을 수 없어요.", 404)
        s.commit()
        return jsonify({"ok": True, "automation": r})
    finally:
        s.close()


@bp.post("/sets/<int:set_id>/snapshot-sources")
def snapshot_sources_route(set_id):
    """[H2] 소싱 현재값 스냅샷 — 변동만 source 이벤트로 즉시 기록(크롤 안 함).
    로컬 확장 크롤(소싱처 업데이트) 완료 직후 호출 → 변동이력 소싱열 즉시 점등.
    현재값 계산은 _current_source_value_map 공유(이력 첫줄 시드와 동일 단일 진실 원천)."""
    from lemouton.sets.change_service import snapshot_source_values
    s = SessionLocal()
    try:
        vmap = _current_source_value_map(s, set_id)
        if vmap is None:
            return _err("구성을 찾을 수 없어요.", 404)
        n = snapshot_source_values(s, set_id=set_id, value_map=vmap)
        s.commit()
        return jsonify({"ok": True, "recorded": n})
    finally:
        s.close()


@bp.post("/sets/channel/<int:channel_id>/send")
def channel_send(channel_id):
    """[2단계 전송] 매칭 옵션 재고를 마켓에 전송. dry_run 기본(시뮬 — 마켓 쓰기 0).
    1차 = 쿠팡 재고만(update_quantity). usable=false(판매중지) 옵션 제외. 보낼값은
    미리보기와 동일(_new_values, 표시값=전송값 parity). 가격 전송·스마트스토어는 후속.
    실제 마켓 쓰기는 dry_run=false 명시 + 사용자 감독 하에서만.
    """
    from lemouton.uploader.market_fetch import fetch_market_options
    from lemouton.sets.models import (SetChannel, SetChannelOption,
                                       SetProduct, SetOption)
    from lemouton.sets.set_link_service import _resolve_env_prefix
    p = request.get_json(silent=True) or {}
    dry_run = bool(p.get("dry_run", True))
    s = SessionLocal()
    try:
        ch = s.get(SetChannel, channel_id)
        if ch is None:
            return _err("채널을 찾을 수 없어요.", 404)
        if not ch.market_product_id:
            return _err("상품번호가 입력되지 않았어요.")
        market = ch.market
        product_id = ch.market_product_id
        env_prefix = _resolve_env_prefix(s, ch.market, ch.account_key)
        rows = (s.query(SetOption.canonical_sku, SetProduct.model_code)
                .join(SetProduct, SetOption.set_product_id == SetProduct.id)
                .filter(SetProduct.set_id == ch.set_id).all())
        skus = {r[0] for r in rows}
        model_codes = {r[1] for r in rows}
        matched = {sco.canonical_sku: sco.market_option_id for sco in
                   s.query(SetChannelOption)
                   .filter_by(channel_id=channel_id, status="matched").all()}
    finally:
        s.close()
    if market != "coupang":
        return jsonify({"ok": False,
                        "error": "현재 실제 전송은 쿠팡 재고만 지원해요(스마트스토어·가격은 준비 중)."})
    if not matched:
        return jsonify({"ok": True, "dry_run": dry_run, "market": market, "results": [],
                        "summary": {"sent": 0, "failed": 0, "skipped": 0, "total": 0},
                        "note": "매칭된 옵션이 없어요(먼저 연동 실행)."})
    newv = _new_values_for_options(model_codes, skus, market)
    fr = fetch_market_options(market, product_id, env_prefix=env_prefix)
    cur = {mo.option_id: mo for mo in fr.options} if fr.success else {}
    client = None
    if not dry_run:
        from lemouton.uploader.market_fetch import _coupang_client
        client = _coupang_client(env_prefix)
    from shared.platforms.coupang.inventory import update_quantity
    results = []
    sent = failed = skipped = 0
    for sku, moid in matched.items():
        nv = newv.get(sku)
        cm = cur.get(str(moid))
        new_stock = nv.get("stock") if nv else None
        label = ((nv.get("color") if nv else None) or "") + " · " + ((nv.get("size") if nv else None) or "")
        if cm is not None and getattr(cm, "usable", True) is False:
            results.append({"sku": sku, "label": label, "skipped": True,
                            "reason": "판매중지 옵션(usable=false)"})
            skipped += 1
            continue
        if new_stock is None:
            results.append({"sku": sku, "label": label, "skipped": True,
                            "reason": "보낼 재고 없음"})
            skipped += 1
            continue
        if dry_run:
            results.append({"sku": sku, "label": label, "new_stock": new_stock,
                            "ok": True, "dry": True})
            continue
        try:
            ok = update_quantity(vendor_item_id=int(moid),
                                 quantity=int(new_stock), client=client)
            if ok:
                results.append({"sku": sku, "label": label,
                                "new_stock": new_stock, "ok": True})
                sent += 1
            else:
                results.append({"sku": sku, "label": label, "ok": False,
                                "error": "재고 전송 실패(마켓 거부)"})
                failed += 1
        except Exception as e:  # noqa: BLE001 — 전송 실패 표면화(폴백 금지)
            results.append({"sku": sku, "label": label, "ok": False,
                            "error": f"{type(e).__name__}: {e}"})
            failed += 1
    return jsonify({"ok": True, "dry_run": dry_run, "market": market,
                    "summary": {"sent": sent, "failed": failed,
                                "skipped": skipped, "total": len(results)},
                    "results": results})
