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
    """[Phase 3b] 검색우선 4단계 연동 흐름 페이지(standalone)."""
    return render_template("sets/flow.html")


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
                          "color": color, "size": size})
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
        return jsonify({"ok": True, "sets": [
            {"id": r.id, "name": r.name} for r in rows]})
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
