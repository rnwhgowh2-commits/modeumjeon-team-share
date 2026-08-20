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
    collect_failed = snap_failed = 0
    try:
        r = collect_all_linked_sets(s)
        s.commit()
        collected = r.get("sets", 0)
        collect_failed = r.get("failed", 0)
        try:
            from webapp.routes.api_pricing import _option_matrix_data
        except Exception:
            _option_matrix_data = None
        try:
            from webapp.routes.api_benefits import compute_breakdown
        except Exception:
            compute_breakdown = None
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
                            if o.get("sku") not in skus:
                                continue
                            is_pur = o.get("purchase_priority_resolved") == "purchase"
                            # 대표 소싱처(최저 표면가) — 최종매입가 breakdown 기준
                            _srcs = [x for x in (o.get("sources") or [])
                                     if x.get("crawled_price") is not None]
                            _srcs.sort(key=lambda x: x["crawled_price"])
                            _rep = _srcs[0] if _srcs else None
                            _surface = _rep["crawled_price"] if _rep else o.get("src_cost")
                            _cost = None
                            if _rep and not is_pur and compute_breakdown is not None:
                                try:
                                    _bd = compute_breakdown(
                                        s, sku=o["sku"], source_id=_rep["source_id"],
                                        sale_price=_rep["crawled_price"],
                                        source_product_id=_rep.get("source_product_id"))
                                    _cost = (_bd or {}).get("final_price")
                                except Exception:
                                    _cost = None   # breakdown 실패는 미기록(폴백 금지)
                            vmap[o["sku"]] = {
                                "stock": o.get("purchase_stock") if is_pur else o.get("src_stock"),
                                "surface": _surface,            # 소싱 표면가(crawled_price)
                                "cost": _cost,                  # 최종매입가(혜택 차감)
                                "ss_price": o.get("ss_price"),  # 판매예정가(스마트스토어)
                                "cp_price": o.get("cp_price"),  # 판매예정가(쿠팡)
                            }
                    snapped += snapshot_source_values(s, set_id=sid, value_map=vmap)
                    s.commit()
                except Exception:
                    # 조용한 실패 금지 — 세트별 스냅샷 실패도 로그+카운트로 표면화
                    s.rollback()
                    snap_failed += 1
                    logger.exception("sets_collect: set_id=%s 스냅샷 실패", sid)
        if collect_failed or snap_failed:
            logger.warning("sets_collect: 수집실패 %d세트 · 스냅샷실패 %d세트",
                           collect_failed, snap_failed)
        logger.info("sets_collect: collected %d, source changes %d", collected, snapped)
        return {"ok": True, "collected": collected, "snapped": snapped,
                "collect_failed": collect_failed, "snap_failed": snap_failed}
    except Exception:
        s.rollback()
        logger.exception("sets collect job failed")
        return {"ok": False, "collected": collected, "snapped": snapped}
    finally:
        s.close()
