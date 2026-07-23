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


# ── 11번가: 미정산 M = stlPlnAmt − 배송비 / K = ordPayAmt−배송비+(표기−적용 할인차) ──

def _e11_rows(monkeypatch, od):
    import shared.platforms.eleven11.orders as e11o

    def one(since, until, client=None):
        yield od

    def none(since, until, client=None):
        return iter(())

    for name in ("iter_preparing",):
        monkeypatch.setattr(e11o, name, one)
    for name in ("iter_orders", "iter_shipping", "iter_delivered", "iter_completed",
                 "iter_cancel", "iter_canceled", "iter_return", "iter_exchange"):
        monkeypatch.setattr(e11o, name, none)
    since = _dt.datetime(2026, 7, 20, tzinfo=KST)
    until = _dt.datetime(2026, 7, 22, tzinfo=KST)
    return oe.eleven11_order_rows(since, until, client=object(),
                                  include_settlement=False)


_E11_OD = {
    "ordNo": "20260721086650134", "ordPrdSeq": "1", "ordDt": "2026-07-21 16:30:45",
    "prdNm": "나이키 오프코트", "ordQty": "1", "selPrc": "34600",
    "ordAmt": "34600", "ordPayAmt": "37150", "dlvCst": "3000", "bndlDlvYN": "N",
    "stlPlnAmt": "32913", "tmallDscPrcPerSeq": "450", "tmallApplyDscAmt": "450",
    "rcvrNm": "홍길동",
}


def test_11번가_미정산_M은_stlPlnAmt에서_배송비를_뺀다(monkeypatch):
    """라이브 프로브 실측(2026-07-23, 086650134): stlPlnAmt=32,913 은 배송비 3,000 포함
    — 샵마인 M열 29,913 = stlPlnAmt − dlvCst. N열은 _finalize 가 +배송비로 복원."""
    r = _e11_rows(monkeypatch, dict(_E11_OD))[0]
    assert r["정산예정금액"] == 32913 - 3000        # 29913
    assert r["배송비"] == "3000"
    fin = oe._finalize_rows([dict(r)])[0]
    assert fin["정산예정금(배송비포함)"] == 32913     # N = stlPlnAmt 그대로


def test_11번가_K는_적용할인_기준(monkeypatch):
    """라이브 프로브 실측(086884234): ordPayAmt 는 tmall '표기' 할인(4,700)을 뺀 값인데
    샵마인 K=28,400 은 '적용' 할인(tmallApplyDscAmt 4,400) 기준 = ordAmt−적용할인.
    K = ordPayAmt − 배송비 + (표기−적용 차액). 차액 0이면 기존과 동일."""
    od = dict(_E11_OD, ordNo="20260722086884234", ordAmt="32800", selPrc="32800",
              ordPayAmt="28100", stlPlnAmt="27683", tmallDscPrcPerSeq="4700",
              tmallApplyDscAmt="4400")
    od.pop("dlvCst")                              # 무료배송(dlvCstType 03)
    r = _e11_rows(monkeypatch, od)[0]
    assert r["실결제금액"] == 28100 + (4700 - 4400)   # 28400 = 샵 K
    assert r["정산예정금액"] == 27683                 # ship 0 → stlPlnAmt 그대로


def test_11번가_할인차가_없으면_기존_공식(monkeypatch):
    r = _e11_rows(monkeypatch, dict(_E11_OD))[0]
    assert r["실결제금액"] == 37150 - 3000            # 34150 (차액 0)


# ── 쿠팡: 배송비 = shippingPrice + remotePrice(도서산간) ─────────────────────────

def test_쿠팡_배송비는_도서산간_추가비를_포함한다(monkeypatch):
    """라이브 프로브 실측(6101762660613): shippingPrice 0 + remotePrice 5,000
    (remoteArea=True) — 샵마인 배송비 5,000. remotePrice 를 안 더하면 L·N열 누락."""
    box = copy.deepcopy(_BOX)
    box["shippingPrice"] = {"units": 0}
    box["remotePrice"] = {"units": 5000}
    rows = _cp_rows(monkeypatch, box)
    assert rows[0]["배송비"] == 5000


# ── 롯데온: 제휴 판별 = 주문 자체 chNo(크롤 확정 다음, 이력 추정보다 우선) ────────

