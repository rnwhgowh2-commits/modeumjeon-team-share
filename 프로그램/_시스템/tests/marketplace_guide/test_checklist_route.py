# -*- coding: utf-8 -*-
"""개발 체크리스트 데이터 라우트."""
import pytest
from flask import Flask

from webapp.routes import marketplace_guide as mg


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")   # _admin_only 우회
    app = Flask(__name__)
    app.register_blueprint(mg.bp)
    return app.test_client()


def test_checklist_json_ok(client):
    r = client.get("/marketplace-guide/checklist.json")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["columns"]) == 25
    assert len(data["rows"]) == 6
    assert len(data["cells"]) == 150


def test_every_cell_has_the_keys_the_screen_reads(client):
    """화면 조각이 읽는 키가 하나라도 빠지면 정보창이 백지가 된다."""
    data = client.get("/marketplace-guide/checklist.json").get_json()
    need = ("state", "spec", "required", "evidence", "note",
            "wiring", "wiring_note", "api", "conflict", "verified")
    for key, cell in data["cells"].items():
        for k in need:
            assert k in cell, f"{key} 에 {k} 없음"


def test_cell_key_is_market_then_column(client):
    """키를 뒤집으면 화면 조회가 전부 빗나가는데 개수는 그대로라 안 잡힌다."""
    data = client.get("/marketplace-guide/checklist.json").get_json()
    assert "smartstore:5" in data["cells"]
    assert "5:smartstore" not in data["cells"]


def test_drift_banner_is_carried_to_the_screen(client, monkeypatch):
    """🔴 배너가 화면까지 안 가면, 거짓 검증완료를 아무도 못 본다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "load_marks",
                        lambda name="dev_checklist_marks.json":
                        ({"smartstore:2": {"verified": "2026-08-12"}}, ""))
    data = client.get("/marketplace-guide/checklist.json").get_json()
    assert data["drift"], "배너가 화면까지 안 왔다"
    assert "상품명" in data["drift"][0]


def test_stored_only_cells_exist(client):
    """정책값 대부분이 저장만 되는 현실이 표에 그대로 드러나야 한다."""
    data = client.get("/marketplace-guide/checklist.json").get_json()
    assert sum(1 for c in data["cells"].values() if c["state"] == "stored") > 0
