# -*- coding: utf-8 -*-
"""쿠팡 지급내역조회(settlement-histories) — 「입금됐나」를 실제로 아는 유일한 창구.

🔴 왜 필요한가(2026-08-06 라이브 실측) — revenue-history 는 `settlementDate` 가 안 오고
   (1,820행에 0건), ESM 은 날짜가 전부 null 이다. 그래서 「받을 날이 지났는데 입금 확인 불가」
   가 8,066만 쌓였고 그중 쿠팡이 6,158만(76%)이었다. 이 API 는 정산 **회차**마다
   status(DONE 지급완료 / SUBJECT 지급예정)와 지급일을 준다.

★ 이 API 는 **주문 단위가 아니라 정산 회차 단위**다. 조인은 매출인식일로 한다:
   회차의 [revenueRecognitionDateFrom, To] 안에 주문의 recognitionDate 가 들어가면 그 회차 몫.
★ 주정산은 70%(WEEKLY) + 30%(RESERVE) 두 회차로 나뉜다 — 같은 구간에 둘 다 있을 수 있고
   앞은 DONE·뒤는 SUBJECT 인 상태가 정상이다.
"""
from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import line_uid as L
from lemouton.markets import order_ingest as OI
from lemouton.markets import order_store as OS

KST = _dt.timezone(_dt.timedelta(hours=9))


@pytest.fixture
def session():
    import lemouton.markets.models_orders  # noqa: F401
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


_HIST = [
    {"settlementType": "WEEKLY", "settlementDate": "2026-07-20", "status": "DONE",
     "revenueRecognitionDateFrom": "2026-07-06", "revenueRecognitionDateTo": "2026-07-12",
     "finalAmount": 1000000},
    {"settlementType": "RESERVE", "settlementDate": "2026-08-18", "status": "SUBJECT",
     "revenueRecognitionDateFrom": "2026-07-06", "revenueRecognitionDateTo": "2026-07-12",
     "finalAmount": 400000},
    {"settlementType": "MONTHLY", "settlementDate": "2026-08-15", "status": "SUBJECT",
     "revenueRecognitionDateFrom": "2026-07-13", "revenueRecognitionDateTo": "2026-07-19",
     "finalAmount": 900000},
]


class _Client:
    _cfg = {"vendor_id": "A1"}

    def __init__(self, rows=None):
        self.calls = []
        self.rows = _HIST if rows is None else rows

    def request(self, method, path, query=""):
        self.calls.append(query)
        return {"data": list(self.rows)}


# ── 파서 ──────────────────────────────────────────────────────────────────────

def test_회차_목록을_읽어_인식일_구간과_지급상태를_돌려준다():
    from shared.platforms.coupang import settlements as cs
    cli = _Client()
    out = cs.fetch_settlement_histories("2026-07", client=cli)
    assert len(out) == 3
    assert out[0]["status"] == "DONE"
    assert out[0]["settlementDate"] == "2026-07-20"
    assert out[0]["from"] == "2026-07-06" and out[0]["to"] == "2026-07-12"
    assert "revenueRecognitionYearMonth=2026-07" in cli.calls[0]


def test_인식일로_회차를_찾는다_지급완료와_예정이_갈린다():
    from shared.platforms.coupang import settlements as cs
    hist = cs.fetch_settlement_histories("2026-07", client=_Client())
    got = cs.match_by_recognition_date(hist, "2026-07-08")
    assert got["paid_date"] == "2026-07-20"        # DONE 회차 = 실제 받은 날
    assert got["expect_date"] == "2026-08-18"      # 남은 SUBJECT 회차 = 앞으로 받을 날
    got2 = cs.match_by_recognition_date(hist, "2026-07-15")
    assert got2["paid_date"] is None               # 아직 지급 완료 회차 없음
    assert got2["expect_date"] == "2026-08-15"


def test_구간_밖_인식일은_아무것도_안_준다():
    from shared.platforms.coupang import settlements as cs
    hist = cs.fetch_settlement_histories("2026-07", client=_Client())
    assert cs.match_by_recognition_date(hist, "2026-06-01") == {
        "paid_date": None, "expect_date": None}
    assert cs.match_by_recognition_date(hist, "") == {
        "paid_date": None, "expect_date": None}


