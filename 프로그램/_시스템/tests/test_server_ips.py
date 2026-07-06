# -*- coding: utf-8 -*-
"""[TEST] 우리 서버 IP 명부 CRUD API — /accounts/api/server-ips.

팀 공유 영속화(ServerIp). 목록 조회(빈 경우 기본 서버 시드) · 추가 · 삭제 · 유효성.
격리: 기존 행을 스냅샷 후 비우고, 테스트 끝나면 원복(실데이터 보호).
"""
import os
import pathlib

import pytest
from flask import Flask

os.environ.setdefault("ENVIRONMENT", "test")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")   # accounts _admin_only 우회
    import webapp.server_ip_model  # noqa: F401  (테이블 등록)
    from shared.db import engine, SessionLocal
    from webapp.server_ip_model import ServerIp
    # 이 테이블만 생성(다른 모델의 FK 타깃 미등록 문제 회피)
    ServerIp.__table__.create(bind=engine, checkfirst=True)

    # ── 스냅샷 후 비우기 ──
    s = SessionLocal()
    snapshot = [{"name": r.name, "ip": r.ip, "sort_order": r.sort_order}
                for r in s.query(ServerIp).all()]
    s.query(ServerIp).delete(synchronize_session=False)
    s.commit()
    s.close()

    from webapp.routes import accounts as acc
    app = Flask(__name__,
                root_path=pathlib.Path(acc.__file__).parents[2].as_posix())
    app.register_blueprint(acc.bp)
    yield app.test_client()

    # ── 원복 ──
    s = SessionLocal()
    s.query(ServerIp).delete(synchronize_session=False)
    for row in snapshot:
        s.add(ServerIp(**row))
    s.commit()
    s.close()


def test_list_seeds_default_when_empty(client):
    r = client.get("/accounts/api/server-ips")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    ips = [i["ip"] for i in data["items"]]
    assert "54.116.196.90" in ips   # 업로드 서버 기본 시드


def test_add_and_list(client):
    client.get("/accounts/api/server-ips")   # seed
    r = client.post("/accounts/api/server-ips",
                    json={"name": "예비 서버", "ip": "3.35.140.22"})
    assert r.status_code == 200
    item = r.get_json()["item"]
    assert item["ip"] == "3.35.140.22"
    assert item["name"] == "예비 서버"
    assert isinstance(item["id"], int)

    r2 = client.get("/accounts/api/server-ips")
    ips = [i["ip"] for i in r2.get_json()["items"]]
    assert "3.35.140.22" in ips


def test_add_missing_ip_rejected(client):
    r = client.post("/accounts/api/server-ips", json={"name": "이름만"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_add_blank_name_ok(client):
    # 이름 없이 IP만도 허용(이름은 선택).
    r = client.post("/accounts/api/server-ips", json={"ip": "1.2.3.4"})
    assert r.status_code == 200
    assert r.get_json()["item"]["ip"] == "1.2.3.4"


def test_delete(client):
    add = client.post("/accounts/api/server-ips",
                      json={"name": "삭제대상", "ip": "9.9.9.9"}).get_json()
    sid = add["item"]["id"]
    r = client.delete(f"/accounts/api/server-ips/{sid}")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    ips = [i["ip"] for i in client.get("/accounts/api/server-ips").get_json()["items"]]
    assert "9.9.9.9" not in ips


def test_delete_missing_is_404(client):
    r = client.delete("/accounts/api/server-ips/99999999")
    assert r.status_code == 404
