"""POST /api/sources/parse — 로컬 확장이 창에서 긁은 HTML 을 서버 기존 파서로 추출.

설계 A안: 무신사·롯데온은 확장 JS 가 직접 추출하고, 르무통·SSF·SSG·스스르무통은
이 엔드포인트가 crawlers[source_key].parse_html(html,url) 로 구조화한다.
"""
from __future__ import annotations
import os
from dataclasses import asdict
from flask import Blueprint, jsonify, request

bp = Blueprint("api_sources_parse", __name__, url_prefix="/api")

_PARSE_SOURCES = {"lemouton", "ssf", "ssg", "ss_lemouton"}


@bp.before_request
def _admin_only():
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


@bp.post("/sources/parse")
def parse_source_html():
    body = request.get_json(silent=True) or {}
    source_key = body.get("source_key")
    url = body.get("url")
    html = body.get("html")
    # 스스 per-SKU 재고 맵("색상||사이즈"→수량) — 확장이 n/v2 API 로 수집해 동봉(선택).
    sku_stock = body.get("sku_stock") if isinstance(body.get("sku_stock"), dict) else None
    if source_key not in _PARSE_SOURCES:
        return jsonify(ok=False, error="bad_source",
                       message=f"parse 지원 소싱처 아님: {source_key}"), 400
    if not isinstance(url, str) or not isinstance(html, str) or not html.strip():
        return jsonify(ok=False, error="bad_input", message="url·html 필요"), 400
    from lemouton.sourcing.crawlers import build_crawlers
    crawler = build_crawlers().get(source_key)
    if crawler is None or not hasattr(crawler, "parse_html"):
        return jsonify(ok=False, error="no_parser"), 400
    try:
        # [2026-06-20 money-safe] SSG 딜페이지(dealItemView) — 자동 '대표상품' 크롤 금지.
        #   딜 페이지 itemView 링크에 SSG 광고 캐러셀(data-advert) 상품이 섞여 '첫 itemView'가
        #   무관한 광고상품(예: 여성 와이드 바지)일 수 있음 → 엉뚱한 가격/재고(금전 위험).
        #   딜은 모델 선택(resolve_deal_models)으로 단일 itemView URL 을 지정해 크롤해야 한다.
        if source_key == "ssg" and "uitemObjArr.push" not in html:
            # 딜 HTML 직접 파싱(옵션 없음=정직한 '데이터 없음'). 대표상품 자동선택 폐기.
            res = crawler.parse_html(html, url)
        elif source_key == "ss_lemouton" and sku_stock:
            # ss_lemouton 만 sku_stock 을 받아 옵션별 재고 교정. 타 파서는 (html,url) 시그니처.
            res = crawler.parse_html(html, url, sku_stock=sku_stock)
        else:
            res = crawler.parse_html(html, url)
    except Exception as e:
        return jsonify(ok=False, error="parse_failed", message=str(e)[:200]), 200
    payload = asdict(res)
    # ★ 2026-06-22 — navGrab(SSF·SSG·르무통·스스) 동적 혜택 서버측 저장.
    #   서버 크롤러가 옵션에 채운 동적 키(멤버십포인트·기프트포인트·SSG MONEY·상품쿠폰 등)를
    #   여기서 SourceProduct.dynamic_benefits_json 에 직접 저장한다(확장이 그 키를 드롭해
    #   라이브에서 비어 있던 사고 수정). 무신사·롯데온은 직읽기 경로(별도)라 여기 안 옴.
    _dbg = None
    try:
        _dbg = _save_navgrab_dynamic_benefits(source_key, url, payload.get("options") or [])
    except Exception as _e:
        _dbg = {"error": str(_e)[:160]}  # 저장 실패해도 파싱 결과 반환은 유지
    return jsonify(ok=True, _dyn_debug=_dbg, **payload)


