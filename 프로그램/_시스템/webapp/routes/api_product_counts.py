# -*- coding: utf-8 -*-
"""계층 분석 등록수 API — /api/product-counts (원본 app.py:1335~1359 이식).

프런트(margin_embed.html)의 계층 분석(마켓›계정›브랜드›소싱처)에서 각 경로별 등록수를
입력하면 매출효율(매출÷등록수)·마진효율(순마진÷등록수)을 계산한다. 그 등록수를 팀 공유
DB(ProductCountConfig)에 저장한다.

원본은 단일 사용자 product_counts.json 이었으나 팀 공유 앱에서는 DB 한 행으로 승격
([[keyword_store]]·[[api_brand_dict]] 와 동일). 저장소만 다르고 API 계약(GET {counts},
POST {key,count,delete?})은 원본과 동일하다.
"""
from flask import Blueprint, jsonify, request

from shared.db import SessionLocal
from lemouton.margin import product_count_store

bp = Blueprint("api_product_counts", __name__, url_prefix="/api")


@bp.get("/product-counts")
def api_product_counts_get():
    """계층 경로별 등록수 전체 조회 (원본 계약: {"counts": {...}})."""
    session = SessionLocal()
    try:
        return jsonify({"counts": product_count_store.get_counts(session)})
    finally:
        session.close()


@bp.post("/product-counts")
def api_product_counts_post():
    """계층 경로별 등록수 저장/삭제 (원본 계약: body {key, count, delete?})."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "invalid body"}), 400
    key = str(body.get("key", "")).strip()
    if not key:
        return jsonify({"error": "key required"}), 400
    if not body.get("delete"):
        try:
            int(body.get("count", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "count must be integer"}), 400
    session = SessionLocal()
    try:
        counts = product_count_store.set_count(
            session, key,
            count=int(body.get("count", 0)),
            delete=bool(body.get("delete")),
        )
        return jsonify({"ok": True, "counts": counts})
    finally:
        session.close()
