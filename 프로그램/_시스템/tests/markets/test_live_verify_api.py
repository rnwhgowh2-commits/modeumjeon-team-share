# -*- coding: utf-8 -*-
"""판매처관리 「🧪 라이브 검증」 API.

흐름
  1. POST .../verify-live          — 실주문을 불러와 자동판정 + 샘플 3건 반환. **기록 안 함**
  2. 사장님이 마켓 화면과 대조
  3. POST .../verify-live/confirm  — 「맞음」. 이때만 검증 기록이 저장되고 마켓이 열린다

원칙
  · 주문 0건 = 대조할 게 없음 → '확인 불가'. 통과시키지 않는다(폴백·추측 금지).
  · 필수 항목(주문번호·주문일·상품명·단가)이 비면 자동판정 실패 → 사장님이 「맞음」을
    눌러도 저장 거부. 깨진 숫자가 주문내역·마진계산기로 들어가는 걸 막는다.
"""
import datetime as _dt

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import shared.db as shared_db
from lemouton.markets import order_export as oe
from lemouton.sourcing.models_v2 import UploadAccount
from webapp.routes import accounts as mod


def _row(ono="A123", name="테스트상품", price="19900"):
    return {"오픈마켓주문번호": ono, "주문일": "2026-07-19 10:00", "상품명": name,
            "단가": price, "수량": "1", "주문상태": "결제완료", "수령자": "홍길동"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    UploadAccount.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    monkeypatch.setattr(mod, "SessionLocal", Session)
    monkeypatch.setattr(shared_db, "SessionLocal", Session)   # 게이트(order_export)도 같은 DB
    monkeypatch.setenv("DISABLE_AUTH", "1")

    s = Session()
    try:
        s.add(UploadAccount(account_key="가게A_auction", display_name="가게A",
                            market="auction", env_prefix="AUCTION_MAIN", is_active=True))
        s.commit()
    finally:
        s.close()

    app = Flask(__name__)
    app.register_blueprint(mod.bp)
    app.config["TESTING"] = True
    with app.test_client() as c:
        c._Session = Session
        yield c


def _stub_fetch(monkeypatch, rows, claim_wired=True):
    monkeypatch.setattr(mod, "_live_verify_fetch", lambda market, prefix, days=7: rows)
    # 대부분의 테스트는 '클레임 조회가 붙은 뒤'의 정상 동작을 검증한다.
    # 미배선 차단 자체는 아래 test_클레임_미배선이면_통과시키지_않는다 가 본다.
    monkeypatch.setattr(mod, "_ESM_CLAIM_WIRED", claim_wired)


def test_주문이_있으면_건수와_샘플을_돌려준다(client, monkeypatch):
    _stub_fetch(monkeypatch, [_row(f"A{i}") for i in range(5)])
    d = client.post("/accounts/api/upload/accounts/1/verify-live").get_json()
    assert d["ok"] is True and d["auto_pass"] is True
    assert d["count"] == 5
    assert len(d["samples"]) == 3            # 샘플은 최대 3건
    assert d["samples"][0]["주문번호"] == "A0"


def test_검증만으로는_기록되지_않는다(client, monkeypatch):
    """대조 전에 열리면 안 된다 — confirm 이 있어야 저장."""
    _stub_fetch(monkeypatch, [_row()])
    client.post("/accounts/api/upload/accounts/1/verify-live")
    s = client._Session()
    try:
        assert s.query(UploadAccount).get(1).live_verified_at is None
    finally:
        s.close()
    assert "auction" not in oe.supported_markets()


def test_주문_0건은_확인불가로_통과시키지_않는다(client, monkeypatch):
    _stub_fetch(monkeypatch, [])
    d = client.post("/accounts/api/upload/accounts/1/verify-live").get_json()
    assert d["auto_pass"] is False
    assert "확인 불가" in " ".join(d["issues"])


def test_필수항목이_비면_자동판정_실패(client, monkeypatch):
    _stub_fetch(monkeypatch, [_row(), {**_row(), "단가": ""}])
    d = client.post("/accounts/api/upload/accounts/1/verify-live").get_json()
    assert d["auto_pass"] is False
    assert any("단가" in x for x in d["issues"])


def test_확인을_누르면_기록되고_마켓이_열린다(client, monkeypatch):
    _stub_fetch(monkeypatch, [_row()])
    client.post("/accounts/api/upload/accounts/1/verify-live")
    r = client.post("/accounts/api/upload/accounts/1/verify-live/confirm", json={"count": 1})
    assert r.status_code == 200, r.get_json()

    s = client._Session()
    try:
        acc = s.query(UploadAccount).get(1)
        assert acc.live_verified_at is not None and acc.live_verified_count == 1
    finally:
        s.close()
    assert "auction" in oe.supported_markets()


def test_자동판정_실패면_확인을_눌러도_저장되지_않는다(client, monkeypatch):
    _stub_fetch(monkeypatch, [])
    client.post("/accounts/api/upload/accounts/1/verify-live")
    r = client.post("/accounts/api/upload/accounts/1/verify-live/confirm", json={"count": 0})
    assert r.status_code == 409

    s = client._Session()
    try:
        assert s.query(UploadAccount).get(1).live_verified_at is None
    finally:
        s.close()


def test_검증대상이_아닌_마켓은_거부된다(client, monkeypatch):
    """쿠팡 등 이미 열린 마켓에 이 버튼을 쓸 이유가 없다(오조작 방지)."""
    s = client._Session()
    try:
        s.add(UploadAccount(account_key="쿠팡A_coupang", display_name="쿠팡A",
                            market="coupang", env_prefix="COUPANG_MAIN", is_active=True))
        s.commit()
        cid = s.query(UploadAccount).filter_by(market="coupang").one().id
    finally:
        s.close()
    r = client.post(f"/accounts/api/upload/accounts/{cid}/verify-live")
    assert r.status_code == 400


def test_없는_계정은_404(client):
    assert client.post("/accounts/api/upload/accounts/999/verify-live").status_code == 404


def test_클레임_미배선_플래그가_꺼지면_다시_차단된다(client, monkeypatch):
    """클레임 배선을 되돌리면(플래그 OFF) 다시 잠겨야 한다.

    2026-07-20 현재는 배선 완료라 플래그가 True 지만, 배선이 깨지거나 되돌려졌을 때
    검증이 그대로 통과해버리면 취소·반품이 빠진 숫자가 공개된다 — 그 안전장치 검증.
    """
    _stub_fetch(monkeypatch, [_row()], claim_wired=False)
    d = client.post("/accounts/api/upload/accounts/1/verify-live").get_json()
    assert d["count"] == 1                      # 정상 주문은 잘 들어옴
    assert d["auto_pass"] is False              # 그래도 통과시키지 않는다
    assert any("취소·반품" in x for x in d["issues"])


def test_클레임_미배선_플래그_OFF_면_확인을_눌러도_저장되지_않는다(client, monkeypatch):
    _stub_fetch(monkeypatch, [_row()], claim_wired=False)
    r = client.post("/accounts/api/upload/accounts/1/verify-live/confirm", json={})
    assert r.status_code == 409
    s = client._Session()
    try:
        assert s.query(UploadAccount).get(1).live_verified_at is None
    finally:
        s.close()
    assert "auction" not in oe.supported_markets()
