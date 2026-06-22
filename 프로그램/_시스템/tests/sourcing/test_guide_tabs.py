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


def test_tab1_flow_cards():
    html = (TPL / "map.html").read_text(encoding="utf-8")
    s1 = html.split('id="s1"')[1].split('id="s2"')[0]
    assert "크롤러" in s1 and "저장" in s1 and "계산" in s1 and "표시" in s1
    assert "compute_market_price" in s1
    assert "BG_PARSE" in s1


def test_tab2_stock_states_and_glossary():
    html = (TPL / "map.html").read_text(encoding="utf-8")
    s2 = html.split('id="s2"')[1].split('id="s3"')[0]
    assert "API 호출" in s2 and "HTML 파싱" in s2 and "DOM 읽기" in s2
    for k in ["품절", "한정", "충분", "특이사항", "옵션없음", "크롤실패"]:
        assert k in s2, k
    for src in ["무신사", "SSG", "SSF", "롯데온", "스마트", "르무통"]:
        assert src in s2, src
    assert "outOfStock" in s2 and "품절임박" in s2 and "usablInvQty" in s2


def test_tab3_price_methods():
    html = (TPL / "map.html").read_text(encoding="utf-8")
    s3 = html.split('id="s3"')[1].split('id="s4"')[0]
    assert "표면노출가" in s3 and "혜택" in s3
    assert "표면 노출가 − 혜택" in s3 or "표면노출가 − 혜택" in s3
    for src in ["무신사", "SSG", "롯데온"]:
        assert src in s3, src
    assert "api_benefits.py" in s3
