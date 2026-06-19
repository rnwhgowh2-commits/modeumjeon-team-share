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
        # [2026-06-19] SSG 딜페이지(dealItemView) — uitemObj 인라인 JS 가 없어 parse_html 직접 불가
        #   → 라이브(확장→parse) 경로에선 그동안 '옵션 추출 실패'(크롤실패)였다. 확장이 보낸 딜 HTML 로
        #   대표 itemView(딜에 묶인 첫 단품=다색 상품) URL 을 해석해, 서버사이드로 그 단품을 fetch+parse 한다.
        #   대표가 다색 상품이면 전 색상 커버. (기존 fetch() 의 딜 처리 로직과 동일 — parse 경로에도 적용.)
        if source_key == "ssg" and "uitemObjArr.push" not in html and hasattr(crawler, "_fetch_html"):
            from lemouton.sourcing.crawlers.ssg import _resolve_deal_representative_url
            rep_url = _resolve_deal_representative_url(url, html)
            if rep_url:
                rep_html = crawler._fetch_html(rep_url)
                res = crawler.parse_html(rep_html, rep_url)
            else:
                res = crawler.parse_html(html, url)
        elif source_key == "ss_lemouton" and sku_stock:
            # ss_lemouton 만 sku_stock 을 받아 옵션별 재고 교정. 타 파서는 (html,url) 시그니처.
            res = crawler.parse_html(html, url, sku_stock=sku_stock)
        else:
            res = crawler.parse_html(html, url)
    except Exception as e:
        return jsonify(ok=False, error="parse_failed", message=str(e)[:200]), 200
    return jsonify(ok=True, **asdict(res))
