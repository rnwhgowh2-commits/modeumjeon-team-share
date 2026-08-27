# -*- coding: utf-8 -*-
"""aggregator.aggregate — matched → summary + 6종 집계."""
from lemouton.margin import aggregator as A
from lemouton.margin.config import DEFAULT_PRICE_RANGES


def _row(**kw):
    base = {"주문일": "2026-07-04", "일자": "2026-07-04", "월": "2026-07",
            "마켓": "쿠팡", "브랜드": "나이키", "금액대": "5~10만",
            "상품명": "코트 12345", "상품코드": "12345",
            "단가": 80000, "판매가": 80000, "실결제금액": 80000,
            "정산예상금액": 70000, "구매가격": 50000, "순마진": 20000,
            "마진율": 25.0, "수량_매출": 1, "수령인": "홍길동",
            "이상가": False, "매칭타입": "정밀", "간단메모": ""}
    base.update(kw)
    return base


def test_empty_returns_empty_shape():
    out = A.aggregate([], DEFAULT_PRICE_RANGES)
    assert out["summary"] == {}
    assert out["market"] == [] and out["daily"] == []
    assert out["filters"]["brands"] == []


def test_summary_totals():
    out = A.aggregate([_row(), _row(마켓="스마트스토어")], DEFAULT_PRICE_RANGES)
    s = out["summary"]
    assert s["총매출"] == 160000
    assert s["총매입"] == 100000
    assert s["총순마진"] == 40000
    assert round(s["평균마진율"], 2) == 25.0


def test_groupings_present():
    out = A.aggregate([_row()], DEFAULT_PRICE_RANGES)
    for key in ("market", "daily", "monthly", "brand", "priceRange", "product"):
        assert len(out[key]) == 1, key
    assert out["daily"][0]["일자"] == "2026-07-04"
    assert out["monthly"][0]["월"] == "2026-07"
    assert out["brand"][0]["브랜드"] == "나이키"


def test_unfulfilled_without_trace_is_excluded_from_totals():
    """_주문미이행 AND NOT _매입흔적 → 집계 제외 (마진율 인플레이션 차단)."""
    rows = [_row(), _row(마켓주문번호="2", _주문미이행=True, 구매가격=0, 순마진=70000)]
    out = A.aggregate(rows, DEFAULT_PRICE_RANGES)
    assert out["summary"]["총순마진"] == 20000


def test_unfulfilled_with_trace_is_included():
    rows = [_row(), _row(마켓주문번호="2", _주문미이행=True, _매입흔적=True,
                         구매가격=0, 순마진=70000)]
    out = A.aggregate(rows, DEFAULT_PRICE_RANGES)
    assert out["summary"]["총순마진"] == 90000


def test_unpriced_trace_row_kept_in_totals_but_excluded_from_brand_breakdown():
    """[2026-08-27] 사장님 신고 — 브랜드별·일별 탭에 매입 0원인데 매출·순마진이 찍혀
    마진율이 90%대로 부풀어 보였다(실측: 플리츠플리즈 82건, 전부 송장은 있고
    구매가격=0). 매입흔적(송장/URL)만으로 "이행" 취급해 정상 집계에 넣었더니,
    원가를 모르는 행이 마치 고마진인 것처럼 보인 것 — "주문이행 = 실제 매입 있음"
    이라는 확정 기준대로 구매가격이 없으면 브랜드별 등 "정상" 집계에서 뺀다.
    (총계에는 그대로 남긴다 — 이상가와 같은 패턴, 존재를 숨기지 않음.)
    """
    unpriced = _row(마켓주문번호="2", 브랜드="아디다스", _주문미이행=True, _매입흔적=True,
                     구매가격=0, 순마진=70000, 국내송장번호="123")
    out = A.aggregate([_row(), unpriced], DEFAULT_PRICE_RANGES)
    # 총계엔 남는다(기존 동작 유지)
    assert out["summary"]["총순마진"] == 90000
    assert out["summary"]["매칭건수"] == 2
    # 브랜드별 breakdown 엔 구매가 미확정 행(아디다스)이 안 잡힌다
    brands = {r["브랜드"] for r in out["brand"]}
    assert brands == {"나이키"}
    assert out["summary"]["정상순마진"] == 20000
    assert out["summary"]["구매가미확정건수"] == 1


def test_filters_expose_brands_and_markets():
    out = A.aggregate([_row(), _row(마켓="스마트스토어", 브랜드="아디다스")],
                      DEFAULT_PRICE_RANGES)
    assert out["filters"]["brands"] == ["나이키", "아디다스"]
    assert out["filters"]["markets"] == ["스마트스토어", "쿠팡"]
    assert out["filters"]["priceRange"] == ["~1만", "1~3만", "3~5만", "5~10만", "10만~"]
