"""소싱처 크롤링 가이드 — 전체보기/상세 렌더 + crawl_guide JSON GET/PUT + ④ 검증."""
from __future__ import annotations

import io
import os
import zipfile
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request, send_file, abort, make_response

from shared.db import SessionLocal
# [2026-06-30 단일명부] 가이드도 단일 명부(SourcingSource)를 읽는다(이전 SourceRegistry).
#   식별자는 SourcingSource.id(정수) — 엔드포인트 시그니처 유지. name→label.
from lemouton.sourcing.models import SourcingSource
from lemouton.sourcing import crawl_guide as cg
from lemouton.sourcing import source_registry as sr
from lemouton.sourcing import roster
from lemouton.sourcing.crawl_queue import enqueue_verify, get_job
from webapp.routes.guide_sync import compute_guide_drift

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
    """단일 명부(SourcingSource) 활성 소싱처 — 빌트인 seed·가이드 이관 보장 후."""
    roster.seed_if_needed()
    s = SessionLocal()
    try:
        return (s.query(SourcingSource)
                  .filter(SourcingSource.is_active.is_(True))
                  .order_by(SourcingSource.is_builtin.desc(),
                            SourcingSource.sort_order, SourcingSource.id).all())
    finally:
        s.close()


def _source(sid: int):
    s = SessionLocal()
    try:
        return s.query(SourcingSource).get(sid)
    finally:
        s.close()


def _save_guide(s, src, guide: dict) -> None:
    """검증 후 명부(SourcingSource).crawl_guide 에 직렬화 저장."""
    src.crawl_guide = cg.dumps(guide)
    s.commit()


def _guide_is_blank(guide: dict) -> bool:
    """카드가 미작성인가 — 6항목 중 status=ok 가 하나도 없으면 미작성."""
    return not any(f.get("status") == "ok" for f in guide.get("fields", {}).values())


def _queue_items():
    """분석/업데이트 대기 목록. 신규(빈 카드+URL) + 업데이트(update_requested)."""
    out = []
    for src in _sources():
        guide = cg.loads(src.crawl_guide)
        has_url = len(guide.get("sample_urls", [])) > 0
        if guide.get("update_requested"):
            out.append({"id": src.id, "name": src.label, "kind": "update",
                        "note": guide["update_requested"].get("note", ""),
                        "url_count": len(guide.get("sample_urls", []))})
        elif has_url and _guide_is_blank(guide):
            out.append({"id": src.id, "name": src.label, "kind": "new",
                        "note": "", "url_count": len(guide["sample_urls"])})
    return out


def _find_existing_by_domain(s, urls):
    """입력 URL 의 도메인이 (a)이미 등록된 소싱처의 URL 또는 (b)빌트인 크롤지원
    소싱처(카탈로그)와 겹치면 그 소싱처 정보를 반환 → 중복 신규 생성 차단.

    hmall 중복 교훈: 진짜 hmall 레지스트리 행은 sample_urls 가 비어 도메인 매칭이
    안 잡힐 수 있으므로 (b)카탈로그 도메인 매칭이 필수. 첫 매칭 반환, 없으면 None.
    """
    domains = {sr.domain_of(u) for u in urls}
    domains.discard("")
    if not domains:
        return None
    # (a) 이미 등록된 소싱처의 sample_urls 도메인과 겹치나
    for src in _sources():
        guide = cg.loads(src.crawl_guide)
        su = {sr.domain_of(x.get("url", "")) for x in guide.get("sample_urls", [])}
        su.discard("")
        if domains & su:
            return {"kind": "registered", "id": src.id, "name": src.label}
    # (b) 빌트인 크롤지원 소싱처(카탈로그)와 도메인 겹치나
    for u in urls:
        c = sr.catalog_by_domain(u)
        if c:
            return {"kind": "builtin", "name": c["label"], "key": c["key"]}
    return None


