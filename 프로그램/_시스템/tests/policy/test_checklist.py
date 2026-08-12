# -*- coding: utf-8 -*-
"""개발 체크리스트 — 열 정의와 셀 판정."""
import pytest

from lemouton.policy import checklist as C


def _cols():
    return {"columns": C.load_columns()}


def test_columns_are_25():
    cols = _cols()["columns"]
    assert len(cols) == 25, f"엑셀 Sheet2 는 B~Z 25열이다 (지금 {len(cols)})"


def test_every_column_has_required_keys():
    for c in _cols()["columns"]:
        for k in ("col", "group", "name", "rule", "item", "specs"):
            assert k in c, f"{c.get('name')} 에 {k} 없음"


def test_specs_cover_six_markets():
    markets = {"coupang", "smartstore", "lotteon", "eleven11", "auction", "gmarket"}
    for c in _cols()["columns"]:
        assert set(c["specs"]) == markets, f"{c['name']} 의 마켓 목록이 다름"


def test_item_maps_to_real_policy_item_or_none():
    from lemouton.registration.process_policy import ITEM_KEYS
    for c in _cols()["columns"]:
        if c["item"] is not None:
            assert c["item"] in ITEM_KEYS, f"{c['name']} → 없는 항목 {c['item']}"


def test_price_column_carries_owner_rule():
    """사장님이 엑셀에 적어 두신 「▶」 기준이 살아 있어야 한다."""
    price = [c for c in _cols()["columns"] if c["item"] == "price"][0]
    assert "할인가" in price["rule"] and "마진율" in price["rule"]


def test_specs_are_not_all_empty():
    """열마다 적어도 한 마켓에는 실제 내용이 있어야 한다 — 엑셀을 헛읽으면 여기서 걸린다."""
    for c in _cols()["columns"]:
        assert any(v.strip() for v in c["specs"].values()), f"{c['name']} 의 마켓 값이 전부 비었다"


def test_column_numbers_are_unique():
    """col 로 열을 찾는 코드가 나중에 생긴다 — 중복이면 엉뚱한 열을 집는다."""
    nums = [c["col"] for c in _cols()["columns"]]
    assert len(nums) == len(set(nums)), f"열 번호 중복: {nums}"
