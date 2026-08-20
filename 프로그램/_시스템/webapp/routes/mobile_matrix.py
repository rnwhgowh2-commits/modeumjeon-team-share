# -*- coding: utf-8 -*-
"""폰 전용 매트릭스 화면 — `/mobile/matrix` (D-1 · 사장님 확정 「검색 → 옵션 카드」).

mobile_orders.py 처럼 따로 둔 이유: 껍데기(mobile_shell)·주문(mobile_orders)과
관심사가 다르다. 옵션×소싱처 가격·재고는 매트릭스 세계의 일이라, 여기 붙이면
그쪽을 고칠 때 다른 폰 화면 시험이 같이 흔들린다.

데이터는 새 집계를 만들지 않는다 — PC 매트릭스 화면(/matrix)이 쓰는 **같은 함수**
(`webapp.routes.matrix._rows_for` — 표면가·최종매입가·재고의 단일 진실 원천)를
그대로 불러 얇게 실어 나른다. PC 격자(JSON `/api/bundles/<code>/option-matrix`)는
한 모음전을 통째로 내리는 큰 판이라 폰 검색엔 안 맞고, `_rows_for` 가 옵션 단위라
정확히 이 화면 크기다.

[중요] 재고·가격 1원칙(프로젝트 CLAUDE.md) 보존:
  · 모르면 「확인불가」 — 있음으로 둔갑 금지. 판정은 **서버(여기) 한 곳**에서 하고
    폰 JS 는 그대로 그린다(같은 판정 두 곳 금지).
  · 가격은 최종매입가(final) 우선, 없으면 표면가(surface) — 단 **종류를 밝힌다**
    (price_kind). 둘 다 없으면 None — 폰이 '-' 로 그린다(폴백 가격 발명 금지).
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import or_

from shared.db import SessionLocal

_log = logging.getLogger(__name__)

bp = Blueprint("mobile_matrix", __name__, url_prefix="/mobile")

#: 카드 최대 개수 — 폰 한 화면에서 훑을 수 있는 만큼만. 넘치면 more 로 밝힌다.
_MAX_CARDS = 20

# 재고 센티넬 — 999 이상 = 「재고 있음」(개수 아님). 원천은 guide_url_result 하나뿐.
#   여기 숫자를 또 적으면 센티넬이 바뀔 때 한쪽만 고쳐져 폰이 「재고 999」를 그린다.
from lemouton.sourcing.guide_url_result import _STOCK_IN_STOCK_SENTINEL


def _stock_badge(stock) -> dict:
    """재고 값 → 폰 배지 {kind, label}. **서버 한 곳의 판정**이다.

    의미는 정본 `guide_url_result._stock_label` 과 같은 부류
    (시험 test_재고_판정_규칙이_정본과_같은_부류다 가 전 구간 대조):
      None·음수 → 확인불가(unknown)  /  0 → 품절(oos)
      센티넬 이상 → 재고 있음(ok)     /  그 외 → 재고 N(ok)
    """
    try:
        n = int(stock)
    except (TypeError, ValueError):
        return {"kind": "unknown", "label": "확인불가"}
    if n < 0:
        return {"kind": "unknown", "label": "확인불가"}
    if n == 0:
        return {"kind": "oos", "label": "품절"}
    if n >= _STOCK_IN_STOCK_SENTINEL:
        return {"kind": "ok", "label": "재고 있음"}
    return {"kind": "ok", "label": f"재고 {n}"}


def _source_row(x: dict) -> dict:
    """`_rows_for` 의 소싱처 한 칸 → 폰 카드 한 줄.

    가격 규칙 = PC 매트릭스 정보창의 「최저」 판정(final || surface —
    api_pricing._pick_cost_source 와 같은 규칙)과 동일하되, 어느 값인지 밝힌다.
    """
    final, surface = x.get("final"), x.get("surface")
    if final:
        price, kind = final, "final"
    elif surface:
        price, kind = surface, "surface"
    else:
        price, kind = None, None            # 지어내지 않는다 — 폰이 '-' 로 그린다
    return {
        "label": x.get("label"), "no": x.get("no"), "url": x.get("url"),
        "surface": surface, "final": final,
        "price": price, "price_kind": kind,
        "badge": _stock_badge(x.get("stock")),
    }


@bp.route("/matrix")
def matrix():
    """매트릭스 폰 화면 — 검색 먼저(fD1). 데이터는 아래 검색 API 가 준다."""
    return render_template("mobile/matrix.html")


@bp.get("/matrix/api/search")
def search_api():
    """옵션·모음전 검색 → 옵션 카드 목록.

    query: ?q=니트 블랙 M   (공백 = 낱말 AND — 전부 맞는 옵션만)
    응답: {ok, q, more, items:[{sku, display_no, title, color, size, article_no,
           sources:[{label, no, url, surface, final, price, price_kind, badge}]}]}
    more = 카드 상한(_MAX_CARDS)을 넘는 결과가 더 있다 — 정확한 총수는 안 센다
           (count 는 전수 스캔이라, 폰은 「더 좁혀라」 안내면 충분하다).

    검색 대상 = PC 매트릭스 목록(/matrix ?q=)이 보는 이름·번호(모음전 이름·모델번호)
    + 옵션 낱말(SKU·옵션번호·색·사이즈). PC 는 모음전 단위라 이름까지만 보는데,
    폰 시안(fD1)의 예시가 「니트 블랙 M」이라 옵션 낱말까지 잇는다.
    """
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"ok": False, "error": "두 글자 이상 적어 주세요."}), 400
    tokens = q.split()[:6]

    from lemouton.sourcing.models import Model, Option
    from webapp.routes.matrix import _rows_for
    s = SessionLocal()
    try:
        query = (s.query(Option, Model)
                 .join(Model, Option.model_code == Model.model_code))
        for t in tokens:
            like = f"%{t}%"
            query = query.filter(or_(
                Model.model_name_display.ilike(like),
                Model.model_name_raw.ilike(like),
                Model.model_code.ilike(like),
                Model.display_no.ilike(like),
                Option.canonical_sku.ilike(like),
                Option.display_no.ilike(like),
                Option.color_code.ilike(like),
                Option.color_display.ilike(like),
                Option.size_code.ilike(like),
                Option.size_display.ilike(like),
            ))
        # 스캔은 **한 번만** — count() 를 따로 돌리면 요청마다 전수 스캔이 2번 된다
        #   (옵션 10만+ · 인덱스 없는 ilike · 타이핑마다 호출되는 검색이라 제일 비싼
        #    절반이 「정확한 total」 하나를 위해 존재했다). 한 개 더 가져와 「넘침」만
        #   판정한다 — 정확한 총수 대신 **정직한 상한 표기**(20개 넘음)를 쓴다.
        pairs = (query.order_by(Option.model_code, Option.sort_order,
                                Option.color_code, Option.size_code)
                 .limit(_MAX_CARDS + 1).all())
        more = len(pairs) > _MAX_CARDS
        pairs = pairs[:_MAX_CARDS]

        skus = [o.canonical_sku for o, _m in pairs]
        rows, _colors, _sizes = _rows_for(s, skus)
        by_sku = {r["sku"]: r for r in rows}

        items = []
        for o, m in pairs:
            r = by_sku.get(o.canonical_sku) or {}
            items.append({
                "sku": o.canonical_sku,
                "display_no": o.display_no,
                "title": m.model_name_display or m.model_name_raw or m.model_code,
                "color": o.color_display or o.color_code,
                "size": o.size_display or o.size_code,
                "article_no": r.get("article_no") or "",
                "sources": [_source_row(x) for x in r.get("sources", [])],
            })
    except Exception as e:      # noqa: BLE001
        _log.exception("[mobile-matrix] 검색 실패 q=%s", q)
        return jsonify({"ok": False, "error": f"불러오지 못했어요: {e}"}), 500
    finally:
        s.close()
    return jsonify({"ok": True, "q": q, "more": more, "items": items})
