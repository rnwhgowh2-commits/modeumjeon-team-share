# -*- coding: utf-8 -*-
"""크롤링 가이드 탭 통합 — 라우트 제거 + map 7탭 + 정본 동기화 검증."""
import pathlib
import pytest
from flask import Flask
from webapp.routes import sourcing_guide as sg

TPL = pathlib.Path(sg.__file__).parent.parent / "templates" / "sourcing_guide"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")   # _admin_only 우회
    app = Flask(__name__)
    app.register_blueprint(sg.bp)
    return app.test_client()


def test_how_to_route_removed(client):
    assert client.get("/sourcing-guide/how-to").status_code == 404


def test_how_to_template_deleted():
    assert not (TPL / "how_to_add.html").exists()


def test_no_how_to_links_in_templates():
    for f in TPL.rglob("*.html"):
        assert "/sourcing-guide/how-to" not in f.read_text(encoding="utf-8"), f.name


def test_map_design_tokens():
    css = (TPL / "map.html").read_text(encoding="utf-8")
    assert "Pretendard" in css
    assert "#191F28" in css and "#6B7684" in css and "#1B64DA" in css and "#DC2626" in css
    assert "klabel" in css            # "핵심" 라벨 클래스
    assert "align-items:center" in css  # 카드 세로 중앙정렬


def test_map_has_seventh_tab():
    html = (TPL / "map.html").read_text(encoding="utf-8")
    assert 'data-s="s7"' in html
    assert "신규추가" in html
