"""맵핑 (모음전 상품 ↔ 재고관리 SKU) 라우트 — 차원·캐노니컬·별칭 CRUD + 자동 매칭.

V5 아코디언 UI. 사이드바 양쪽 (모음전 + 재고관리) 동일 URL.
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash

from shared.db import SessionLocal
from lemouton.mapping.models import AliasDimension, AliasCanonical, AliasMapping
from lemouton.mapping.matcher import match_options_batch, learn_alias


bp = Blueprint("mapping", __name__, url_prefix="/mapping")


@bp.get("/")
def index():
    """맵핑 페이지 — 차원·캐노니컬·별칭 아코디언 UI."""
    s = SessionLocal()
    try:
        dims = (
            s.query(AliasDimension)
            .filter(AliasDimension.is_active.is_(True))
            .order_by(AliasDimension.sort_order, AliasDimension.id)
            .all()
        )
        return render_template(
            "mapping/index.html",
            active="mapping",
            dimensions=dims,
        )
    finally:
        s.close()


# ============ 차원 (dimension) CRUD ============

@bp.post("/dimension/create")
def dimension_create():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("차원 이름을 입력하세요.", "error")
        return redirect(url_for("mapping.index"))
    try:
        weight = int(request.form.get("weight") or 0)
    except ValueError:
        weight = 0
    s = SessionLocal()
    try:
        if s.query(AliasDimension).filter(AliasDimension.name == name).first():
            flash(f"차원 '{name}' 이미 존재합니다.", "error")
            return redirect(url_for("mapping.index"))
        max_sort = s.query(AliasDimension).count()
        d = AliasDimension(name=name, weight=weight, sort_order=max_sort)
        s.add(d)
        s.commit()
        flash(f"차원 '{name}' 추가됨.", "success")
    finally:
        s.close()
    return redirect(url_for("mapping.index"))


@bp.post("/dimension/<int:dim_id>/update")
def dimension_update(dim_id):
    s = SessionLocal()
    try:
        d = s.query(AliasDimension).filter(AliasDimension.id == dim_id).first()
        if not d:
            flash("차원을 찾을 수 없습니다.", "error")
            return redirect(url_for("mapping.index"))
        name = (request.form.get("name") or "").strip()
        if name:
            d.name = name
        try:
            w = request.form.get("weight")
            if w is not None and w != "":
                d.weight = int(w)
        except ValueError:
            pass
        s.commit()
        flash(f"차원 업데이트됨.", "success")
    finally:
        s.close()
    return redirect(url_for("mapping.index"))


@bp.post("/dimension/<int:dim_id>/delete")
def dimension_delete(dim_id):
    s = SessionLocal()
    try:
        d = s.query(AliasDimension).filter(AliasDimension.id == dim_id).first()
        if d:
            s.delete(d)
            s.commit()
            flash(f"차원 '{d.name}' 삭제됨 (캐노니컬·별칭 포함).", "success")
    finally:
        s.close()
    return redirect(url_for("mapping.index"))


# ============ 캐노니컬 (canonical) CRUD ============

@bp.post("/canonical/create")
def canonical_create():
    try:
        dim_id = int(request.form.get("dimension_id") or 0)
    except ValueError:
        dim_id = 0
    value = (request.form.get("value") or "").strip()
    if not dim_id or not value:
        flash("차원·값 모두 필요.", "error")
        return redirect(url_for("mapping.index"))
    s = SessionLocal()
    try:
        if s.query(AliasCanonical).filter(
            AliasCanonical.dimension_id == dim_id,
            AliasCanonical.value == value,
        ).first():
            flash(f"이미 존재: {value}", "error")
            return redirect(url_for("mapping.index"))
        c = AliasCanonical(dimension_id=dim_id, value=value)
        s.add(c)
        s.commit()
        flash(f"캐노니컬 '{value}' 추가됨.", "success")
    finally:
        s.close()
    return redirect(url_for("mapping.index"))


@bp.post("/canonical/<int:can_id>/update")
def canonical_update(can_id):
    s = SessionLocal()
    try:
        c = s.query(AliasCanonical).filter(AliasCanonical.id == can_id).first()
        if not c:
            flash("없음.", "error")
            return redirect(url_for("mapping.index"))
        new_val = (request.form.get("value") or "").strip()
        if new_val:
            c.value = new_val
        s.commit()
        flash("캐노니컬 업데이트됨.", "success")
    finally:
        s.close()
    return redirect(url_for("mapping.index"))


@bp.post("/canonical/<int:can_id>/delete")
def canonical_delete(can_id):
    s = SessionLocal()
    try:
        c = s.query(AliasCanonical).filter(AliasCanonical.id == can_id).first()
        if c:
            s.delete(c)
            s.commit()
            flash(f"캐노니컬 '{c.value}' 삭제됨.", "success")
    finally:
        s.close()
    return redirect(url_for("mapping.index"))


# ============ 별칭 (alias) CRUD ============

def _wants_json() -> bool:
    """AJAX 호출 여부 — X-Requested-With 헤더 명시 또는 ?format=json 쿼리만 JSON.

    Accept: */* 도 accept_mimetypes.accept_json=true 가 되는 버그 회피 — 일반 폼
    submit 시 JSON 페이지가 화면에 노출되는 사고 방지.
    """
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    if request.args.get("format") == "json":
        return True
    return False


@bp.post("/alias/create")
def alias_create():
    """캐노니컬에 별칭 추가. AJAX 헤더 있을 때만 JSON, 일반 폼 submit 은 redirect."""
    try:
        can_id = int(request.form.get("canonical_id") or 0)
    except ValueError:
        can_id = 0
    alias = (request.form.get("alias") or "").strip()
    if not can_id or not alias:
        if _wants_json():
            return jsonify({"ok": False, "error": "missing"}), 400
        flash("동의어를 입력하세요.", "error")
        return redirect(url_for("mapping.index"))
    s = SessionLocal()
    try:
        if s.query(AliasMapping).filter(
            AliasMapping.canonical_id == can_id,
            AliasMapping.alias == alias,
        ).first():
            if _wants_json():
                return jsonify({"ok": False, "error": "duplicate"}), 409
            flash(f"이미 등록된 동의어: {alias}", "error")
            return redirect(url_for("mapping.index"))
        m = AliasMapping(
            canonical_id=can_id,
            alias=alias,
            source=request.form.get("source") or "manual",
        )
        s.add(m)
        s.commit()
        if _wants_json():
            return jsonify({"ok": True, "id": m.id})
        flash(f"동의어 '{alias}' 추가됨.", "success")
    finally:
        s.close()
    return redirect(url_for("mapping.index"))


@bp.post("/alias/<int:m_id>/delete")
def alias_delete(m_id):
    s = SessionLocal()
    try:
        m = s.query(AliasMapping).filter(AliasMapping.id == m_id).first()
        if m:
            alias = m.alias
            s.delete(m)
            s.commit()
            if _wants_json():
                return jsonify({"ok": True})
            flash(f"동의어 '{alias}' 삭제됨.", "success")
    finally:
        s.close()
    return redirect(url_for("mapping.index"))


# ============ Playground — 자동 매칭 흐름 페이지 ============

@bp.get("/match/playground")
def match_playground():
    """모음전 옵션 → 자동 매칭 → 검토 → picker → 학습 흐름 데모 페이지.

    실제 모음전(bundles) 페이지에 다음 사이클에 부착할 컴포넌트의 검증 페이지.
    """
    s = SessionLocal()
    try:
        dims = (
            s.query(AliasDimension)
            .filter(AliasDimension.is_active.is_(True))
            .order_by(AliasDimension.sort_order, AliasDimension.id)
            .all()
        )
        return render_template("mapping/playground.html", active="mapping", dimensions=dims)
    finally:
        s.close()


@bp.post("/match/run")
def match_run():
    """JSON API — market_values 리스트 받아 매칭 결과 반환.

    Request:
      { "rows": [{"모델":"클래식","색상":"파랑","사이즈":"230mm"}, ...] }
    Response:
      {
        "results": [
          {
            "row_index": 0,
            "status": "auto" | "review" | "unmatched",
            "canonical": {"모델":"르무통 클래식","색상":"블루","사이즈":"230"},
            "matched_by": ["alias","alias","alias"],
            "unmatched_dims": [],
          },
          ...
        ],
        "summary": {"total": N, "auto": x, "review": y, "unmatched": z}
      }
    """
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows") or []
    s = SessionLocal()
    try:
        results = match_options_batch(s, rows)
        summary = {"total": len(results), "auto": 0, "review": 0, "unmatched": 0}
        out = []
        for i, r in enumerate(results):
            summary[r.status] += 1
            out.append({
                "row_index": i,
                "status": r.status,
                "canonical": r.canonical_values,
                "matched_by": [m.matched_by for m in r.dim_matches],
                "unmatched_dims": r.unmatched_dims,
            })
        return jsonify({"results": out, "summary": summary})
    finally:
        s.close()


@bp.post("/match/learn")
def match_learn():
    """사용자가 수동 매핑한 결과를 사전에 학습.

    Request:
      { "dimension":"색상", "market_value":"다크그레이", "canonical":"그레이" }
    Response: { "ok": true, "id": N }
    """
    payload = request.get_json(silent=True) or {}
    dim = (payload.get("dimension") or "").strip()
    mv = (payload.get("market_value") or "").strip()
    cv = (payload.get("canonical") or "").strip()
    if not dim or not mv or not cv:
        return jsonify({"ok": False, "error": "missing"}), 400
    s = SessionLocal()
    try:
        m = learn_alias(s, dim, mv, cv)
        if m is None:
            s.rollback()
            return jsonify({"ok": False, "error": "duplicate_or_invalid"})
        s.commit()
        return jsonify({"ok": True, "id": m.id})
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        s.close()


# ============ Seed (초기 기본 차원) ============

@bp.post("/seed-defaults")
def seed_defaults():
    """기본 3 차원 (모델 50·색상 25·사이즈 25) seed — 처음 진입 시 호출."""
    s = SessionLocal()
    try:
        if s.query(AliasDimension).count() > 0:
            flash("이미 차원이 등록되어 있습니다 — seed 생략.", "error")
            return redirect(url_for("mapping.index"))
        for sort_order, (name, weight) in enumerate([
            ("모델", 50), ("색상", 25), ("사이즈", 25),
        ]):
            s.add(AliasDimension(name=name, weight=weight, sort_order=sort_order))
        s.commit()
        flash("기본 차원 3개 (모델·색상·사이즈) 생성됨.", "success")
    finally:
        s.close()
    return redirect(url_for("mapping.index"))
