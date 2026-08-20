# -*- coding: utf-8 -*-
"""주문 내역 화면 설정 저장 — 열 순서·너비·빠른 기간·엑셀 양식 (팀 공유).

사장님(2026-08-12): "기간 직접 만들었는데 자꾸 사라져. 프로그램 재배포 때문인건지?"

🔴 원인은 재배포가 아니었다 — 브라우저 안(localStorage)에만 있었다(라이브 확인:
   빠른 기간·열 구성·엑셀 양식 셋 다 「없음」). 서버로 옮기되, 컨테이너 data/ 는
   **진짜로 배포마다 사라지므로** state_store(호스트 마운트)를 쓴다.
"""
import pathlib

import webapp.routes.orders as om


def _client():
    from flask import Flask
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


def test_처음엔_비어_있고_기본값을_지어내지_않는다(monkeypatch, tmp_path):
    """기본값은 화면이 안다 — 서버가 또 만들면 두 곳이 갈린다."""
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    j = _client().get("/orders/api/view-prefs").get_json()
    assert j["ok"] and j["prefs"] == {}


def test_저장하고_다시_받으면_그대로다(monkeypatch, tmp_path):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    c = _client()
    q = [{"name": "최근 3일", "kind": "lastN", "n": 3, "def": True}]
    assert c.post("/orders/api/view-prefs", json={"quick": q}).status_code == 200
    assert c.get("/orders/api/view-prefs").get_json()["prefs"]["quick"] == q


def test_보낸_칸만_덮어쓴다(monkeypatch, tmp_path):
    """🔴 열 너비만 보냈는데 빠른 기간이 같이 지워지면 사장님은
    「고쳤더니 딴 게 사라졌다」를 겪는다."""
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    c = _client()
    c.post("/orders/api/view-prefs", json={"quick": [{"name": "오늘", "kind": "today"}]})
    c.post("/orders/api/view-prefs", json={"widths": {"상품명": 320}})
    p = c.get("/orders/api/view-prefs").get_json()["prefs"]
    assert p["widths"] == {"상품명": 320}
    assert p["quick"][0]["name"] == "오늘", "빠른 기간이 같이 지워졌습니다"


def test_모르는_칸은_저장하지_않는다(monkeypatch, tmp_path):
    """화면이 아무거나 밀어 넣어 상태 파일이 붓지 않게 — 저장은 화이트리스트."""
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    c = _client()
    c.post("/orders/api/view-prefs", json={"widths": {"a": 1}, "이상한칸": [1, 2, 3]})
    assert "이상한칸" not in c.get("/orders/api/view-prefs").get_json()["prefs"]


def test_None_은_그_칸을_지운다(monkeypatch, tmp_path):
    """「기본값으로 되돌리기」 — 지우는 길이 없으면 한번 고치면 못 돌아온다."""
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    c = _client()
    c.post("/orders/api/view-prefs", json={"widths": {"상품명": 320}})
    c.post("/orders/api/view-prefs", json={"widths": None})
    assert "widths" not in c.get("/orders/api/view-prefs").get_json()["prefs"]


def test_너무_큰_값은_거부한다(monkeypatch, tmp_path):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    c = _client()
    r = c.post("/orders/api/view-prefs", json={"widths": {"x" * 300000: 1}})
    assert r.status_code == 400 and not r.get_json()["ok"]


def test_배포를_견디는_자리에_쓴다(monkeypatch, tmp_path):
    """🔴 컨테이너 data/ 에 두면 **배포마다 사라진다** — 그러면 사장님이 신고하신
    증상이 이번엔 진짜로 재배포 탓이 된다(CLAUDE.md)."""
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    from lemouton.markets import order_view_prefs as vp
    vp.save({"widths": {"상품명": 100}})
    assert (tmp_path / "order_view_prefs.json").exists(), \
        "state_store 가 아닌 곳에 저장했습니다"
