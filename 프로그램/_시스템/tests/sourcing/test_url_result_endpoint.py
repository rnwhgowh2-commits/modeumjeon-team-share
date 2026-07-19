# -*- coding: utf-8 -*-
"""[S5] POST /sourcing-guide/api/<sid>/url-result — 주소 1건 크롤 결과 접수.

확장이 로컬에서 긁은 raw 결과를 받아 계산하고 sample_urls[i].result 에 넣는다.
산수는 guide_url_result 가 하고(거기서 전수 검증), 여기서는 **배선**만 본다.

가장 중요한 것 — 이 라우트는 가이드 JSON 말고 **아무것도 건드리면 안 된다**.
실상품 크롤 데이터(/api/sources/crawl-result 경로)를 이 버튼이 덮어쓰면
지도에서 예시 주소 하나 눌렀다가 매트릭스 가격이 바뀌는 사고가 난다.
"""
import json
import os

import pytest

from lemouton.sourcing import crawl_guide as cg
from lemouton.sourcing.models import SourcingSource
from shared.db import SessionLocal

_TMPL_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "webapp", "templates")
)

LABEL = "테스트S5소싱처"
URL_A = "https://example.com/p/1"
URL_B = "https://example.com/p/2"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    for _m in ("lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
               "lemouton.sources.models", "lemouton.templates.models",
               "lemouton.inventory.models", "lemouton.mapping.models",
               "webapp.icon_store_model"):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()

    from flask import Flask
    from webapp.routes import sourcing_guide as sg
    app = Flask(__name__, template_folder=_TMPL_DIR)
    app.register_blueprint(sg.bp)
    app.config.update(TESTING=True)
    return app.test_client()


def _guide_json(benefits=()):
    g = cg.empty_skeleton()
    g["sample_urls"] = [{"url": URL_A, "is_lead": True, "name": "기본", "memo": ""},
                        {"url": URL_B, "is_lead": False, "name": "", "memo": ""}]
    g["pricing"] = {"benefits": list(benefits)}
    return cg.dumps(cg.validate_guide(g))


@pytest.fixture
def sid(benefits=()):
    """테스트용 소싱처 1개 — 예시 주소 2건이 들어 있다."""
    s = SessionLocal()
    try:
        for r in s.query(SourcingSource).filter_by(label=LABEL).all():
            s.delete(r)
        s.commit()
        src = SourcingSource(source_key="tests5", label=LABEL, domain="example.com",
                             crawl_guide=_guide_json([
                                 {"name": "제휴 할인", "apply": "deduct", "status": "always",
                                  "method": "정액(원)", "value": 3000,
                                  "value_source": "fixed", "triggers": [], "match": "any"},
                             ]))
        s.add(src)
        s.commit()
        out = src.id
    finally:
        s.close()
    yield out
    s = SessionLocal()
    try:
        for r in s.query(SourcingSource).filter_by(label=LABEL).all():
            s.delete(r)
        s.commit()
    finally:
        s.close()


def _guide_of(sid):
    s = SessionLocal()
    try:
        return cg.loads(s.query(SourcingSource).get(sid).crawl_guide)
    finally:
        s.close()


def _post(client, sid, body):
    return client.post(f"/sourcing-guide/api/{sid}/url-result",
                       data=json.dumps(body), content_type="application/json")


# ── 정상 경로 ──────────────────────────────────────────────────────────────

def test_saves_result_on_matching_url(client, sid):
    r = _post(client, sid, {"url": URL_A,
                            "raw": {"status": "ok", "price": 100000, "stock": 999}})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["result"]["final_price"] == 97000

    saved = _guide_of(sid)["sample_urls"]
    assert saved[0]["result"]["final_price"] == 97000
    assert saved[0]["result"]["surface_price"] == 100000
    assert saved[0]["result"]["stock_label"] == "재고 있음"
    assert saved[0]["result"]["status"] == "done"


def test_only_the_matching_url_is_touched(client, sid):
    """다른 주소의 결과는 건드리지 않는다."""
    _post(client, sid, {"url": URL_A, "raw": {"status": "ok", "price": 100000}})
    saved = _guide_of(sid)["sample_urls"]
    assert saved[0]["result"] is not None
    assert saved[1]["result"] is None


def test_failed_crawl_is_recorded_with_reason(client, sid):
    """실패도 저장한다 — 눌렀는데 아무 일도 안 난 것처럼 두지 않는다."""
    r = _post(client, sid, {"url": URL_A,
                            "raw": {"status": "error", "error": "로그인이 풀렸습니다"}})
    assert r.status_code == 200
    saved = _guide_of(sid)["sample_urls"][0]["result"]
    assert saved["status"] == "failed"
    assert saved["error"] == "로그인이 풀렸습니다"
    assert saved["final_price"] is None


def test_recrawl_overwrites_previous_result(client, sid):
    _post(client, sid, {"url": URL_A, "raw": {"status": "ok", "price": 100000}})
    _post(client, sid, {"url": URL_A, "raw": {"status": "ok", "price": 200000}})
    saved = _guide_of(sid)["sample_urls"][0]["result"]
    assert saved["surface_price"] == 200000


# ── 나머지 가이드가 날아가지 않는다 ────────────────────────────────────────

def test_other_guide_content_survives(client, sid):
    """결과만 얹는다 — 혜택·주소 목록이 사라지면 안 된다."""
    before = _guide_of(sid)
    _post(client, sid, {"url": URL_A, "raw": {"status": "ok", "price": 100000}})
    after = _guide_of(sid)
    assert [u["url"] for u in after["sample_urls"]] == [u["url"] for u in before["sample_urls"]]
    assert after["pricing"]["benefits"] == before["pricing"]["benefits"]
    assert after["sample_urls"][0]["name"] == "기본"
    assert after["sample_urls"][0]["is_lead"] is True


# ── 거절 ───────────────────────────────────────────────────────────────────

def test_unknown_url_is_rejected(client, sid):
    """가이드에 없는 주소는 받지 않는다 — 아무 URL 결과나 꽂히면 안 된다."""
    r = _post(client, sid, {"url": "https://evil.example.com/x",
                            "raw": {"status": "ok", "price": 100000}})
    assert r.status_code == 404


def test_missing_raw_is_rejected(client, sid):
    r = _post(client, sid, {"url": URL_A})
    assert r.status_code == 400


def test_unknown_source_is_404(client):
    r = _post(client, 99999999, {"url": URL_A, "raw": {"status": "ok", "price": 1}})
    assert r.status_code == 404
