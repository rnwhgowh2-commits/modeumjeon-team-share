# -*- coding: utf-8 -*-
"""Task C1+C2 — /orders/margin-embed 바레 라우트: 원본 풀페이지 무수정 이식 + 엔드포인트 재배선."""
import re

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_bare_route_200(client):
    r = client.get("/orders/margin-embed")
    assert r.status_code == 200


def test_sameorigin_header(client):
    r = client.get("/orders/margin-embed")
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"


def test_serves_original_page_signatures(client):
    """원본 페이지의 서명 마커 — 무수정 이식 확인(내 재구현 _margin.html 이 아님)."""
    html = client.get("/orders/margin-embed").get_data(as_text=True)
    # 원본 렌더/분류 함수명 — 재구현본엔 없는 원본 고유 문자열
    assert "_getRowsByCardFilter_internal" in html
    assert "renderBlackspot" in html
    assert "_getCardKeywords" in html


def test_standalone_not_base_shell(client):
    """base.html 셸(사이드바)을 확장하지 않는 원본 풀페이지여야 한다."""
    html = client.get("/orders/margin-embed").get_data(as_text=True)
    # 원본은 자체 <html>/<body> 를 가진 완결 문서 (모음전 사이드바 마커 없음)
    # [2026-07-31] <body> 에 디자인 타입 클래스가 붙는다 — 태그는 그대로 하나뿐이다.
    # [2026-08-01] <html> 에 디자인 타입 클래스가 붙는다 — 태그는 그대로 하나뿐이다.
    assert re.search(r'<html lang="ko"[^>]*>', html), '완결 문서가 아니다'
    assert html.count("<html") == 1
    assert re.search(r'<body[^>]*>', html), '완결 문서가 아니다 — body 가 없다'
    assert html.count('<body') == 1
    # 모음전 사이드바 셸 마커가 없어야 함 (base.html 미확장 증거)
    assert 'id="sidebar"' not in html


def test_디자인타입이_이_화면에도_걸린다(client):
    """사장님 지적 — 검정 타입인데 마진계산기만 흰 디자인이던 문제.

    이 화면은 base.html 을 안 써서 ds 클래스도 tokens.css 도 없었다.
    빌드가 넣어 준 두 가지가 실제로 응답에 나오는지 본다.
    """
    html = client.get("/orders/margin-embed").get_data(as_text=True)
    assert 'tokens.css' in html, '토큰 CSS 가 안 실렸다 — 어두운 타입이 안 걸린다'
    assert 'margin_embed_ds.css' in html
    m = re.search(r'<body class="([^"]*)"', html)
    assert m, 'body 에 디자인 타입 클래스 자리가 없다'


def test_endpoints_rewired_to_api_margin(client):
    html = client.get("/orders/margin-embed").get_data(as_text=True)
    assert "'/api/margin/analyze'" in html
    assert "/api/margin/upload" in html
    assert "'/api/margin/export'" in html
    # 2026-09: 매출 보조 엑셀 업로드(전 마켓 API 연동 완료로 폐지) 엔드포인트는
    # 더 이상 화면에 없어야 한다.
    assert "upload-shopmine" not in html


def test_no_bare_original_endpoints(client):
    """원본 바레 엔드포인트가 남아있지 않아야 한다(재배선 누락 방지)."""
    html = client.get("/orders/margin-embed").get_data(as_text=True)
    assert "fetch('/api/analyze'" not in html
    assert "fetch('/api/upload'" not in html
    assert "fetch('/api/download'" not in html


def test_asset_ref_points_to_ported_static(client):
    html = client.get("/orders/margin-embed").get_data(as_text=True)
    # url_for('static', filename='margin_rules.js') 가 해석된 경로
    assert "/static/margin_rules.js" in html
    # 원본의 js/ 하위경로가 남아있지 않아야 함
    assert "js/margin_rules.js" not in html


def test_card_keyword_default_renders(client):
    """_getCardKeywords 내장 default 로 카드가 분석 전에도 렌더 가능해야 한다."""
    html = client.get("/orders/margin-embed").get_data(as_text=True)
    # 내장 default 카드 키 (index.html 5702~5710)
    assert "confirmed_blackspot" in html
    assert "tracking_failed" in html
