# -*- coding: utf-8 -*-
"""스마트스토어 옵션 파싱 실패가 success=True 로 위장되지 않고 표면화되는지 (#12)."""
from shared.platforms.smartstore.get_options import fetch_product_options


class _Client:
    def __init__(self, resp):
        self._resp = resp

    def request(self, method, path):
        return self._resp


def _resp(combinations):
    return {"originProduct": {"name": "P", "salePrice": 140000,
            "detailAttribute": {"optionInfo": {"optionCombinations": combinations}}}}


def test_all_options_parse_ok():
    resp = _resp([
        {"id": 1, "optionName1": "블랙", "optionName2": "230", "stockQuantity": 5, "price": 0, "usable": True},
        {"id": 2, "optionName1": "블랙", "optionName2": "240", "stockQuantity": 3, "price": 0, "usable": True},
    ])
    r = fetch_product_options(123, client=_Client(resp))
    assert r.success
    assert len(r.options) == 2
    assert r.parse_failed == 0
    assert r.combinations_total == 2


def test_partial_parse_failure_is_surfaced():
    resp = _resp([
        {"id": 1, "optionName1": "블랙", "optionName2": "230", "stockQuantity": 5, "price": 0, "usable": True},
        {"id": 2, "optionName1": "블랙", "optionName2": "240", "stockQuantity": "broken", "price": 0, "usable": True},
    ])
    r = fetch_product_options(123, client=_Client(resp))
    # HTTP 성공 + 파싱된 옵션은 사용하되, 실패 건수를 반드시 표면화
    assert len(r.options) == 1
    assert r.parse_failed == 1
    assert r.combinations_total == 2
