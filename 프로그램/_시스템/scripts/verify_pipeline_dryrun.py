# -*- coding: utf-8 -*-
"""재크롤 없는 드라이런 전수 검증 리포트.

목적:
  사용자가 "드라이런 숫자 = 실제 판매처 화면" 대조를 할 수 있도록, **이미 저장된
  크롤 데이터**(SourceOption)로 각 마켓에 전송될 값(new price / new stock)을
  **실제 어댑터 호출 없이** 산출·리포트한다.

★ 안전 (반드시 지킬 것):
  · full_cycle() 의 Phase A(fetch_unique_sources + run_pipeline(crawlers=...)) 는
    실제 크롤(네트워크·DB 쓰기)을 트리거하므로 **절대 호출하지 않는다.**
  · 이 스크립트의 Phase A 대체물(build_a_output_from_stored)은 네트워크를 타지 않고
    이미 DB 에 저장된 SourceOption(current_price / current_stock)만 읽는다
    (lemouton.sources.service.get_source_data_for_sku — 가격결정 단계가 쓰는 조회 헬퍼).
  · Phase B(pricing)·Phase C(formatter)는 순수 계산·DB 읽기뿐이라 크롤을 유발하지 않는다.
  · 실제 마켓 API 어댑터는 호출하지 않는다(집계만).
"""
from __future__ import annotations

from collections import defaultdict


