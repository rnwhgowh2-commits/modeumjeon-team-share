# -*- coding: utf-8 -*-
"""SKU 스코프 — only_skus 필터가 지정 SKU만 남기는지."""
from scripts.verify_pipeline_dryrun import filter_a_output


def test_filter_keeps_only_target_skus():
    a_output = {"SKU_A": {"x": 1}, "SKU_B": {"x": 2}, "SKU_C": {"x": 3}}
    out = filter_a_output(a_output, only_skus=["SKU_A", "SKU_C"])
    assert set(out.keys()) == {"SKU_A", "SKU_C"}


def test_filter_none_returns_all():
    a_output = {"SKU_A": {}, "SKU_B": {}}
    assert filter_a_output(a_output, only_skus=None) == a_output


def test_filter_empty_list_returns_empty():
    a_output = {"SKU_A": {}, "SKU_B": {}}
    assert filter_a_output(a_output, only_skus=[]) == {}


def test_filter_unknown_sku_ignored():
    a_output = {"SKU_A": {}}
    out = filter_a_output(a_output, only_skus=["SKU_A", "SKU_ZZZ"])
    assert set(out.keys()) == {"SKU_A"}
