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


def _undo_shopmine_word_purge(text: str) -> str:
    """2026-09 "샵마인" 단어 제거 작업(사장님 지시)에서 의도적으로 바꾼 식별자를
    원본 이름으로 되돌린다 — 무수정 이식 가드가 이 사전 승인된 리네임까지 diff 로
    잡으면 안 되므로, 비교 직전에만 원복해 실제 로직 변조와 구분한다."""
    reps = [
        ("MARKET_SELL_COLS", "SHOPMINE_COLS"),
        ("_PANMAECHEO_TO_CHANNEL_CODE", "_PANMAECHEO_TO_SHOPMINE"),
        ("market_to_channel_code", "market_to_shopmine"),
        ("market_df", "shopmine_df"),
        ("market_by_order", "shopmine_by_order"),
        ("market_lookup", "shopmine_lookup"),
        ("market_has_normal", "shopmine_has_normal"),
        ("market_all_statuses", "shopmine_all_statuses"),
        ("matched_market_keys", "matched_shopmine_keys"),
        ("market_key", "shopmine_key"),
        ("market_row", "shopmine_row"),
        ("market_only", "shopmine_only"),
        ("판매처 매출", "샵마인 매출"),
        ("판매처_매칭", "샵마인_매칭"),
        ("판매처_정상건존재", "샵마인_정상건존재"),
        ("판매처_모든주문상태", "샵마인_모든주문상태"),
        ("판매처_주문상태", "샵마인_주문상태"),
        ("판매처_정산예상금액(배송비포함)", "샵마인_정산예상금액(배송비포함)"),
        ("판매처_송장입력", "샵마인_송장입력"),
        ("판매처_{col}", "샵마인_{col}"),
        ("판매처 오픈마켓주문번호", "샵마인 오픈마켓주문번호"),
        ("# 판매처(마켓 API) 측 정보", "# 샵마인 측 정보"),
        ("'판매처_*' 필드", "'샵마인_*' 필드"),
        ("판매처에만 있는 행", "샵마인에만 있는 행"),
    ]
    for new, old in reps:
        text = text.replace(new, old)
    # 삭제된 죽은 필드 '샵마인_샵마인주문상태' 한 줄 — 실데이터에서 늘 빈 문자열이던
    # 필드라 2026-09 정리 때 아예 지웠다(단순 리네임이 아니라 삭제). 원본과의 줄 단위
    # diff 를 맞추려면 이 자리에 그 줄을 되살려 넣어야 한다(로직상으로는 죽은 채였다).
    text = text.replace(
        "            '샵마인_주문상태':           str(s_row.get('주문상태', '') or ''),\n"
        "            '샵마인_정산예상금액(배송비포함)':",
        "            '샵마인_주문상태':           str(s_row.get('주문상태', '') or ''),\n"
        "            '샵마인_샵마인주문상태':     str(s_row.get('샵마인주문상태', '') or ''),\n"
        "            '샵마인_정산예상금액(배송비포함)':",
    )
    return text


def test_source_is_verbatim_except_import_lines():
    """원본과의 diff 가 config import 두 줄 + 승인된 샵마인 리네임뿐이어야 한다.

    원본은 개발자 PC 에만 있는 단독앱이라 CI·팀원 PC 에서는 skip 된다.
    (skip 이 아니라 FileNotFoundError 로 '에러' 나면 스위트 전체가 빨개진다.)
    """
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")
    ported = _undo_shopmine_word_purge(
        pathlib.Path(M.__file__).read_text(encoding="utf-8")).splitlines()
    original = ORIGINAL.read_text(encoding="utf-8").splitlines()

    def strip(lines):
        # 무수정 이식에서 유일하게 손대는 것 = 패키지 경로 import 줄:
        #   from config import ...            → from lemouton.margin.config import ...
        #   from modules import brand_dict    → from lemouton.margin import brand_dict
        #   from modules.brand_dict import .. → from lemouton.margin.brand_dict import ..
        skip = ("config import", "import brand_dict", "brand_dict import")
        return [ln for ln in lines if not any(s in ln for s in skip)]

    assert strip(ported) == strip(original), \
        "matcher 본문이 원본과 다릅니다 — 무수정 이식 규칙 위반"


def test_original_path_guard_is_skippable():
    """원본 경로가 없는 PC(CI·팀원)에서 이 파일이 FileNotFoundError 로 '에러' 나면 안 된다.
    가드가 있으면 skip 된다. (test_export.py 는 같은 패턴을 이미 쓰고 있다.)"""
    import inspect
    src = inspect.getsource(test_source_is_verbatim_except_import_lines)
    assert "ORIGINAL.exists()" in src, "원본 부재 시 skip 가드가 없습니다"
