# -*- coding: utf-8 -*-
"""판매처 계정 등록 — 계정명 중복 판정은 '마켓 안에서만'.

사고: 쿠팡에 「브랜드위시」가 있으면 옥션에 「브랜드위시」를 못 만들었다
(2026-07-20, ESM 옥션 키 등록 중 발견). 사장님 입장에서 마켓이 다르면
완전히 다른 계정이므로 같은 이름을 쓸 수 있어야 한다.

원인: UploadAccount.account_key 에 DB 전역 UNIQUE 제약이 걸려 있는데,
등록 모달이 account_key 를 계정명 그대로("브랜드위시") 만들어 보냈다.
(빠른 추가 경로는 이미 "{별칭}_{market}" 규칙을 지키고 있었다 — 모달만 예외)

규칙
  · 같은 마켓 + 같은 계정명 → 409 거부 (사용자가 둘을 구분할 수 없음)
  · 다른 마켓 + 같은 계정명 → 허용. account_key 는 내부 슬러그이므로
    마켓 접미사를 붙여 전역 유일성을 유지한다.
"""
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.sourcing.models_v2 import UploadAccount
from webapp.routes import accounts as mod


@pytest.fixture
def client(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    UploadAccount.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    # accounts.py 는 `from shared.db import SessionLocal` 로 모듈에 바인딩 → 모듈 속성 패치.
    monkeypatch.setattr(mod, "SessionLocal", Session)
    monkeypatch.setenv("DISABLE_AUTH", "1")   # before_request(admin 전용) 통과

    app = Flask(__name__)
    app.register_blueprint(mod.bp)
    app.config["TESTING"] = True
    with app.test_client() as c:
        c._Session = Session
        yield c


def _create(client, name, market, prefix):
    return client.post("/accounts/api/upload/accounts", json={
        "account_key": name,          # 모달이 보내는 형태 = 계정명 그대로
        "display_name": name,
        "market": market,
        "env_prefix": prefix,
    })


def test_같은_계정명이라도_마켓이_다르면_등록된다(client):
    r1 = _create(client, "브랜드위시", "coupang", "COUPANG_MAIN")
    assert r1.status_code == 200, r1.get_json()

    r2 = _create(client, "브랜드위시", "auction", "AUCTION_MAIN")
    assert r2.status_code == 200, r2.get_json()

    # 화면에 보이는 이름은 그대로 유지되어야 한다.
    s = client._Session()
    try:
        names = {(a.market, a.display_name) for a in s.query(UploadAccount).all()}
        keys = [a.account_key for a in s.query(UploadAccount).all()]
    finally:
        s.close()
    assert names == {("coupang", "브랜드위시"), ("auction", "브랜드위시")}
    # 내부 슬러그는 전역 UNIQUE 라 서로 달라야 한다.
    assert len(set(keys)) == 2, keys


def test_같은_마켓_같은_계정명은_거부된다(client):
    assert _create(client, "브랜드위시", "auction", "AUCTION_MAIN").status_code == 200
    r = _create(client, "브랜드위시", "auction", "AUCTION_2")
    assert r.status_code == 409
    assert "브랜드위시" in r.get_json()["error"]


def test_응답의_account_key_는_실제_저장값과_같다(client):
    _create(client, "브랜드위시", "coupang", "COUPANG_MAIN")
    r = _create(client, "브랜드위시", "gmarket", "GMARKET_MAIN")
    returned = r.get_json()["account_key"]

    s = client._Session()
    try:
        acc = s.query(UploadAccount).filter_by(market="gmarket").one()
    finally:
        s.close()
    assert returned == acc.account_key


def _rename(client, account_id, new_name):
    return client.patch(f"/accounts/api/upload/accounts/{account_id}",
                        json={"display_name": new_name})


def test_이름수정도_다른_마켓과_같은_이름이면_허용된다(client):
    _create(client, "브랜드위시", "coupang", "COUPANG_MAIN")
    aid = _create(client, "브랙드웍스", "auction", "AUCTION_MAIN").get_json()["id"]

    r = _rename(client, aid, "브랜드위시")   # 쿠팡에 같은 이름이 있어도 마켓이 다르므로 OK
    assert r.status_code == 200, r.get_json()

    s = client._Session()
    try:
        assert s.query(UploadAccount).filter_by(market="auction").one().display_name == "브랜드위시"
    finally:
        s.close()


def test_이름수정으로_같은_마켓_안에서_동명계정을_만들_수_없다(client):
    """같은 마켓에 같은 이름 둘 = 화면에서 구분 불가 + 업로드 계정 오해석 위험."""
    _create(client, "가게A", "auction", "AUCTION_MAIN")
    bid = _create(client, "가게B", "auction", "AUCTION_2").get_json()["id"]

    r = _rename(client, bid, "가게A")
    assert r.status_code == 409, r.get_json()

    s = client._Session()
    try:  # 거부됐으니 이름이 그대로여야 한다
        assert s.query(UploadAccount).get(bid).display_name == "가게B"
    finally:
        s.close()


def test_자기_이름_그대로_저장은_막지_않는다(client):
    aid = _create(client, "가게A", "auction", "AUCTION_MAIN").get_json()["id"]
    assert _rename(client, aid, "가게A").status_code == 200


def test_env_prefix_중복은_계속_막는다(client):
    """마켓별 키 분리 장치(env_prefix)는 완화 대상이 아니다 — 키 누출 방지."""
    assert _create(client, "가게A", "auction", "AUCTION_MAIN").status_code == 200
    r = _create(client, "가게B", "auction", "AUCTION_MAIN")
    assert r.status_code == 409
    assert "env_prefix" in r.get_json()["error"]