def test_롯데온_chNo_제휴_판별():
    """라이브 70건 전수 프로브(2026-07-23): 제휴 채널 주문만 판매가×2% 추가 차감.
    이력 추정만으론 제휴 40건 미포착(+2%)·직영 1건 오포착(−2%)이 실측됐다."""
    assert oe._lo_channel_affiliate("100065") is True     # 제휴(네이버 등)
    assert oe._lo_channel_affiliate("100071") is True
    assert oe._lo_channel_affiliate("100195") is False    # 롯데ON 직영
    assert oe._lo_channel_affiliate("999999") is None     # 미지 → 이력 폴백
    assert oe._lo_channel_affiliate("") is None


def test_롯데온_제휴_정산공식_샵마인_검산():
    """실측 218674866(chNo=100065): slAmt 61,000·셀러할인 2,344·롯데할인 9,376·
    배송비 4,000 → compute_settlement(제휴)=53,374, 빌더 사후 −배송비 = 49,374 = 샵 M."""
    from lemouton.margin.lotteon_settlement import compute_settlement
    v = compute_settlement(61000, 4000, 4000, 2344, 9376, True)
    assert v - 4000 == 49374                              # M열(배송비 제외) = 샵마인
    v0 = compute_settlement(61000, 4000, 4000, 2344, 9376, False)
    assert v0 - v == round(61000 * 0.02)                  # 제휴 유무 차이 = 정확히 2%


def test_11번가_비묶음_bndlDlvSeq_0은_배송키가_아니다(monkeypatch):
    """라이브 실측(2026-07-23): 비묶음 주문도 bndlDlvSeq='0'(기본값)으로 온다 — '0'을
    배송키로 쓰면 서로 다른 주문 전부가 같은 키를 공유해 첫 행 빼고 배송비가 전부
    소거된다(배송준비중 23행 전멸 실측). '0'은 없음으로 보고 주문번호로 대체."""
    import shared.platforms.eleven11.orders as e11o

    od1 = dict(_E11_OD, bndlDlvSeq="0")
    od2 = dict(_E11_OD, ordNo="20260721086559882", bndlDlvSeq="0",
               ordPayAmt="37600", ordAmt="34600", stlPlnAmt="33003")

    def two(since, until, client=None):
        yield od1
        yield od2

    def none(since, until, client=None):
        return iter(())

    monkeypatch.setattr(e11o, "iter_preparing", two)
    for name in ("iter_orders", "iter_shipping", "iter_delivered", "iter_completed",
                 "iter_cancel", "iter_canceled", "iter_return", "iter_exchange"):
        monkeypatch.setattr(e11o, name, none)
    since = _dt.datetime(2026, 7, 20, tzinfo=KST)
    until = _dt.datetime(2026, 7, 22, tzinfo=KST)
    rows = oe.eleven11_order_rows(since, until, client=object(),
                                  include_settlement=False)
    fin = oe._finalize_rows(rows)
    assert [r["배송비"] for r in fin] == [3000, 3000]   # 서로 다른 주문 — 둘 다 유지
    assert fin[1]["정산예정금(배송비포함)"] == 33003     # N = stlPlnAmt 복원


def test_11번가_진짜_묶음배송은_한_번만(monkeypatch):
    """실 묶음(bndlDlvSeq 동일·0 아님)은 기존 규약대로 배송건당 1회만 계상."""
    import shared.platforms.eleven11.orders as e11o

    od1 = dict(_E11_OD, bndlDlvSeq="4506571")
    od2 = dict(_E11_OD, ordNo="20260721086559882", bndlDlvSeq="4506571")

    def two(since, until, client=None):
        yield od1
        yield od2

    def none(since, until, client=None):
        return iter(())

    monkeypatch.setattr(e11o, "iter_preparing", two)
    for name in ("iter_orders", "iter_shipping", "iter_delivered", "iter_completed",
                 "iter_cancel", "iter_canceled", "iter_return", "iter_exchange"):
        monkeypatch.setattr(e11o, name, none)
    since = _dt.datetime(2026, 7, 20, tzinfo=KST)
    until = _dt.datetime(2026, 7, 22, tzinfo=KST)
    fin = oe._finalize_rows(oe.eleven11_order_rows(since, until, client=object(),
                                                   include_settlement=False))
    assert [r["배송비"] for r in fin] == [3000, 0]     # 같은 묶음 — 1회만


# ── ESM 추정: 비율 분모 = 원금(단가×수량) — 옛 저장분 실결제 오염 회피 ────────────

def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from shared.db import Base
    import lemouton.markets.models_orders  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"]])
    return sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()