def _save_navgrab_dynamic_benefits(source_key: str, url: str, options: list) -> dict:
    """parse 결과 options 의 동적 혜택을 (url + site=source_key) 매칭 SourceProduct 에 저장.

    ★ site 일치 필수 — 같은 URL 이 여러 SourceProduct(site 다름)에 걸려 있어, site 를
      안 가리면 엉뚱한 상품(예: 'lemouton')에 저장돼 compute_breakdown(site='ssf')이 못 읽음.
    """
    from lemouton.pricing.benefit_parse import extract_dynamic_benefits_from_options
    from lemouton.sources.service import normalize_url
    from lemouton.sources.models import SourceProduct
    from shared.db import SessionLocal
    import json as _json
    dyn = extract_dynamic_benefits_from_options(options)
    s = SessionLocal()
    try:
        target = normalize_url(url)
        url_cands = [p for p in s.query(SourceProduct)
                     .filter(SourceProduct.deleted_at.is_(None)).all()
                     if p.url and normalize_url(p.url) == target]
        # site == source_key 우선, 없으면 None(잘못된 site 에 저장하지 않음)
        sp = next((p for p in url_cands if getattr(p, "site", None) == source_key), None)
        dbg = {"target": target[:70], "dyn_keys": list(dyn.keys()),
               "url_cands": [{"id": p.id, "site": getattr(p, "site", None)} for p in url_cands]}
        if sp is None:
            dbg["matched"] = False
            return dbg
        sp.dynamic_benefits_json = _json.dumps(dyn, ensure_ascii=False) if dyn else None
        s.commit()
        dbg.update({"matched": True, "sp_id": sp.id, "sp_site": sp.site, "committed": True})
        return dbg
    finally:
        s.close()


@bp.post("/sources/resolve-deal-models")
def resolve_deal_models_ep():
    """[2026-06-19 모델매핑] 멀티모델 딜 URL → 묶인 모델 목록 + 우리 모델 자동매칭.

    body: {url, target_model?} — target_model(예: "메이트") 주면 자동매칭 결과 동봉.
    Returns: {ok, is_multi, models:[{item_id,name,url}], matched, ambiguous}
    """
    body = request.get_json(silent=True) or {}
    url = body.get("url")
    target = (body.get("target_model") or "").strip()
    html_in = body.get("html")  # [2026-06-21] 브라우저(한국 IP)가 받은 딜 HTML — 서버 fetch 불안정 회피
    if not isinstance(url, str) or not url.strip():
        return jsonify(ok=False, error="url 필요"), 400
    from lemouton.sourcing.crawlers import build_crawlers
    from lemouton.sourcing.crawlers.ssg import resolve_deal_models, match_deal_model
    crawler = build_crawlers().get("ssg")
    if crawler is None or not hasattr(crawler, "_fetch_html"):
        return jsonify(ok=False, error="ssg 크롤러 없음"), 400
    # 딜 HTML — 브라우저가 보낸 게 있으면 그걸 우선(서버 도쿄 IP fetch 가 간헐적으로 단일상품
    #   HTML 을 반환해 '모델 선택 불필요' 오판하던 문제 회피). 없으면 서버 fetch.
    url_is_deal = 'dealitemview' in url.lower()
    if isinstance(html_in, str) and len(html_in) > 1000:
        html = html_in
    else:
        try:
            html = crawler._fetch_html(url)
        except Exception as e:
            return jsonify(ok=False, error=f"딜 페이지 로드 실패: {str(e)[:120]}"), 200
    # 단일상품(딜 URL 아님) + uitemObj 존재 → 모델 선택 불필요.
    #   ★ 딜(dealItemView) URL 이면 uitemObj 유무와 무관하게 항상 모델 링크를 해석한다
    #   (딜 페이지에 대표상품 uitemObj 가 끼어 있어도 단일상품으로 오판하지 않게).
    if (not url_is_deal) and "uitemObjArr.push" in html:
        return jsonify(ok=True, is_multi=False, models=[], matched=None, ambiguous=False)
    try:
        models = resolve_deal_models(url, html, fetch_html=crawler._fetch_html,
                                     parse_html=crawler.parse_html)
    except Exception as e:
        return jsonify(ok=False, error=f"딜 모델 해석 실패: {str(e)[:120]}"), 200
    if not models:
        # 묶인 모델 링크를 못 찾음 = 단일상품으로 취급(매핑 불필요)
        return jsonify(ok=True, is_multi=False, models=[], matched=None, ambiguous=False)
    matched, ambiguous = match_deal_model(models, target) if target else (None, False)
    return jsonify(ok=True, is_multi=True, models=models, matched=matched, ambiguous=ambiguous)
