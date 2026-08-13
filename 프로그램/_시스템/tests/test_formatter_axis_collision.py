# -*- coding: utf-8 -*-
"""마켓에 **같은 옵션 이름 두 줄**이 올라가는 것을 막는다 (2026-08-13).

왜 이 시험이 있나
  마켓 전송은 옵션 이름을 `색상 + 사이즈` 두 칸으로만 만든다
  (`formatter/esm.py`·`coupang.py`·`lotteon.py`).
  모델모음전 3축(모델·색상·사이즈)은 모델 값이 그 두 칸 어디에도 안 들어가서,
  **모델이 달라도 (색상,사이즈)가 같으면 마켓 옵션 이름이 똑같아진다.**
      메이트 블랙 250 →  「블랙 250」
      스위트 블랙 250 →  「블랙 250」   ← 손님이 못 고르고, 주문이 어느 모델인지 모른다

  🔴 만드는 단계는 멀쩡하다(축 값·SKU·옵션명 전부 다르다). **전송에서만** 겹친다.
     그래서 만들기를 막지 않고 **전송을 막는다** — 위험이 있는 자리에 막이를 둔다.
     「마켓별 옵션 1/2/3축 구성 정책」(상품가공)이 생기면 이 막이는 풀린다.

  재고 확인 불가 때와 같은 처방이다 — 틀린 값을 보내느니 그 옵션만 보류한다.
"""
import os

os.environ.setdefault("ENVIRONMENT", "test")

import pytest

from lemouton.formatter.pipeline import run_formatter


class _Opt:
    def __init__(self, sku, color, size, oid):
        self.canonical_sku = sku
        self.model_code = "모델모음전"
        self.color_code = color
        self.color_display = color
        self.size_code = size
        self.size_display = size
        self.lemouton_only = False
        self.naver_option_id = oid
        self.coupang_option_id = None
        self.lotteon_option_id = None
        self.auction_option_id = None
        self.gmarket_option_id = None


class _Model:
    model_code = "모델모음전"
    model_name_display = "모델모음전"
    naver_product_id = 55555
    coupang_product_id = None
    lotteon_product_id = None
    auction_product_id = None
    gmarket_product_id = None
    naver_product_name_override = None
    coupang_product_name_override = None


def _run(monkeypatch, opts):
    """opts = {sku: (색상, 사이즈, 옵션ID)}"""
    import lemouton.formatter.pipeline as P
    monkeypatch.setattr(P, "get_option_by_canonical",
                        lambda s, sku: _Opt(sku, *opts[sku]))
    monkeypatch.setattr(P, "get_model", lambda s, code: _Model())
    a = {sku: {"boxhero_stock": 5, "boxhero_purchase_price": None, "sources": []}
         for sku in opts}
    b = {"decisions": {sku: {"ss": {"displayed": True, "price": 50000}} for sku in opts},
         "alerts": []}
    return run_formatter(None, a, b)


def _names(r):
    p = r.get("smartstore", {}).get("모델모음전")
    return [o["option_name"] for o in p["options"]] if p else []


def test_같은_옵션이름_두_줄은_마켓에_안_올라간다(monkeypatch):
    """🔴 모델만 다른 두 옵션 — 마켓 이름이 둘 다 「블랙 250」이 된다."""
    r = _run(monkeypatch, {"SKU-M1": ("블랙", "250", 1001),
                           "SKU-M2": ("블랙", "250", 1002)})
    names = _names(r)
    assert len(names) == len(set(names)), f"같은 이름이 두 줄 올라갔다: {names}"


def test_왜_막았는지_알려_준다(monkeypatch):
    """조용히 빼면 「왜 안 올라갔지」가 된다 — 사유를 남긴다."""
    r = _run(monkeypatch, {"SKU-M1": ("블랙", "250", 1001),
                           "SKU-M2": ("블랙", "250", 1002)})
    kinds = [a.get("type") for a in r["alerts"]]
    assert "option_name_collision" in kinds, r["alerts"]
    msg = " ".join(str(a.get("message", "")) for a in r["alerts"])
    assert "옵션 이름" in msg and ("모델" in msg or "축" in msg), msg


def test_안_겹치면_예전_그대로_다_올라간다(monkeypatch):
    """겹치지 않는 보통 상품(색상모음전)은 하나도 안 막힌다 — 회귀 방지."""
    r = _run(monkeypatch, {"SKU-A": ("블랙", "250", 1001),
                           "SKU-B": ("블랙", "260", 1002),
                           "SKU-C": ("크림", "250", 1003)})
    assert len(_names(r)) == 3
    assert not [a for a in r["alerts"] if a.get("type") == "option_name_collision"]
