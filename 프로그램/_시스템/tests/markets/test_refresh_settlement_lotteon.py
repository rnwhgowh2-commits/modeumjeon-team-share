# -*- coding: utf-8 -*-
"""롯데온 정산 스윕 — 구매확정 뒤에 인식되는 실정산을 옛 주문까지 되짚는다.

🔴 왜 롯데온도 따로인가 — 정산 스윕이 없어 적재틱(7~21일)이 닫힌 뒤 구매확정된
  주문의 실정산(SettleItmdSales.pymtAmt)이 영영 안 들어와 추정치로 고착됐다
  (옥션·G마켓·쿠팡이 이미 닫은 그 갭).

★ 조인 키 = odNo 단일(쿠팡의 (주문번호,옵션ID) 복합키와 다름 — 인라인 조인과 동형).
★ 창은 구매확정일(정산기준일) 기준이라 '지금'에서 뒤로 잡는다(주문일 창 아님).
★ rate 버킷이 계정별이라 계정 병렬이 안전(11번가·스스의 IP전역과 다름).
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
    import lemouton.markets.models_orders  # noqa: F401  — 테이블 등록
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _order_date(days_ago: int) -> str:
    return (_dt.datetime.now(KST) - _dt.timedelta(days=days_ago)
            ).strftime("%Y-%m-%d %H:%M:%S")


def _row(uid="lotteon|LO500|1", ono="LO500", days_ago=40, seq="1", **kw):
    """days_ago 기본 40 — 스윕이 '주문일 창'으로 좁히지 않음을 보이려 일부러 오래된 주문."""
    row = {L.FIELD: uid, "판매처": "롯데온", "쇼핑몰": "롯데온",
           "오픈마켓주문번호": ono, "_send_ids": {"od_seq": seq},   # 라인(벌) 조인 키
           "주문일": _order_date(days_ago), "주문상태": "구매확정",
           "상품명": "테스트 상품", "단가": 30000, "수량": 1,
           "실결제금액": 30000, "배송비": 0,
           "정산예정금액": 27000, "_settle_source": "estimated"}
    row.update(kw)
    return row


def _patch(monkeypatch, order_map, clients=(("메인", object()),), calls=None):
    """order_map = {odNo: pymtAmt} 또는 {(odNo,odSeq): pymtAmt}.

    스윕은 itmd_line_map((odNo,odSeq)→pymtAmt) 로 조인한다(다품 2배 방지). odNo 만 준 항목은
    단일라인(odSeq="1") 으로 감싼다 — 기존 단일라인 테스트 하위호환.
    """
    monkeypatch.setattr(OI, "_esm_settlement_clients", lambda market: list(clients))
    from shared.platforms.lotteon import settlement as _lo

    def _fake_line(since, until, *, client=None, **_kw):
        if calls is not None:
            calls.append((since.date(), until.date(), client))
        out = {}
        for k, v in order_map.items():
            key = k if isinstance(k, tuple) else (k, "1")
            out[key] = v
        return out
    monkeypatch.setattr(_lo, "itmd_line_map", _fake_line)


def test_옛_주문도_구매확정창이_덮으면_실정산으로_갱신(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch(monkeypatch, {"LO500": 26500})

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "26500"
    assert stored["_settle_source"] == "real"
    # 파생열(배송비포함)도 함께 갱신 — 마진계산기가 읽는 칸이 옛값으로 남지 않게.
    assert str(stored["정산예정금(배송비포함)"]) == "26500"


def test_유료배송_주문은_배송비포함이_pymtAmt와_같다_과대금지(session, monkeypatch):
    """🔴 pymtAmt 는 배송비 포함액. 저장 정산예정금액은 상품분(−배송비)이라야
      _finalize 가 +배송비로 배송비포함 = pymtAmt 를 복원한다. raw pymtAmt 를 넣으면
      배송비포함 = pymtAmt+배송비 로 유료배송 주문마다 마진이 배송비만큼 과대해진다."""
    OS.save([_row(배송비=3000)], session=session)
    _patch(monkeypatch, {"LO500": 30000})            # pymtAmt(배송비 포함)

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    # 마진계산기가 읽는 칸(배송비포함)이 pymtAmt 와 정확히 같아야 한다(과대 없음).
    assert str(stored["정산예정금(배송비포함)"]) == "30000"
    # 정산예정금액(상품분)은 배송비를 뺀 값.
    assert str(stored["정산예정금액"]) == "27000"


def test_전액할인_0원_정산도_실정산으로_확정(session, monkeypatch):
    """pymtAmt=0(100% 쿠폰/전액할인 구매확정)은 미정산이 아니라 실정산 0 —
      건너뛰면 추정치(27000)로 고착돼 과대. 인라인(if hit)·ESM/쿠팡과 같이 수용."""
    OS.save([_row()], session=session)
    _patch(monkeypatch, {"LO500": 0})

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_source"] == "real"
    assert str(stored["정산예정금(배송비포함)"]) == "0"


def test_0원정산_유료배송_엣지는_인라인과_동일하게_배송비_안뺀다(session, monkeypatch):
    """pymtAmt=0·배송비>0 엣지 — _lo_subtract_shipping_once 가드(0<ship≤st)로 st=0 이면
      안 뺀다. 인라인과 동일: 정산예정금액=0(음수 K 방지), 배송비포함=배송비."""
    OS.save([_row(배송비=3000)], session=session)
    _patch(monkeypatch, {"LO500": 0})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "0"            # 음수로 안 떨어진다
    assert str(stored["정산예정금(배송비포함)"]) == "3000"


def test_이미_실정산인_행은_건드리지_않는다(session, monkeypatch):
    OS.save([_row(정산예정금액=26500, _settle_source="real")], session=session)
    _patch(monkeypatch, {"LO500": 11111})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "26500"


def test_정산조회에_없는_주문은_그대로_둔다(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch(monkeypatch, {"OTHER": 50000})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "27000"
    assert stored["_settle_source"] == "estimated"


def test_클레임_행은_건드리지_않는다(session, monkeypatch):
    OS.save([_row(주문상태="반품완료", _kind="change", _change_date="2026-07-10")],
            session=session)
    _patch(monkeypatch, {"LO500": 26500})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 0


def test_구매확정_창은_주문일과_무관하게_최근이다(session, monkeypatch):
    """조회 창은 정산기준일(구매확정일) 기준이라 '지금'에서 뒤로 잡힌다(주문일 40일 전과 무관)."""
    OS.save([_row(days_ago=40)], session=session)
    calls = []
    _patch(monkeypatch, {"LO500": 26500}, calls=calls)

    OI.refresh_settlement_lotteon(session=session)

    assert calls, "정산조회가 호출돼야 한다"
    since, until, _ = calls[0]
    today = _dt.datetime.now(KST).date()
    assert (today - since).days <= OI.LOTTEON_SETTLE_SWEEP_DAYS + 1
    assert (today - until).days <= OI.LOTTEON_SETTLE_SWEEP_SKIP_DAYS + 1


def test_다계정_정산이_합쳐진다(session, monkeypatch):
    """서로 다른 계정의 정산맵이 합쳐져 각자 주문을 갱신한다(대표계정만 물으면 누락)."""
    OS.save([_row(uid="lotteon|LO500|1", ono="LO500"),
             _row(uid="lotteon|LO900|1", ono="LO900")], session=session)

    monkeypatch.setattr(OI, "_esm_settlement_clients",
                        lambda market: [("A", object()), ("B", object())])
    from shared.platforms.lotteon import settlement as _lo
    by_client = {}

    def _fake_line(since, until, *, client=None, **_kw):
        # 계정 A 는 LO500 만, 계정 B 는 LO900 만 안다. (odNo,odSeq) 라인맵 반환.
        idx = len(by_client)
        by_client[id(client)] = idx
        return {("LO500", "1"): 26500} if idx == 0 else {("LO900", "1"): 31000}
    monkeypatch.setattr(_lo, "itmd_line_map", _fake_line)

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 2


def test_이미real_배송비_이중가산은_교정한다(session, monkeypatch):
    """🔴 #477 이전 저장된 real 행 — 배송비가 상품분에서 안 빠져 '배송비포함'이
      pymtAmt+배송비 로 굳음(2026-07-25 정답지 실측 42건). 스윕이 교정해야 한다.

    라이브 실측 2026070413404406: pymtAmt=41,265(=정답지) 인데 저장 배송비포함=45,265.
    """
    OS.save([_row(정산예정금액=41265, 배송비=4000, _settle_source="real",
                  ono="LO477")], session=session)
    # 저장된 배송비포함을 옛 버그 상태(pymtAmt+배송비=45,265)로 만든다.
    from lemouton.markets.models_orders import MarketOrderLine
    o = session.query(MarketOrderLine).filter_by(market="lotteon").first()
    r = dict(o.row); r["정산예정금(배송비포함)"] = 45265; o.row = r
    session.commit()

    _patch(monkeypatch, {"LO477": 41265})            # 크롤 실정산(배송비 포함)
    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금(배송비포함)"]) == "41265"   # 이중가산 제거
    assert str(stored["정산예정금액"]) == "37265"            # 상품분(−배송비)


def test_이미real_이중가산_교정은_멱등(session, monkeypatch):
    """교정 뒤 배송비포함==amt 라 서명이 안 맞아 다시 안 건드린다(이중차감 금지)."""
    OS.save([_row(정산예정금액=41265, 배송비=4000, _settle_source="real",
                  ono="LO477")], session=session)
    from lemouton.markets.models_orders import MarketOrderLine
    o = session.query(MarketOrderLine).filter_by(market="lotteon").first()
    r = dict(o.row); r["정산예정금(배송비포함)"] = 45265; o.row = r
    session.commit()
    _patch(monkeypatch, {"LO477": 41265})

    OI.refresh_settlement_lotteon(session=session)       # 1회차 교정
    stat2 = OI.refresh_settlement_lotteon(session=session)  # 2회차

    assert stat2["updated"] == 0                          # 두 번째는 건드리지 않음
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금(배송비포함)"]) == "41265"   # 33,265 로 안 떨어짐


def test_이미real_정상건은_재동기화_안한다(session, monkeypatch):
    """이중가산 서명이 아니면(배송비포함==amt) 정산 재조회 값이 달라도 확정 real 을 덮지 않는다."""
    OS.save([_row(정산예정금액=26500, 배송비=0, _settle_source="real")],
            session=session)
    _patch(monkeypatch, {"LO500": 11111})                # transient/다른 값
    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["updated"] == 0
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "26500"           # 확정 real 안 덮음


def test_이미real_경계일_정산2배도_교정한다(session, monkeypatch):
    """🔴 itmd_map 경계일 중복으로 pymtAmt 가 2배로 굳은 real 행(2026-07-25 실측 5건
      단일라인). settlement.py 경계 dedup 뒤 itmd 는 바른 값을 주므로, 저장 배송비포함이
      정확히 2×pymtAmt 면 되돌린다. 배송비 0 이라 배송비 서명엔 안 걸린다."""
    OS.save([_row(정산예정금액=101322, 배송비=0, _settle_source="real",
                  ono="LO2X")], session=session)
    from lemouton.markets.models_orders import MarketOrderLine
    o = session.query(MarketOrderLine).filter_by(market="lotteon").first()
    r = dict(o.row); r["정산예정금(배송비포함)"] = 202644; o.row = r   # 2배로 굳음
    session.commit()
    _patch(monkeypatch, {"LO2X": 101322})            # dedup 뒤 바른 pymtAmt

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금(배송비포함)"]) == "101322"   # 2배 제거


def test_이미real_경계2배_교정은_멱등(session, monkeypatch):
    OS.save([_row(정산예정금액=101322, 배송비=0, _settle_source="real",
                  ono="LO2X")], session=session)
    from lemouton.markets.models_orders import MarketOrderLine
    o = session.query(MarketOrderLine).filter_by(market="lotteon").first()
    r = dict(o.row); r["정산예정금(배송비포함)"] = 202644; o.row = r
    session.commit()
    _patch(monkeypatch, {"LO2X": 101322})

    OI.refresh_settlement_lotteon(session=session)
    stat2 = OI.refresh_settlement_lotteon(session=session)

    assert stat2["updated"] == 0                      # 두 번째는 서명 불일치 → 안 건드림
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금(배송비포함)"]) == "101322"   # 50,661 로 안 떨어짐


def test_다품_벌별_정산으로_2배_교정(session, monkeypatch):
    """🔴 다품(2벌) 주문 — itmd odNo 총액을 라인마다 대입해 저장 N=2×(2026-07-25 실측
      2026070213054145). 스윕이 벌(odNo,odSeq)별 pymtAmt 로 재도출해 2배를 교정한다.

    네이버 정산: 벌1=벌2=41,624. 저장분은 각 라인 배송비포함=83,248(=2×41,624).
    """
    OS.save([_row(uid="lotteon|MULTI|1", ono="MULTI", seq="1", _settle_source="real"),
             _row(uid="lotteon|MULTI|2", ono="MULTI", seq="2", _settle_source="real")],
            session=session)
    from lemouton.markets.models_orders import MarketOrderLine
    for o in session.query(MarketOrderLine).filter_by(market="lotteon").all():
        r = dict(o.row); r["정산예정금(배송비포함)"] = 83248; o.row = r   # 2배로 굳음
    session.commit()

    # 벌별 정산: (MULTI,1)=41,624 · (MULTI,2)=41,624
    _patch(monkeypatch, {("MULTI", "1"): 41624, ("MULTI", "2"): 41624})
    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["updated"] == 2
    rows = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01", session=session)
    for r in rows:
        assert str(r["정산예정금(배송비포함)"]) == "41624"   # 각 벌 실값(2배 제거)


def test_다품_odSeq불명_옛행은_폴백안함(session, monkeypatch):
    """odSeq 없는 옛 다품 행은 단일라인 폴백을 안 한다(엉뚱한 벌값 대입 방지)."""
    OS.save([_row(uid="lotteon|OLD|1", ono="OLD", seq="", _settle_source="estimated")],
            session=session)  # seq 공란
    _patch(monkeypatch, {("OLD", "1"): 40000, ("OLD", "2"): 30000})  # 다품(2벌)
    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 0                                       # 폴백 안 함 → 미갱신


# ══════════════════════════════════════════════════════════════════════════
# [2026-08-02] 원천 ② 셀러오피스 크롤(lotteon_settlements)
#
# 🔴🔴 왜 추가됐나 — 크롤이 통째로 헛돌고 있었다.
#   확장이 크롤로 정산예정금을 모아 lotteon_settlements 에 쌓는데, 그 표를 읽는
#   코드가 order_export.lotteon_order_rows **한 곳뿐**이었다(= 롯데온을 라이브로
#   조회할 때만). 저장분에 밀어넣는 경로가 없어 라이브 창(21일) 밖은 영영 안 붙었다.
#   라이브 실측: 깊은 회차로 크롤표를 1,598→2,121건(양수 228→373) 늘렸는데
#   저장분 실정산율은 49.3% → 49.3% 로 **한 톨도 안 올랐다**.
#   승격 가능분 135건(그중 배송완료 102 = 「진짜 문제」 149건의 68%).
# ══════════════════════════════════════════════════════════════════════════

def _with_crawl(session, rows):
    """lotteon_settlements 표를 만들고 (od_no, od_seq, amt) 를 넣는다."""
    from lemouton.sourcing.models_v2 import LotteonSettlement
    LotteonSettlement.__table__.create(session.get_bind(), checkfirst=True)
    for od, seq, amt in rows:
        session.add(LotteonSettlement(od_no=od, od_seq=seq, pymt_tgt_amt=amt))
    session.commit()


def test_크롤정산이_OpenAPI_없는_주문도_실정산으로_올린다(session, monkeypatch):
    """미정산 구간은 셀러오피스 크롤이 유일 원천 — OpenAPI 는 구매확정분만 준다."""
    OS.save([_row(ono="LO900", days_ago=50)], session=session)
    _with_crawl(session, [("LO900", "1", 28800)])
    _patch(monkeypatch, {})                      # OpenAPI 는 이 주문을 모른다

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["crawl_rows"] == 1 and stat["updated"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "28800"
    assert stored["_settle_source"] == "real"


def test_크롤_0원은_실정산으로_단정하지_않는다(session, monkeypatch):
    """🔴 크롤표 2,121건 중 0원이 1,744건.

    0을 실정산으로 박으면 그 주문 마진이 「매입가 전액 손실」로 뒤집힌다.
    「미정산이라 0」인지 「취소돼서 진짜 0」인지 이 표만으론 못 가른다 → 그대로 둔다.
    """
    OS.save([_row(ono="LO901", days_ago=50)], session=session)
    _with_crawl(session, [("LO901", "1", 0)])
    _patch(monkeypatch, {})

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["crawl_rows"] == 0 and stat["updated"] == 0
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_source"] == "estimated"      # 추정 그대로
    assert str(stored["정산예정금액"]) == "27000"


def test_크롤_음수도_건너뛴다(session, monkeypatch):
    """환불 초과(procSeq +X/−X 합산 음수, 실측 1건) — 0원과 같은 이유로 단정 금지."""
    OS.save([_row(ono="LO902", days_ago=50)], session=session)
    _with_crawl(session, [("LO902", "1", -1500)])
    _patch(monkeypatch, {})

    assert OI.refresh_settlement_lotteon(session=session)["updated"] == 0


def test_크롤이_OpenAPI보다_우선(session, monkeypatch):
    """둘 다 있으면 크롤값 — order_export 인라인 조인과 같은 서열(미정산 포함 오차0)."""
    OS.save([_row(ono="LO903", days_ago=50)], session=session)
    _with_crawl(session, [("LO903", "1", 31000)])
    _patch(monkeypatch, {"LO903": 26500})        # OpenAPI 도 값을 준다

    OI.refresh_settlement_lotteon(session=session)

    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "31000"


def test_크롤_유료배송도_배송비포함이_크롤값과_같다_과대금지(session, monkeypatch):
    """크롤 pymtTgtAmt 도 배송비 포함액 — OpenAPI 와 같은 차감 규약을 타야 한다.

    안 빼면 _finalize 가 배송비를 다시 더해 배송비포함 = 크롤값+배송비 로 마진 과대.
    """
    OS.save([_row(ono="LO904", days_ago=50, 배송비=3000)], session=session)
    _with_crawl(session, [("LO904", "1", 30000)])
    _patch(monkeypatch, {})

    OI.refresh_settlement_lotteon(session=session)

    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "27000"                # 상품분(−배송비)
    assert str(stored["정산예정금(배송비포함)"]) == "30000"        # 크롤값 복원


def test_OpenAPI가_비어도_크롤만으로_돈다(session, monkeypatch):
    """옛 코드는 `if not smap: return` 이 크롤을 읽기 전에 있어 통째로 조기 반환됐다."""
    OS.save([_row(ono="LO905", days_ago=50)], session=session)
    _with_crawl(session, [("LO905", "1", 25000)])
    _patch(monkeypatch, {})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["settle_rows"] == 0 and stat["crawl_rows"] == 1
    assert stat["updated"] == 1


# ══════════════════════════════════════════════════════════════════════════
# [2026-08-03] 「팔았는데 정산 0원」 되돌리기
#   인라인 조인이 크롤 0원을 real 로 박던 결함의 잔재를 푼다. 정산 크롤 창을 180일로
#   넓히자 크롤표에 0원이 1,744건 쌓였고, 라이브 실측에서 real·0원 행이
#   10건(전부 반품완료=정상) → 21건으로 늘며 그중 **배송완료 5건**이 생겼다.
#   배송완료인데 0원 = 팔았는데 한 푼도 못 받았다는 뜻(마진이 매입가 전액 손실).
# ══════════════════════════════════════════════════════════════════════════

def test_배송완료인데_정산0원이면_되돌린다(session, monkeypatch):
    OS.save([_row(ono="LO910", days_ago=50, 주문상태="배송완료",
                  정산예정금액=0, _settle_source="real")], session=session)
    _patch(monkeypatch, {})                       # 어느 원천도 이 주문을 모른다

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["zero_reverted"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == ""       # 값을 비운다(0 을 다른 숫자로 안 바꾼다)
    assert stored["_settle_source"] == "none"     # 다음 스윕·추정이 정상 경로로 채운다


def test_취소반품의_0원은_진짜_0이라_안_건드린다(session, monkeypatch):
    """zero_cancel 규약 — 거래가 무산된 건의 0 은 옳은 값이다."""
    for i, st in enumerate(("취소완료", "반품완료", "회수지시", "철회")):
        OS.save([_row(uid=f"lotteon|LOC{i}|1", ono=f"LOC{i}", days_ago=50,
                      주문상태=st, 정산예정금액=0, _settle_source="real")],
                session=session)
    _patch(monkeypatch, {})

    assert OI.refresh_settlement_lotteon(session=session)["zero_reverted"] == 0


def test_OpenAPI가_확정한_0원은_안_되돌린다(session, monkeypatch):
    """🔴 100% 쿠폰·전액할인 구매확정 = **진짜 실정산 0**.

    되돌리면 추정치로 돌아가 오히려 과대해진다
    (test_전액할인_0원_정산도_실정산으로_확정 이 못 박은 규약과 한 몸).
    애매한 건 크롤 0원뿐이고, 그건 애초에 smap 에 안 들어간다.
    """
    OS.save([_row(ono="LO911", days_ago=50, 주문상태="구매확정")], session=session)
    _patch(monkeypatch, {"LO911": 0})             # OpenAPI 가 0 을 확정해서 준다

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["zero_reverted"] == 0
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_source"] == "real" and str(stored["정산예정금액"]) == "0"


def test_되돌림은_멱등이다(session, monkeypatch):
    """두 번 돌려도 한 번만 센다 — 첫 회차에 real 이 아니게 되므로 다시 안 걸린다."""
    OS.save([_row(ono="LO912", days_ago=50, 주문상태="배송완료",
                  정산예정금액=0, _settle_source="real")], session=session)
    _patch(monkeypatch, {})

    assert OI.refresh_settlement_lotteon(session=session)["zero_reverted"] == 1
    assert OI.refresh_settlement_lotteon(session=session)["zero_reverted"] == 0


# ══════════════════════════════════════════════════════════════════════════
# [2026-08-03] 단일라인 폴백은 **odSeq 를 모를 때만**
#   주석은 처음부터 "odSeq 불명(옛 행)" 이었는데 코드가 그 조건을 안 걸었다.
#   라이브 실측 2026071416415130 — seq1=10,000 / seq2=0(크롤). seq2 가 배송완료·real·
#   0원으로 굳어 있었는데, 형제 seq1 이 smap 에 하나 있다는 이유로 「근거 있음」 판정을
#   받아 되돌림에서 건너뛰어졌다. 형제의 금액은 이 라인의 근거가 아니다.
# ══════════════════════════════════════════════════════════════════════════

def test_odSeq를_아는_행은_형제_라인_값을_안_가져온다(session, monkeypatch):
    """다품 주문에서 seq2 가 smap 에 없으면 seq1 값을 쓰면 안 된다 — 같은 돈 2배 계상."""
    OS.save([_row(uid="lotteon|LO920|1", ono="LO920", seq="1", days_ago=50),
             _row(uid="lotteon|LO920|2", ono="LO920", seq="2", days_ago=50)],
            session=session)
    _patch(monkeypatch, {("LO920", "1"): 10000})      # seq1 만 정산이 있다

    OI.refresh_settlement_lotteon(session=session)

    got = {str((r.get("_send_ids") or {}).get("od_seq")): r
           for r in OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                            session=session)}
    assert str(got["1"]["정산예정금액"]) == "10000" and got["1"]["_settle_source"] == "real"
    assert got["2"]["_settle_source"] == "estimated"   # 형제 값을 안 받는다
    assert str(got["2"]["정산예정금액"]) == "27000"     # 추정 그대로


def test_형제라인이_있어도_내_라인_0원은_되돌린다(session, monkeypatch):
    """라이브 1건이 안 풀렸던 바로 그 모양 — 형제 seq1 만 smap 에 있는 경우."""
    OS.save([_row(uid="lotteon|LO921|1", ono="LO921", seq="1", days_ago=50),
             _row(uid="lotteon|LO921|2", ono="LO921", seq="2", days_ago=50,
                  주문상태="배송완료", 정산예정금액=0, _settle_source="real")],
            session=session)
    _patch(monkeypatch, {("LO921", "1"): 10000})

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["zero_reverted"] == 1
    got = {str((r.get("_send_ids") or {}).get("od_seq")): r
           for r in OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                            session=session)}
    assert got["2"]["_settle_source"] == "none" and str(got["2"]["정산예정금액"]) == ""


def test_odSeq_불명인_옛_행은_단일라인_폴백을_그대로_쓴다(session, monkeypatch):
    """폴백 자체는 살아 있어야 한다 — 옛 저장분(odSeq 공란) 구제가 그 존재 이유."""
    OS.save([_row(ono="LO922", days_ago=50, _send_ids={})], session=session)
    _patch(monkeypatch, {"LO922": 26500})             # 그 주문 라인이 딱 하나

    OI.refresh_settlement_lotteon(session=session)

    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "26500" and stored["_settle_source"] == "real"
