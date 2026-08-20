# -*- coding: utf-8 -*-
"""보내기 경로가 **적용 카드를 무시하고 마켓을 이진으로 갈랐던 것**(2026-08-13).

`webapp/routes/sets_api.py` 의 `_new_values_for_options` 한 dict 안에 결함이 둘 있었다.

🔴 ① 적용 카드 무시 — 재고는 「어느 카드가 적용됐나」(`purchase_priority_resolved`)를
   보는데 **가격은 안 본다.** 사입이 적용된 옵션에도 소싱 카드 가격(`cp_price`)이 나간다.
   매트릭스는 `pur_cp_price` 를 따로 주고 있는데 안 쓴다.
   → `preview.py` 머리말이 못 박은 「표시가 = 업로드가」가 이 지점에서 깨진다.
   → 쿠팡은 실전송이 열려 있어 **지금 실제로 나가는 값**이다.

🔴 ② 마켓 이진 else — `market=="smartstore"` 가 아니면 **전부 쿠팡 가격**을 준다.
   수수료가 마켓마다 다르다(스스 6% · 쿠팡 11.55% · 롯데온 18% · 11번가 11% ·
   옥션/G마켓 15% — `pricing/unified.py:257`). 롯데온이 11.55% 기준 가격을 받는다.
   지금은 롯데온 실전송이 잠겨 있어 손해가 안 났지만, 그 잠금을 푸는 순간 터진다.
   → 모르는 마켓은 **지어내지 않고 None**(전송 보류)으로 둔다. 같은 파일의 기존
     「가격을 못 정했어요」 보류가 그대로 잡아 준다.
"""
from __future__ import annotations

import pytest

from webapp.routes import sets_api


_OPT_SRC = {
    "sku": "SKU1", "purchase_priority_resolved": "source",
    "src_stock_qty": 7, "purchase_stock": 3,
    "ss_price": 10000, "cp_price": 11000,
    "pur_ss_price": 8000, "pur_cp_price": 8800,
    "is_active": True,
}
_OPT_PUR = dict(_OPT_SRC, purchase_priority_resolved="purchase")


def _fake_matrix(opt):
    return lambda mc: {"ok": True, "options": [opt]}


def _values(monkeypatch, opt, market):
    import webapp.routes.api_pricing as AP
    monkeypatch.setattr(AP, "_option_matrix_data", _fake_matrix(opt))
    return sets_api._new_values_for_options({"M1"}, {"SKU1"}, market)["SKU1"]


# ── ① 적용 카드 ──────────────────────────────────────────────────────────────
def test_소싱이_적용된_옵션은_소싱_가격이_나간다(monkeypatch):
    v = _values(monkeypatch, _OPT_SRC, "coupang")

    assert v["price"] == 11000
    assert v["stock"] == 7


def test_사입이_적용된_옵션은_사입_가격이_나간다(monkeypatch):
    """🔴 재고만 적용 카드를 보고 가격은 안 봤다 — 표시가와 전송가가 갈렸다."""
    v = _values(monkeypatch, _OPT_PUR, "coupang")

    assert v["stock"] == 3, "재고는 원래 맞았다"
    assert v["price"] == 8800, f"사입 적용인데 소싱 가격이 나간다: {v['price']}"


def test_스마트스토어도_적용_카드를_따른다(monkeypatch):
    v = _values(monkeypatch, _OPT_PUR, "smartstore")

    assert v["price"] == 8000


# ── ② 마켓 이진 else ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("market", ["lotteon", "eleven11", "auction", "gmarket"])
def test_칸이_없는_마켓은_쿠팡_가격을_지어내지_않는다(monkeypatch, market):
    """수수료가 다르다 — 쿠팡 기준 가격을 물려주면 그 차이만큼 손해다.

    모르면 None(보류). 같은 파일의 「가격을 못 정했어요」 보류가 잡는다.
    """
    v = _values(monkeypatch, _OPT_SRC, market)

    assert v["price"] is None, \
        f"{market} 에 쿠팡 가격 {v['price']} 를 지어내 보낸다"


def test_재고는_마켓과_무관하게_그대로_준다(monkeypatch):
    """가격을 보류해도 재고까지 막지는 않는다 — 서로 다른 축이다."""
    v = _values(monkeypatch, _OPT_SRC, "lotteon")

    assert v["stock"] == 7
