# -*- coding: utf-8 -*-
"""브랜드 사전 — 조회·추가/삭제·자동추천 (설정 탭 '브랜드 사전' + '미확정 정리').

원본 마진계산기 `app.py::/api/brand_dict*` 3라우트를 모음전으로 이식.
- 프런트(margin_embed)는 원본 경로 `/api/brand_dict`·`/api/brand_dict/suggest` 를 그대로 호출
  (씨앗으로 리매핑하지 않음) → 여기서 같은 경로로 서빙한다.
- 저장방식: 원본과 동일하게 파일 기반(`lemouton/margin/brand_dict.py` 의 save_brand_dict).
  extract_brand(=matcher) 가 get_map 캐시를 쓰므로, 저장 즉시 재분석 없이 반영된다.
- 무상태: 원본은 store['buy_df'] 에서 상품명을 읽지만 모음전 analyze 는 무상태이므로
  업로드 시 스테이징된 매입 엑셀(margin.pending_store)의 '마켓상품명' 을 사용한다.
"""
from flask import Blueprint, jsonify, request

from lemouton.margin import brand_dict as _bd

bp = Blueprint("api_brand_dict", __name__, url_prefix="/api")


@bp.get("/brand_dict")
def api_brand_dict_get():
    """브랜드 사전(키워드→정규화 브랜드) 조회."""
    return jsonify({"brands": _bd.get_map()})


@bp.get("/brand_dict/suggest")
def api_brand_dict_suggest():
    """미확정 상품명에서 브랜드 후보를 추출·순위화(사전 일괄추가용).

    모음전은 무상태 → 마지막 업로드된 매입 엑셀(pending_store)의 '마켓상품명' 을 사용.
    ★스테이징은 DB 단일 행이다 — 워커가 여럿이라 프로세스 전역 dict 는 못 쓴다.
    업로드 전이면 빈 결과(추측 금지).
    """
    from webapp.routes import api_margin
    from lemouton.margin.brand_suggest import suggest_from_names
    from lemouton.margin.matcher import extract_brand

    from lemouton.margin import pending_store
    from lemouton.margin.buy_parser import parse_buy

    empty = {"suggestions": [], "unresolvable": 0,
             "total_unclassified": 0, "unresolved_products": []}
    _sess = api_margin.SessionLocal()
    try:
        staged = pending_store.get(_sess)
    finally:
        _sess.close()
    if not staged or not staged.get("buy_bytes"):
        return jsonify(empty)
    try:
        df = parse_buy(staged["buy_bytes"], staged.get("buy_filename") or "buy.xlsx")
    except Exception:                                  # noqa: BLE001 — 제안은 부가 기능
        return jsonify(empty)
    if df is None or "마켓상품명" not in getattr(df, "columns", []):
        return jsonify(empty)
    names = df["마켓상품명"].dropna().astype(str).tolist()
    return jsonify(suggest_from_names(names, extract_brand))


@bp.post("/brand_dict")
def api_brand_dict_post():
    """브랜드 사전에 키워드 추가/삭제. 저장 즉시 캐시 갱신 → extract_brand 재시작 없이 반영.

    body = {"items": [{"keyword","brand"}, ...]}  (일괄추가)
        or {"keyword","brand"[,"delete":true]}    (단건)
    """
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "invalid body"}), 400

    items = body.get("items")
    if isinstance(items, list):
        mapping = dict(_bd.get_map())
        added = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            kw = str(it.get("keyword", "")).strip()
            br = str(it.get("brand", "")).strip()
            if kw and br:
                mapping[kw] = br
                added += 1
        _bd.save_brand_dict(mapping)
        return jsonify({"ok": True, "added": added, "brands": mapping})

    keyword = str(body.get("keyword", "")).strip()
    if not keyword:
        return jsonify({"error": "keyword required"}), 400
    mapping = dict(_bd.get_map())
    if body.get("delete"):
        mapping.pop(keyword, None)
    else:
        brand = str(body.get("brand", "")).strip()
        if not brand:
            return jsonify({"error": "brand required"}), 400
        mapping[keyword] = brand
    _bd.save_brand_dict(mapping)
    return jsonify({"ok": True, "brands": mapping})
