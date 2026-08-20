# -*- coding: utf-8 -*-
"""gate-preview 엔드포인트 검증 — Flask 테스트 클라이언트 (DB 없이 _source 스텁).

크롤된 혜택 라인 + 저장된 키워드 설정 → 포함/제외 판정 + 최종 매입가 를 HTTP 로 확인.
"""
import json
import pytest
from flask import Flask

from webapp.routes import sourcing_guide as sg


# 르무통 메이트 실제 혜택 라인
LINES = [
    "등급 할인 불가", "상품 쿠폰", "적립금 사용", "구매 적립 / 선할인",
    "최대 적립", "10% 추가 적립", "결제혜택",
]


class FakeSrc:
    def __init__(self, guide):
        self.id = 3
        self.name = "무신사"
        self.crawl_guide = json.dumps(guide, ensure_ascii=False)


def _b(name, triggers, match):
    """validate_guide 통과용 — apply/status 필수 필드 포함."""
    return {"name": name, "triggers": triggers, "match": match,
            "apply": "deduct", "status": "always"}


def _guide(benefits, excludes):
    return {"version": 2, "pricing": {"benefits": benefits},
            "exclude_keywords": excludes}


@pytest.fixture
def client(monkeypatch):
    # _admin_only 게이트는 ENVIRONMENT=='team-share-dev' 에서만 발동 → 테스트는 우회
    monkeypatch.setenv("ENVIRONMENT", "test")
    app = Flask(__name__)
    app.register_blueprint(sg.bp)
    return app.test_client()


def _post(client, monkeypatch, *, benefits, excludes, body):
    monkeypatch.setattr(sg, "_source", lambda sid: FakeSrc(_guide(benefits, excludes)))
    return client.post("/sourcing-guide/api/3/gate-preview",
                       data=json.dumps(body), content_type="application/json")


def test_grade_discount_excluded_by_bulga(client, monkeypatch):
    """저장된 제외 '불가' → '등급 할인 불가' 라인 veto → 등급 할인 미적용."""
    benefits = [
        _b("등급 할인", ["등급 할인"], "any"),
        _b("상품 쿠폰", ["쿠폰"], "any"),
    ]
    excludes = [{"word": "불가", "with": [], "except": []}]
    r = _post(client, monkeypatch, benefits=benefits, excludes=excludes,
              body={"benefit_lines": LINES})
    assert r.status_code == 200
    data = r.get_json()
    by = {g["name"]: g["applied"] for g in data["gated"]}
    assert by == {"등급 할인": False, "상품 쿠폰": True}


def test_any_vs_all_via_http(client, monkeypatch):
    """포함 any → 적용, all[적립+캐시백] → 미적용 (HTTP 경유 분기 확인)."""
    r_any = _post(client, monkeypatch,
                  benefits=[_b("구매적립", ["적립", "캐시백"], "any")],
                  excludes=[], body={"benefit_lines": LINES})
    r_all = _post(client, monkeypatch,
                  benefits=[_b("구매적립", ["적립", "캐시백"], "all")],
                  excludes=[], body={"benefit_lines": LINES})
    assert r_any.get_json()["gated"][0]["applied"] is True
    assert r_all.get_json()["gated"][0]["applied"] is False


def test_final_price_with_amounts(client, monkeypatch):
    """크롤 금액 동봉 시 최종 매입가까지 계산. 126,900 -5,000(쿠폰) ×0.9(적립10%) = 109,710."""
    benefits = [
        _b("등급 할인", ["등급 할인"], "any"),
        _b("상품 쿠폰", ["쿠폰"], "any"),
        _b("구매적립", ["적립"], "any"),
    ]
    excludes = [{"word": "불가", "with": [], "except": []}]
    body = {
        "benefit_lines": LINES,
        "base_price": 126900,
        "amounts": {
            "등급 할인": {"type": "amount", "value": 0},
            "상품 쿠폰": {"type": "amount", "value": 5000},
            "구매적립": {"type": "rate", "value": 0.10},
        },
    }
    r = _post(client, monkeypatch, benefits=benefits, excludes=excludes, body=body)
    data = r.get_json()
    # 126,900 - 5,000(쿠폰) = 121,900 → -12,190(10%적립) = 109,710 → 백원 버림 → 109,700
    assert data["final_price"] == 109700


def test_invalid_lines_rejected(client, monkeypatch):
    r = _post(client, monkeypatch, benefits=[], excludes=[],
              body={"benefit_lines": "not-a-list"})
    assert r.status_code == 400
