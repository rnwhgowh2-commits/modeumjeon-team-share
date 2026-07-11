# -*- coding: utf-8 -*-
"""margin 탭 화면 — 렌더 + 정적파일 로드 + 서브탭 자리."""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_margin_tab_renders(client):
    r = client.get("/orders/?tab=margin")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="margin-app"' in html


def test_left_subnav_has_11_slots(client):
    html = client.get("/orders/?tab=margin").get_data(as_text=True)
    for label in ("요약", "전체내역", "일별", "월별", "브랜드별", "금액대별",
                  "상품별", "마켓별", "소싱처별"):
        assert label in html, label
    # 준비중 2개 자리
    assert "블랙스팟" in html and "설정" in html
    assert html.count('data-mtab=') >= 9


def test_static_assets_referenced(client):
    html = client.get("/orders/?tab=margin").get_data(as_text=True)
    assert "margin_rules.js" in html
    assert "margin_app.js" in html
    assert "margin.css" in html


def test_upload_steps_present(client):
    html = client.get("/orders/?tab=margin").get_data(as_text=True)
    assert "더망고" in html      # ① 엑셀
    assert "분석 시작" in html     # ④ 분석 버튼
