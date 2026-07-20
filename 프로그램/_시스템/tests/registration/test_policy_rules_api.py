# -*- coding: utf-8 -*-
"""가공정책 상세 — 13항목 폼 API (스키마 · 규칙 조회 · 저장).

화면은 스키마에서 폼을 그린다. 손으로 짠 폼 13개가 아니라서 화면과 저장이 안 어긋난다.
"""
import uuid

import pytest

_MARK = "규칙API"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import ProcessPolicy
    s = SessionLocal()
    try:
        for p in s.query(ProcessPolicy).all():
            if p.name and p.name.startswith(_MARK):
                s.delete(p)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _policy(client):
    nm = f"{_MARK}-{uuid.uuid4().hex[:8]}"
    return client.post('/bulk/api/process/policies', json={"name": nm}).get_json()["id"]


# ── 스키마 ──────────────────────────────────────────────────────

def test_스키마_API가_13항목을_준다(client):
    j = client.get('/bulk/api/process/schema').get_json()
    assert len(j["items"]) == 13


def test_항목마다_설계서_근거가_붙어_있다(client):
    """화면에 「§7-10」이 뜨면 근거를 바로 찾을 수 있다."""
    for it in client.get('/bulk/api/process/schema').get_json()["items"]:
        assert it["spec_ref"].startswith("§7")


def test_칸마다_형과_기본값이_있다(client):
    for it in client.get('/bulk/api/process/schema').get_json()["items"]:
        for f in it["fields"]:
            assert f["type"] in ("bool", "int", "text", "choice", "list")
            assert "default" in f


# ── 규칙 조회 ───────────────────────────────────────────────────

def test_저장_전에도_13칸이_다_온다(client):
    """빈 정책이어도 화면이 13칸을 그릴 수 있어야 한다 — 기본값으로 채워 준다."""
    j = client.get(f'/bulk/api/process/policies/{_policy(client)}/rules').get_json()
    assert len(j["rules"]) == 13
    assert j["saved_keys"] == []


def test_설계서_기본값이_그대로_온다(client):
    r = client.get(f'/bulk/api/process/policies/{_policy(client)}/rules').get_json()["rules"]
    assert r["shipping"]["return_fee"] == 5000
    assert r["shipping"]["jeju_extra"] == 3000
    assert r["shipping"]["ship_days"] == 3
    assert r["name"]["max_len"] == 100


def test_없는_정책은_404(client):
    assert client.get('/bulk/api/process/policies/9999999/rules').status_code == 404


# ── 저장 ────────────────────────────────────────────────────────

def test_항목을_저장한다(client):
    pid = _policy(client)
    r = client.post(f'/bulk/api/process/policies/{pid}/rules',
                    json={"item_key": "shipping", "config": {"return_fee": 3000}})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    got = client.get(f'/bulk/api/process/policies/{pid}/rules').get_json()
    assert got["rules"]["shipping"]["return_fee"] == 3000
    assert got["rules"]["shipping"]["jeju_extra"] == 3000     # 안 건드린 칸은 기본값
    assert "shipping" in got["saved_keys"]


def test_모르는_칸은_400과_사유(client):
    r = client.post(f'/bulk/api/process/policies/{_policy(client)}/rules',
                    json={"item_key": "shipping", "config": {"retrun_fee": 3000}})
    assert r.status_code == 400
    assert "retrun_fee" in r.get_json()["error"]


def test_모르는_항목도_400(client):
    r = client.post(f'/bulk/api/process/policies/{_policy(client)}/rules',
                    json={"item_key": "nmae", "config": {}})
    assert r.status_code == 400


# ── 🔴 마켓별 덮어쓰기 ──────────────────────────────────────────

def test_마켓별로_다르게_저장된다(client):
    """「스스는 100자, 쿠팡은 50자」."""
    pid = _policy(client)
    client.post(f'/bulk/api/process/policies/{pid}/rules',
                json={"item_key": "name", "config": {"max_len": 100}})
    client.post(f'/bulk/api/process/policies/{pid}/rules',
                json={"item_key": "name", "config": {"max_len": 50}, "market": "coupang"})

    ss = client.get(f'/bulk/api/process/policies/{pid}/rules?market=smartstore').get_json()
    cp = client.get(f'/bulk/api/process/policies/{pid}/rules?market=coupang').get_json()
    assert ss["rules"]["name"]["max_len"] == 100
    assert cp["rules"]["name"]["max_len"] == 50


def test_마켓별로_고쳐도_다른_항목은_공통을_쓴다(client):
    pid = _policy(client)
    client.post(f'/bulk/api/process/policies/{pid}/rules',
                json={"item_key": "shipping", "config": {"return_fee": 7000}})
    client.post(f'/bulk/api/process/policies/{pid}/rules',
                json={"item_key": "name", "config": {"max_len": 50}, "market": "coupang"})
    cp = client.get(f'/bulk/api/process/policies/{pid}/rules?market=coupang').get_json()
    assert cp["rules"]["name"]["max_len"] == 50        # 마켓별
    assert cp["rules"]["shipping"]["return_fee"] == 7000   # 공통


# ── 상세 페이지 ─────────────────────────────────────────────────

def test_상세_페이지에_폼이_들어간다(client):
    html = client.get(f'/bulk/process/policy/{_policy(client)}').get_data(as_text=True)
    assert 'pd-rules' in html
    assert '모든 마켓 공통' in html
