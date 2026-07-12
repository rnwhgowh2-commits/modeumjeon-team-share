# -*- coding: utf-8 -*-
"""/api/sourcing-sites + /api/settings 라우트 (Task D3).

이식된 마진 계산기 페이지(margin_embed.html ⚙️설정 → 소싱처 계정 관리)의
원본 HTTP 계약을 그대로 만족시키되, 저장소만 원본의 서버측 settings.json(평문)
→ 모음전 기존 자격증명 DB(SourcingCredential) 로 승격한다.

원본 계약 (C:/dev/대량등록 마진계산기/app.py 1633–1671):
  · GET  /api/sourcing-sites → {<site>: {name, login_methods, login_method_labels}}
  · GET  /api/settings       → {accounts: {<site>: [{id, pw(마스킹), ...}]}}
  · POST /api/settings       → {accounts: {...}}; pw 가 마스킹 값이면 기존 pw 유지.

페이지 마스킹 sentinel = '***' (margin_embed.html line 2528: acc.pw === '***').
"""
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import shared.db as shared_db
from lemouton.sourcing.models_v2 import SourcingCredential
from lemouton.margin.models import SourcingAccountOwner
from lemouton.auth import sourcing_credentials as sc
from lemouton.margin import sourcing_owner_store
from webapp.routes import api_sourcing_settings as mod

PW_MASK = "***"


