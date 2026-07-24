# -*- coding: utf-8 -*-
"""order_export._settle_source — real / estimated / none 태깅."""
import datetime as dt

import pytest

from lemouton.markets import order_export as oe


@pytest.fixture(autouse=True)
def _clear_learned_rates():
    """상품별 실요율 '기억'을 비운 상태에서 시작한다.

    쿠팡 요율 학습(2026-07-25)은 조회를 넘어 DB 에 남는다 — 그게 기능이다. 대신
    테스트가 서로의 기억을 물려받으면 **먼저 돈 테스트에 따라 결과가 갈린다**
    (실제로 test_coupang_settled_is_real 이 vid 9 = 12% 를 남겨 unsettled 쪽이
    8,845 대신 8,800 을 봤다). 기억 자체를 테스트할 때는 명시적으로 심는다.
    """
    from lemouton.margin.models import MarketLearnedRates
    try:
        from shared.db import SessionLocal
        with SessionLocal() as s:
            row = s.get(MarketLearnedRates, 1)
            if row is not None:
                s.delete(row)
                s.commit()
    except Exception:   # noqa: BLE001 — DB 없는 환경이면 기억도 없다
        pass
    yield

KST = dt.timezone(dt.timedelta(hours=9))
SINCE = dt.datetime(2026, 7, 5, tzinfo=KST)
UNTIL = dt.datetime(2026, 7, 8, tzinfo=KST)


class CoupangSettled:
    _cfg = {"vendor_id": "A1"}

    def request(self, method, path, query=""):
        if "ordersheets" in path:
            return {"data": [{"shipmentBoxId": 1, "orderId": 100, "status": "FINAL_DELIVERY",
                              "orderer": {}, "receiver": {}, "shippingPrice": 0,
                              "orderItems": [{"vendorItemId": 9, "sellerProductName": "코트",
                                              "shippingCount": 1,
                                              "salesPrice": {"units": 10000}}]}],
                    "nextToken": ""}
        if "revenue-history" in path:
            return {"data": [{"orderId": 100,
                              "items": [{"vendorItemId": 9, "settlementAmount": 8800}]}],
                    "hasNext": False}
        return {"data": [], "nextToken": ""}


class CoupangUnsettled(CoupangSettled):
    def request(self, method, path, query=""):
        if "revenue-history" in path:
            return {"data": [], "hasNext": False}
        return CoupangSettled.request(self, method, path, query)


def test_coupang_settled_is_real():
    rows = oe.coupang_order_rows(SINCE, UNTIL, client=CoupangSettled())
    r = next(r for r in rows if str(r["오픈마켓주문번호"]) == "100")
    assert r["_settle_source"] == "real"
    assert r["정산예정금액"] == 8800


def test_coupang_unsettled_is_estimated():
    """실요율을 모르면(기억도 없으면) 계약 기본율 11.55%."""
    rows = oe.coupang_order_rows(SINCE, UNTIL, client=CoupangUnsettled())
    r = next(r for r in rows if str(r["오픈마켓주문번호"]) == "100")
    assert r["_settle_source"] == "estimated"
    assert r["정산예정금액"] == round(10000 * oe.CP_FEE_FACTOR)


def test_coupang_unsettled_uses_remembered_rate():
    """지난 조회에서 정산 확정분으로 배운 그 상품의 실요율을 다시 쓴다.

    2026-07-25 샵마인 대조 회귀: 고정 11.55% 라서 미정산 주문 7건이 건당
    133~167원씩 정산 과다였다(실제 요율 11.67~12.56%).
    """
    from lemouton.margin import learned_rates_store as lrs
    from shared.db import SessionLocal

    with SessionLocal() as s:
        lrs.merge(s, coupang_fee_rates={"9": 0.12})

    rows = oe.coupang_order_rows(SINCE, UNTIL, client=CoupangUnsettled())
    r = next(r for r in rows if str(r["오픈마켓주문번호"]) == "100")
    assert r["_settle_source"] == "estimated"
    assert r["정산예정금액"] == 8800          # 10,000 × (1 − 0.12), 기본율이면 8,845


def test_coupang_settled_teaches_the_rate():
    """정산 확정분을 지나가면 그 상품 요율이 기억에 남는다."""
    from lemouton.margin import learned_rates_store as lrs

    oe.coupang_order_rows(SINCE, UNTIL, client=CoupangSettled())
    assert lrs.load_safe()["coupang_fee_rates"].get("9") == pytest.approx(0.12)


def test_settle_source_survives_finalize():
    rows = oe._finalize_rows([{"주문일": "2026-07-05", "단가": 100, "수량": 1,
                               "정산예정금액": 88, "_settle_source": "estimated"}])
    assert rows[0]["_settle_source"] == "estimated"


def test_settle_source_not_in_xlsx_columns():
    """엑셀 출력 컬럼은 불변 — 기존 소비자 영향 없음."""
    assert "_settle_source" not in oe.ALL_COLUMNS
    assert "_settle_source" not in oe.resolve_columns(None)
