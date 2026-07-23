# -*- coding: utf-8 -*-
"""샵마인 대조탭 — 라우트(run/latest, 지난번 대비)·템플릿 계약."""
import pathlib

import flask
import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import lemouton.markets.models_orders  # noqa: F401
import lemouton.markets.models_shopmine  # noqa: F401
from webapp.routes import orders as om
from lemouton.markets import shopmine_recon as R

TPL = pathlib.Path(om.__file__).parents[1] / "templates"


@pytest.fixture
def client(monkeypatch):
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
        Base.metadata.tables["shopmine_recon_runs"],
    ])
    Maker = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(om, "SessionLocal", Maker)
    # 실 엑셀 파싱은 엔진 테스트가 커버 — 라우트는 파싱 결과를 주입해 검증
    monkeypatch.setattr(R, "parse_master", lambda raw: [{
        "market": "coupang", "mall": "06.쿠팡", "sm_alias": "계정1",
        "order_no": "A1", "sm_uid": "u1", "order_date": "2026-04-22",
        "product": "상품", "option": "블랙", "qty": 1, "unit": 32400,
        "opt_add": 0, "paid": 32400, "ship": 0, "settle_incl": 28000,
        "fee": 4400, "status": "정산완료"}])
    app = flask.Flask(__name__, template_folder=str(TPL))
    app.register_blueprint(om.bp)
    return app.test_client()


def _upload(client):
    import io as _io
    return client.post("/orders/shopmine-recon/run", data={
        "file": (_io.BytesIO(b"stub"), "master.xls")})


def test_run_requires_file(client):
    r = client.post("/orders/shopmine-recon/run")
    assert r.status_code == 400 and not r.get_json()["ok"]


def test_run_reconciles_and_persists(client):
    j = _upload(client).get_json()
    assert j["ok"]
    # 빈 적재 → 존재 0/1, 누락 1 (정직 — 조용한 성공 금지)
    assert j["summary"]["existence"] == {"total": 1, "found": 0, "missing": 1}
    assert j["detail"]["missing"][0]["order_no"] == "A1"
    assert j["prev"] is None                      # 첫 실행 = 지난번 없음


def test_second_run_carries_prev_summary(client):
    _upload(client)
    j = _upload(client).get_json()
    assert j["ok"] and j["prev"] is not None
    assert j["prev"]["existence"]["missing"] == 1  # 지난번 대비 재료


def test_latest_returns_last_run(client):
    assert client.get("/orders/shopmine-recon/latest").get_json()["latest"] is None
    _upload(client)
    j = client.get("/orders/shopmine-recon/latest").get_json()
    assert j["ok"] and j["latest"]["summary"]["sm_rows"] == 1
    assert j["latest"]["detail"]["missing"]


def test_recon_subtab_registered_and_renders():
    assert any(t["key"] == "recon" for t in om.SUBTABS)
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(str(TPL)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    html = env.get_template("orders/index.html").render(
        tab="recon", subtabs=om.SUBTABS, active="orders_recon", cfg=None)
    assert 'id="smr-file"' in html                 # 업로드 입력
    assert 'shopmine-recon/run' in html            # 대조 실행 배선
    assert 'shopmine-recon/latest' in html         # 초기 로드 배선
    assert '판정불가' in html and '정의·허용차이' in html   # 3분류 어휘
