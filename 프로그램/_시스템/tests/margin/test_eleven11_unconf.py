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


def _line(sess, uid, *, settle=None, src="store", **extra):
    from lemouton.markets.models_orders import MarketOrderLine as L
    row = {"판매처": "11번가", "주문상태": "배송완료"}
    if settle is not None:
        row["정산예정금(배송비포함)"] = settle
        row["_settle_source"] = src
    row.update(extra)
    sess.add(L(line_uid=uid, market="eleven11",
               order_no=uid.split("|")[1], row=row))
    sess.commit()


def _stored(sess):
    from lemouton.markets.models_orders import MarketOrderLine as L
    return dict(sess.query(L).one().row)


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
    """무의미한 쓰기 방지 — 단, 「같다」는 **우리가 쓰는 칸 전부**가 같을 때다.

    🔴 2026-08-13 정정 — 옛 시험은 N열만 맞으면 「같다」로 봤다. 그래서 M열이 빈
      옛 행이 영영 안 고쳐졌고, 저장분 보강이 도는 순간 그 행의 N 이 빈칸이 됐다
      (아래 `test_N은_같은데_M이_비었으면_채운다`). 그래서 M·_stl_net 도 채워 둔다.
    """
    s = _sess()
    _line(s, "eleven11|20260806090786705|1", settle=47894, src="real",
          정산예정금액=47894, _stl_net=True, 배송비=0)
    rows, _ = EU.parse_rows({"list": [LIVE]})
    rep = EU.apply_rows(rows, session=s)
    assert (rep["적용"], rep["값동일"]) == (0, 1)


# ── 🔴 저장분 보강이 실값을 조용히 지우던 것 ────────────────────

def test_적용값이_저장분_보강을_견딘다():
    """🔴 이 파일에서 제일 중요한 시험 — 실값이 **조용히 지워지고 있었다**.

    여태 N열(정산예정금(배송비포함))에만 직접 쓰고 M열(정산예정금액)은 안 건드렸다.
    그런데 저장분 보강(`order_export` 의 `enrich`)이 `_finalize_rows` 를 **다시 돌린다**.
    거기서 N 은 `M + 배송비` 로 새로 만들어진다 →
      · M 이 비어 있으면 N 이 **빈칸**이 된다
      · M 에 추정치가 있으면 그 추정치 + 배송비로 **덮인다**
    둘 다 사장님이 화면에서 본 마켓 실값이 사라지는 것이다.
    """
    from lemouton.markets.order_export import _finalize_rows
    s = _sess()
    _line(s, "eleven11|20260806090786705|1", settle=50000, src="store",
          배송비=2500, 단가=58400, 수량=1)
    rows, _ = EU.parse_rows({"list": [LIVE]})
    EU.apply_rows(rows, session=s)

    row = _stored(s)
    assert row["정산예정금(배송비포함)"] == 47894      # 붙인 직후
    _finalize_rows([row])                              # 저장분 보강 흉내
    assert row["정산예정금(배송비포함)"] == 47894, \
        f'저장분 보강이 마켓 실값을 덮었다: {row["정산예정금(배송비포함)"]}'


def test_M열을_11번가_규약대로_같이_채운다():
    """구매확정 **후** 빌더가 이미 쓰는 규약 그대로 — M = 실값 − 배송비, `_stl_net=True`.

    (order_export 11번가 빌더: `정산예정금액 = stlPlnAmt − 배송비`.
     stlAmt 도 stlPlnAmt 와 같이 배송비를 품고 있다 — 이 모듈 머리글 실측 참고.)
    🔴 규약이 두 벌이 되면 같은 주문이 경로에 따라 다른 값이 된다(원천 분열).
    """
    s = _sess()
    _line(s, "eleven11|20260806090786705|1", settle=50000, src="store", 배송비=2500)
    rows, _ = EU.parse_rows({"list": [LIVE]})
    EU.apply_rows(rows, session=s)

    row = _stored(s)
    assert row["정산예정금액"] == 47894 - 2500
    assert row["_stl_net"] is True, '구 저장분과 구분할 표식이 없다'


def test_배송비가_없으면_M과_N이_같다():
    s = _sess()
    _line(s, "eleven11|20260806090786705|1", settle=50000, src="store")
    rows, _ = EU.parse_rows({"list": [LIVE]})
    EU.apply_rows(rows, session=s)

    row = _stored(s)
    assert row["정산예정금액"] == 47894
    assert row["정산예정금(배송비포함)"] == 47894


def test_N은_같은데_M이_비었으면_채운다():
    """🔴 「값 같으면 안 쓴다」가 **깨진 옛 행을 영영 보호**하면 안 된다.

    N 만 실값이고 M 이 빈 행이 저장분에 그대로 있다. 그 행은 저장분 보강이 도는
    순간 N 이 빈칸이 된다. 다음 수집 때 고쳐 줘야 한다.
    """
    s = _sess()
    _line(s, "eleven11|20260806090786705|1", settle=47894, src="real")   # M 없음
    rows, _ = EU.parse_rows({"list": [LIVE]})
    rep = EU.apply_rows(rows, session=s)

    assert rep["적용"] == 1, 'M 이 빈 채로 「값 같음」 처리해 버렸다'
    assert _stored(s)["정산예정금액"] == 47894


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
