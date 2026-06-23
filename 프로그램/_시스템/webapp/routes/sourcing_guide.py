"""소싱처 크롤링 가이드 — 전체보기/상세 렌더 + crawl_guide JSON GET/PUT + ④ 검증."""
from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request, send_file, abort, make_response

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


# ════════════════════════════════════════════════════════════
#  크롤러 설치 가이드 — 팀원이 본인 PC 크롬에 '모음전 크롤러' 확장을 설치해
#  무신사·롯데온을 로컬 로그인 브라우저로 긁고 결과를 서버에 저장하게 안내.
#  확장 단일 원본 = 프로그램/_시스템/extension/moum-crawler (배포 트리 안 → 라이브 다운로드 가능).
# ════════════════════════════════════════════════════════════
# 이 파일: .../webapp/routes/sourcing_guide.py → 두 단계 위가 앱 루트(_시스템)
_EXT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "extension", "moum-crawler")
)


@bp.route("/install")
def install():
    """크롤러 설치 가이드 페이지 (시안 5 — 진행 체크리스트)."""
    return render_template("sourcing_guide/install.html", active="sourcing_guide",
                           ext_available=os.path.isdir(_EXT_DIR))


@bp.route("/install/download")
def install_download():
    """'모음전 크롤러' 확장 폴더를 즉석 zip 으로 묶어 다운로드.

    압축 후 풀면 `moum-crawler/` 폴더가 생기고, 사용자는 chrome://extensions 에서
    이 폴더를 '압축해제된 확장 로드'로 선택하면 된다.
    """
    if not os.path.isdir(_EXT_DIR):
        abort(404, description="확장 원본 폴더를 찾을 수 없습니다.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(_EXT_DIR):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, _EXT_DIR)
                zf.write(full, os.path.join("moum-crawler", rel))
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name="모음전-크롤러.zip")


# ════════════════════════════════════════════════════════════
#  데이터·코드 지도 — 크롤링/재고/가격/매트릭스 표시의 단일 진실 원천(SSOT).
#  정본 = 프로그램/_시스템/docs/크롤링-가이드.md (배포 포함). 사용자=HTML 렌더, Claude=원문 .md.
# ════════════════════════════════════════════════════════════
_GUIDE_MD = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "크롤링-가이드.md")
)


@bp.route("/map")
def data_code_map():
    """데이터·코드 지도 (HTML 렌더 — 6탭 + 보기/원문 토글).

    ?bare=1 → 사이드바 없는 최소 레이아웃(_bare.html). 전체보기의 팝업 모달이 iframe 으로 띄움.
    """
    if request.args.get("bare"):
        # 전체보기의 same-origin iframe 팝업으로 띄움 → 전역 X-Frame-Options: DENY 예외.
        #   (setdefault 라 라우트에서 먼저 박으면 after_request 가 안 덮음)
        resp = make_response(render_template(
            "sourcing_guide/map.html", active="sourcing_guide", layout="_bare.html"))
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        return resp
    return render_template("sourcing_guide/map.html", active="sourcing_guide", layout="base.html")


