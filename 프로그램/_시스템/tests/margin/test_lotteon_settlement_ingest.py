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
    assert r.get_json() == {"upserted": 2, "skipped": 0, "source": "manual"}

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
    assert r.get_json() == {"upserted": 1, "skipped": 0, "source": "manual"}

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
    assert r.get_json() == {"upserted": 1, "skipped": 2, "source": "manual"}
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
    assert r.get_json() == {"upserted": 0, "skipped": 0, "source": "manual"}


# ── [2026-08-02] 자동 회차 대응 — {source, rows} 봉투 + 가짜 주문번호 차단 ──
#  배경(라이브 실측): lotteon_settlements 에 진단 프로브가 넣은 'TESTOD999'(12,345원)가
#  남아 있었다. ingest 가 od_no 를 숫자로 검사하지 않아 뭐든 들어왔다.
#  또 표가 **언제·무엇으로** 채워졌는지 알 길이 없어, 자동 회차가 멈춘 것을
#  '크롤 버그'로 오해할 뻔했다 → source 를 기록한다.

def test_ingest_envelope_records_source(client):
    """{"source":"auto","rows":[...]} 형태 — 자동 회차가 쓰는 봉투."""
    body = {"source": "auto",
            "rows": [{"odNo": "20260801001", "odSeq": "1", "pymtTgtAmt": 9000,
                      "slChNo": "제휴", "trNo": "TR9"}]}
    r = client.post("/api/margin/lotteon-settlement", json=body)
    assert r.status_code == 200
    assert r.get_json() == {"upserted": 1, "skipped": 0, "source": "auto"}
    assert _rows(client)[("20260801001", "1")].source == "auto"


def test_ingest_bare_list_still_works_and_is_manual(client):
    """옛 형태(맨 리스트)도 계속 받는다.

    확장은 사장님 크롬에 설치돼 있어 서버와 동시에 안 바뀐다. 새 서버가 옛 확장의
    push 를 거절하면 정산 수집이 통째로 멈추는데, 에러는 확장 안에서 삼켜져 조용하다.
    """
    r = client.post("/api/margin/lotteon-settlement",
                    json=[{"odNo": "20260801002", "pymtTgtAmt": 100, "trNo": "TR9"}])
    assert r.status_code == 200
    assert r.get_json()["source"] == "manual"
    assert _rows(client)[("20260801002", "1")].source == "manual"


def test_ingest_rejects_non_numeric_odno(client):
    """가짜 주문번호(TESTOD999 등)는 저장하지 않고 skipped 로 센다."""
    body = {"source": "manual",
            "rows": [{"odNo": "TESTOD999", "odSeq": "1", "pymtTgtAmt": 12345},
                     {"odNo": "2026080100 3", "odSeq": "1", "pymtTgtAmt": 1},
                     {"odNo": "20260801004", "odSeq": "1", "pymtTgtAmt": 500}]}
    r = client.post("/api/margin/lotteon-settlement", json=body)
    assert r.get_json() == {"upserted": 1, "skipped": 2, "source": "manual"}
    keys = set(_rows(client))
    assert keys == {("20260801004", "1")}


def test_purge_fake_dry_run_then_confirm(client):
    """오염 행 청소 — confirm 없이는 안 지우고, 숫자 주문번호는 건드리지 않는다."""
    Session = client._Session
    s = Session()
    s.add(LotteonSettlement(od_no="TESTOD999", od_seq="1", pymt_tgt_amt=12345, tr_no="TR9"))
    s.add(LotteonSettlement(od_no="20260801005", od_seq="1", pymt_tgt_amt=7000, tr_no="TR9"))
    s.commit()
    s.close()

    dry = client.post("/api/margin/lotteon-settlement/purge-fake", json={}).get_json()
    assert dry["dry_run"] is True and dry["건수"] == 1
    assert dry["대상"][0]["od_no"] == "TESTOD999"
    assert len(_rows(client)) == 2                      # 아직 안 지웠다

    done = client.post("/api/margin/lotteon-settlement/purge-fake",
                       json={"confirm": True}).get_json()
    assert done["deleted"] == 1
    assert set(_rows(client)) == {("20260801005", "1")}  # 실주문은 그대로
