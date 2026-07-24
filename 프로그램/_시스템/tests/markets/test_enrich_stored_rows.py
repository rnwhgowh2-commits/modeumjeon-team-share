# -*- coding: utf-8 -*-
"""저장분 읽기 보강 — 마진계산기가 주문내역보다 덜 채워진 값을 보면 안 된다.

배경(2026-07-24 라이브 실측) — 주문내역(90일 이내)은 마켓을 라이브로 조회한 뒤 그
결과에 이력 채움·정산 추정을 태워 보여준다. 그 보강은 화면에 뿌릴 때 메모리에서만
일어나고 저장분엔 안 남는다. 그래서 저장분만 읽는 마진계산기는 같은 주문을 덜 채워진
채로 봤다: 같은 14일 창·같은 line_uid 대조에서
    11번가 — 정산예정금 16 · 실결제 19 · 단가 10 · 수령자 10 · 상품명 6
    롯데온 — 실결제 32 · 수령자 16
이 라이브엔 값이 있는데 저장분엔 빈칸이었다(거의 전부 취소완료 행).

사장님 지시: "오픈마켓 주문번호가 매칭되는 건 공란이 있으면 안 된다 — 적어도
주문내역 수준만큼은 채워져야 한다."
"""
from __future__ import annotations

from lemouton.markets import line_uid as L
from lemouton.markets import order_export as OE
from lemouton.markets import order_store as OS


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import lemouton.markets.models_orders  # noqa: F401
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"]])
    return sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()


def test_취소완료_행이_저장분_활성행에서_채워진다():
    """적재 당시엔 같은 주문의 활성 행이 아직 저장분에 없어 채움이 빈손이었다.
    그 뒤 저장분이 채워져도 클레임 행은 다시 안 채워졌다 — 읽을 때 채운다."""
    s = _sess()
    OS.save([{L.FIELD: "eleven11|A1|1", "판매처": "11번가", "오픈마켓주문번호": "A1",
              "주문일": "2026-07-18 10:00:00", "주문상태": "배송완료",
              "상품명": "나이키 에어맥스", "옵션": "사이즈:270", "단가": 94200,
              "수량": 1, "실결제금액": 94200, "수령자": "권장원",
              "수령자전화번호": "0504-1", "_settle_source": "real"}], session=s)
    claim = {L.FIELD: "eleven11|A1|1", "_kind": "change", "판매처": "11번가",
             "오픈마켓주문번호": "A1", "주문상태": "취소완료",
             "상품명": "", "단가": "", "실결제금액": "", "수령자": ""}
    OE.enrich_stored_rows([claim], session=s)
    assert claim["상품명"] == "나이키 에어맥스"
    assert str(claim["단가"]) == "94200"
    assert str(claim["실결제금액"]) == "94200"
    assert claim["수령자"] == "권장원"
    s.close()


def test_이미_있는_값은_덮지_않는다():
    """빈 칸만 채운다 — 주문조회·정산이 이미 준 값을 덮으면 날조가 된다.

    (주문상태는 '반품완료' — 취소완료·취소요청·철회는 _finalize_rows 가 실결제를
     원금으로 통일하는 샵마인 규약 대상이라 '안 덮는다'를 재는 데 부적절하다.)"""
    s = _sess()
    OS.save([{L.FIELD: "eleven11|B1|1", "판매처": "11번가", "오픈마켓주문번호": "B1",
              "주문일": "2026-07-18 10:00:00", "주문상태": "배송완료",
              "상품명": "저장분 이름", "단가": 11111, "수량": 1,
              "실결제금액": 11111, "_settle_source": "real"}], session=s)
    claim = {L.FIELD: "eleven11|B1|1", "_kind": "change", "판매처": "11번가",
             "오픈마켓주문번호": "B1", "주문상태": "반품완료",
             "상품명": "실제로 온 이름", "단가": 22222, "수량": 1, "실결제금액": ""}
    OE.enrich_stored_rows([claim], session=s)
    assert claim["상품명"] == "실제로 온 이름" and claim["단가"] == 22222
    assert str(claim["실결제금액"]) == "11111"       # 빈 칸만 채워졌다
    s.close()