@bp.route("/map.md")
def data_code_map_raw():
    """정본 마크다운 원문 그대로 (MD 바로열기). Claude가 그대로 읽고 복귀."""
    try:
        with open(_GUIDE_MD, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        abort(404, description="정본 문서를 찾을 수 없습니다.")
    from flask import Response
    return Response(text, mimetype="text/markdown; charset=utf-8")


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
            apply_bundles = bool(incoming.get("apply_to_bundles"))
            if "verification" not in incoming:
                incoming["verification"] = cg.loads(src.crawl_guide).get("verification")
            guide = cg.validate_guide(incoming)
        except ValueError as e:
            return jsonify(ok=False, error="invalid", message=str(e)), 400
        guide["updated_at"] = _now_iso()
        src.crawl_guide = cg.dumps(guide)
        # 혜택 '값' 입력칸 → 소싱처 기본셋팅(SourceBenefitTemplate) 연결 (2026-06-13).
        #   템플릿 동기화는 항상(새 모음전부터 반영). apply_to_bundles 확인 시 기존 모음전까지 덮어씀(비가역).
        from webapp.routes.api_benefits import (
            sync_templates_from_crawl_guide, snapshot_bundle_from_templates,
        )
        benefits_synced = sync_templates_from_crawl_guide(s, sid, guide)
        bundles_applied = 0
        if apply_bundles and benefits_synced:
            from lemouton.sourcing.models import Model
            codes = [c[0] for c in s.query(Model.model_code).all() if c[0]]
            for code in codes:
                r = snapshot_bundle_from_templates(s, code, source_ids=[sid])
                if r["options"]:
                    bundles_applied += 1
        s.commit()
        return jsonify(ok=True, guide=guide,
                       benefits_synced=benefits_synced, bundles_applied=bundles_applied)
    finally:
        s.close()


@bp.route("/api/<int:sid>/gate-preview", methods=["POST"])
def api_gate_preview(sid: int):
    """키워드 게이트 실검증 — 크롤된 혜택 라인에 '저장된' 포함/제외 키워드를 적용.

    설계: 무신사 = 로그인 브라우저가 크롤러. 브라우저가 르무통 페이지에서 읽은
    혜택 라인을 보내면, 서버가 이 소싱처 가이드 ③의 저장된 키워드 규칙으로
    어떤 혜택이 포함/제외되는지 판정(+선택적으로 최종 매입가 계산)해 돌려준다.
    DB 쓰기 없음 — 순수 미리보기(머니 경로 무영향).

    payload: {
      benefit_lines: [str, ...],          # 크롤된 혜택 문구 라인 (필수)
      base_price?: int,                    # 회원가(표면 노출가) — 최종가 계산용
      amounts?: {benefit_name: {type:'rate'|'amount', value: float}}  # 크롤된 혜택 금액
    }
    returns: {ok, lines, gated:[{name,applied,matched_lines,excluded,reason}],
              final_price?, base_price?}
    """
    from lemouton.pricing.benefit_gate import gate_benefits

    src = _source(sid)
    if src is None:
        return jsonify(ok=False, error="not_found"), 404
    body = request.get_json(force=True) or {}
    lines = body.get("benefit_lines")
    if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
        return jsonify(ok=False, error="invalid", message="benefit_lines 는 문자열 리스트"), 400

    guide = cg.loads(src.crawl_guide)
    pricing = guide.get("pricing") or {}
    benefits = pricing.get("benefits") or []
    excludes = guide.get("exclude_keywords") or []

    gated = gate_benefits(benefits, lines, excludes)

    out = {"ok": True, "lines": lines, "gated": gated,
           "exclude_keywords": excludes}

    # 선택: 크롤 금액(amounts)이 오면 게이트 결과로 최종 매입가까지 계산.
    base_price = body.get("base_price")
    amounts = body.get("amounts") or {}
    if isinstance(base_price, (int, float)) and base_price > 0 and amounts:
        from lemouton.pricing.final_price import compute_final_price

        class _It:
            def __init__(self, name, btype, value, enabled):
                self.id = -1; self.benefit_name = name; self.benefit_type = btype
                self.value = value; self.enabled = enabled
                self.category = None; self.sort_order = 999; self.template_id = None

        items = []
        for g in gated:
            a = amounts.get(g["name"]) or {}
            bt = a.get("type", "amount")
            val = float(a.get("value") or 0)
            items.append(("dyn", _It(g["name"], bt, val, enabled=g["applied"])))
        res = compute_final_price(float(base_price), items, base_override=None)
        out["base_price"] = int(base_price)
        out["final_price"] = res["final_price"]
        out["steps"] = res["steps"]
    return jsonify(out)


@bp.route("/api/<int:sid>/save-check", methods=["POST"])
def api_save_check(sid: int):
    """④ 신규 검증 결과 저장 (시안 2-C) — verification.saved_checks 에 누적(최신순) + ① 기준 샘플 URL 동시 등록.

    payload: {url, name?, final_price?, summary?}
    """
    s = SessionLocal()
    try:
        src = s.query(SourceRegistry).get(sid)
        if src is None:
            return jsonify(ok=False, error="not_found"), 404
        body = request.get_json(force=True) or {}
        url = (body.get("url") or "").strip()
        guide = cg.loads(src.crawl_guide)
        ver = guide.get("verification") or {}
        checks = list(ver.get("saved_checks") or [])
        entry = {
            "url": url or None,
            "name": str(body.get("name", ""))[:80],
            "final_price": body.get("final_price"),
            "summary": str(body.get("summary", ""))[:200],
            "saved_at": _now_iso(),
        }
        # 같은 URL 이전 기록 제거 후 맨 앞에 (최신순, 최대 50)
        checks = [c for c in checks if c.get("url") != url or not url]
        checks.insert(0, entry)
        ver["saved_checks"] = checks[:50]
        guide["verification"] = ver
        # ① 기준 샘플 URL 동시 등록 (중복 방지)
        added_to_samples = False
        if url and (url.startswith("http://") or url.startswith("https://")):
            samples = list(guide.get("sample_urls") or [])
            if not any(u.get("url") == url for u in samples):
                samples.append({"url": url, "is_lead": False})
                guide["sample_urls"] = samples
                added_to_samples = True
        guide = cg.validate_guide(guide)
        guide["updated_at"] = _now_iso()
        src.crawl_guide = cg.dumps(guide)
        s.commit()
        return jsonify(ok=True, saved_checks=guide["verification"]["saved_checks"],
                       added_to_samples=added_to_samples)
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