@bp.post("/api/add-source")
def api_add_source():
    """신규 소싱처: 이름 + URL 다중 → SourceRegistry 생성 + sample_urls 저장.
    저장 즉시 전체보기에 '미정의'로 등장하고 '분석 대기' 큐에 잡힌다.

    존재검사 게이트: 같은 이름/도메인이 이미 있으면 exists=True 로 막고 '기존
    업데이트'로 유도(중복 방지). force=True 면 무시하고 강행(사용자 명시 확인 후).
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    urls = [u.strip() for u in (data.get("urls") or []) if str(u).strip()]
    force = bool(data.get("force"))
    if not name:
        return jsonify(ok=False, error="소싱처 이름을 입력하세요."), 400
    if len(name) > 64:
        return jsonify(ok=False, error="이름은 64자 이내."), 400
    s = SessionLocal()
    try:
        dup = s.query(SourcingSource).filter_by(label=name).first()
        if dup and not force:
            return jsonify(ok=False, exists=True,
                           existing={"kind": "registered", "id": dup.id, "name": dup.label},
                           error=f"'{name}' 은 이미 등록된 소싱처에요. 기존 업데이트로 진행하세요."), 409
        if not force:
            hit = _find_existing_by_domain(s, urls)
            if hit:
                label = hit.get("name", "")
                msg = (f"이 사이트는 이미 크롤 지원되는 소싱처({label})예요. "
                       if hit["kind"] == "builtin" else
                       f"같은 사이트가 이미 '{label}' 으로 등록돼 있어요. ")
                return jsonify(ok=False, exists=True, existing=hit,
                               error=msg + "기존 업데이트 탭에서 진행하세요."), 409
        # 단일 명부(SourcingSource) 행 생성 — source_key 는 첫 URL 도메인에서 도출(불변).
        import re as _re
        dom = ""
        for u in urls:
            dom = sr.domain_of(u)
            if dom:
                break
        base = _re.sub(r"[^a-z0-9]", "",
                       (dom.split(".")[0].lower() if dom else _re.sub(r"[^a-z0-9]", "", name.lower()))) or "src"
        existing_keys = {r[0] for r in s.query(SourcingSource.source_key).all()}
        key, n = base, 2
        while key in existing_keys:
            key, n = f"{base}{n}", n + 1
        src = SourcingSource(
            source_key=key, label=name, domain=(dom or (key + ".com")),
            favicon_url=(f"https://{dom}/favicon.ico" if dom else None),
            is_active=True, is_builtin=False, has_adapter=False, sort_order=100,
        )
        s.add(src)
        s.flush()
        guide = cg.empty_skeleton()
        guide["sample_urls"] = [
            {"url": u, "is_lead": (i == 0)} for i, u in enumerate(urls)
        ]
        guide["updated_at"] = _now_iso()
        try:
            _save_guide(s, src, guide)
        except ValueError as e:
            s.rollback()
            return jsonify(ok=False, error=f"URL 형식이 올바르지 않습니다: {e}"), 400
        return jsonify(ok=True, id=src.id, name=src.label,
                       url_count=len(guide["sample_urls"]))
    finally:
        s.close()


@bp.post("/api/<int:sid>/save-urls")
def api_save_urls(sid: int):
    """기존 소싱처 sample_urls 전체 교체(추가/수정/삭제 결과 리스트). 첫 URL=대표."""
    data = request.get_json(silent=True) or {}
    urls = [u.strip() for u in (data.get("urls") or []) if str(u).strip()]
    s = SessionLocal()
    try:
        src = s.query(SourcingSource).get(sid)
        if not src:
            return jsonify(ok=False, error="소싱처를 찾을 수 없어요."), 404
        guide = cg.loads(src.crawl_guide)
        guide["sample_urls"] = [{"url": u, "is_lead": (i == 0)} for i, u in enumerate(urls)]
        guide["updated_at"] = _now_iso()
        try:
            _save_guide(s, src, guide)
        except ValueError as e:
            s.rollback()
            return jsonify(ok=False, error=f"URL 형식이 올바르지 않습니다: {e}"), 400
        return jsonify(ok=True, url_count=len(urls))
    finally:
        s.close()


@bp.post("/api/<int:sid>/request-update")
def api_request_update(sid: int):
    """기존 소싱처 크롤 업데이트 요청 — update_requested 플래그 설정(=업데이트 대기 큐)."""
    data = request.get_json(silent=True) or {}
    note = (data.get("note") or "").strip()
    s = SessionLocal()
    try:
        src = s.query(SourcingSource).get(sid)
        if not src:
            return jsonify(ok=False, error="소싱처를 찾을 수 없어요."), 404
        guide = cg.loads(src.crawl_guide)
        guide["update_requested"] = {"at": _now_iso(), "note": note}
        _save_guide(s, src, guide)
        return jsonify(ok=True)
    finally:
        s.close()


@bp.post("/api/<int:sid>/merge-into/<int:target_sid>")
def api_merge_into(sid: int, target_sid: int):
    """중복 소싱처 정리 — sid(빈 중복 카드)의 URL 을 target 으로 옮기고 sid 제거.

    안전장치: sid 는 반드시 '빈 카드'(크롤 정의 없음)여야 한다 — 실제 크롤 설정이
    있는 소싱처는 실수 삭제 금지(데이터 무결성). hmall 중복(②HMALL 분석대기 →
    ①현대홈쇼핑) 정리에 사용."""
    if sid == target_sid:
        return jsonify(ok=False, error="자기 자신과 병합할 수 없어요."), 400
    s = SessionLocal()
    try:
        src = s.query(SourcingSource).get(sid)
        tgt = s.query(SourcingSource).get(target_sid)
        if not src or not tgt:
            return jsonify(ok=False, error="소싱처를 찾을 수 없어요."), 404
        if src.is_builtin:
            return jsonify(ok=False, error="빌트인 소싱처는 병합·삭제할 수 없어요."), 400
        src_guide = cg.loads(src.crawl_guide)
        if not _guide_is_blank(src_guide):
            return jsonify(ok=False,
                           error=f"'{src.label}' 은 크롤 정의가 있어 안전상 병합 불가. 빈 중복 카드만 정리합니다."), 400
        # URL 합치기(중복 제거, target 대표 유지)
        tgt_guide = cg.loads(tgt.crawl_guide)
        seen, merged = set(), []
        for x in tgt_guide.get("sample_urls", []) + src_guide.get("sample_urls", []):
            u = (x.get("url") or "").strip()
            if u and u not in seen:
                seen.add(u)
                merged.append({"url": u, "is_lead": (len(merged) == 0)})
        tgt_guide["sample_urls"] = merged
        tgt_guide["updated_at"] = _now_iso()
        try:
            _save_guide(s, tgt, tgt_guide)
        except ValueError as e:
            s.rollback()
            return jsonify(ok=False, error=f"URL 형식 오류: {e}"), 400
        s.delete(src)
        s.commit()
        return jsonify(ok=True, target=tgt.label, url_count=len(merged))
    except Exception as e:
        s.rollback()
        return jsonify(ok=False, error=f"병합 실패(참조 제약 가능): {str(e)[:120]}"), 400
    finally:
        s.close()


@bp.get("/api/queue")
def api_queue():
    return jsonify(ok=True, items=_queue_items())


# ── [2026-06-30] 소싱처 명부 관리 — 사전 통합. 전체보기 행 인라인 편집이 호출. ──
#   사전(/source-registry) 제거 후 관리 API 를 여기로 이동. 로그인 게이트만(admin 강제 X).
@bp.put("/api/source/<key>")
def api_source_update(key):
    """이름변경(name) / 로고(logo_url→favicon) / 숨김(is_active)."""
    data = request.get_json(silent=True) or {}
    try:
        if "name" in data:
            roster.rename(key, data["name"])
        if "logo_url" in data:
            dom = sr.domain_of((data.get("logo_url") or "").strip())
            roster.set_logo(key, domain=(dom or None),
                            favicon_url=(f"https://{dom}/favicon.ico" if dom else None))
        if "is_active" in data:
            roster.set_active(key, bool(data["is_active"]))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, key=key)


@bp.delete("/api/source/<key>")
def api_source_delete(key):
    """커스텀 + 참조 0 일 때만 삭제. 빌트인은 차단(roster.delete 가드)."""
    try:
        roster.delete(key)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, deleted=key)


@bp.post("/api/sources/reorder")
def api_sources_reorder():
    data = request.get_json(silent=True) or {}
    keys = data.get("keys") or []
    if not isinstance(keys, list):
        return jsonify(ok=False, error="keys must be a list"), 400
    s = SessionLocal()
    try:
        rows = {r.source_key: r for r in s.query(SourcingSource).all()}
        for order, k in enumerate(keys):
            if k in rows:
                rows[k].sort_order = order
        s.commit()
        return jsonify(ok=True, reordered=len(keys))
    finally:
        s.close()


@bp.route("/add")
def add_page():
    """소싱처 추가·업데이트 카드 — 2탭(신규/기존) 페이지."""
    sources = [{"id": x.id, "name": x.label} for x in _sources()]
    return render_template("sourcing_guide/add.html",
                           active="sourcing_guide", sources=sources)


@bp.route("/")
def overview():
    rows = []
    usage = roster.usage_by_key()           # source_key → 참조 수(삭제 가드 표시)
    for src in _sources():
        guide = cg.loads(src.crawl_guide)
        pending = bool(guide.get("update_requested")) or \
            (len(guide.get("sample_urls", [])) > 0 and _guide_is_blank(guide))
        rows.append({
            "id": src.id, "key": src.source_key, "name": src.label, "guide": guide,
            "pending": pending,
            # [2026-06-30 사전 통합] 행 인라인 관리(로고·이름·숨김·삭제)용 메타
            "domain": src.domain or "",
            "main_url": (("https://" + src.domain) if src.domain else ""),
            "favicon_url": src.favicon_url or "",
            "is_builtin": bool(src.is_builtin),
            "is_active": bool(src.is_active),
            "usage": usage.get(src.source_key, 0),
        })
    return render_template("sourcing_guide/overview.html", rows=rows,
                           active="sourcing_guide", **_ext_ctx())


# ════════════════════════════════════════════════════════════
#  크롤러 설치 가이드 — 팀원이 본인 PC 크롬에 '모음전 크롤러' 확장을 설치해
#  무신사·롯데온을 로컬 로그인 브라우저로 긁고 결과를 서버에 저장하게 안내.
#  확장 단일 원본 = 프로그램/_시스템/extension/moum-crawler (배포 트리 안 → 라이브 다운로드 가능).
# ════════════════════════════════════════════════════════════
# 이 파일: .../webapp/routes/sourcing_guide.py → 두 단계 위가 앱 루트(_시스템)
_EXT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "extension", "moum-crawler")
)


def _ext_version() -> str:
    """확장 manifest.json 의 현재 버전 — 다운로드/표시가 항상 최신본을 가리키도록."""
    import json as _json
    try:
        with open(os.path.join(_EXT_DIR, "manifest.json"), encoding="utf-8") as f:
            return str((_json.load(f) or {}).get("version") or "")
    except (OSError, ValueError):
        return ""


def _ext_ctx() -> dict:
    """설치 페이지/모달 공통 컨텍스트 — 가용 여부 + 최신 버전(항상 manifest 기준).
    설치 모달(_install_modal.html)을 include 하는 라우트는 이걸 넘겨야 다운로드가 켜진다."""
    return {"ext_available": os.path.isdir(_EXT_DIR), "ext_version": _ext_version()}


@bp.route("/install")
def install():
    """크롤러 설치 가이드 페이지 (시안 5 — 진행 체크리스트)."""
    return render_template("sourcing_guide/install.html", active="sourcing_guide",
                           **_ext_ctx())


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
    _ver = _ext_version()
    _name = f"모음전-크롤러-v{_ver}.zip" if _ver else "모음전-크롤러.zip"
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=_name)


# ════════════════════════════════════════════════════════════
#  데이터·코드 지도 — 크롤링/재고/가격/매트릭스 표시의 단일 진실 원천(SSOT).
#  정본 = 프로그램/_시스템/docs/크롤링-가이드.md (배포 포함). 사용자=HTML 렌더, Claude=원문 .md.
# ════════════════════════════════════════════════════════════
_GUIDE_MD = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "크롤링-가이드.md")
)
# 앱 루트(_시스템) = 이 파일 기준 ../.. (guide_sync 검사용)
_APP_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


@bp.route("/map")
def data_code_map():
    """데이터·코드 지도 (HTML 렌더 — 6탭 + 보기/원문 토글).

    ?bare=1 → 사이드바 없는 최소 레이아웃(_bare.html). 전체보기의 팝업 모달이 iframe 으로 띄움.
    """
    drift = compute_guide_drift(_APP_ROOT)
    if request.args.get("bare"):
        # 전체보기의 same-origin iframe 팝업으로 띄움 → 전역 X-Frame-Options: DENY 예외.
        #   (setdefault 라 라우트에서 먼저 박으면 after_request 가 안 덮음)
        resp = make_response(render_template(
            "sourcing_guide/map.html", active="sourcing_guide", layout="_bare.html", drift=drift))
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        return resp
    return render_template("sourcing_guide/map.html", active="sourcing_guide", layout="base.html", drift=drift)


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
    sources = [{"id": x.id, "name": x.label} for x in _sources()]
    return render_template("sourcing_guide/detail.html",
                           src={"id": src.id, "name": src.label},
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
        src = s.query(SourcingSource).get(sid)
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
        src = s.query(SourcingSource).get(sid)
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
        src = s.query(SourcingSource).get(sid)
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
        src = s.query(SourcingSource).get(sid)
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
            data = shot.capture_screenshot(url, source_name=src.label)
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
        job = enqueue_verify(url, required_login=(src.label or "").lower(),
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
            src = s.query(SourcingSource).get(sid)
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
