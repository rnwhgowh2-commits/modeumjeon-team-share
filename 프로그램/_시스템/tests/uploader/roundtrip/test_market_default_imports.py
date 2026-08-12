# -*- coding: utf-8 -*-
"""각 마켓 어댑터의 **기본 함수 import 경로가 진짜로 있는지** 검사한다.

[2026-08-12 라이브] 11번가 왕복 첫 시도가 이걸로 죽었다:
    ImportError: cannot import name 'get_product_price'
                 from 'shared.platforms.eleven11.prices'
`get_product_price` 는 `prices.py` 가 아니라 `products.py` 에 있었다.

🔴 왜 시험이 못 잡았나 — 단위시험이 함수를 **전부 주입**해서 어댑터가 기본 경로를
   한 번도 밟지 않았다. 「시험은 통과하는데 라이브에서 죽는」 전형이다.
   (feedback_test_that_tests_nothing: 시험 대상이 없으면 시험은 아무것도 안 본다)

여기서는 주입하지 않고 **import 자체만** 확인한다 — 마켓에 아무것도 보내지 않는다.
"""
from __future__ import annotations

import importlib

import pytest

#: (모듈, 함수) — 어댑터가 주입 없이 기본으로 집어 오는 함수들.
DEFAULTS = [
    # 11번가
    ("shared.platforms.eleven11.products", "get_product_price"),
    ("shared.platforms.eleven11.stocks_query", "get_stocks"),
    ("shared.platforms.eleven11.prices", "update_price"),
    ("shared.platforms.eleven11.inventory", "update_stock_by_stock_no"),
    # 옥션·G마켓
    ("shared.platforms.esm.prices", "update_price"),
    ("shared.platforms.esm.inventory", "update_stock"),
    ("shared.platforms.esm.inventory", "update_base_stock"),
    ("shared.platforms.esm.inventory", "_find_option_details"),
    ("shared.platforms.esm.inventory", "_option_id_of"),
    ("shared.platforms.esm.inventory", "_ci_get"),
    # 롯데온
    ("shared.platforms.lotteon.prices", "update_prices"),
    ("shared.platforms.lotteon.inventory", "update_stocks"),
]


@pytest.mark.parametrize("module_path,func_name", DEFAULTS)
def test_어댑터가_기본으로_쓰는_함수가_실제로_있다(module_path, func_name):
    mod = importlib.import_module(module_path)

    assert hasattr(mod, func_name), (
        f"{module_path} 에 {func_name} 이 없다 — 어댑터가 라이브에서 ImportError 로 죽는다")


def test_11번가_어댑터가_주입_없이_되읽기를_시도한다():
    """주입을 빼고 실제 기본 경로를 태운다. 통신은 가짜 client 가 막는다.

    ImportError 는 통과시키지 않고, 통신 실패(우리가 만든 가짜)만 허용한다.
    """
    from lemouton.uploader.roundtrip.markets.eleven11 import make_eleven11_ops

    class DeadClient:
        def request(self, *a, **kw):
            raise ConnectionError("시험용 — 실제로 나가지 않는다")

    # 되읽기가 예외를 삼켜 '확인불가'로 만드는 게 정상이다.
    # 여기서 ImportError 가 나면 예외를 삼키기 전에 터진다 → 시험이 잡는다.
    snap = make_eleven11_ops("P1", client=DeadClient()).snapshot()

    assert snap.value_of("sale_price") is None
    assert "stock" in snap.missing
