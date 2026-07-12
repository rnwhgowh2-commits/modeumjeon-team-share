# -*- coding: utf-8 -*-
"""마진 config 상수 — 원본과 값이 같아야 한다."""
from lemouton.margin import config as C


def test_market_map_roundtrip():
    assert C.MARKET_MAP["스마트스토어"] == "04.스마트스토어"
    assert C.MARKET_REVERSE["04.스마트스토어"] == "스마트스토어"
    assert len(C.MARKET_MAP) == 6


def test_coupang_fee_rate():
    assert C.COUPANG_FEE_RATE == 0.1155


def test_default_price_ranges():
    labels = [lbl for _, _, lbl in C.DEFAULT_PRICE_RANGES]
    assert labels == ["~1만", "1~3만", "3~5만", "5~10만", "10만~"]


def test_settlement_sets_present_for_matcher():
    # matcher.match_for_classifier 가 import 한다 — 무수정 이식 유지
    assert "구매확정" in C.SETTLEMENT_O_EXACT
    assert "반품완료" in C.SETTLEMENT_X_EXACT
    assert "취소철회(구매확정)" in C.SETTLEMENT_X_EXCEPT_TO_O


def test_shopmine_cols():
    assert C.SHOPMINE_COLS["order_no"] == "오픈마켓주문번호"
    assert C.SHOPMINE_COLS["settlement"] == "정산예상금액(배송비포함)"


def test_no_filesystem_constants():
    # 단독앱 경로 상수는 이식하지 않는다
    assert not hasattr(C, "ROOT")
    assert not hasattr(C, "PROFILES_DIR")
    assert not hasattr(C, "DEPLOY_MODE")