def test_ESM_추정은_원금기준_비율(monkeypatch):
    """실측(2026-07-23 G마켓 4471677631): 샵 M=원금×0.87 인데 우리 추정이 +3,041 —
    옛 저장분 실결제(쿠폰 할인후 BuyerPayAmt)와 새 규약(K=원금)이 섞여 비율 오염.
    단가×수량(원금)은 두 시절 모두 동일 → 분모를 원금으로 통일."""
    from lemouton.markets import line_uid as L
    from lemouton.markets import order_store as OS
    s = _sess()
    # 옛 저장분: 쿠폰 10,000 할인 주문 — 실결제 73,500, 원금 83,500, 실정산 72,645(=원금×0.87)
    OS.save([{L.FIELD: "gmarket|H1", "판매처": "G마켓", "오픈마켓주문번호": "H1",
              "주문일": "2026-07-01 10:00:00", "주문상태": "배송완료", "상품명": "코르테즈",
              "단가": 83500, "수량": 1, "실결제금액": 73500, "정산예정금액": 72645,
              "_settle_source": "real"}], session=s)
    row = {"판매처": "G마켓", "_kind": "order", "주문상태": "배송준비중",
           "단가": 40200, "수량": 1, "실결제금액": 40200,
           "정산예정금액": "", "오픈마켓주문번호": "N9"}
    oe.estimate_settle_from_history([row], "gmarket", session=s)
    assert row["정산예정금액"] == round(40200 * (72645 / 83500))   # 34974 = 샵 실측
    s.close()


# ── 11번가 초고속취소 자동복구 — 주문라인 없는 클레임을 by-no 재조회 ────────────

def test_주문라인_없는_11번가_클레임을_byno로_복구(monkeypatch):
    """실측(2026-07-23): 주문→취소완료가 20분 틱 사이에 끝나면 클레임 이벤트만 남고
    주문 라인이 없어 주문일이 비고 주문일 탭에서 통째 빠진다(5건). 자동 복구."""
    from lemouton.markets import order_ingest as OI
    from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine
    s = _sess()
    s.add(MarketClaimEvent(event_uid="e11|GAP1|c", market="eleven11",
                           order_no="GAP1", status="취소완료", row={}))
    s.add(MarketClaimEvent(event_uid="e11|OK1|c", market="eleven11",
                           order_no="OK1", status="취소완료", row={}))
    s.add(MarketOrderLine(line_uid="eleven11|OK1|1", market="eleven11",
                          order_no="OK1", order_date="2026-07-22 10:00:00", row={}))
    s.commit()
    called = {}

    def _fake_byno(nos, session=None):
        called["nos"] = list(nos)
        return {"orders_new": 1, "orders_updated": 0}

    monkeypatch.setattr(OI, "ingest_eleven11_orders_by_no", _fake_byno)
    st = OI.restore_eleven11_claim_gaps(session=s)
    assert called["nos"] == ["GAP1"]           # 라인 있는 OK1 은 재조회 안 함
    assert st["targets"] == 1
    s.close()


def test_복구대상_없으면_byno_호출_안함(monkeypatch):
    from lemouton.markets import order_ingest as OI
    s = _sess()
    monkeypatch.setattr(OI, "ingest_eleven11_orders_by_no",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("호출 금지")))
    st = OI.restore_eleven11_claim_gaps(session=s)
    assert st == {"targets": 0, "restored": 0}
    s.close()


def test_ESM_추정_시장비율은_최빈값(monkeypatch):
    """G마켓 실정산율은 0.87(수수료 13%)에 강하게 몰린다 — 반품·부분환불이 섞인
    이력의 중앙값(라이브 실측 0.85 오염)이 아니라 최빈 구간을 쓴다(샵마인=0.87 일치)."""
    from lemouton.markets import line_uid as L
    from lemouton.markets import order_store as OS
    s = _sess()
    hist = []
    for i, (amt, settle) in enumerate([(100000, 87000), (50000, 43500),
                                       (100000, 70000), (100000, 72000),
                                       (100000, 74000)]):  # 0.87×2 + 서로 다른 오염 3(중앙값=0.74)
        hist.append({L.FIELD: f"gmarket|M{i}", "판매처": "G마켓", "오픈마켓주문번호": f"M{i}",
                     "주문일": "2026-07-01 10:00:00", "주문상태": "배송완료", "상품명": "x",
                     "단가": amt, "수량": 1, "실결제금액": amt, "정산예정금액": settle,
                     "_settle_source": "real"})
    OS.save(hist, session=s)
    row = {"판매처": "G마켓", "_kind": "order", "주문상태": "배송준비중",
           "단가": 40200, "수량": 1, "실결제금액": 40200,
           "정산예정금액": "", "오픈마켓주문번호": "N10"}
    oe.estimate_settle_from_history([row], "gmarket", session=s)
    assert row["정산예정금액"] == round(40200 * 0.87)   # 34974 — 최빈 0.87(중앙값이면 34,974≠)
    s.close()


