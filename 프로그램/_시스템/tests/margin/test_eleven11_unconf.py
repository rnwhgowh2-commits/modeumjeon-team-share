# -*- coding: utf-8 -*-
"""11번가 구매확정 전 정산예정액 — 2026-08-08 라이브 실측 10건 기반.

🔴 이 테스트가 지키는 것 = 「0건은 없다가 아니다」.
   전날 구매확정일 축으로만 조회해 0건이 나오자 「마켓이 안 준다」고 오판했고,
   결제일 축으로 바꾸니 바로 나왔다. 그래서 여기선 **못 붙은 건이 응답에 남는지**를
   반드시 확인한다 — 조인 축이 어긋나도 「성공」으로 보이면 같은 오판이 반복된다.
"""
from __future__ import annotations

from lemouton.margin import eleven11_unconf as EU

# 라이브 실측 1행 그대로(고객정보 제외). selPrc 58,400 − deductAmt 10,506 = stlAmt 47,894
LIVE = {
    "ordNo": "20260806090786705", "ordPrdSeq": "1", "ordPrdStat": "발주확인",
    "selPrc": "58400", "deductAmt": "10506", "stlAmt": "47894",
    "selFee": "1,776", "selFixedFee": "13.00%", "stlPlnDy": "",
    "ordStlEndDt": "2026/08/06", "sellerId": "rnwhgowh1",
}


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import lemouton.markets.models_orders  # noqa: F401
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        eng, tables=[Base.metadata.tables["market_order_lines"]])
    return sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()


def _line(sess, uid, *, settle=None, src="store"):
    from lemouton.markets.models_orders import MarketOrderLine as L
    row = {"판매처": "11번가", "주문상태": "배송완료"}
    if settle is not None:
        row["정산예정금(배송비포함)"] = settle
        row["_settle_source"] = src
    sess.add(L(line_uid=uid, market="eleven11",
               order_no=uid.split("|")[1], row=row))
    sess.commit()


def test_parse_실측행_그대로():
    rows, skipped = EU.parse_rows({"list": [LIVE]}, account="르무통(11번가)")
    assert skipped == 0
    r = rows[0]
    assert r["line_uid"] == "eleven11|20260806090786705|1"
    assert r["stl_amt"] == 47894           # 콤마 없는 값
    assert r["ord_prd_stat"] == "발주확인"   # 구매확정 전이라는 증거
    assert r["pay_date"] == "2026/08/06"


def test_parse_콤마섞인금액도_읽는다():
    rows, _ = EU.parse_rows({"list": [dict(LIVE, stlAmt="1,234,567")]})
    assert rows[0]["stl_amt"] == 1234567


def test_parse_조인키_없으면_버린다():
    """ordNo·ordPrdSeq 가 없으면 추측하지 않고 버린다."""
    bad = [dict(LIVE, ordNo=""), dict(LIVE, ordPrdSeq=""), dict(LIVE, stlAmt="")]
    rows, skipped = EU.parse_rows({"list": bad})
    assert (len(rows), skipped) == (0, 3)


def test_parse_fetch감싼_형태도_읽는다():
    """확장이 {ok,status,json:{list}} 그대로 올려도 받는다."""
    rows, _ = EU.parse_rows({"json": {"list": [LIVE]}})
    assert len(rows) == 1


def test_적용_store를_real로_덮는다():
    """발송대기 때 값(store)을 마켓 실값(real)이 대체한다."""
    s = _sess()
    _line(s, "eleven11|20260806090786705|1", settle=50000, src="store")
    rows, _ = EU.parse_rows({"list": [LIVE]})
    rep = EU.apply_rows(rows, session=s)
    assert (rep["적용"], rep["미매칭"]) == (1, 0)
    assert rep["바뀐금액합"] == 47894 - 50000

    from lemouton.markets.models_orders import MarketOrderLine as L
    row = s.query(L).one().row
    assert row["정산예정금(배송비포함)"] == 47894
    assert row["_settle_source"] == "real"
    assert row["_11st_unconf_stat"] == "발주확인"   # 근거를 행에 남긴다


def test_적용_같은값이면_다시_안쓴다():
    s = _sess()
    _line(s, "eleven11|20260806090786705|1", settle=47894, src="real")
    rows, _ = EU.parse_rows({"list": [LIVE]})
    rep = EU.apply_rows(rows, session=s)
    assert (rep["적용"], rep["값동일"]) == (0, 1)


def test_미매칭이_응답에_남는다():
    """🔴 조인 축이 어긋나면 **드러나야** 한다 — 조용한 0건 금지."""
    s = _sess()
    _line(s, "eleven11|다른주문|1", settle=1000)
    rows, _ = EU.parse_rows({"list": [LIVE]})
    rep = EU.apply_rows(rows, session=s)
    assert (rep["적용"], rep["미매칭"]) == (0, 1)
    assert rep["미매칭목록"][0]["주문번호"] == "20260806090786705"
    assert rep["미매칭목록"][0]["정산예정"] == 47894


def test_적용값이_단일원천을_통과한다():
    """sell_source 가 이 값을 그대로 쓰는지 — 여기서 갈리면 화면 숫자가 어긋난다."""
    from lemouton.margin.sell_source import _settlement_for
    amt, src = _settlement_for({"판매처": "11번가", "주문상태": "배송완료",
                                "정산예정금(배송비포함)": 47894,
                                "_settle_source": "real", "배송비": 2500})
    assert (amt, src) == (47894, "real")   # 배송비를 또 더하지 않는다(이중계상 금지)
