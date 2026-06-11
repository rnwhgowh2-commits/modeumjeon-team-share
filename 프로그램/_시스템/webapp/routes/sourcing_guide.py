"""소싱처 크롤링 가이드 — 전체보기/상세 렌더 + crawl_guide JSON GET/PUT + ④ 검증."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request

from shared.db import SessionLocal
from lemouton.sourcing.models_pricing import SourceRegistry
from lemouton.sourcing import crawl_guide as cg
from lemouton.sourcing.crawl_queue import enqueue_verify, get_job

bp = Blueprint("sourcing_guide", __name__, url_prefix="/sourcing-guide")


@bp.before_request
def _admin_only():
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sources():
    s = SessionLocal()
    try:
        return s.query(SourceRegistry).order_by(SourceRegistry.sort_order, SourceRegistry.id).all()
    finally:
        s.close()


def _source(sid: int):
    s = SessionLocal()
    try:
        return s.query(SourceRegistry).get(sid)
    finally:
        s.close()


@bp.route("/")
def overview():
    rows = []
    for src in _sources():
        guide = cg.loads(src.crawl_guide)
        rows.append({"id": src.id, "name": src.name, "guide": guide})
    return render_template("sourcing_guide/overview.html", rows=rows, active="sourcing_guide")


@bp.route("/how-to")
def how_to_add():
    """신규 소싱처 추가 가이드 (시안 E 분기 순서도). 정식 SOP = docs/신규-소싱처-추가-가이드.md."""
    return render_template("sourcing_guide/how_to_add.html", active="sourcing_guide")


@bp.route("/<int:sid>")
def detail(sid: int):
    src = _source(sid)
    if src is None:
        return "not found", 404
    guide = cg.loads(src.crawl_guide)
    sources = [{"id": x.id, "name": x.name} for x in _sources()]
    return render_template("sourcing_guide/detail.html",
                           src={"id": src.id, "name": src.name},
                           guide=guide, sources=sources, active="sourcing_guide")


@bp.route("/api/<int:sid>", methods=["GET"])
def api_get(sid: int):
    src = _source(sid)
    if src is None:
        return jsonify(ok=False, error="not_found"), 404
    return jsonify(ok=True, guide=cg.loads(src.crawl_guide))


@bp.route("/api/<int:sid>", methods=["PUT"])
def api_put(sid: int):
    s = SessionLocal()
    try:
        src = s.query(SourceRegistry).get(sid)
        if src is None:
            return jsonify(ok=False, error="not_found"), 404
        try:
            incoming = request.get_json(force=True) or {}
            if "verification" not in incoming:
                incoming["verification"] = cg.loads(src.crawl_guide).get("verification")
            guide = cg.validate_guide(incoming)
        except ValueError as e:
            return jsonify(ok=False, error="invalid", message=str(e)), 400
        guide["updated_at"] = _now_iso()
        src.crawl_guide = cg.dumps(guide)
        s.commit()
        return jsonify(ok=True, guide=guide)
    finally:
        s.close()


@bp.route("/api/<int:sid>/example-shot", methods=["POST"])
def api_example_shot(sid: int):
    """④ 예제 기준 스크린샷 — 드래그앤드랍 업로드. 이미지는 data URL 로 guide JSON 에 저장(재배포 영속)."""
    s = SessionLocal()
    try:
        src = s.query(SourceRegistry).get(sid)
        if src is None:
            return jsonify(ok=False, error="not_found"), 404
        body = request.get_json(force=True) or {}
        idx = body.get("index")
        img = body.get("image", "")
        if not isinstance(idx, int) or not isinstance(img, str) or not img.startswith("data:image/"):
            return jsonify(ok=False, error="invalid"), 400
        if len(img) > 600_000:
            return jsonify(ok=False, error="too_large", message="이미지가 너무 큽니다"), 400
        guide = cg.loads(src.crawl_guide)
        exs = (guide.get("verification") or {}).get("examples") or []
        if idx < 0 or idx >= len(exs):
            return jsonify(ok=False, error="bad_index"), 400
        exs[idx]["screenshot_url"] = img
        guide["updated_at"] = _now_iso()
        src.crawl_guide = cg.dumps(guide)
        s.commit()
        return jsonify(ok=True)
    finally:
        s.close()


@bp.route("/api/<int:sid>/example-shot/auto", methods=["POST"])
def api_example_shot_auto(sid: int):
    """④ 예제 기준 스크린샷 — 서버 Playwright 자동 캡처 → R2 → screenshot_url 저장.

    캡처는 Playwright 브라우저가 설치된 환경(개발 PC)에서 실행. 결과 URL 은
    Supabase guide JSON 에 저장되어 prod/dev 어디서나 표시된다.
    """
    s = SessionLocal()
    try:
        src = s.query(SourceRegistry).get(sid)
        if src is None:
            return jsonify(ok=False, error="not_found"), 404
        body = request.get_json(force=True) or {}
        idx = body.get("index")
        if not isinstance(idx, int):
            return jsonify(ok=False, error="invalid"), 400
        guide = cg.loads(src.crawl_guide)
        exs = (guide.get("verification") or {}).get("examples") or []
        if idx < 0 or idx >= len(exs):
            return jsonify(ok=False, error="bad_index"), 400
        url = exs[idx].get("url")
        if not url:
            return jsonify(ok=False, error="no_url", message="예제에 URL이 없습니다"), 400
        from lemouton.sourcing import screenshot as shot
        try:
            data = shot.capture_screenshot(url, source_name=src.name)
            public = shot.store_guide_screenshot(sid, idx, data)
        except RuntimeError as e:
            return jsonify(ok=False, error="capture_failed", message=str(e)), 502
        exs[idx]["screenshot_url"] = public
        exs[idx]["captured_at"] = _now_iso()
        guide["updated_at"] = _now_iso()
        src.crawl_guide = cg.dumps(guide)
        s.commit()
        return jsonify(ok=True, url=public)
    finally:
        s.close()


@bp.route("/api/<int:sid>/verify", methods=["POST"])
def api_verify(sid: int):
    src = _source(sid)
    if src is None:
        return jsonify(ok=False, error="not_found"), 404
    url = (request.get_json(force=True) or {}).get("url", "")
    try:
        job = enqueue_verify(url, required_login=(src.name or "").lower(),
                             triggered_by="guide_verify")
    except ValueError as e:
        return jsonify(ok=False, error="invalid_url", message=str(e)), 400
    return jsonify(ok=True, job_id=job["id"], status=job["status"])


@bp.route("/api/<int:sid>/verify/<int:job_id>", methods=["GET"])
def api_verify_status(sid: int, job_id: int):
    job = get_job(job_id)
    if job is None:
        return jsonify(ok=False, error="not_found"), 404
    if job["status"] == "done" and job.get("result") and job.get("phase") == "verify":
        s = SessionLocal()
        try:
            src = s.query(SourceRegistry).get(sid)
            if src is not None:
                cur = cg.loads(src.crawl_guide)
                lnc = (cur.get("verification") or {}).get("last_new_check") or {}
                if lnc.get("job_id") != job_id:   # 이미 병합된 잡이면 재기록 안 함
                    merged = cg.merge_verification(cur, "last_new_check",
                                                   {**job["result"], "job_id": job_id,
                                                    "status": "done"})
                    src.crawl_guide = cg.dumps(merged)
                    s.commit()
        finally:
            s.close()
    return jsonify(ok=True, job=job)
