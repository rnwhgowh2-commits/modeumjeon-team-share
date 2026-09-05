# -*- coding: utf-8 -*-
"""배송비도 수수료를 뗀다 — N열(`정산예정금(배송비포함)`)이 **마켓 실값**을 쓴다.

🔴 판정 근거(2026-08-13, 사장님이 주신 쿠팡 자기 정산 엑셀 9개·449행·153주문 전수):
   배송료는 `<기본배송료>`/`<추가배송료>` 라는 **독립 정산 행**으로 오고, 판매액에
   서비스이용율 3.0%(VAT 별도) → 실효 3.3% 수수료가 붙는다. 예외 0건.
     4,000→3,868(105건) · 3,000→2,901(10) · 10,000→9,670(5) · 9,000→8,703(2)
     6,000→5,802(1) · −4,000→−3,868(환불 1)
   즉 「N = M + 고객배송비 **전액**」(2026-07-23 정답지 45건 근거)은 **정답지의 계산
   정의**였고, 「마켓이 실제로 주는 돈」은 아니었다. 우리 N열의 소비처(마진계산기·
   이행판정·KPI)는 전부 후자를 묻는다 → 실값 채택(사장님 확정: "실마켓은 100% 정답").

🔴 이 시험이 지키는 되돌림 함정 4가지
  1. M열(`정산예정금액`)엔 안 넣는다 — 스스에서 그렇게 했다가 `_finalize` 가 또 더해
     이중 계상 사고(2026-08-07, 2,910원 과다).
  2. 배송건당 1회 규약(`_shipkey`) 을 실값에도 똑같이 적용 — 다건 주문에서 여러 번 금지.
  3. 실값이 없는 마켓(롯데온·11번가·옥션·G마켓)은 **지금 그대로** 고객배송비 전액.
     롯데온은 M에서 배송비를 뺐다가 `_finalize` 가 되더하는 구조라 바뀌면 터진다.
  4. 취소완료 행은 손대지 않는다(정산 0 규약 그대로).
"""
import pytest

from lemouton.markets import order_export as oe


