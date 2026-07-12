# -*- coding: utf-8 -*-
"""matcher 무수정 이식 검증 — 함수 존재 + 핵심 동작 + 원본과 바이트 동치(import 줄 제외)."""
import pathlib

import pandas as pd
import pytest

from lemouton.margin import matcher as M

ORIGINAL = pathlib.Path(r"C:\dev\대량등록 마진계산기\modules\matcher.py")


def test_public_api_present():
    for name in ("match_data", "match_for_classifier", "normalize_order_number",
                 "order_match_keys", "extract_product_code", "extract_brand",
                 "normalize_option"):
        assert hasattr(M, name), name


def test_smartstore_order_keys_both_sides():
    assert M.order_match_keys("1234(5678)", "스마트스토어") == ["1234", "5678"]
    assert M.order_match_keys("1234", "쿠팡") == ["1234"]


def test_extract_product_code_last_5plus_digits():
    assert M.extract_product_code("[매장정품] 코트 12345 67890") == "67890"
    assert M.extract_product_code("코트") == ""


def test_normalize_option_sorts_and_unifies():
    assert M.normalize_option("블랙/95-1개") == M.normalize_option("95,블랙")


def test_match_data_stage1_precise():
    buy = pd.DataFrame([{
        "마켓주문일자": "26.07.04", "마켓명": "쿠팡", "마켓주문번호": "1001",
        "수령인명": "홍길동", "마켓상품명": "코트 12345", "옵션1": "블랙/95",
        "구매가격": 50000, "사이트주문번호": "SO-1", "간단메모": "",
    }])
    sell = pd.DataFrame([{
        "오픈마켓주문번호": "1001", "상품명": "코트 12345", "옵션": "블랙/95",
        "단가": 80000, "수량": 1, "실결제금액": 80000,
        "정산예상금액_배송비포함": 70000, "쇼핑몰": "06.쿠팡",
        "수취고객명": "홍길동", "주문일": "2026-07-04", "수수료율": "11.55%",
    }])
    matched, un_buy, un_sell = M.match_data(buy, sell)
    assert len(matched) == 1 and not un_buy and not un_sell
    r = matched[0]
    assert r["매칭타입"] == "정밀"
    assert r["순마진"] == 20000          # 70000 정산 − 50000 매입
    assert r["마진율"] == 25.0           # 20000 / 80000 판매가
    assert r["마켓"] == "쿠팡"           # MARKET_REVERSE 역변환


def test_source_is_verbatim_except_import_lines():
    """원본과의 diff 가 config import 두 줄뿐이어야 한다 (docstring 포함 전부 동일).

    원본은 개발자 PC 에만 있는 단독앱이라 CI·팀원 PC 에서는 skip 된다.
    (skip 이 아니라 FileNotFoundError 로 '에러' 나면 스위트 전체가 빨개진다.)
    """
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")
    ported = pathlib.Path(M.__file__).read_text(encoding="utf-8").splitlines()
    original = ORIGINAL.read_text(encoding="utf-8").splitlines()

    def strip(lines):
        return [ln for ln in lines if "config import" not in ln]

    assert strip(ported) == strip(original), \
        "matcher 본문이 원본과 다릅니다 — 무수정 이식 규칙 위반"


def test_original_path_guard_is_skippable():
    """원본 경로가 없는 PC(CI·팀원)에서 이 파일이 FileNotFoundError 로 '에러' 나면 안 된다.
    가드가 있으면 skip 된다. (test_export.py 는 같은 패턴을 이미 쓰고 있다.)"""
    import inspect
    src = inspect.getsource(test_source_is_verbatim_except_import_lines)
    assert "ORIGINAL.exists()" in src, "원본 부재 시 skip 가드가 없습니다"