def test_ESM_추정은_상품별_실정산율이_시장율보다_우선(monkeypatch):
    """라이브 실측(2026-07-23 저장분 271행): G마켓 계약율은 카테고리별로 다르다 —
    나이키·LEE 0.87(13%) / 잔스포츠·아이더 0.85(15%). 같은 상품의 과거 실정산율이
    가장 정확한 예측이므로 pid 이력(0.85 카테고리)이 시장 최빈(0.87)을 이긴다."""
    from lemouton.markets import line_uid as L
    from lemouton.markets import order_store as OS
    s = _sess()
    rows = [{L.FIELD: "gmarket|P1", "판매처": "G마켓", "오픈마켓주문번호": "P1",
             "주문일": "2026-07-01 10:00:00", "주문상태": "배송완료", "상품명": "x",
             "_pd_market_product_id": "PD-A", "단가": 100000, "수량": 1,
             "실결제금액": 100000, "정산예정금액": 85000, "_settle_source": "real"}]
    for i, amt in enumerate((87000, 43500)):
        rows.append({L.FIELD: f"gmarket|Q{i}", "판매처": "G마켓", "오픈마켓주문번호": f"Q{i}",
                     "주문일": "2026-07-01 10:00:00", "주문상태": "배송완료", "상품명": "y",
                     "단가": amt * 100 // 87, "수량": 1, "실결제금액": amt * 100 // 87,
                     "정산예정금액": amt, "_settle_source": "real"})
    OS.save(rows, session=s)
    row = {"판매처": "G마켓", "_kind": "order", "주문상태": "배송준비중",
           "_pd_market_product_id": "PD-A", "단가": 40200, "수량": 1,
           "실결제금액": 40200, "정산예정금액": "", "오픈마켓주문번호": "N11"}
    oe.estimate_settle_from_history([row], "gmarket", session=s)
    assert row["정산예정금액"] == round(40200 * 0.85)   # pid 실율 0.85(15% 카테고리) 우선
    s.close()


# ── 11번가 낡은 정산 스냅샷 자동 갱신 — 배송중·배송완료·구매확정 by-no 재조회 ────

def test_낡은_11번가_배송완료_스냅샷을_byno로_갱신(monkeypatch):
    """11번가는 배송 후에도 정산예정금(stlPlnAmt)을 갱신한다(T-쿠폰 등 — 샵마인 대조
    실측 ±610~1,347). 배송완료 조회는 stlPlnAmt 미제공이라 저장분 스냅샷이 정본인데,
    낡으면 그대로 틀린다 → 오래 안 본 순으로 by-no 재조회."""
    import datetime as dt
    from lemouton.markets import order_ingest as OI
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    old = dt.datetime.utcnow() - dt.timedelta(hours=30)
    s.add(MarketOrderLine(line_uid="eleven11|STALE1|1", market="eleven11",
                          order_no="STALE1", order_date="2026-07-20 10:00:00",
                          status="배송완료", row={}, last_seen_at=old))
    s.add(MarketOrderLine(line_uid="eleven11|FRESH1|1", market="eleven11",
                          order_no="FRESH1", order_date="2026-07-20 11:00:00",
                          status="배송완료", row={},
                          last_seen_at=dt.datetime.utcnow()))
    s.add(MarketOrderLine(line_uid="eleven11|PREP1|1", market="eleven11",
                          order_no="PREP1", order_date="2026-07-20 12:00:00",
                          status="배송준비중", row={}, last_seen_at=old))
    s.commit()
    called = {}

    def _fake_byno(nos, session=None):
        called["nos"] = list(nos)
        return {"orders_new": 0, "orders_updated": len(nos)}

    monkeypatch.setattr(OI, "ingest_eleven11_orders_by_no", _fake_byno)
    st = OI.refresh_eleven11_stale_settles(session=s)
    assert called["nos"] == ["STALE1"]     # 최근 본 것(FRESH1)·준비중(목록조회가 갱신)은 제외
    assert st == {"targets": 1, "refreshed": 1}
    s.close()


