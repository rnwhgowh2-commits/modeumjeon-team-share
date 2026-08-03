# -*- coding: utf-8 -*-
"""롯데온 정산 크롤 — **계정별 회차 기록**.

🔴🔴 왜 별도 표인가 (2026-08-03 사장님 질문에서 나옴)
  「계정별로 제대로 돌고 있는지, 최근 언제 됐는지 어디서 봐?」 → 볼 데가 없었다.
  회차 요약은 「7계정」·「실패 2」뿐이라 **어느 계정인지** 모른다.

  대안으로 lotteon_settlements.updated_at 을 쓸 수도 있었지만 그건 「값이 바뀐 시각」이라
  양방향으로 틀린다:
    · 로그인은 됐는데 바뀐 정산이 없으면 → 멀쩡한데 낡아 보임(거짓 경보)
    · 한 계정이 막혀도 다른 계정 값 하나만 바뀌면 → 갱신돼 경보가 안 뜸
  라이브 실측이 정확히 그 상태였다 — 화면은 「7계정 성공」인데 두 계정 시각이 7~10시간
  낡아 있었다. 짐작을 없애려면 회차 자체를 기록해야 한다.
"""
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.sourcing.models_v2 import LotteonCrawlRun
from webapp.routes import api_margin


@pytest.fixture
def client(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 'r.db'}", future=True)
    LotteonCrawlRun.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    monkeypatch.setattr(api_margin, "SessionLocal", Session)
    app = Flask(__name__)
    app.register_blueprint(api_margin.bp)
    c = app.test_client()
    c._Session = Session
    return c


def _post(c, runs):
    return c.post("/api/margin/lotteon-crawl-run", json={"runs": runs})


def test_계정별_결과가_남고_읽힌다(client):
    r = _post(client, [
        {"env_prefix": "LOTTEON_A", "tr_no": "LO111", "display_name": "브랜드박스",
         "result": "ok", "rows": 42, "deep": True},
        {"env_prefix": "LOTTEON_B", "display_name": "브랜드위시",
         "result": "verify", "detail": "본인인증 필요(새 기기·가끔)"},
    ])
    assert r.get_json() == {"ok": True, "saved": 2, "skipped": 0}

    got = {x["env_prefix"]: x for x in
           client.get("/api/margin/lotteon-crawl-run").get_json()["runs"]}
    assert got["LOTTEON_A"]["result"] == "ok" and got["LOTTEON_A"]["rows"] == 42
    assert got["LOTTEON_A"]["deep"] is True and got["LOTTEON_A"]["tr_no"] == "LO111"
    assert got["LOTTEON_B"]["result"] == "verify"
    assert "본인인증" in got["LOTTEON_B"]["detail"]
    assert got["LOTTEON_A"]["ran_at"] and got["LOTTEON_B"]["ran_at"]


def test_실패도_반드시_기록한다(client):
    """정작 알아야 하는 게 실패다 — 성공만 남기면 표가 늘 초록이다."""
    _post(client, [{"env_prefix": "LOTTEON_C", "result": "fail",
                    "detail": "[로그인] 아이디·비밀번호를 확인하세요"}])
    got = client.get("/api/margin/lotteon-crawl-run").get_json()["runs"][0]
    assert got["result"] == "fail" and "비밀번호" in got["detail"]


def test_계정당_한_행만_남는다(client):
    """화면이 묻는 건 「지금 이 계정이 되고 있나」 하나 — 이력을 쌓아도 답은 같다."""
    _post(client, [{"env_prefix": "LOTTEON_D", "result": "fail", "detail": "옛 실패"}])
    _post(client, [{"env_prefix": "LOTTEON_D", "result": "ok", "rows": 7}])
    runs = client.get("/api/margin/lotteon-crawl-run").get_json()["runs"]
    assert len(runs) == 1 and runs[0]["result"] == "ok" and runs[0]["rows"] == 7


def test_로그인_실패는_판매자ID를_지우지_않는다(client):
    """🔴 실패 회차엔 tr_no 를 모른다. 빈 값으로 덮으면 지난 회차에 알아낸 것을 잃는다."""
    _post(client, [{"env_prefix": "LOTTEON_E", "tr_no": "LO999",
                    "display_name": "브랜드조이", "result": "ok", "rows": 3}])
    _post(client, [{"env_prefix": "LOTTEON_E", "result": "fail", "detail": "로그인 실패"}])
    got = client.get("/api/margin/lotteon-crawl-run").get_json()["runs"][0]
    assert got["result"] == "fail"
    assert got["tr_no"] == "LO999" and got["display_name"] == "브랜드조이"


def test_모르는_결과값은_버리고_개수를_남긴다(client):
    """조용한 실패 금지 — 몇 건을 왜 버렸는지 응답에 남긴다."""
    r = _post(client, [
        {"env_prefix": "LOTTEON_F", "result": "성공"},       # 정해진 3값이 아님
        {"result": "ok"},                                     # 계정 식별자 없음
        {"env_prefix": "LOTTEON_G", "result": "ok"},
    ])
    assert r.get_json() == {"ok": True, "saved": 1, "skipped": 2}


def test_runs가_리스트가_아니면_400(client):
    assert client.post("/api/margin/lotteon-crawl-run", json={}).status_code == 400
