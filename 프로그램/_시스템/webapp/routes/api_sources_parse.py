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
    return jsonify(ok=True, **asdict(res))


@bp.post("/sources/resolve-deal-models")
def resolve_deal_models_ep():
    """[2026-06-19 모델매핑] 멀티모델 딜 URL → 묶인 모델 목록 + 우리 모델 자동매칭.

    body: {url, target_model?} — target_model(예: "메이트") 주면 자동매칭 결과 동봉.
    Returns: {ok, is_multi, models:[{item_id,name,url}], matched, ambiguous}
    """
    body = request.get_json(silent=True) or {}
    url = body.get("url")
    target = (body.get("target_model") or "").strip()
    if not isinstance(url, str) or not url.strip():
        return jsonify(ok=False, error="url 필요"), 400
    from lemouton.sourcing.crawlers import build_crawlers
    from lemouton.sourcing.crawlers.ssg import resolve_deal_models, match_deal_model
    crawler = build_crawlers().get("ssg")
    if crawler is None or not hasattr(crawler, "_fetch_html"):
        return jsonify(ok=False, error="ssg 크롤러 없음"), 400
    try:
        html = crawler._fetch_html(url)
    except Exception as e:
        return jsonify(ok=False, error=f"딜 페이지 로드 실패: {str(e)[:120]}"), 200
    # 딜(멀티모델)이 아니면 단일상품 — 매핑 불필요
    if "uitemObjArr.push" in html:
        return jsonify(ok=True, is_multi=False, models=[], matched=None, ambiguous=False)
    try:
        models = resolve_deal_models(url, html, fetch_html=crawler._fetch_html,
                                     parse_html=crawler.parse_html)
    except Exception as e:
        return jsonify(ok=False, error=f"딜 모델 해석 실패: {str(e)[:120]}"), 200
    matched, ambiguous = match_deal_model(models, target) if target else (None, False)
    return jsonify(ok=True, is_multi=True, models=models, matched=matched, ambiguous=ambiguous)
