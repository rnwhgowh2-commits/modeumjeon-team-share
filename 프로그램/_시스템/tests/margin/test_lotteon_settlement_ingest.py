# -*- coding: utf-8 -*-
"""POST /api/margin/lotteon-settlement — 크롤러 push ingest.

크롬 확장(로컬 크롤러)이 롯데온 판매자센터 soapi selectBgtSettleManagementList
결과(pymtTgtAmt=정산예정금액, slChNo=판매경로)를 라인 단위로 push한다.
키는 (od_no, od_seq) — 여러 라인 주문의 이중계상을 막기 위해 라인별로 upsert한다.

바레 Flask 앱 + tmp sqlite 세션으로 라우트만 검증(다른 margin 라우트 테스트와 동일 패턴,
test_api_margin.py 의 client fixture 미러).
"""
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.sourcing.models_v2 import LotteonSettlement
from webapp.routes import api_margin


@pytest.fixture
def client(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", future=True)
    LotteonSettlement.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    monkeypatch.setattr(api_margin, "SessionLocal", Session)

    app = Flask(__name__)
    app.register_blueprint(api_margin.bp)
    c = app.test_client()
    c._Session = Session
    return c


def _rows(c, Session=None):
    Session = Session or c._Session
    s = Session()
    try:
        return {(r.od_no, r.od_seq): r for r in s.query(LotteonSettlement).all()}
    finally:
        s.close()


def test_ingest_two_lines_same_order_diff_seq(client):
    payload = [
        {"odNo": "20260715001", "odSeq": "1", "pymtTgtAmt": 12000, "slChNo": "제휴", "trNo": "TR1"},
        {"odNo": "20260715001", "odSeq": "2", "pymtTgtAmt": 8000, "slChNo": "제휴", "trNo": "TR1"},
    ]
    r = client.post("/api/margin/lotteon-settlement", json=payload)
    assert r.status_code == 200
    assert r.get_json() == {"upserted": 2}

    rows = _rows(client)
    assert len(rows) == 2
    assert rows[("20260715001", "1")].pymt_tgt_amt == 12000
    assert rows[("20260715001", "2")].pymt_tgt_amt == 8000
    assert rows[("20260715001", "1")].sl_chnl == "제휴"
    assert rows[("20260715001", "1")].tr_no == "TR1"


def test_ingest_upsert_updates_amount_no_duplicate(client):
    first = [{"odNo": "20260715002", "odSeq": "1", "pymtTgtAmt": 5000, "slChNo": "롯데ON", "trNo": "TR1"}]
    assert client.post("/api/margin/lotteon-settlement", json=first).status_code == 200

    second = [{"odNo": "20260715002", "odSeq": "1", "pymtTgtAmt": 5500, "slChNo": "롯데ON", "trNo": "TR1"}]
    r = client.post("/api/margin/lotteon-settlement", json=second)
    assert r.status_code == 200
    assert r.get_json() == {"upserted": 1}

    rows = _rows(client)
    assert len(rows) == 1                      # 중복 행 없음
    assert rows[("20260715002", "1")].pymt_tgt_amt == 5500   # 갱신됨


def test_ingest_missing_odno_skipped(client):
    payload = [
        {"odNo": "", "odSeq": "1", "pymtTgtAmt": 1000},
        {"odSeq": "1", "pymtTgtAmt": 1000},
        {"odNo": "20260715003", "odSeq": "1", "pymtTgtAmt": 3000, "slChNo": "제휴", "trNo": "TR1"},
    ]
    r = client.post("/api/margin/lotteon-settlement", json=payload)
    assert r.status_code == 200
    assert r.get_json() == {"upserted": 1}
    rows = _rows(client)
    assert len(rows) == 1
    assert ("20260715003", "1") in rows


def test_ingest_default_odseq_is_1(client):
    payload = [{"odNo": "20260715004", "pymtTgtAmt": 7000, "slChNo": "제휴", "trNo": "TR1"}]
    r = client.post("/api/margin/lotteon-settlement", json=payload)
    assert r.status_code == 200
    rows = _rows(client)
    assert ("20260715004", "1") in rows


def test_ingest_non_list_body_is_400(client):
    r = client.post("/api/margin/lotteon-settlement", json={"odNo": "x"})
    assert r.status_code == 400


def test_ingest_empty_list_ok_zero_upserted(client):
    r = client.post("/api/margin/lotteon-settlement", json=[])
    assert r.status_code == 200
    assert r.get_json() == {"upserted": 0}
