# -*- coding: utf-8 -*-
"""포매터 재고 배선 회귀 시험 — 크롤 재고가 실제로 payload 까지 실리는지.

이 배선이 끊겨 있어서 「상품수집&전송」 보내기가 전 옵션에 재고 0(품절)을
보내고 있었다(2026-08-06 실측). 단위 규칙(test_stock_policy_send.py)만으로는
같은 사고를 다시 못 잡는다 — 실제로 payload 에 실리는지를 여기서 고정한다.
"""
import os

os.environ.setdefault("ENVIRONMENT", "test")

import pytest

from lemouton.formatter.pipeline import run_formatter


class _FakeOption:
    def __init__(self, sku, model_code):
        self.canonical_sku = sku
        self.model_code = model_code
        self.color_code = "블랙"
        self.color_display = "블랙"
        self.size_code = "250"
        self.size_display = "250"
        self.lemouton_only = False
        self.naver_option_id = 1001
        self.coupang_option_id = None
        self.lotteon_option_id = None
        self.auction_option_id = None
        self.gmarket_option_id = None


class _FakeModel:
    model_code = "테스트모델"
    model_name_display = "테스트모델"
    naver_product_id = 55555
    coupang_product_id = None
    lotteon_product_id = None
    auction_product_id = None
    gmarket_product_id = None
    naver_product_name_override = None
    coupang_product_name_override = None


@pytest.fixture()
def patched(monkeypatch):
    """DB 없이 포매터만 돌린다 — 마스터 조회 2개만 가짜로."""
    import lemouton.formatter.pipeline as P
    monkeypatch.setattr(P, "get_option_by_canonical",
                        lambda s, sku: _FakeOption(sku, "테스트모델"))
    monkeypatch.setattr(P, "get_model", lambda s, code: _FakeModel())
    return None


def _b_output(sku, price=50000):
    return {"decisions": {sku: {"ss": {"displayed": True, "price": price}}},
            "alerts": []}


def _ss_stock(result, sku):
    payload = result["smartstore"]["테스트모델"]
    for o in payload["options"]:
        if o["option_id"] == 1001:
            return o["stock"]
    raise AssertionError(f"{sku} 옵션이 payload 에 없음")


def test_내재고_0이어도_크롤재고가_payload에_실린다(patched):
    """무재고 상품 — 이 시험이 깨지면 마켓이 통째로 품절된다."""
    sku = "SKU-TESTAAA1"
    a = {sku: {"boxhero_stock": 0, "boxhero_purchase_price": None,
               "sources": [{"name": "무신사", "stock": 6, "price": 40000}]}}
    r = run_formatter(None, a, _b_output(sku))
    assert _ss_stock(r, sku) == 6


def test_내재고와_크롤재고가_합산된다(patched):
    sku = "SKU-TESTAAA2"
    a = {sku: {"boxhero_stock": 3, "boxhero_purchase_price": None,
               "sources": [{"name": "무신사", "stock": 4, "price": 40000}]}}
    r = run_formatter(None, a, _b_output(sku))
    assert _ss_stock(r, sku) == 7


def test_상한_100_이_payload에도_적용된다(patched):
    sku = "SKU-TESTAAA3"
    a = {sku: {"boxhero_stock": 0, "boxhero_purchase_price": None,
               "sources": [{"name": "무신사", "stock": 900, "price": 40000}]}}
    r = run_formatter(None, a, _b_output(sku))
    assert _ss_stock(r, sku) == 100


def test_확인불가면_그_옵션은_전송에서_빠지고_알림이_남는다(patched):
    """0(품절)을 보내는 대신 아예 안 보낸다."""
    sku = "SKU-TESTAAA4"
    a = {sku: {"boxhero_stock": 0, "boxhero_purchase_price": None,
               "sources": [{"name": "무신사", "stock": None, "price": 40000}]}}
    r = run_formatter(None, a, _b_output(sku))
    assert r["smartstore"] == {}      # 모델 통째로 후보 없음
    holds = [x for x in r["alerts"] if x.get("type") == "stock_unknown_hold"]
    assert len(holds) == 1
    assert holds[0]["canonical_sku"] == sku
