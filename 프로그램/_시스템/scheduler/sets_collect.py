"""[E] 연동 구성 주기 수집 — 판매처 현재값 + 소싱 변동 스냅샷.

스케줄러(BackgroundScheduler) 잡. 마켓에 쓰지 않음(읽기+로컬). env 가드로 부하 통제.
소싱 변동은 머니-크리티컬 글로벌 크롤 핫패스 대신 세트 단위 스냅샷으로 포착.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def collect_and_snapshot_all() -> dict:
    """연동된 전 구성: 판매처 현재값 수집 + 소싱 변동 스냅샷. 결과 요약 dict."""
    from shared.db import SessionLocal
    from lemouton.sets.collect_service import collect_all_linked_sets
    from lemouton.sets.set_service import list_linked_sets, get_set_detail
    from lemouton.sets.change_service import snapshot_source_values
    s = SessionLocal()
    collected = snapped = 0
    try:
        r = collect_all_linked_sets(s)
        s.commit()
        collected = r.get("sets", 0)
        try:
            from webapp.routes.api_pricing import _option_matrix_data
        except Exception:
            _option_matrix_data = None
        if _option_matrix_data is not None:
            for row in list_linked_sets(s):
                sid = row["set_id"]
                try:
                    detail = get_set_detail(s, sid)
                    if not detail:
                        continue
                    skus = set()
                    for p in detail["products"]:
                        skus.update(p["options"])
                    vmap = {}
                    for mc in {p["model_code"] for p in detail["products"]}:
                        data = _option_matrix_data(mc)
                        if not data.get("ok"):
                            continue
                        for o in data.get("options", []):
                            if o.get("sku") in skus:
                                is_pur = o.get("purchase_priority_resolved") == "purchase"
                                vmap[o["sku"]] = {
                                    "stock": o.get("purchase_stock") if is_pur else o.get("src_stock"),
                                    "price": o.get("src_cost"),
                                }
                    snapped += snapshot_source_values(s, set_id=sid, value_map=vmap)
                    s.commit()
                except Exception:
                    s.rollback()
        logger.info("sets_collect: collected %d, source changes %d", collected, snapped)
        return {"ok": True, "collected": collected, "snapped": snapped}
    except Exception:
        s.rollback()
        logger.exception("sets collect job failed")
        return {"ok": False, "collected": collected, "snapped": snapped}
    finally:
        s.close()