# ─────────────────────────────────────────────────────────────────────────────
# 순수 요약 함수 — 어댑터·DB 없이 결정적. TDD 대상.
# ─────────────────────────────────────────────────────────────────────────────
def summarize_uploads(uploads: list[dict]) -> dict:
    by_market: dict[str, dict] = {}
    zero_price: list[dict] = []
    zero_stock: list[dict] = []
    for u in uploads:
        m = u["market"]
        slot = by_market.setdefault(m, {"count": 0, "items": []})
        slot["count"] += 1
        slot["items"].append(u)
        if not u.get("new_price"):
            zero_price.append({"market": m, "canonical_sku": u["canonical_sku"]})
        if not u.get("new_stock"):
            zero_stock.append({"market": m, "canonical_sku": u["canonical_sku"]})
    return {
        "total": len(uploads),
        "by_market": by_market,
        "anomalies": {"zero_price": zero_price, "zero_stock": zero_stock},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase A 대체 — 재크롤 없이 저장된 SourceOption 으로 a_output(옵션 aggregate) 생성.
# ─────────────────────────────────────────────────────────────────────────────
def build_a_output_from_stored(session) -> dict[str, dict]:
    """이미 저장된 SourceOption 으로 run_pipeline 과 같은 모양의 a_output 을 만든다.

    run_pipeline(Phase A)은 crawler.fetch(url) 로 **실크롤**해 aggregate 를 만든다.
    여기서는 크롤 없이, OptionSourceLink 로 매핑된 canonical_sku 각각에 대해
    get_source_data_for_sku(=저장된 SourceOption.current_price/stock 읽기)로
    sources 리스트를 채운다.

    반환 모양은 run_pipeline 과 동일:
      { canonical_sku: {"boxhero_stock": int, "boxhero_purchase_price": None,
                        "sources": [{"name": site, "stock": int, "price": int}, ...]} }

    · boxhero_stock 은 박스히어로 records 없이 산출할 수 없으므로 aggregate 기본값 0
      (run_pipeline 도 records 없으면 0). 재고 최종값은 formatter 가 sources 로 계산.
    · price/stock 이 None(확인불가)이면 run_pipeline 의 .get(..., 0) 기본값 의미에
      맞춰 0 으로 수렴시킨다 — 리포트에서 0원/재고0 이상치로 표면화된다.
    """
    from lemouton.sources.models import OptionSourceLink
    from lemouton.sources.service import get_source_data_for_sku

    skus = [row[0] for row in
            session.query(OptionSourceLink.canonical_sku).distinct().all()]

    a_output: dict[str, dict] = {}
    for sku in skus:
        rows = get_source_data_for_sku(session, sku)
        sources = [{
            "name": r["site"],
            "stock": r["stock"] if r["stock"] is not None else 0,
            "price": r["price"] if r["price"] is not None else 0,
        } for r in rows]
        a_output[sku] = {
            "boxhero_stock": 0,
            "boxhero_purchase_price": None,
            "sources": sources,
        }
    return a_output


def build_c_output(session) -> dict:
    """저장된 크롤 데이터 → B(pricing) → C(formatter) → 마켓별 페이로드 dict.

    scheduler/jobs.py full_cycle() 의 Phase B·C 를 그대로 따르되, Phase A 만
    재크롤 없는 build_a_output_from_stored 로 대체한다. 각 단계는 실크롤/실전송을
    유발하지 않는다.
    """
    # Phase A(대체): 재크롤 없이 저장 데이터로 aggregate
    a_output = build_a_output_from_stored(session)

    # Phase B: pricing — jobs.py Phase B 미러(입력 형식·settings 동일).
    #   a_output 이 비면 pricing 엔진을 아예 부르지 않는다(graceful skip, jobs.py 동일).
    b_output: dict = {"decisions": {}, "alerts": []}
    if a_output:
        try:
            from lemouton.pricing.engine import run_pricing_engine
            # decide_ss/coupang 는 각 옵션 dict 안 canonical_sku 를 기대 → enrich.
            a_enriched = {sku: {**(opt or {}), "canonical_sku": sku}
                          for sku, opt in a_output.items()}
            settings = {
                "ss_fee_rate": 0.06,
                "coupang_fee_rate": 0.1155,
                "delivery_fee": 3000,
                "rounding_unit": 100,
            }
            b_output = run_pricing_engine(a_enriched, settings) or b_output
        except Exception as e:   # noqa: BLE001 — jobs.py Phase B 도 예외를 삼키고 진행
            print(f"[warn] Phase B(pricing) 건너뜀: {e}")

    # Phase C: formatter — a_output + b_output → 마켓별 페이로드.
    from lemouton.formatter.pipeline import run_formatter
    c_output = run_formatter(session, a_output, b_output) or {}
    return c_output


def _print_report(c_output: dict, uploads: list[dict]) -> None:
    # Windows 콘솔(cp949)에서도 한글·기호가 깨지지 않게 stdout 을 UTF-8 로.
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # py3.7+
    except Exception:   # noqa: BLE001
        pass

    rep = summarize_uploads(uploads)
    zero_price = rep["anomalies"]["zero_price"]
    zero_stock = rep["anomalies"]["zero_stock"]
    alerts = c_output.get("alerts", []) or []

    print("=" * 60)
    print("드라이런 전수 검증 리포트 (재크롤·실전송 없음)")
    print("=" * 60)
    print(f"총 전송 후보: {rep['total']} 건")
    print("-" * 60)
    print("마켓별 건수:")
    if rep["by_market"]:
        for market in sorted(rep["by_market"]):
            print(f"  · {market:<12} {rep['by_market'][market]['count']} 건")
    else:
        print("  (없음 — 매핑된 전송 대상 옵션이 없음)")
    print("-" * 60)
    print(f"0원 후보: {len(zero_price)} 건 (앞 20건)")
    for row in zero_price[:20]:
        print(f"  · {row['market']:<12} {row['canonical_sku']}")
    print(f"재고0 후보: {len(zero_stock)} 건 (앞 20건)")
    for row in zero_stock[:20]:
        print(f"  · {row['market']:<12} {row['canonical_sku']}")
    print("-" * 60)
    print(f"formatter alerts: {len(alerts)} 건 (앞 20건)")
    for a in alerts[:20]:
        _t = a.get("type", "?")
        _m = a.get("message", "")
        _id = a.get("canonical_sku") or a.get("model_code") or ""
        print(f"  · [{_t}] {_id} {_m}")
    print("=" * 60)


def main() -> None:
    from shared.db import SessionLocal
    from lemouton.uploader.runtime import build_sku_by_option
    from lemouton.uploader.orchestrator import _extract_uploads

    session = SessionLocal()
    try:
        c_output = build_c_output(session)
        sku_by_option = build_sku_by_option(session)
        uploads = _extract_uploads(c_output, sku_by_option)
        _print_report(c_output, uploads)
    finally:
        session.close()


if __name__ == "__main__":
    main()
