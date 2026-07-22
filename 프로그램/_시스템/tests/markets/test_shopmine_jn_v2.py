# -*- coding: utf-8 -*-
"""샵마인 J~N열 정합 2차 — 2026-07-23 재추출(파일3) 387건 대조로 확정된 규약.

실측 근거(샵마인=정답지, 사장님 확정):
· 쿠팡: M열 = 상품정산만(배송비 정산 불포함), N열 = M + 고객배송비 **전액**
  (45건 전수 N=M+ship — 배송비 3% 차감은 N에 안 나타남).
· G마켓: K열(실결제) = 단가×수량 **원금**(판매자 쿠폰 할인 전) — 13/13 전수.
  할인 있던 12건이 전부 (샵K=원금, 우리K=할인후) 로 어긋났고 M열은 이미 일치.
· 스스: CANCELED_BY_NOPAYMENT 가 영문 원코드 그대로 노출 + zero_cancel 미적용
  (샵 '취소완료(미결제)' K=원금 43,000 vs 우리 33,900 실측).
· 쿠팡 반품완료·롯데온 취소요청/철회: 샵 K열 = 원금(단가×수량) — 정산(M)은 건드리지 않음.
"""
import copy
import datetime as _dt

import pytest

from lemouton.markets import order_export as oe

KST = _dt.timezone(_dt.timedelta(hours=9))


# ── 쿠팡: 정산예정금액(M)에 배송비 정산을 더하지 않는다 ─────────────────────────

_BOX = {
    "shipmentBoxId": "SB-1", "orderId": "OID-1",
    "orderedAt": "2026-07-10T10:00:00", "shippingPrice": {"units": 4000},
    "orderer": {"name": "구매자"}, "receiver": {"name": "수령인", "addr1": "서울"},
    "orderItems": [{
        "vendorItemId": "VI-1", "sellerProductName": "챔피온 티셔츠",
        "shippingCount": 1, "salesPrice": {"units": 25100},
        "orderPrice": {"units": 25100},
    }],
}


def _cp_rows(monkeypatch, box, settle=None, deliv=None):
    calls = {"n": 0}

    def fake(w0, w1, client=None, status=None, next_token=None):
        calls["n"] += 1
        return {"data": [box]} if calls["n"] == 1 else {"data": []}

    import shared.platforms.coupang.orders as cp_orders
    monkeypatch.setattr(cp_orders, "fetch_orders", fake)
    monkeypatch.setattr(oe, "_coupang_settle_map",
                        lambda *a, **k: (settle or {}, deliv or {}))
    since = _dt.datetime(2026, 7, 9, tzinfo=KST)
    until = _dt.datetime(2026, 7, 11, tzinfo=KST)
    return oe.coupang_order_rows(since, until, client=object(),
                                 include_settlement=True)


def test_쿠팡_추정_정산은_상품분만_배송비는_N열에서만(monkeypatch):
    """샵마인 실측(769222526): 샵 M=상품만, 샵 N=M+배송비 4,000 전액.
    기존엔 M에 배송비×0.97 이 더해져 +4,014 씩 어긋났다(3건)."""
    rows = _cp_rows(monkeypatch, copy.deepcopy(_BOX))
    r = rows[0]
    assert r["정산예정금액"] == round(25100 * 0.8845)      # 22201 — 상품 추정만
    assert r["_settle_source"] == "estimated"
    fin = oe._finalize_rows([dict(r)])[0]
    assert fin["정산예정금(배송비포함)"] == round(25100 * 0.8845) + 4000


def test_쿠팡_실정산도_상품분만_배송비정산은_더하지_않는다(monkeypatch):
    """N=M+고객배송비 규약 유지 — M에 배송비정산(97%)이 섞이면 N이 이중 가산된다."""
    rows = _cp_rows(monkeypatch, copy.deepcopy(_BOX),
                    settle={("OID-1", "VI-1"): 22000}, deliv={"OID-1": 3880})
    assert rows[0]["정산예정금액"] == 22000
    assert rows[0]["_settle_source"] == "real"


# ── ESM(옥션·G마켓): 실결제 = 원금(단가×수량+옵션추가금) ────────────────────────

def test_G마켓_실결제는_원금으로_통일():
    """샵마인 13/13 전수: K열=단가×수량(쿠폰 할인 전). 할인 반영값(BuyerPayAmt)을 덮는다."""
    r = oe._finalize_rows([{
        "판매처": "G마켓", "주문상태": "배송중", "단가": 83500, "수량": 1,
        "배송비": 0, "실결제금액": 73500, "정산예정금액": 72645,
        "오픈마켓주문번호": "E1", "주문일": "2026-07-18 10:00:00",
    }])[0]
    assert r["실결제금액"] == 83500
    assert r["정산예정금액"] == 72645          # M열은 건드리지 않는다(이미 일치)


