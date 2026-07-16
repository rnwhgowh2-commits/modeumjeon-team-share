# -*- coding: utf-8 -*-
"""드라이런 검증 리포트 요약 헬퍼 — 어댑터·DB 없이 순수 집계만 테스트."""
from scripts.verify_pipeline_dryrun import summarize_uploads


def test_groups_by_market_and_flags_anomalies():
    uploads = [
        {"market": "smartstore", "canonical_sku": "A", "new_price": 12000, "new_stock": 3},
        {"market": "smartstore", "canonical_sku": "B", "new_price": 0,     "new_stock": 5},   # 0원 = 이상
        {"market": "coupang",    "canonical_sku": "C", "new_price": 9000,  "new_stock": 0},    # 재고0 = 주의
        {"market": "lotteon",    "canonical_sku": "D", "new_price": 5000,  "new_stock": 2},
    ]
    rep = summarize_uploads(uploads)
    assert rep["by_market"]["smartstore"]["count"] == 2
    assert rep["by_market"]["coupang"]["count"] == 1
    assert rep["by_market"]["lotteon"]["count"] == 1
    assert {"market": "smartstore", "canonical_sku": "B"} in rep["anomalies"]["zero_price"]
    assert {"market": "coupang", "canonical_sku": "C"} in rep["anomalies"]["zero_stock"]


def test_empty_uploads():
    rep = summarize_uploads([])
    assert rep["total"] == 0
    assert rep["by_market"] == {}
    assert rep["anomalies"] == {"zero_price": [], "zero_stock": []}
