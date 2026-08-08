# -*- coding: utf-8 -*-
"""롯데온 지급내역 — 「언제 실제로 입금됐나」.

🔴 2026-08-07 실브라우저로 찾은 롯데온 입금 확인의 **유일한** 창구.
   정산 OpenAPI 8종·정산예정금액조회·정산요약·셀러머니 전부 실지급일이 없었다.
   그 전까지 롯데온만 「받았을 것(확인 불가) 2,604만 + 입금일 지남 1,337만」이 판정 불가.

★ 롯데온은 **일정산** — 구매확정일(seStdDt) 단위로 묶여 며칠 뒤 지급(07-10 확정 → 07-13 지급).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.margin import lotteon_paid as LP
from lemouton.sourcing.models_v2 import LotteonSettlePaid


@pytest.fixture
def session(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'lp.db'}", future=True)
    LotteonSettlePaid.__table__.create(eng, checkfirst=True)
    s = sessionmaker(bind=eng, future=True, expire_on_commit=False)()
    yield s
    s.close()


# 2026-08-07 라이브 실측 응답 모양 그대로
_RESP = {"returnCode": "SUCCESS", "data": {"settleDetailList": {"totalCount": 2, "dataList": [
    {"seStdDt": "2026-07-10", "seCmptDt": "2026-07-13", "seCclCdText": "일정산",
     "slAmt": "84400.00", "pymtTgtAmt": "110978.00", "fnlPymtBgtAmt": "110661.00"},
    {"seStdDt": "2026-07-11", "seCmptDt": "2026-07-13", "seCclCdText": "일정산",
     "slAmt": "110900.00", "pymtTgtAmt": "97435.00", "fnlPymtBgtAmt": "97435.00"},
]}}}


def test_지급내역을_읽는다():
    rows, skipped = LP.parse_rows(_RESP, tr_no="LO10161082", account="브랜드박스(롯데온)")
    assert skipped == 0 and len(rows) == 2
    r = rows[0]
    assert r["se_std_dt"] == "2026-07-10"        # 구매확정일 = 조인 축
    assert r["se_cmpt_dt"] == "2026-07-13"       # ★실제 입금된 날
    assert r["fnl_pymt_bgt_amt"] == 110661       # ★그날 실지급액


def test_정산기준일이_없는_행은_버린다():
    """조인 축이 없으면 어느 주문에도 못 붙인다."""
    rows, skipped = LP.parse_rows(
        {"data": {"settleDetailList": {"dataList": [{"seCmptDt": "2026-07-13"}]}}},
        tr_no="LO1")
    assert rows == [] and skipped == 1


def test_저장하고_같은_날을_다시_넣어도_안_쌓인다(session):
    rows, _ = LP.parse_rows(_RESP, tr_no="LO1")
    assert LP.save(rows, session=session) == 2
    LP.save(rows, session=session)
    assert LP.summary(session=session)["날짜수"] == 2


def test_판매자ID가_없으면_저장하지_않는다(session):
    """계정 구분이 안 되면 다른 계정 값과 섞인다."""
    rows, _ = LP.parse_rows(_RESP, tr_no="")
    LP.save(rows, session=session)
    assert LP.summary(session=session)["날짜수"] == 0


def test_구매확정일로_받은_날을_찾는다(session):
    LP.save(LP.parse_rows(_RESP, tr_no="LO1")[0], session=session)
    m = LP.paid_date_map(session=session)
    assert m["2026-07-10"] == "2026-07-13"
    assert m["2026-07-11"] == "2026-07-13"


def test_아직_지급_안_된_날은_안_담는다(session):
    """정산완료일이 없으면 「받았다」로 단정하지 않는다."""
    resp = {"data": {"settleDetailList": {"dataList": [
        {"seStdDt": "2026-08-06", "seCmptDt": "", "fnlPymtBgtAmt": "546181.00"}]}}}
    LP.save(LP.parse_rows(resp, tr_no="LO1")[0], session=session)
    assert LP.paid_date_map(session=session) == {}


def test_계정이_여럿이면_가장_늦은_완료일을_쓴다(session):
    """한 계정이라도 아직 안 들어왔으면 「다 받았다」고 하면 안 된다 — 보수적으로."""
    for tr, cmpt in (("LO1", "2026-07-13"), ("LO2", "2026-07-15")):
        LP.save(LP.parse_rows(
            {"data": {"settleDetailList": {"dataList": [
                {"seStdDt": "2026-07-10", "seCmptDt": cmpt, "fnlPymtBgtAmt": "1"}]}}},
            tr_no=tr)[0], session=session)
    assert LP.paid_date_map(session=session)["2026-07-10"] == "2026-07-15"


def test_요약이_지급합을_준다(session):
    LP.save(LP.parse_rows(_RESP, tr_no="LO1")[0], session=session)
    s = LP.summary(session=session)
    assert s["지급확정"] == 2
    assert s["지급합"] == 110661 + 97435
    assert s["최근완료일"] == "2026-07-13"


# ── 수신 라우트 ───────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """바레 Flask + tmp sqlite — 다른 margin 라우트 테스트와 같은 패턴."""
    from flask import Flask
    from webapp.routes import api_margin
    eng = create_engine(f"sqlite:///{tmp_path / 'lpapi.db'}", future=True)
    LotteonSettlePaid.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    monkeypatch.setattr(api_margin, "SessionLocal", Session)
    app = Flask(__name__)
    app.register_blueprint(api_margin.bp)
    c = app.test_client()
    c._Session = Session
    return c


def test_라우트가_지급내역을_저장한다(client):
    r = client.post("/api/margin/lotteon-paid",
                    json={"trNo": "LO10161082", "account": "브랜드박스(롯데온)",
                          "rows": _RESP})
    assert r.status_code == 200
    assert r.get_json()["saved"] == 2


def test_판매자ID_없으면_400(client):
    """계정이 섞이면 합계가 조용히 틀어진다 — 아예 받지 않는다."""
    r = client.post("/api/margin/lotteon-paid", json={"rows": _RESP})
    assert r.status_code == 400


def test_rows_없으면_400(client):
    r = client.post("/api/margin/lotteon-paid", json={"trNo": "LO1"})
    assert r.status_code == 400
