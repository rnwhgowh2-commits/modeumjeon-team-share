"""판매처 추가·업데이트 + 데이터 코드 지도 (판매처판).

소싱처 가이드(sourcing_guide)의 판매처 짝. /add·/map 을 ?bare=1 로 열면
same-origin iframe 팝업용 최소 레이아웃 + X-Frame-Options: SAMEORIGIN.
(전역 기본 X-Frame-Options: DENY 가 same-origin iframe 까지 막으므로 라우트에서 예외.)
"""
from __future__ import annotations

import os

from flask import Blueprint, render_template, request, make_response

bp = Blueprint("marketplace_guide", __name__, url_prefix="/marketplace-guide")


@bp.before_request
def _admin_only():
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


def _markets():
    """MARKET_METADATA 단일 출처 — 신규 추가용(coming_soon) / 연동됨(ready) 분리."""
    from webapp.routes.accounts import MARKET_METADATA
    coming, ready = [], []
    for key, meta in sorted(MARKET_METADATA.items(),
                            key=lambda kv: kv[1].get("sort_order", 999)):
        row = {"key": key, "label": meta["label"], "icon": meta.get("icon", "🔧"),
               "api_type": meta.get("api_type", ""), "status": meta.get("status", "")}
        (ready if meta.get("status") == "ready" else coming).append(row)
    return coming, ready


@bp.route("/add")
def add_page():
    """판매처 추가·업데이트 — 2탭(신규/기존). ?bare=1 → 사이드바 없는 팝업 iframe용."""
    coming, ready = _markets()
    if request.args.get("bare"):
        resp = make_response(render_template(
            "marketplace_guide/add.html", layout="_bare.html", coming=coming, ready=ready))
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        return resp
    return render_template("marketplace_guide/add.html",
                           layout="base.html", coming=coming, ready=ready)


@bp.route("/map")
def data_code_map():
    """데이터 코드 지도(판매처판). ?bare=1 → 팝업 iframe용 최소 레이아웃."""
    if request.args.get("bare"):
        resp = make_response(render_template("marketplace_guide/map.html", layout="_bare.html"))
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        return resp
    return render_template("marketplace_guide/map.html", layout="base.html")
