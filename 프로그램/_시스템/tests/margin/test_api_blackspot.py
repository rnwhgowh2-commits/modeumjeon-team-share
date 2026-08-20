# -*- coding: utf-8 -*-
r"""/api/blackspot/fetch_order_no 라우트 — 소싱처 주문번호 추출(순수 파싱, 브라우저 없음).

페이지(orders/margin_embed.html)의 [🔍 소싱처] 버튼이 {uid, memo} 를 POST 하면
UI 계약 {success, order_no, site_key, site_name, account_id, source, logs[], error}
를 돌려준다. 무상태 서버라 matched_count/missing_count 는 만들지 않는다(거짓 숫자 금지).
"""
import pathlib

import pytest
from flask import Flask

from webapp.routes import api_blackspot


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(api_blackspot.bp)
    app.config["TESTING"] = True
    return app.test_client()


def test_success_text_memo(client):
    """메모에 주문번호 명시 → success + source=메모텍스트, UI 계약 필드 전부 존재."""
    r = client.post("/api/blackspot/fetch_order_no",
                    json={"uid": "m_0", "memo": "무신사 주문번호 : 202508031019270004 계정 무신사/rnwhgowh2"})
    assert r.status_code == 200
    b = r.get_json()
    for k in ("success", "order_no", "site_key", "site_name", "account_id", "source", "logs", "error"):
        assert k in b, k
    assert b["success"] is True
    assert b["order_no"] == "202508031019270004"
    assert b["source"] == "메모텍스트"
    assert b["site_key"] == "musinsa"
    assert isinstance(b["logs"], list) and b["logs"]


def test_success_url_template(client):
    """소싱처 주문상세 URL 매칭 → success + source=URL파싱."""
    r = client.post("/api/blackspot/fetch_order_no",
                    json={"uid": "m_1",
                          "memo": "26.04.14 무신사 / rnwhgowh1 https://www.musinsa.com/order/order-detail/ORD9911"})
    b = r.get_json()
    assert b["success"] is True
    assert b["order_no"] == "ORD9911"
    assert b["source"] == "URL파싱"


def test_failure_no_extractable(client):
    """URL 은 있으나 주문번호 추출 불가 → 정직한 실패(수동 입력 필요)."""
    r = client.post("/api/blackspot/fetch_order_no",
                    json={"uid": "m_2", "memo": "무신사 https://www.musinsa.com/"})
    b = r.get_json()
    assert b["success"] is False
    assert "수동 입력 필요" in b["error"]


def test_empty_memo(client):
    """memo 미동봉(씨앗 미적용 캐시 등) → '간단메모 비어있음' 정직한 실패(거짓 성공 금지)."""
    r = client.post("/api/blackspot/fetch_order_no", json={"uid": "m_3"})
    b = r.get_json()
    assert b["success"] is False
    assert b["error"] == "간단메모 비어있음"


def test_no_fabricated_counts(client):
    """무상태 서버 → matched_count/missing_count 를 만들어내지 않는다."""
    r = client.post("/api/blackspot/fetch_order_no",
                    json={"uid": "m_4", "memo": "주문번호: ABC123456"})
    b = r.get_json()
    assert "matched_count" not in b
    assert "missing_count" not in b


def test_manual_order_no_honest_unsupported_stub(client):
    """[✏️ 반영] → /api/blackspot/manual_order_no: 재매칭은 미지원이므로 200 + success:false
    + 명확한 안내(404 raw 실패로 사용자 혼란시키지 않음, 재매칭 꾸며내지 않음)."""
    r = client.post("/api/blackspot/manual_order_no",
                    json={"uid": "m_0", "site_order_no": "202508031019270004"})
    assert r.status_code == 200
    b = r.get_json()
    assert b["success"] is False
    assert "아직 지원되지 않습니다" in b["error"]
    # 거짓 재매칭 숫자를 만들어내지 않는다.
    assert "matched_count" not in b
    assert "missing_count" not in b


def test_route_registered_at_exact_literal_path():
    """리터럴 경로가 정확히 /api/blackspot/fetch_order_no 로 매핑된다(페이지가 하드코딩)."""
    app = Flask(__name__)
    app.register_blueprint(api_blackspot.bp)
    rules = [r.rule for r in app.url_map.iter_rules()
             if r.endpoint != "static"]
    assert "/api/blackspot/fetch_order_no" in rules
    # 그 경로에 매핑된 규칙이 정확히 하나(중복 없음)
    dupe = [r for r in rules if r == "/api/blackspot/fetch_order_no"]
    assert len(dupe) == 1


def test_no_route_collision_in_full_app_registration():
    """전체 라우트 등록 소스에서 /api/blackspot/fetch_order_no 를 정의하는 곳은
    api_blackspot 한 곳뿐(다른 blueprint 와 경로 충돌 없음)."""
    routes_dir = pathlib.Path(api_blackspot.__file__).resolve().parent
    hits = []
    for p in routes_dir.glob("*.py"):
        txt = p.read_text(encoding="utf-8")
        if "fetch_order_no" in txt and 'route(' in txt:
            # 라우트 규칙 문자열로 등장하는 파일만
            if '"/fetch_order_no"' in txt or "'/fetch_order_no'" in txt \
               or "/blackspot/fetch_order_no" in txt:
                hits.append(p.name)
    assert hits == ["api_blackspot.py"], f"경로 정의가 여러 곳: {hits}"