def test_옥션도_동일_원금_규약():
    r = oe._finalize_rows([{
        "판매처": "옥션", "주문상태": "배송완료", "단가": 20000, "수량": 2,
        "옵션추가금": 1000, "배송비": 3000, "실결제금액": 39000,
        "정산예정금액": "", "오픈마켓주문번호": "E2", "주문일": "2026-07-18 10:00:00",
    }])[0]
    assert r["실결제금액"] == 41000            # 20000×2 + 옵션 1000


def test_ESM_단가가_없으면_기존_실결제_유지():
    """원금을 계산할 수 없으면 덮지 않는다(날조 금지)."""
    r = oe._finalize_rows([{
        "판매처": "G마켓", "주문상태": "배송중", "단가": "", "수량": "",
        "배송비": 0, "실결제금액": 73500, "정산예정금액": "",
        "오픈마켓주문번호": "E3", "주문일": "2026-07-18 10:00:00",
    }])[0]
    assert r["실결제금액"] == 73500


def test_ESM_빌더가_실결제를_원금으로_채운다(monkeypatch):
    """미정산 신규 주문도 K열이 나와야 역산 추정(estimate)이 돈다
    (실측 471551517: 발송대기인데 실결제·정산 전부 공란)."""
    od = {"OrderNo": "G-1", "OrderDate": "2026-07-20 10:00:00",
          "GoodsName": "나이키 코르테즈", "ContrAmount": "1", "SalePrice": "87000",
          "ShippingFee": "0", "OrderStatus": "배송준비중", "SiteGoodsNo": "SG1"}
    monkeypatch.setattr(oe, "_esm_all_orders", lambda *a, **k: [od])
    monkeypatch.setattr("shared.platforms.esm.settlements.settle_detail_map",
                        lambda *a, **k: {})
    since = _dt.datetime(2026, 7, 19, tzinfo=KST)
    until = _dt.datetime(2026, 7, 21, tzinfo=KST)
    rows = oe.esm_order_rows("gmarket", since, until, client=None)
    assert rows[0]["실결제금액"] == 87000


# ── 스스: 미결제 취소 상태 한글화 → zero_cancel 자동 적용 ────────────────────────

def test_스스_미결제취소_한글화():
    assert oe._status_ko("smartstore", "CANCELED_BY_NOPAYMENT") == "취소완료(미결제)"


def test_스스_미결제취소는_정산0_실결제_원금():
    """실측 913547351: 샵 K=43,000(원금)·정산 없음 vs 우리 K=33,900·M=31,866(추정 날조)."""
    r = oe._finalize_rows([{
        "판매처": "스마트스토어", "주문상태": "취소완료(미결제)", "단가": 43000,
        "수량": 1, "배송비": 0, "실결제금액": 33900, "정산예정금액": 31866,
        "오픈마켓주문번호": "S1", "주문일": "2026-07-18 10:00:00", "_kind": "change",
    }])[0]
    assert r["정산예정금액"] == 0
    assert r["실결제금액"] == 43000
    assert r["_settle_source"] == "zero_cancel"


# ── 취소요청·철회·쿠팡 반품완료: K열 = 원금 (M열은 불변) ─────────────────────────

def test_취소요청_실결제는_원금_정산은_불변():
    """실측 616897117: 샵 K=138,100(원금) — 취소요청(철회 포함)도 원금 표기."""
    r = oe._finalize_rows([{
        "판매처": "롯데온", "주문상태": "취소요청", "단가": 138100, "수량": 1,
        "배송비": 0, "실결제금액": 130160, "정산예정금액": 118559,
        "오픈마켓주문번호": "L1", "주문일": "2026-07-16 10:00:00", "_kind": "change",
    }])[0]
    assert r["실결제금액"] == 138100
    assert r["정산예정금액"] == 118559         # 미확정이라 0 강제 안 함(기존 규약 유지)


def test_쿠팡_반품완료_실결제는_원금():
    """실측 749312893: 샵 K=52,200(단가) vs 우리 29,200(할인후). 정산(공란)은 그대로."""
    r = oe._finalize_rows([{
        "판매처": "쿠팡", "주문상태": "반품완료", "단가": 52200, "수량": 1,
        "배송비": 0, "실결제금액": 29200, "정산예정금액": "",
        "오픈마켓주문번호": "C1", "주문일": "2026-07-16 10:00:00", "_kind": "change",
    }])[0]
    assert r["실결제금액"] == 52200
    assert r["정산예정금액"] == ""


def test_정상주문_실결제는_덮지_않는다():
    """K=원금 규약은 취소·반품·ESM 한정 — 다른 마켓 정상 주문의 실결제(할인 반영)는 보존."""
    r = oe._finalize_rows([{
        "판매처": "롯데온", "주문상태": "배송완료", "단가": 61000, "수량": 1,
        "배송비": 4000, "실결제금액": 49280, "정산예정금액": 50594,
        "오픈마켓주문번호": "L2", "주문일": "2026-07-16 10:00:00",
    }])[0]
    assert r["실결제금액"] == 49280