@pytest.fixture
def client(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    SourcingCredential.__table__.create(eng, checkfirst=True)
    SourcingAccountOwner.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    # 스토어는 호출 시점에 `from shared.db import SessionLocal` 로 읽는다 → 속성 패치로 충분.
    monkeypatch.setattr(shared_db, "SessionLocal", Session)

    app = Flask(__name__)
    app.register_blueprint(mod.bp)
    app.config["TESTING"] = True
    c = app.test_client()
    c._Session = Session
    return c


def _seed(source, account_key, id_value, pw_value, login_method="direct"):
    sc.default_store().upsert(
        source=source, account_key=account_key,
        id_value=id_value, pw_value=pw_value, login_method=login_method,
    )


# ── 라우트 경로 (리터럴 /api) ──────────────────────────────────────
def test_routes_are_literal_api_paths(client):
    methods = {}
    for r in client.application.url_map.iter_rules():
        methods.setdefault(r.rule, set()).update(r.methods)
    assert "/api/sourcing-sites" in methods
    assert "/api/settings" in methods
    assert "GET" in methods["/api/sourcing-sites"]
    assert "GET" in methods["/api/settings"]
    assert "POST" in methods["/api/settings"]


# ── GET /api/sourcing-sites ────────────────────────────────────────
def test_sourcing_sites_shape(client):
    r = client.get("/api/sourcing-sites")
    assert r.status_code == 200
    body = r.get_json()
    assert isinstance(body, dict)
    assert "musinsa" in body
    site = body["musinsa"]
    assert set(site.keys()) >= {"name", "login_methods", "login_method_labels"}
    assert isinstance(site["login_methods"], list)
    assert "direct" in site["login_methods"]
    # 라벨 map 은 login_methods 를 모두 커버
    for m in site["login_methods"]:
        assert m in site["login_method_labels"]


def test_sourcing_sites_naver_derived(client):
    # ssg 는 supports_naver=True → login_methods 에 naver 포함
    body = client.get("/api/sourcing-sites").get_json()
    assert "naver" in body["ssg"]["login_methods"]
    assert body["ssg"]["login_method_labels"]["naver"]  # 라벨 존재


# ── GET /api/settings ──────────────────────────────────────────────
def test_settings_get_empty_when_no_creds(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.get_json() == {"accounts": {}}


def test_settings_get_masks_pw(client):
    _seed("musinsa", "default", "user1", "secret-pw")
    body = client.get("/api/settings").get_json()
    accs = body["accounts"]["musinsa"]
    assert len(accs) == 1
    assert accs[0]["id"] == "user1"
    assert accs[0]["pw"] == PW_MASK          # 실제 pw 노출 금지
    assert accs[0]["login_method"] == "direct"
    assert "secret-pw" not in str(body)      # 어디에도 평문 없음


# ── POST /api/settings ─────────────────────────────────────────────
def test_post_saves_to_store_visible_in_fresh_session(client):
    payload = {"accounts": {"musinsa": [
        {"id": "buyerA", "pw": "pwA", "owner": "영빈", "login_method": "direct"},
    ]}}
    r = client.post("/api/settings", json=payload)
    assert r.status_code == 200
    assert r.get_json().get("success") is True
    # 팀 공유 영속 증명 — 새 스토어/세션이 값을 본다.
    allc = sc.default_store().load_all()
    assert allc["musinsa"]["default"]["id"] == "buyerA"
    assert allc["musinsa"]["default"]["pw"] == "pwA"


def test_post_masked_pw_preserves_existing(client):
    _seed("musinsa", "default", "user1", "secret-pw")
    # GET → 마스킹된 상태를 그대로 다시 POST (사용자가 pw 안 건드림)
    body = client.get("/api/settings").get_json()
    assert body["accounts"]["musinsa"][0]["pw"] == PW_MASK
    r = client.post("/api/settings", json=body)
    assert r.status_code == 200
    # 기존 pw 유지 — 마스킹 값이 실제 pw 를 덮어쓰지 않음
    assert sc.default_store().load_all()["musinsa"]["default"]["pw"] == "secret-pw"


def test_post_new_real_pw_overwrites(client):
    _seed("musinsa", "default", "user1", "old-pw")
    body = client.get("/api/settings").get_json()
    body["accounts"]["musinsa"][0]["pw"] = "new-pw"   # 사용자가 새 pw 입력
    r = client.post("/api/settings", json=body)
    assert r.status_code == 200
    assert sc.default_store().load_all()["musinsa"]["default"]["pw"] == "new-pw"


def test_post_removes_account_deleted_from_list(client):
    _seed("musinsa", "default", "userA", "pwA")
    _seed("musinsa", "_2", "userB", "pwB")
    body = client.get("/api/settings").get_json()
    accs = body["accounts"]["musinsa"]
    assert len(accs) == 2
    # 첫 계정(userA)만 남기고 저장 → userB 제거
    kept = [a for a in accs if a["id"] == "userA"]
    body["accounts"]["musinsa"] = kept
    r = client.post("/api/settings", json=body)
    assert r.status_code == 200
    allc = sc.default_store().load_all()
    ids = {c["id"] for c in allc.get("musinsa", {}).values()}
    assert ids == {"userA"}


def test_post_adds_second_account_gets_stable_key(client):
    _seed("musinsa", "default", "userA", "pwA")
    body = client.get("/api/settings").get_json()
    body["accounts"]["musinsa"].append(
        {"id": "userB", "pw": "pwB", "owner": "", "login_method": "direct"})
    r = client.post("/api/settings", json=body)
    assert r.status_code == 200
    allc = sc.default_store().load_all()["musinsa"]
    assert len(allc) == 2
    ids = {c["id"] for c in allc.values()}
    assert ids == {"userA", "userB"}
    # 기존 계정은 default 키 유지
    assert allc["default"]["id"] == "userA"


def test_post_blank_row_not_persisted(client):
    payload = {"accounts": {"musinsa": [
        {"id": "", "pw": "", "owner": "", "login_method": "direct"},
    ]}}
    r = client.post("/api/settings", json=payload)
    assert r.status_code == 200
    assert sc.default_store().load_all() == {}


def test_post_id_without_pw_is_400(client):
    # id 는 있는데 pw 가 비어있음(마스킹도 아님) → 저장 불가, 조용한 실패 금지 → 400.
    payload = {"accounts": {"musinsa": [
        {"id": "userX", "pw": "", "owner": "", "login_method": "direct"},
    ]}}
    r = client.post("/api/settings", json=payload)
    assert r.status_code == 400
    # 아무것도 저장되지 않음(원자성)
    assert sc.default_store().load_all() == {}


def test_post_unknown_source_is_400(client):
    payload = {"accounts": {"__nope__": [
        {"id": "x", "pw": "y", "owner": "", "login_method": "direct"},
    ]}}
    r = client.post("/api/settings", json=payload)
    assert r.status_code == 400


def test_post_non_dict_accounts_400(client):
    r = client.post("/api/settings", json={"accounts": [1, 2, 3]})
    assert r.status_code == 400


# ── owner(담당자) round-trip — 사이드 테이블 SourcingAccountOwner ──────
def test_post_owner_persists_and_roundtrips(client):
    payload = {"accounts": {"musinsa": [
        {"id": "buyerA", "pw": "pwA", "owner": "홍길동", "login_method": "direct"},
    ]}}
    assert client.post("/api/settings", json=payload).status_code == 200
    body = client.get("/api/settings").get_json()
    assert body["accounts"]["musinsa"][0]["owner"] == "홍길동"
    # 새 세션(팀 공유 영속)도 본다
    assert sourcing_owner_store.load_all()["musinsa"]["default"] == "홍길동"


def test_post_clear_owner_persists_empty(client):
    client.post("/api/settings", json={"accounts": {"musinsa": [
        {"id": "buyerA", "pw": "pwA", "owner": "홍길동", "login_method": "direct"}]}})
    # 마스킹 pw 그대로 두고 owner 만 비움
    body = client.get("/api/settings").get_json()
    body["accounts"]["musinsa"][0]["owner"] = ""
    assert client.post("/api/settings", json=body).status_code == 200
    after = client.get("/api/settings").get_json()
    assert after["accounts"]["musinsa"][0]["owner"] == ""
    # 빈 값 → 행 제거(빈 행 축적 방지)
    assert sourcing_owner_store.load_all().get("musinsa", {}) == {}


def test_removing_account_removes_owner_row(client):
    client.post("/api/settings", json={"accounts": {"musinsa": [
        {"id": "buyerA", "pw": "pwA", "owner": "홍길동", "login_method": "direct"}]}})
    assert sourcing_owner_store.load_all()["musinsa"]["default"] == "홍길동"
    # 계정을 리스트에서 제거 → owner 행도 제거
    assert client.post("/api/settings", json={"accounts": {"musinsa": []}}).status_code == 200
    s2 = client._Session()
    try:
        assert s2.query(SourcingAccountOwner).count() == 0  # 새 세션이 사라진 것을 본다
    finally:
        s2.close()
