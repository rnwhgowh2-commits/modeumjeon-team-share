# -*- coding: utf-8 -*-
"""로켓그로스 정산 수신 — 크롤러 push → 회차별 upsert.

🔴 왜 크롤인가(2026-08-07 라이브 실측) — 로켓그로스 정산액을 주는 OpenAPI 가 **없다**.
   매출내역(revenue-history)에 로켓그로스 주문은 0건이고, 정산 회차(settlement-histories)도
   마켓플레이스 몫만 담는다(세소 6월 대상액 11,081,786 ≈ 마켓플레이스 계산 11,131,180).
   Wing 화면 API(/tenants/rfm/v2/settlements/status/api)가 유일한 창구이고, 그건
   **로그인 세션 쿠키**가 필요해 서버에서 못 부른다 → 로컬 크롤 → 서버 push(롯데온과 동형).

★ 회차 신원 = (settlementGroupKey, settlementRatio). groupKey 는 기간 기반이라
  같은 기간의 30%·70% 회차가 **같은 키를 공유**한다 — ratio 를 빼면 서로 덮어쓴다.
★ totalArFactoringDeductionAmount = 빠른정산 계좌인출액 = **이미 받은 돈**.
  마켓플레이스는 전용 필드가 없어 역산했는데 로켓그로스는 필드가 있어 정확하다.
"""
from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.sourcing.models_v2 import RocketGrowthSettlement
from webapp.routes import api_margin


@pytest.fixture
def client(tmp_path, monkeypatch):
    """바레 Flask + tmp sqlite — test_lotteon_settlement_ingest.py 와 같은 패턴."""
    eng = create_engine(f"sqlite:///{tmp_path / 'rg.db'}", future=True)
    RocketGrowthSettlement.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    monkeypatch.setattr(api_margin, "SessionLocal", Session)
    app = Flask(__name__)
    app.register_blueprint(api_margin.bp)
    c = app.test_client()
    c._Session = Session
    return c


def _row(group="A013-2026-06-01-2026-06-07", ratio=30, **kw):
    r = {"settlementGroupKey": group, "settlementRatio": ratio,
         "settlementDate": "2026-08-02T15:00:00Z",
         "settlementPeriodStartDate": "2026-05-31T15:00:00Z",
         "settlementPeriodEndDate": "2026-06-06T15:00:00Z",
         "finalSettlementAmount": 127470.0,
         "settlementStatusReportDetail": {
             "totalSalesAmount": 6796800.0,
             "totalPayableAmount": 1274681,
             "totalArFactoringDeductionAmount": 1147211.0,
             "totalFinalSettlementAmount": 127470.0}}
    r.update(kw)
    return r


def test_회차를_저장한다(client):
    r = client.post("/api/margin/rg-settlement",
                    json={"account": "세소(쿠팡)", "rows": [_row()]})
    assert r.status_code == 200
    assert r.get_json()["saved"] == 1


def test_같은_기간의_30과_70은_서로_다른_회차다(client):
    """groupKey 는 기간 기반이라 공유된다 — ratio 를 안 보면 한쪽이 사라진다."""
    body = {"account": "세소(쿠팡)", "rows": [_row(ratio=30), _row(ratio=70)]}
    r = client.post("/api/margin/rg-settlement", json=body)
    assert r.get_json()["saved"] == 2


def test_같은_회차를_다시_보내면_덮어쓴다(client):
    client.post("/api/margin/rg-settlement",
                json={"account": "세소(쿠팡)", "rows": [_row()]})
    r = client.post("/api/margin/rg-settlement",
                    json={"account": "세소(쿠팡)", "rows": [_row()]})
    assert r.get_json()["saved"] == 1          # 겹쳐 쌓이지 않는다


def test_회차키가_없으면_버리고_건수를_알린다(client):
    """조용히 삼키면 크롤이 멈춘 걸 아무도 모른다."""
    r = client.post("/api/margin/rg-settlement",
                    json={"account": "세소", "rows": [{"settlementRatio": 30}]})
    body = r.get_json()
    assert body["saved"] == 0 and body["skipped"] == 1


def test_rows_없는_본문은_400(client):
    r = client.post("/api/margin/rg-settlement", json={"account": "세소"})
    assert r.status_code == 400


def test_요약이_지급액과_빠른정산을_갈라_준다(client):
    """화면이 「받을 돈」과 「이미 받은 돈」을 나눠 보여주려면 둘이 갈려 있어야 한다."""
    from lemouton.margin import rg_settlement as RG
    client.post("/api/margin/rg-settlement",
                json={"account": "세소(쿠팡)",
                      "rows": [_row(ratio=30), _row(ratio=70, group="A013-2026-06-08-2026-06-14",
                                                    finalSettlementAmount=264141.0)]})
    with client._Session() as s:
        got = RG.summary(session=s)
    assert got["지급액"] == 1274681 * 2
    assert got["빠른정산"] == int(1147211 * 2)
    assert got["받을돈"] == got["지급액"] - got["빠른정산"]
    assert got["계정별"][0]["계정"] == "세소(쿠팡)"


def test_빠른정산이_지급액보다_크면_받을돈은_0(client):
    """음수로 흘리면 총액이 근거 없이 줄어든다 — 모르면 0."""
    from lemouton.margin import rg_settlement as RG
    r = _row()
    r["settlementStatusReportDetail"]["totalArFactoringDeductionAmount"] = 9_999_999
    client.post("/api/margin/rg-settlement", json={"account": "세소", "rows": [r]})
    with client._Session() as s:
        assert RG.summary(session=s)["받을돈"] == 0
