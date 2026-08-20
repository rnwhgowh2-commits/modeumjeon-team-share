# -*- coding: utf-8 -*-
"""스마트스토어 정합성 대조 — 엑셀 없이 **마켓 API 로 직접**.

노션 원문: 정산관리 > 정산 내역(일별) > 정산예정일(1달) / 일반정산금액 + 빠른정산금액 /
「스스 기준, 집하일 하면 줌」.

🔴 사장님께 파일을 부탁하기 전에 이미 있는 자동 경로를 쓴다(로켓그로스 엑셀 184개를
   요청했던 실수와 같은 부류를 피한다).
"""
import datetime as dt

import pytest

from lemouton.margin import settle_recon as SR

TODAY = dt.date(2026, 8, 13)


def _iter(by_day):
    """{날짜: [행,...]} 를 주는 가짜 조회기. period_type 을 기록해 축을 검사한다."""
    seen = {"period": set(), "days": []}

    def it(search_date=None, period_type=None, client=None, **kw):
        seen["period"].add(period_type)
        seen["days"].append(search_date)
        return iter(by_day.get(search_date, []))

    return it, seen


def _row(amt, ptype="PROD_ORDER", stype="NORMAL_SETTLE_ORIGINAL"):
    return {"settleExpectAmount": amt, "productOrderType": ptype, "settleType": stype}


def test_정산예정일_축으로_1달을_훑는다():
    """🔴 결제일 축으로 부르면 **다른 것을 비교하게 된다** — 축을 못 박는다."""
    it, seen = _iter({"2026-08-13": [_row(1000)], "2026-09-12": [_row(2000)]})
    out = SR.market_actual_smartstore(today=TODAY, iter_fn=it)
    assert seen["period"] == {SR.SS_PERIOD_SCHEDULE}
    assert SR.SS_PERIOD_SCHEDULE == "SETTLE_CASEBYCASE_SETTLE_SCHEDULE_DATE"
    assert len(seen["days"]) == 31                    # 오늘~+30일
    assert out["합계"] == 3000 and out["금액건수"] == 2
    assert out["기간시작"] == "2026-08-13" and out["기간끝"] == "2026-09-12"


def test_일반정산과_빠른정산을_모두_더한다():
    """노션: 「일반정산금액 + 빠른정산금액」 — 종류를 가리지 않는다."""
    it, _ = _iter({"2026-08-13": [_row(1000, stype="NORMAL_SETTLE_ORIGINAL"),
                                  _row(500, stype="QUICK_SETTLE")]})
    out = SR.market_actual_smartstore(today=TODAY, iter_fn=it)
    assert out["합계"] == 1500
    assert out["정산구분별"]["QUICK_SETTLE"]["금액"] == 500


def test_배송비_정산을_따로_센다():
    """배송비 정산 실값 — 우리 N열이 고객배송비를 더하는지 재는 재료."""
    it, _ = _iter({"2026-08-13": [_row(10000), _row(2910, ptype="DELIVERY")]})
    out = SR.market_actual_smartstore(today=TODAY, iter_fn=it)
    assert out["합계"] == 12910
    assert out["배송비정산합"] == 2910


def test_금액_없는_행은_0으로_안_메운다():
    it, _ = _iter({"2026-08-13": [_row(None), _row(700)]})
    out = SR.market_actual_smartstore(today=TODAY, iter_fn=it)
    assert out["합계"] == 700 and out["금액건수"] == 1


def test_전부_실패하면_0원이_아니라_에러다():
    """🔴 가장 위험한 실패는 「에러 나는 것」이 아니라 **조용히 0원**이다."""
    def it(**kw):
        raise RuntimeError("HTTP 401")
    with pytest.raises(ValueError) as e:
        SR.market_actual_smartstore(today=TODAY, iter_fn=it)
    assert "못 불러온" in str(e.value)


def test_일부만_실패하면_사유를_들고_돌아온다():
    def it(search_date=None, **kw):
        if search_date == "2026-08-15":
            raise RuntimeError("HTTP 429")
        return iter([_row(100)] if search_date == "2026-08-13" else [])
    out = SR.market_actual_smartstore(today=TODAY, iter_fn=it)
    assert out["합계"] == 100
    assert out["오류"] and "2026-08-15" in out["오류"][0]


def test_주문단위_대조는_시도하지_않는다():
    """배송비 행이 상품과 **다른 번호**(배송비번호)를 달고 와 억지로 맞추면 가짜 불일치."""
    it, _ = _iter({"2026-08-13": [_row(1000)]})
    out = SR.market_actual_smartstore(today=TODAY, iter_fn=it)
    assert out["order_col"] == ""
    assert SR.compare_orders(out, [])["가능"] is False
