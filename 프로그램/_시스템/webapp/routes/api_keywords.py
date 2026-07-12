# -*- coding: utf-8 -*-
r"""카드별 분류 키워드 API — `/api/keywords` (GET/POST).

마진 계산기 페이지(/orders/margin-embed 의 ⚙️설정 탭)가 이 리터럴 경로를 호출한다.
`/api/margin` 프리픽스가 아니라 최상위 `/api/keywords` 여야 한다 — 이식된 원본 페이지
(_getCardKeywords / _saveKeywordEditor) 가 그 경로를 하드코딩했기 때문.

원본 계약: C:\dev\대량등록 마진계산기\app.py 1283–1310 그대로.
저장소만 단일 사용자 card_keywords.json → 팀 공유 DB(CardKeywordConfig) 로 승격.

■ 소비자 형태(검증됨): margin_embed.html 의 _getCardKeywords() 는
  window.analysisData.summary._card_keywords 를 읽고, 이는 POST 응답의
  resp.data.cards (cards dict) 로 채워진다. 즉 프론트는 응답에서 `.cards` 를
  추출한다. 따라서 GET/POST 응답 모두 top-level `cards` 를 포함한 전체 설정을
  원본과 동일하게 돌려준다(원본 계약과 100% 일치).
"""
from flask import Blueprint, jsonify, request

from shared.db import SessionLocal
from lemouton.margin import keyword_store

bp = Blueprint("api_keywords", __name__, url_prefix="/api")


@bp.route("/keywords", methods=["GET"])
def api_keywords_get():
    """카드별 키워드 설정 조회 — 전체 설정 JSON 그대로."""
    s = SessionLocal()
    try:
        return jsonify(keyword_store.get_config(s))
    finally:
        s.close()


@bp.route("/keywords", methods=["POST"])
def api_keywords_post():
    """카드별 키워드 설정 저장 (cards dict 전체 또는 한 카드만)."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "invalid body"}), 400
    s = SessionLocal()
    try:
        current = keyword_store.get_config(s)
        if "cards" in body and isinstance(body["cards"], dict):
            # 전체 cards 교체
            current["cards"] = body["cards"]
        elif "card" in body and "data" in body:
            # 한 카드만 교체: {card: 'confirmed_blackspot', data: {memo:[...], mg:[...]}}
            card_name = body["card"]
            if not isinstance(card_name, str) or not card_name:
                return jsonify({"error": "invalid card name"}), 400
            if "cards" not in current or not isinstance(current.get("cards"), dict):
                current["cards"] = {}
            current["cards"][card_name] = body["data"]
        else:
            return jsonify({"error": "expected {cards: {...}} or {card, data}"}), 400
        keyword_store.save_config(s, current)
        return jsonify({"status": "ok", "data": current})
    finally:
        s.close()