def test_취소완료는_실결제를_원금으로_통일한다():
    """샵마인 규약(사장님 확정) — 취소완료 K열 = 단가×수량 원금. 주문내역이 그렇게
    보여주므로 저장분 보강도 같은 규약을 통과해야 두 화면 숫자가 같아진다."""
    s = _sess()
    row = {L.FIELD: "eleven11|B2|1", "_kind": "change", "판매처": "11번가",
           "오픈마켓주문번호": "B2", "주문상태": "취소완료",
           "상품명": "나이키", "단가": 22222, "수량": 1, "실결제금액": ""}
    OE.enrich_stored_rows([row], session=s)
    assert row["실결제금액"] == 22222 and row["정산예정금액"] == 0   # 취소 = 정산 없음
    s.close()


def test_마켓별_옵션이_라이브_조회와_같다(monkeypatch):
    """마켓마다 채움 옵션이 다르고(11번가=빈 정상행까지·쿠팡=연락처 빈 행까지),
    정산 추정을 켜는 마켓도 다르다(11번가·옥션·G마켓만). 저장분 보강이 라이브보다
    **더** 채우면 같은 주문이 화면마다 또 달라진다 — 방향만 반대인 같은 병."""
    fills, ests = [], []
    monkeypatch.setattr(OE, "fill_claim_blanks_from_history",
                        lambda rows, market, session=None, **kw: fills.append((market, kw)) or rows)
    monkeypatch.setattr(OE, "estimate_settle_from_history",
                        lambda rows, market, session=None: ests.append(market) or rows)
    OE.enrich_stored_rows([
        {L.FIELD: "eleven11|A|1", "판매처": "11번가"},
        {L.FIELD: "coupang|B|1", "판매처": "쿠팡"},
        {L.FIELD: "lotteon|C|1", "판매처": "롯데온"},
        {L.FIELD: "gmarket|D|1", "판매처": "G마켓"},
        {L.FIELD: "smartstore|E|1", "판매처": "스마트스토어"},
    ])
    got = dict(fills)
    assert got["eleven11"] == {"include_blank_orders": True,
                               "settle_from_store_for_orders": True,
                               "include_blank_contact_orders": True}
    assert got["coupang"] == {"include_blank_contact_orders": True}
    assert got["lotteon"] == {} and got["gmarket"] == {}
    assert "smartstore" not in got          # 라이브가 안 태우니 여기서도 안 태운다
    assert sorted(ests) == ["eleven11", "gmarket"]   # 정산 추정은 이 마켓들만


def test_한_마켓_보강이_깨져도_나머지는_돈다(monkeypatch):
    """보강은 부가 기능이다 — 하나가 터져도 주문을 통째로 잃으면 안 된다."""
    ok = []

    def _fill(rows, market, session=None, **kw):
        if market == "eleven11":
            raise RuntimeError("이 마켓만 실패")
        ok.append(market)
        return rows

    monkeypatch.setattr(OE, "fill_claim_blanks_from_history", _fill)
    monkeypatch.setattr(OE, "estimate_settle_from_history", lambda rows, m, session=None: rows)
    rows = OE.enrich_stored_rows([
        {L.FIELD: "eleven11|A|1", "판매처": "11번가"},
        {L.FIELD: "coupang|B|1", "판매처": "쿠팡"},
    ])
    assert ok == ["coupang"] and len(rows) == 2


def test_채운_정산이_마진이_읽는_열까지_반영된다():
    """마진계산기는 `정산예정금(배송비포함)`을 읽는다. 이 파생열은 _finalize_rows 만
    계산하므로, 보강으로 정산예정금액을 채워도 재계산을 안 하면 빈칸 그대로 남는다."""
    s = _sess()
    OS.save([{L.FIELD: "eleven11|C1|1", "판매처": "11번가", "오픈마켓주문번호": "C1",
              "주문일": "2026-07-18 10:00:00", "주문상태": "배송완료",
              "상품명": "나이키", "옵션": "270", "단가": 50000, "수량": 1,
              "실결제금액": 50000, "배송비": 3000, "정산예정금액": 45000,
              "_settle_source": "real"}], session=s)
    row = {L.FIELD: "eleven11|C1|1", "_kind": "order", "판매처": "11번가",
           "오픈마켓주문번호": "C1", "주문상태": "배송완료", "상품명": "나이키",
           "단가": 50000, "수량": 1, "배송비": 3000,
           "정산예정금액": "", "정산예정금(배송비포함)": ""}
    OE.enrich_stored_rows([row], session=s)
    assert str(row["정산예정금액"]) == "45000"           # 저장분에서 물려받고
    assert row["정산예정금(배송비포함)"] == 48000        # 파생열까지 재계산됐다
    s.close()
