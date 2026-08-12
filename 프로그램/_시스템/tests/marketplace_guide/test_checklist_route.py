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


# ── 화면 조각 (_checklist_matrix.html) ──────────────────────────────────
# 🔴 아래 시험들은 「그 글자가 파일에 있나」만 센다 — 깨진 채로도 통과한다.
#    진짜 검증은 라이브 실화면 측정이다. 그래도 빠뜨림은 이 그물이 막는다.
import pathlib

TPL = pathlib.Path(mg.__file__).parents[1] / "templates"


def _matrix():
    return (TPL / "_checklist_matrix.html").read_text(encoding="utf-8")


def test_first_column_is_sticky():
    html = _matrix()
    assert "position:sticky" in html and "left:0" in html


def test_numbers_use_tabular_nums():
    assert "tabular-nums" in _matrix()


def test_hover_card_lives_on_body_and_is_fixed():
    html = _matrix()
    assert "document.body.appendChild" in html
    assert "position:fixed" in html


def test_hover_delays_match_standard():
    html = _matrix().replace(" ", "")
    assert "OPEN_DELAY=140" in html
    assert "CLOSE_DELAY=250" in html


def test_hover_closes_on_scroll():
    assert "'scroll'" in _matrix() or '"scroll"' in _matrix()


def test_six_states_are_labelled_in_korean():
    html = _matrix()
    for word in ["미착수", "저장만", "나감", "검증완료", "불가", "해당없음"]:
        assert word in html, word


def test_wired_and_done_are_not_the_same_colour():
    """🔴 지금 done 은 0칸이고 wired 가 22칸이다. 둘을 합치면 아무도 확인 안 한 것이 검증완료로 보인다."""
    html = _matrix()
    assert "wired" in html and "done" in html
    import re
    m = re.search(r"wired[^\n]{0,120}", html)
    assert m and "done" not in m.group(0), "wired 와 done 이 한 줄에서 같이 처리된다"


def test_wiring_none_is_handled_separately():
    """🔴 wiring 이 3값이다. 뭉뚱그리면 칸조차 없는 12칸이 「저장은 된다」로 뜬다."""
    assert "'none'" in _matrix() or '"none"' in _matrix()


def test_drift_banner_is_rendered():
    """🔴 배너가 안 그려지면 거짓 검증완료를 아무도 못 본다."""
    assert "drift" in _matrix()


def test_contract_functions_are_exposed():
    html = _matrix()
    assert "window.CHECKLIST_HTML" in html
    assert "window.ckInit" in html


def test_pop_and_panel_have_different_outer_names():
    html = _matrix()
    assert "ckpop" in html and "ckpanel" in html