def test_갱신대상_없으면_byno_호출_안함(monkeypatch):
    from lemouton.markets import order_ingest as OI
    s = _sess()
    monkeypatch.setattr(OI, "ingest_eleven11_orders_by_no",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("호출 금지")))
    st = OI.refresh_eleven11_stale_settles(session=s)
    assert st == {"targets": 0, "refreshed": 0}
    s.close()


# ── 저장분 주문번호 채움: 옵션이 다른 라인의 금액을 붙이지 않는다 ────────────────

def test_옵션이_다른_저장분_라인의_금액은_채우지_않는다():
    """실측(2026-07-23 쿠팡 769047062): 클레임 옵션(409567)과 저장분 라인 옵션(436563)이
    다른데 주문번호 채움이 그 라인의 단가 39,000을 붙임(실제 39,900 — 샵마인 대조 발견).
    옵션 텍스트가 서로 다르면 금액류(단가·실결제·옵션추가금)는 안 붙인다. 주문 단위
    정보(구매자·주소·주문일 등)는 어느 라인이든 같으므로 계속 채운다."""
    from lemouton.markets import line_uid as L
    from lemouton.markets import order_store as OS
    from lemouton.markets import order_export as oe2
    s = _sess()
    OS.save([{L.FIELD: "coupang|BOX1|V436563", "판매처": "쿠팡", "오픈마켓주문번호": "O-MIX",
              "주문일": "2026-07-21 10:00:00", "주문상태": "상품준비중",
              "상품명": "나이키 미니 슈박스", "옵션": "FN3059-323 436563, FREE",
              "단가": 39000, "실결제금액": 39000, "구매자": "김구매",
              "주소": "서울"}], session=s)
    claim = {"판매처": "쿠팡", "오픈마켓주문번호": "O-MIX", "_kind": "change",
             "주문상태": "반품완료", "상품명": "", "옵션": "FN3059-323 409567, FREE",
             "단가": "", "실결제금액": "", "구매자": "", "주소": ""}
    oe2.fill_claim_blanks_from_history([claim], "coupang", session=s)
    assert claim["단가"] == ""              # 다른 옵션 라인 금액 — 안 붙인다
    assert claim["실결제금액"] == ""
    assert claim["구매자"] == "김구매"       # 주문 단위 정보는 채운다
    assert claim["주소"] == "서울"
    s.close()


def test_옵션이_같으면_저장분_금액을_채운다():
    from lemouton.markets import line_uid as L
    from lemouton.markets import order_store as OS
    from lemouton.markets import order_export as oe2
    s = _sess()
    OS.save([{L.FIELD: "coupang|BOX2|V1", "판매처": "쿠팡", "오픈마켓주문번호": "O-SAME",
              "주문일": "2026-07-21 10:00:00", "주문상태": "상품준비중",
              "상품명": "나이키 미니 슈박스", "옵션": "FN3059-323 409567, FREE",
              "단가": 39900, "실결제금액": 39900}], session=s)
    claim = {"판매처": "쿠팡", "오픈마켓주문번호": "O-SAME", "_kind": "change",
             "주문상태": "반품완료", "상품명": "", "옵션": "FN3059-323 409567, FREE",
             "단가": "", "실결제금액": ""}
    oe2.fill_claim_blanks_from_history([claim], "coupang", session=s)
    assert claim["단가"] == 39900


def test_11번가_적용할인이_표기보다_크면_그만큼_뺀다(monkeypatch):
    """실측(2026-07-23 재대조, 7건 전부 +159 균일): 적용할인 > 표기할인인 주문이 있다.
    max(0,…) 하한을 두면 그 차이를 못 빼 K가 그만큼 과대해진다.
    086115548 검산: ordAmt 23,300 − 적용 2,669 = 20,631(샵) = ordPayAmt 23,790 − 배송비
    3,000 + (표기 2,510 − 적용 2,669)."""
    od = dict(_E11_OD, ordNo="20260719086115548", ordAmt="23300", selPrc="23300",
              ordPayAmt="23790", dlvCst="3000", stlPlnAmt="23966",
              tmallDscPrcPerSeq="2510", tmallApplyDscAmt="2669")
    r = _e11_rows(monkeypatch, od)[0]
    assert r["실결제금액"] == 23790 - 3000 + (2510 - 2669)   # 20631 = 샵마인