def test_날짜_형식이_깨진_회차는_건너뛴다():
    from shared.platforms.coupang import settlements as cs
    cli = _Client([{"settlementType": "WEEKLY", "settlementDate": "", "status": "DONE",
                    "revenueRecognitionDateFrom": "", "revenueRecognitionDateTo": "",
                    "finalAmount": 1}])
    assert cs.fetch_settlement_histories("2026-07", client=cli) == []


# ── 인식일 수집 ───────────────────────────────────────────────────────────────

def test_revenue_map_이_매출인식일도_담는다():
    """지급내역과 조인하려면 주문의 인식일이 필요하다(예전엔 안 담았다)."""
    from lemouton.markets import order_export as oe

    class C:
        _cfg = {"vendor_id": "A1"}

        def request(self, method, path, query=""):
            if "revenue-history" in path and "token=&" in query:
                return {"data": [{"orderId": 7, "saleType": "SALE",
                                  "recognitionDate": "2026-07-08",
                                  "items": [{"vendorItemId": 9,
                                             "settlementAmount": 88450}]}],
                        "hasNext": False}
            return {"data": [], "hasNext": False}

    _imap, _deliv, dates = oe._coupang_settle_map(
        _dt.datetime(2026, 7, 5, tzinfo=OI.KST),
        _dt.datetime(2026, 7, 8, tzinfo=OI.KST), C())
    assert dates["7"]["_recognition_date"] == "2026-07-08"


# ── 스윕 저장 ─────────────────────────────────────────────────────────────────

def _cp_row(ono="7", vid="9", **kw):
    row = {L.FIELD: f"coupang|{ono}|{vid}", "판매처": "쿠팡", "쇼핑몰": "쿠팡",
           "오픈마켓주문번호": ono, "_pd_market_option_id": vid,
           "주문일": (_dt.datetime.now(KST) - _dt.timedelta(days=30)
                    ).strftime("%Y-%m-%d %H:%M:%S"),
           "주문상태": "구매확정", "상품명": "코트", "단가": 100000, "수량": 1,
           "실결제금액": 100000, "배송비": 0,
           "정산예정금액": 88450, "_settle_source": "real"}
    row.update(kw)
    return row


def _patch_coupang(monkeypatch, date_map, hist=None):
    monkeypatch.setattr(OI, "_esm_settlement_clients",
                        lambda market: [("계정A", _Client())])
    from lemouton.markets import order_export as oe
    monkeypatch.setattr(oe, "_coupang_settle_map",
                        lambda since, until, cli: ({("7", "9"): 88450}, {}, date_map))
    from shared.platforms.coupang import settlements as cs
    monkeypatch.setattr(cs, "fetch_settlement_histories",
                        lambda ym, client=None: (hist if hist is not None else []))


