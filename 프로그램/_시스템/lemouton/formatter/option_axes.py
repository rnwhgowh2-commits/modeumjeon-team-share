# -*- coding: utf-8 -*-
"""[v3] BundleGroup.option_config_json 기반 마켓별 option_combinations 생성기.

axes config 를 받아 옵션 행을 마켓별 페이로드로 변환:
- 스마트스토어: optionCombinations[] = {optionName1, optionName2, optionName3, stockQuantity, price}
- 쿠팡: items[].attributes[] = {attributeTypeName, attributeValueName} + stockQuantity·salePrice

신규 상품 등록 시 사용. 기존 상품 옵션 변경은 edit_options() 별도.
"""
from __future__ import annotations

from typing import Iterable


VALID_SOURCES = ("color_code", "size_code", "model_code")


def _value_of(option_row: dict, source: str) -> str:
    """source 이름으로 옵션 행에서 값 추출."""
    if source not in VALID_SOURCES:
        raise ValueError(f"unknown source: {source}")
    return (option_row.get(source) or "").strip() or "?"


def build_smartstore_option_combinations(
    options: Iterable[dict],
    axes: list[dict],
    *,
    stock_by_sku: dict[str, int] | None = None,
    price_by_sku: dict[str, int] | None = None,
) -> list[dict]:
    """스마트스토어 optionCombinations 생성.

    Args:
        options: 옵션 행 dict 리스트 (color_code, size_code, model_code, canonical_sku).
        axes: [{'name': '색상', 'source': 'color_code'}, ...] (1~3개)
        stock_by_sku: {canonical_sku: int} (없으면 0)
        price_by_sku: {canonical_sku: int} addPrice (없으면 0)

    Returns:
        [{'optionName1':..., 'optionName2':..., 'stockQuantity': N, 'price': delta}, ...]
    """
    if not (1 <= len(axes) <= 3):
        raise ValueError(f"axes 1~3개 필요 (받은 수: {len(axes)})")
    stock_by_sku = stock_by_sku or {}
    price_by_sku = price_by_sku or {}
    out = []
    seen = set()
    for o in options:
        sku = o.get("canonical_sku") or ""
        # 축별 값 추출
        values = [_value_of(o, ax["source"]) for ax in axes]
        # 동일 (값1, 값2, ...) 조합 중복 제거 (예: 그레이/230 이 메이트 + 클래식 둘에서 나오면 1번만)
        key = tuple(values)
        if key in seen:
            continue
        seen.add(key)
        row = {
            "stockQuantity": int(stock_by_sku.get(sku, 0)),
            "price": int(price_by_sku.get(sku, 0)),
        }
        for i, v in enumerate(values, start=1):
            row[f"optionName{i}"] = v
        out.append(row)
    return out


def build_smartstore_option_types(axes: list[dict]) -> list[dict]:
    """스마트스토어 옵션 타입 (groupName) 정의.

    Returns:
        [{'groupName': '색상', 'sortOrder': 1}, {'groupName': '사이즈', 'sortOrder': 2}, ...]
    """
    if not (1 <= len(axes) <= 3):
        raise ValueError(f"axes 1~3개 필요 (받은 수: {len(axes)})")
    return [{"groupName": ax["name"], "sortOrder": i + 1} for i, ax in enumerate(axes)]


def build_coupang_items(
    options: Iterable[dict],
    axes: list[dict],
    *,
    stock_by_sku: dict[str, int] | None = None,
    price_by_sku: dict[str, int] | None = None,
) -> list[dict]:
    """쿠팡 items[] 페이로드 생성 (신규 등록용).

    Args:
        options: 옵션 행 dict 리스트.
        axes: [{'name': '색상', 'source': 'color_code'}, ...]
        stock_by_sku: {canonical_sku: int}
        price_by_sku: {canonical_sku: int} salePrice (절대값)

    Returns:
        [{'itemName': '...', 'attributes': [{'attributeTypeName':'색상','attributeValueName':'그레이'},...],
          'maximumBuyForPerson':0, 'salePrice': N, 'stockQuantity': N}, ...]
    """
    if not (1 <= len(axes) <= 3):
        raise ValueError(f"axes 1~3개 필요 (받은 수: {len(axes)})")
    stock_by_sku = stock_by_sku or {}
    price_by_sku = price_by_sku or {}
    out = []
    seen = set()
    for o in options:
        sku = o.get("canonical_sku") or ""
        values = [_value_of(o, ax["source"]) for ax in axes]
        key = tuple(values)
        if key in seen:
            continue
        seen.add(key)
        attrs = [
            {"attributeTypeName": ax["name"], "attributeValueName": v}
            for ax, v in zip(axes, values)
        ]
        item_name = " ".join(values)
        out.append({
            "itemName": item_name,
            "attributes": attrs,
            "salePrice": int(price_by_sku.get(sku, 0)),
            "stockQuantity": int(stock_by_sku.get(sku, 0)),
        })
    return out


def build_payloads_for_group(
    group_option_config: dict,
    options: list[dict],
    *,
    stock_by_sku: dict[str, int] | None = None,
    ss_price_by_sku: dict[str, int] | None = None,
    cp_price_by_sku: dict[str, int] | None = None,
) -> dict:
    """그룹의 option_config 로 마켓별 신규등록 페이로드 일괄 생성.

    Returns:
        {
          'smartstore': {'optionTypes': [...], 'optionCombinations': [...]},
          'coupang':    {'items': [...]},
        }
    """
    out: dict = {}
    ss_cfg = (group_option_config or {}).get("smartstore") or {}
    ss_axes = ss_cfg.get("axes") or []
    if ss_axes:
        out["smartstore"] = {
            "optionTypes": build_smartstore_option_types(ss_axes),
            "optionCombinations": build_smartstore_option_combinations(
                options, ss_axes,
                stock_by_sku=stock_by_sku, price_by_sku=ss_price_by_sku),
        }
    cp_cfg = (group_option_config or {}).get("coupang") or {}
    cp_axes = cp_cfg.get("axes") or []
    if cp_axes:
        out["coupang"] = {
            "items": build_coupang_items(
                options, cp_axes,
                stock_by_sku=stock_by_sku, price_by_sku=cp_price_by_sku),
        }
    return out
