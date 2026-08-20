# -*- coding: utf-8 -*-
"""sell_source.from_shopmine_excel — 샵마인 엑셀 → SellRow DF."""
import io

import pandas as pd
import pytest

from lemouton.margin import sell_source as SS


def _xlsx(rows, cols):
    buf = io.BytesIO()
    pd.DataFrame(rows, columns=cols).to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


COLS = ["오픈마켓주문번호", "주문상태", "정산예상금액(배송비포함)", "단가", "수량",
        "쇼핑몰", "삼품명", "옵션", "송장입력", "실결제금액", "마켓수수료",
        "수수료율", "샵마인주문상태", "수취고객명", "주문일"]


def test_columns_are_sellrow_schema():
    data = _xlsx([["1001", "배송완료", 70000, 80000, 1, "06.쿠팡", "코트 12345",
                   "블랙/95", "1234", 80000, 9240, "11.55%", "정산예정", "홍길동",
                   "2026-07-04"]], COLS)
    df = SS.from_shopmine_excel(data, "샵마인.xlsx")
    for c in SS.SELL_COLUMNS:
        assert c in df.columns, c


def test_typo_column_삼품명_is_fixed():
    data = _xlsx([["1001", "배송완료", 70000, 80000, 1, "06.쿠팡", "코트 12345",
                   "블랙/95", "1234", 80000, 9240, "11.55%", "정산예정", "홍길동",
                   "2026-07-04"]], COLS)
    df = SS.from_shopmine_excel(data, "샵마인.xlsx")
    assert df.loc[0, "상품명"] == "코트 12345"
    assert "삼품명" not in df.columns


def test_settlement_column_renamed():
    data = _xlsx([["1001", "배송완료", 70000, 80000, 1, "06.쿠팡", "코트 12345",
                   "블랙/95", "1234", 80000, 9240, "11.55%", "정산예정", "홍길동",
                   "2026-07-04"]], COLS)
    df = SS.from_shopmine_excel(data, "샵마인.xlsx")
    assert df.loc[0, "정산예상금액_배송비포함"] == 70000


def test_coupang_unknown_settlement_is_estimated_from_paid():
    """샵마인 쿠팡 '알수없음' → 실결제금액 × (1 − 0.1155)."""
    data = _xlsx([["1001", "배송완료", "알수없음", 80000, 1, "06.쿠팡", "코트 12345",
                   "블랙/95", "1234", 80000, "알수없음", "알수없음", "정산예정",
                   "홍길동", "2026-07-04"]], COLS)
    df = SS.from_shopmine_excel(data, "샵마인.xlsx")
    assert df.loc[0, "정산예상금액_배송비포함"] == 80000 * (1 - 0.1155)
    assert df.loc[0, "수수료율"] == "11.55%"


def test_settle_source_and_origin_tagged():
    data = _xlsx([["1001", "배송완료", 70000, 80000, 1, "06.쿠팡", "코트 12345",
                   "블랙/95", "1234", 80000, 9240, "11.55%", "정산예정", "홍길동",
                   "2026-07-04"]], COLS)
    df = SS.from_shopmine_excel(data, "샵마인.xlsx")
    assert df.loc[0, "_settle_source"] == "real"
    assert df.loc[0, "_sell_origin"] == "shopmine"


def test_missing_required_column_raises():
    cols = [c for c in COLS if c != "단가"]
    data = _xlsx([["1001", "배송완료", 70000, 1, "06.쿠팡", "코트 12345",
                   "블랙/95", "1234", 80000, 9240, "11.55%", "정산예정",
                   "홍길동", "2026-07-04"]], cols)
    with pytest.raises(ValueError, match="필수 컬럼"):
        SS.from_shopmine_excel(data, "샵마인.xlsx")


def test_optional_columns_are_filled_blank_not_required():
    """옵션·송장입력 등 선택 컬럼이 없어도 통과하고 빈 값으로 채워진다."""
    cols = [c for c in COLS if c not in ("옵션", "송장입력")]
    data = _xlsx([["1001", "배송완료", 70000, 80000, 1, "06.쿠팡", "코트 12345",
                   80000, 9240, "11.55%", "정산예정", "홍길동", "2026-07-04"]], cols)
    df = SS.from_shopmine_excel(data, "샵마인.xlsx")
    assert df.loc[0, "옵션"] == ""
    assert df.loc[0, "송장입력"] == ""
    assert df.loc[0, "단가"] == 80000
