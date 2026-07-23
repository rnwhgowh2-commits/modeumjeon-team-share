# -*- coding: utf-8 -*-
"""④ 상품관리 — 등록한 상품 목록 + 상품별 업데이트 ON/OFF.

설계서: 2026-07-17-신규상품등록-가공템플릿-design.md §3-2 「4) 상품관리 탭」
  더망고에서 가져올 것: 상품별 「상품/가격/재고 업데이트 ON·OFF」 토글,
  원문 상품명 병기, 마켓전송가격, 옵션 목록.

★ 토글 3개(update_product/price/stock)는 ProductDraft 에 **이미 있다** —
  모델 주석에 "Phase 2 상품관리 탭. 컬럼은 지금 만든다" 라고 적혀 있다. 그걸 쓴다.
"""
from flask import jsonify, request

from shared.db import SessionLocal

from . import bp


@bp.get('/api/products')
def list_products():
    """상품 목록 + 토글 + 마켓 등록현황."""
    from lemouton.registration.models import ProductDraft, ProductDraftMarket

    q = (request.args.get('q') or '').strip().lower()
    only = (request.args.get('only') or '').strip()   # '' | 'off' | 'failed'

    s = SessionLocal()
    try:
        rows = (s.query(ProductDraft)
                .filter(ProductDraft.deleted_at.is_(None))
                .order_by(ProductDraft.id.desc()).limit(300).all())
        out = []
        for d in rows:
            mks = s.query(ProductDraftMarket).filter_by(draft_id=d.id).all()
            markets = [{"market": m.market, "account_key": m.account_key,
                        "status": m.status,
                        "market_product_id": m.market_product_id,
                        "error": m.error_message} for m in mks]
            item = {
                "id": d.id, "name": d.name, "brand": d.brand,
                "sale_price": d.sale_price,
                "surface_price": d.surface_price,
                "status": d.status,
                "update_product": bool(d.update_product),
                "update_price": bool(d.update_price),
                "update_stock": bool(d.update_stock),
                "markets": markets,
                # ★ [2026-07-23 리뷰 C-2] 'uncertain'(확인 필요)을 실패에 섞지 않는다 —
                #   장부는 「모른다」인데 화면이 「실패」라고 하면 두 답이 갈린다(모순 금지).
                #   확인 필요는 별도 칸으로 세어, 사장님이 그 상품부터 보게 한다.
                "failed": sum(1 for m in markets if m["status"] == "failed"),
                "uncertain": sum(1 for m in markets if m["status"] == "uncertain"),
                # [3차리뷰 사소①] 상품번호가 있어도 status 가 'ok' 가 아니면 등록됨이
                #   아니다 — PARTIAL(옵션 부착 실패)도 번호는 있다. 번호만 세면 확인이
                #   필요한 건이 「등록 완료」로 뭉개진다.
                "registered": sum(1 for m in markets
                                  if m["market_product_id"] and m["status"] == "ok"),
                # 가격 입력을 받아둔 상품인지 (최종매입가를 계산할 근거가 있나)
                "has_pricing": d.pricing_source_id is not None,
            }
            out.append(item)

        if only == 'off':
            out = [x for x in out if not (x["update_product"] and x["update_price"]
                                          and x["update_stock"])]
        elif only == 'failed':
            out = [x for x in out if x["failed"] > 0]
        elif only == 'uncertain':
            out = [x for x in out if x["uncertain"] > 0]
        if q:
            out = [x for x in out
                   if q in (x["name"] or '').lower() or q in (x["brand"] or '').lower()]

        return jsonify({
            "rows": out,
            "counts": {
                "total": len(out),
                "off": sum(1 for x in out if not (x["update_product"]
                                                  and x["update_price"] and x["update_stock"])),
                "failed": sum(1 for x in out if x["failed"] > 0),
                "uncertain": sum(1 for x in out if x["uncertain"] > 0),
            },
            # ★ 최종매입가는 여기서 안 준다 — 저장값이 아니라 매번 계산하는 값이고,
            #   300행마다 엔진을 돌리면 화면이 느려진다. 상세에서 계산해 보여준다.
            "note": ("최종매입가·마진은 소싱처 혜택에서 매번 계산합니다 — "
                     "목록에는 표면가와 판매가만 싣고, 상세에서 계산해 보여드립니다."),
        })
    except Exception as e:      # noqa: BLE001
        return jsonify({"error": "products_failed", "detail": str(e)[:300]}), 500
    finally:
        s.close()


@bp.post('/api/products/<int:draft_id>/toggle')
def toggle_product_update(draft_id: int):
    """상품별 업데이트 ON/OFF. 원문 사이트 변동을 상품 단위로 끊을 수 있게 한다."""
    from lemouton.registration.models import ProductDraft

    body = request.get_json(silent=True) or {}
    field = (body.get('field') or '').strip()
    if field not in ('update_product', 'update_price', 'update_stock'):
        return jsonify({"ok": False, "error": f"모르는 항목입니다: {field!r}"}), 400
    if not isinstance(body.get('value'), bool):
        return jsonify({"ok": False, "error": "value 는 true/false 여야 합니다."}), 400

    s = SessionLocal()
    try:
        d = s.get(ProductDraft, draft_id)
        if not d or d.deleted_at:
            return jsonify({"ok": False, "error": "없는 상품입니다."}), 404
        setattr(d, field, body['value'])
        s.commit()
        return jsonify({"ok": True, "id": d.id, "field": field, "value": body['value']})
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    finally:
        s.close()