@pytest.fixture(autouse=True)
def _clear_learned_rates(tmp_path, monkeypatch):
    """상품별 실요율 '기억'을 매번 빈 DB 에서 시작한다.

    쿠팡 요율 학습은 조회를 넘어 DB 에 남는다(그게 기능이다). 격리하지 않으면 앞
    테스트가 남긴 요율을 물려받아 **먼저 돈 테스트에 따라 결과가 갈린다** —
    실제로 이 파일에서 settled 테스트가 남긴 11.618% 를 unsettled 테스트가 주워
    기본율 11.55% 대신 그 값으로 추정했다. (test_order_export_settle_source.py 의
    같은 픽스처와 동일한 이유.)
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import lemouton.margin.models  # noqa: F401 — MarketLearnedRates 표 등록
    import shared.db as db

    eng = create_engine(f"sqlite:///{tmp_path / 'learned.db'}")
    db.Base.metadata.create_all(eng)
    monkeypatch.setattr(
        db, "SessionLocal",
        sessionmaker(bind=eng, autoflush=False, autocommit=False,
                     future=True, expire_on_commit=False))
    yield


# ── ① _finalize_rows — 실값이 있으면 그걸 쓴다 ────────────────────────────────
def test_n_column_uses_real_ship_settlement():
    """실값(_ship_settle)이 있으면 고객배송비 대신 그 값을 더한다."""
    rows = oe._finalize_rows([{
        "주문일": "2026-07-05", "판매처": "쿠팡", "단가": 128900, "수량": 1,
        "배송비": 4000, "정산예정금액": 113924, "_ship_settle": 3868,
        "_shipkey": ("coupang", "1100194049219"), "_settle_source": "real",
    }])
    assert rows[0]["정산예정금(배송비포함)"] == 113924 + 3868   # 117,792 (전액이면 117,924)
    # M열은 상품 정산 그대로 — 이중 계상 방지
    assert rows[0]["정산예정금액"] == 113924
    # 고객배송비 열(L)은 「고객이 낸 돈」이라 안 건드린다
    assert rows[0]["배송비"] == 4000


def test_n_column_falls_back_to_customer_fee_when_no_real_value():
    """실값이 없는 마켓은 예전 그대로 — 고객배송비 전액(롯데온 규약 보호)."""
    rows = oe._finalize_rows([{
        "주문일": "2026-07-05", "판매처": "롯데온", "단가": 50000, "수량": 1,
        "배송비": 3000, "정산예정금액": 45000, "_settle_source": "real",
    }])
    assert rows[0]["정산예정금(배송비포함)"] == 48000


def test_real_ship_settlement_counted_once_per_shipment():
    """같은 배송건(_shipkey)의 둘째 행부터는 실값도 0 — 다건 주문 중복 가산 금지."""
    rows = oe._finalize_rows([
        {"주문일": "2026-07-05", "판매처": "쿠팡", "단가": 10000, "수량": 1,
         "배송비": 4000, "정산예정금액": 8845, "_ship_settle": 3868,
         "_shipkey": ("coupang", "A")},
        {"주문일": "2026-07-05", "판매처": "쿠팡", "단가": 20000, "수량": 1,
         "배송비": 4000, "정산예정금액": 17690, "_ship_settle": 3868,
         "_shipkey": ("coupang", "A")},
    ])
    assert rows[0]["정산예정금(배송비포함)"] == 8845 + 3868
    assert rows[1]["정산예정금(배송비포함)"] == 17690        # 둘째 행엔 안 더한다
    assert rows[1]["배송비"] == 0


def test_zero_real_ship_settlement_is_not_treated_as_missing():
    """실값 0 은 「모름」이 아니라 「배송비 정산이 0원」이다 — 폴백 금지.

    🔴 엑셀 실측: 배송료 행 308개 중 184개가 정산금액 0 이었다. 0 을 falsy 로 보고
      고객배송비로 폴백하면 그 184건이 통째로 과대가 된다.
    """
    rows = oe._finalize_rows([{
        "주문일": "2026-07-05", "판매처": "쿠팡", "단가": 59000, "수량": 1,
        "배송비": 4000, "정산예정금액": 52185, "_ship_settle": 0,
        "_shipkey": ("coupang", "21101465230095"),
    }])
    assert rows[0]["정산예정금(배송비포함)"] == 52185


def test_negative_real_ship_settlement_survives():
    """환불 주문은 배송비 정산이 음수(-3,868)로 온다 — 부호 그대로."""
    rows = oe._finalize_rows([{
        "주문일": "2026-07-05", "판매처": "쿠팡", "단가": 30000, "수량": 1,
        "배송비": 0, "정산예정금액": -26535, "_ship_settle": -3868,
        "_shipkey": ("coupang", "19100191129918"),
    }])
    assert rows[0]["정산예정금(배송비포함)"] == -26535 - 3868


def test_ship_settle_is_internal_only():
    """`_ship_settle` 은 내부 키 — 엑셀 열에 새지 않는다."""
    assert "_ship_settle" not in oe.ALL_COLUMNS
    assert "_ship_settle" not in oe.resolve_columns(None)


def test_ship_settle_survives_refinalize():
    """🔴 저장분 재계산(`enrich_stored_rows` → `_finalize_rows` 재호출)에서도 같은 N.

    `_shipkey`·`_oid` 처럼 pop 해 버리면 저장분엔 실값이 없어 N열이 조용히
    「M + 고객배송비」로 되돌아간다. 화면·마진계산기·정산탭이 읽는 것은 **저장분**이라
    그러면 라이브에서 고친 보람이 통째로 사라진다 — 에러도 안 나면서.
    """
    row = {"주문일": "2026-07-05", "판매처": "쿠팡", "단가": 128900, "수량": 1,
           "배송비": 4000, "정산예정금액": 113924, "_ship_settle": 3868,
           "_shipkey": ("coupang", "1100194049219")}
    once = oe._finalize_rows([row])[0]
    assert once["정산예정금(배송비포함)"] == 117792
    assert once["_ship_settle"] == 3868          # 저장에 실려야 한다
    twice = oe._finalize_rows([dict(once)])[0]   # 저장분 재계산(=_shipkey 없음)
    assert twice["정산예정금(배송비포함)"] == 117792


def test_ship_settle_refinalize_is_idempotent_for_second_line():
    """다건 주문의 둘째 행은 재계산해도 배송비가 되살아나지 않는다."""
    rows = oe._finalize_rows([
        {"주문일": "2026-07-05", "판매처": "쿠팡", "단가": 10000, "수량": 1,
         "배송비": 4000, "정산예정금액": 8845, "_ship_settle": 3868,
         "_shipkey": ("coupang", "A")},
        {"주문일": "2026-07-05", "판매처": "쿠팡", "단가": 20000, "수량": 1,
         "배송비": 4000, "정산예정금액": 17690, "_ship_settle": 3868,
         "_shipkey": ("coupang", "A")},
    ])
    again = oe._finalize_rows([dict(r) for r in rows])
    assert again[0]["정산예정금(배송비포함)"] == 8845 + 3868
    assert again[1]["정산예정금(배송비포함)"] == 17690


# ── ② 쿠팡 빌더 — 이미 모으고 버리던 deliveryFee.settlementAmount 를 쓴다 ──────
SINCE = __import__("datetime").datetime(2026, 7, 5)
UNTIL = __import__("datetime").datetime(2026, 7, 6)
RECOGNIZED_ON = "2026-07-06"


def _asked_window(query: str):
    import urllib.parse as up
    q = dict(up.parse_qsl(query))
    return q.get("recognitionDateFrom", ""), q.get("recognitionDateTo", "")


class _CoupangWithDeliveryFee:
    """상품 정산 113,924 + 배송비 정산 3,868(고객배송비는 4,000)."""

    _cfg = {"vendor_id": "A1"}
    DELIV = 3868

    def request(self, method, path, query=""):
        if "ordersheets" in path:
            return {"data": [{"shipmentBoxId": 1, "orderId": 100,
                              "status": "FINAL_DELIVERY", "orderer": {}, "receiver": {},
                              # 🔴 쿠팡 금액은 {units:N} 객체다 — 평범한 int 를 주면
                              #   `_won` 이 ''(모름)을 돌려줘 배송비가 통째로 사라진다.
                              "shippingPrice": {"units": 4000},
                              "orderItems": [{"vendorItemId": 9, "sellerProductName": "가방",
                                              "shippingCount": 1,
                                              "salesPrice": {"units": 128900}}]}],
                    "nextToken": ""}
        if "revenue-history" in path:
            _f, _t = _asked_window(query)
            if not (_f <= RECOGNIZED_ON <= _t):
                return {"data": [], "hasNext": False}
            return {"data": [{"orderId": 100,
                              "deliveryFee": {"settlementAmount": self.DELIV},
                              "items": [{"vendorItemId": 9,
                                         "settlementAmount": 113924}]}],
                    "hasNext": False}
        return {"data": [], "nextToken": ""}


def _built(client):
    """빌더는 N열을 안 만든다 — 파이프라인과 같이 `_finalize_rows` 까지 태운다."""
    return oe._finalize_rows(oe.coupang_order_rows(SINCE, UNTIL, client=client))


def test_coupang_row_uses_delivery_fee_settlement():
    """🔴 실측 재현 — 주문 1100194049219: 배송비 4,000 을 더하면 132원 과대."""
    r = next(r for r in _built(_CoupangWithDeliveryFee())
             if str(r["오픈마켓주문번호"]) == "100")
    assert r["정산예정금액"] == 113924            # M = 상품 정산만(불변)
    assert r["배송비"] == 4000                     # 고객이 낸 배송비(불변)
    assert r["정산예정금(배송비포함)"] == 117792   # 113,924 + 3,868  ← 전액이면 117,924


def test_coupang_zero_delivery_settlement_is_respected():
    """배송비 정산이 0 이면 0 — 고객배송비 4,000 으로 메우지 않는다."""
    cli = _CoupangWithDeliveryFee()
    cli.DELIV = 0
    r = next(r for r in _built(cli) if str(r["오픈마켓주문번호"]) == "100")
    assert r["정산예정금(배송비포함)"] == 113924


class _CoupangNoDeliveryFee(_CoupangWithDeliveryFee):
    """정산 전(미정산) — revenue-history 가 아직 그 주문을 안 준다."""

    def request(self, method, path, query=""):
        if "revenue-history" in path:
            return {"data": [], "hasNext": False}
        return _CoupangWithDeliveryFee.request(self, method, path, query)


def test_coupang_unsettled_estimates_shipping_fee():
    """미정산이면 배송비도 **추정**한다 — 상품 추정과 같은 규율(3.3% 실측).

    실값이 올 때까지 고객배송비 전액을 더하면, 정산 전 주문이 늘 3.3% 부풀어
    이행판정(정산예정금 − 매입가 > 0)이 팔면 손해인 주문을 「가능」으로 내보낸다.
    """
    r = next(r for r in _built(_CoupangNoDeliveryFee())
             if str(r["오픈마켓주문번호"]) == "100")
    assert r["_settle_source"] == "estimated"
    # 🔴 기대값을 **손으로** 적는다 — 종전엔 `round(128900 * CP_FEE_FACTOR)` 처럼
    #   구현식을 그대로 베껴서, 식이 틀려도 시험이 늘 통과했다(2026-08-13 발견).
    #   쿠팡 규칙: 수수료 = 반올림( 버림(기준 × 요율VAT별도) × 1.1 )
    #     상품  128,900 × 10.5% = 13,534.5 → 버림 13,534 → ×1.1 = 14,887.4
    #                                       → 반올림 14,887 → 정산 114,013
    #     배송료  4,000 ×  3.0% =    120.0 → 버림    120 → ×1.1 =    132.0
    #                                       → 반올림    132 → 정산   3,868
    #   합계 117,881. (옛 근사식 `×0.8845` 는 114,012 로 1원 적게 나왔다.)
    assert r["정산예정금(배송비포함)"] == 117881


@pytest.mark.parametrize("fee,settled", [
    (4000, 3868), (3000, 2901), (10000, 9670), (9000, 8703), (6000, 5802),
])
def test_ship_fee_factor_matches_measured_excel(fee, settled):
    """쿠팡 엑셀 배송료 행에서 관측된 값을 **실제 쓰는 식**이 재현하는가.

    🔴 정본은 `cp_fee()` 다 — 상수 `CP_SHIP_FEE_FACTOR`(0.967) 는 근사라 버림 자리가
      달라질 수 있다. 시험은 **라이브가 실제로 부르는 함수**를 걸어야 뜻이 있다.
      (근사 상수도 이 5개 값에서는 같은 답을 내므로 함께 잠가 둔다.)
    """
    assert fee - oe.cp_fee(fee, oe.CP_SHIP_FEE_RATE_EX_VAT) == settled
    assert round(fee * oe.CP_SHIP_FEE_FACTOR) == settled
