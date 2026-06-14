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
        # ss_lemouton 만 sku_stock 을 받아 옵션별 재고 교정. 타 파서는 (html,url) 시그니처.
        if source_key == "ss_lemouton" and sku_stock:
            res = crawler.parse_html(html, url, sku_stock=sku_stock)
        else:
            res = crawler.parse_html(html, url)
    except Exception as e:
        return jsonify(ok=False, error="parse_failed", message=str(e)[:200]), 200
    return jsonify(ok=True, **asdict(res))
