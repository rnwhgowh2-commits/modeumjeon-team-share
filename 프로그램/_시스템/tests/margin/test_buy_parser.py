# -*- coding: utf-8 -*-
"""더망고 매입 엑셀 파서."""
import io

import pandas as pd
import pytest

from lemouton.margin import buy_parser as bp


def _xlsx_bytes(rows: list, cols: list) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows, columns=cols).to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


COLS = ["마켓주문일자", "마켓명", "마켓주문번호", "수령인명",
        "마켓상품명", "옵션1", "사이트주문번호", "구매가격", "간단메모"]


def test_parse_buy_basic():
    data = _xlsx_bytes([
        ["26.07.04", "쿠팡", "1001", "홍길동", "코트 12345", "블랙/95", "SO-1", 50000, ""],
    ], COLS)
    df = bp.parse_buy(data, "더망고.xlsx")
    assert len(df) == 1
    assert df.loc[0, "마켓주문번호"] == "1001"
    assert df.loc[0, "구매가격"] == 50000
    assert "_uid" in df.columns


def test_parse_buy_strips_float_suffix_on_order_no():
    data = _xlsx_bytes([
        ["26.07.04", "쿠팡", 1001.0, "홍길동", "코트 12345", "블랙/95", "SO-1", 50000, ""],
    ], COLS)
    df = bp.parse_buy(data, "더망고.xlsx")
    assert df.loc[0, "마켓주문번호"] == "1001"


def test_parse_buy_sentinel_999_becomes_zero():
    """구매가격 미입력 센티널 999999999.99 는 0 으로 — 집계 왜곡 방지."""
    data = _xlsx_bytes([
        ["26.07.04", "쿠팡", "1001", "홍길동", "코트 12345", "블랙/95", "SO-1", 999999999.99, ""],
    ], COLS)
    df = bp.parse_buy(data, "더망고.xlsx")
    assert df.loc[0, "구매가격"] == 0


def test_parse_buy_missing_required_column_raises():
    data = _xlsx_bytes([["26.07.04", "쿠팡"]], ["마켓주문일자", "마켓명"])
    with pytest.raises(ValueError, match="필수 컬럼"):
        bp.parse_buy(data, "더망고.xlsx")


# ══════════════════════════════════════════════════════════════════════
# HTML 포맷 .xls (더망고 구버전 다운로드) — issue #1139: lxml 우선 파싱으로 바꾼
#   뒤에도 결과가 그대로인지 잠근다.
# ══════════════════════════════════════════════════════════════════════

def _html_xls_bytes(rows: list) -> bytes:
    head = ("<html><head><meta http-equiv='Content-Type' "
            "content='application/vnd.ms-excel;charset=utf-8'></head><body>"
            "<table border='1'><tr>" +
            "".join(f"<td>{c}</td>" for c in COLS) + "</tr>")
    body = "".join(
        "<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>" for r in rows)
    tail = "</table></body></html>"
    return (head + body + tail).encode("utf-8")


def test_parse_buy_html_xls_format_lxml():
    data = _html_xls_bytes([
        ["26.07.04", "쿠팡", "1001", "홍길동", "코트 12345", "블랙/95", "SO-1", "50000", ""],
    ])
    df = bp.parse_buy(data, "더망고.xls")
    assert len(df) == 1
    assert df.loc[0, "마켓주문번호"] == "1001"
    assert df.loc[0, "구매가격"] == 50000
    assert "_uid" in df.columns


def test_parse_buy_html_xls_sentinel_and_multirow():
    data = _html_xls_bytes([
        ["26.07.04", "쿠팡", "1001", "홍길동", "코트 12345", "블랙/95", "SO-1", "50000", ""],
        ["26.07.05", "롯데ON", "1002", "김철수", "신발 54321", "화이트/260", "", "999999999.99", "메모"],
    ])
    df = bp.parse_buy(data, "더망고.xls")
    assert len(df) == 2
    assert df.loc[1, "구매가격"] == 0, "센티널(미입력) 999999999.99 는 HTML 경로에서도 0 이어야 한다"


def test_split_by_site_order_no():
    data = _xlsx_bytes([
        ["26.07.04", "쿠팡", "1001", "A", "코트 12345", "블랙", "SO-1", 50000, ""],
        ["26.07.04", "쿠팡", "1002", "B", "코트 12345", "블랙", "", 0, "s"],
        ["26.07.04", "쿠팡", "1003", "C", "코트 12345", "블랙", "0", 0, "x"],
    ], COLS)
    df = bp.parse_buy(data, "더망고.xlsx")
    valid, missing = bp.split_by_site_order_no(df)
    assert len(valid) == 1 and len(missing) == 2
    assert valid.loc[0, "마켓주문번호"] == "1001"