def test_스윕이_지급완료일과_지급예정일을_저장한다(session, monkeypatch):
    from shared.platforms.coupang import settlements as cs
    OS.save([_cp_row()], session=session)
    _patch_coupang(monkeypatch, {"7": {"_recognition_date": "2026-07-08"}},
                   hist=cs.fetch_settlement_histories("2026-07", client=_Client()))

    stat = OI.refresh_settlement_coupang(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_paid_date"] == "2026-07-20"   # 실제 받은 날
    assert stored["정산예정일"] == "2026-08-18"           # 남은 몫 받을 날
    assert str(stored["정산예정금액"]) == "88450"          # 금액 불가침


def test_지급내역이_없으면_아무것도_안_쓴다(session, monkeypatch):
    """조회 실패·빈 응답을 「지급 안 됨」으로 단정하지 않는다(폴백 금지)."""
    OS.save([_cp_row()], session=session)
    _patch_coupang(monkeypatch, {"7": {"_recognition_date": "2026-07-08"}}, hist=[])

    stat = OI.refresh_settlement_coupang(session=session)
    stored = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert not stored.get("_settle_paid_date")
    assert stat["updated"] == 0


# ══ [2026-08-06 라이브 실측 교정] 응답이 배열로 온다 ═══════════════════════════
#  라이브 첫 실행에서 8계정 전부 AttributeError: 'list' object has no attribute 'get'.
#  문서는 {"data":[...]} 처럼 보이지만 실제로는 **배열이 그대로** 온다.

class _ListClient(_Client):
    def request(self, method, path, query=""):
        self.calls.append(query)
        return list(self.rows)          # dict 로 감싸지 않고 배열 그대로


def test_응답이_배열이어도_읽는다():
    from shared.platforms.coupang import settlements as cs
    out = cs.fetch_settlement_histories("2026-07", client=_ListClient())
    assert len(out) == 3
    assert out[0]["status"] == "DONE"


def test_응답이_None_이면_빈_목록():
    from shared.platforms.coupang import settlements as cs

    class _NoneClient(_Client):
        def request(self, method, path, query=""):
            return None
    assert cs.fetch_settlement_histories("2026-07", client=_NoneClient()) == []


# ══ [2026-08-06 Wing 화면 실측] 회차는 finalAmount 하나가 아니다 ═══════════════
#  사장님이 Wing 「정산 현황」 상세를 열어 보내주셔서 드러난 것:
#   ─ 우리 화면이 계산한 6월 세소 몫 11,131,180 ≈ 쿠팡 정산대상액 11,081,786 (0.44% 차)
#     → **우리 금액은 맞았다.**
#   ─ 그런데 통장 입금액(finalAmount)은 300,756 뿐이었다. 861만이 사라진 게 아니라
#     **빠른정산으로 7/14 에 미리 인출(9,146,923)** 해서 회차에서 공제된 것이다.
#  ⇒ 대조 상대는 finalAmount 가 아니라 **settlementTargetAmount** 이고,
#    빠른정산 선인출액은 **deductionAmount 에서 역산**해야 한다.
_RESERVE_LIVE = {
    "settlementType": "RESERVE", "status": "DONE", "settlementDate": "2026-08-03",
    "revenueRecognitionDateFrom": "2026-06-01", "revenueRecognitionDateTo": "2026-06-30",
    "totalSale": 12723010,            # 판매액(a)
    "settlementTargetAmount": 11081786,  # 정산대상액 (A-B=C) ★ 우리가 대조할 상대
    "settlementAmount": 3324536,      # 지급액(D) = 대상액의 30%
    "pendingReleasedAmount": 0,       # 보류액(E)
    "deductionAmount": 3023780,       # 공제금액(F) 소계
    "sellerServiceFee": 107154,       # ㄴ 판매자서비스이용료
    "dedicatedDeliveryAmount": 0, "debtOfLastWeek": 0,
    "couranteeFee": 0, "sellerDiscountCoupon": 0,
    "finalAmount": 300756,            # 최종지급액 (D+E-F) = 통장 입금액
}


def test_회차가_정산대상액과_공제내역까지_담는다():
    from shared.platforms.coupang import settlements as cs
    h = cs.fetch_settlement_histories("2026-06", client=_Client([_RESERVE_LIVE]))[0]
    assert h["targetAmount"] == 11081786      # 우리 계산과 맞대볼 진짜 숫자
    assert h["settlementAmount"] == 3324536
    assert h["deductionAmount"] == 3023780
    assert h["finalAmount"] == 300756


def test_빠른정산_선인출액을_공제금액에서_역산한다():
    """공제금액 = 빠른정산 계좌인출액 + 알려진 항목들 → 나머지가 선인출액."""
    from shared.platforms.coupang import settlements as cs
    h = cs.fetch_settlement_histories("2026-06", client=_Client([_RESERVE_LIVE]))[0]
    assert h["fastWithdrawn"] == 2916626       # 3,023,780 − 107,154 (Wing 화면과 일치)


def test_공제항목이_다_알려진_것이면_선인출액은_0():
    from shared.platforms.coupang import settlements as cs
    row = dict(_RESERVE_LIVE, deductionAmount=107154)
    h = cs.fetch_settlement_histories("2026-06", client=_Client([row]))[0]
    assert h["fastWithdrawn"] == 0             # 음수로 흘리지 않는다


def test_최종지급액_항등식이_맞는지_스스로_검산한다():
    """지급액 + 보류액 − 공제액 = 최종지급액. 어긋나면 필드 해석이 틀린 것."""
    from shared.platforms.coupang import settlements as cs
    h = cs.fetch_settlement_histories("2026-06", client=_Client([_RESERVE_LIVE]))[0]
    assert h["항등식맞음"] is True
    bad = dict(_RESERVE_LIVE, finalAmount=999)
    assert cs.fetch_settlement_histories(
        "2026-06", client=_Client([bad]))[0]["항등식맞음"] is False


def test_금액_필드가_없는_옛_응답도_깨지지_않는다():
    from shared.platforms.coupang import settlements as cs
    h = cs.fetch_settlement_histories("2026-07", client=_Client())[0]
    assert h["targetAmount"] is None            # 없으면 None (0 으로 지어내지 않는다)
    assert h["fastWithdrawn"] == 0
    assert h["finalAmount"] == 1000000
