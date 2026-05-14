# -*- coding: utf-8 -*-
"""[v3] 업로드 skip 판정 — 옵션별 의미있는 변동만 인정.

마켓 노출은 raw_stock 그대로 (1개도 1개로 노출).
변동 감지에서만 ≤1 vs ≥2 두 그룹으로 분류하여 PUT 여부 판단.
  · 재고 1개 = 결제 직전 품절 위험 → 0과 같은 '사실상 품절' 그룹 (변동 감지 한정)
  · 단, 마켓 stock 자체는 1로 그대로 PUT (lost sale 방지)

룰:
  - 재고: 그룹 전환 (≥2 ↔ ≤1) 일 때만 변동
      · 0 → 5  : 재입고     (변동 ✅)
      · 1 → 5  : 재입고     (변동 ✅)
      · 5 → 0  : 품절       (변동 ✅)
      · 5 → 1  : 사실상 품절 (변동 ✅)
      · 5 → 2  : 안전 재고   (무변동 ❌, 둘 다 ≥2)
      · 3 → 7  : 안전 재고   (무변동 ❌)
      · 0 → 1  : 둘 다 ≤1   (무변동 ❌)
      · 1 → 0  : 둘 다 ≤1   (무변동 ❌)
  - 가격: addPrice / salePrice / immediateDiscount 어느 하나라도 차이 → 변동
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


# 변동 감지 그룹 임계치: 이 값 미만 = '사실상 품절' 그룹 (PUT skip 판단 한정)
# 주의: 마켓 노출 stock 자체에는 영향 X — push 시 raw_stock 그대로 전송
STOCK_AVAILABLE_THRESHOLD = 2


def is_available(stock: int) -> bool:
    """재고 ≥ 임계치 = '재고 있음' 그룹 (변동 감지용)."""
    return int(stock) >= STOCK_AVAILABLE_THRESHOLD


@dataclass
class OptionChange:
    option_id: int
    sku: str
    kind: str       # 'restock' | 'sold_out' | 'price' | 'no_change'
    prev_stock: int
    new_stock: int
    prev_add_price: int
    new_add_price: int


def stock_changed(prev_stock: int, new_stock: int) -> bool:
    """재고 그룹 전환 (≥2 ↔ ≤1) 일 때만 변동으로 인정."""
    return is_available(prev_stock) != is_available(new_stock)


def classify_option_change(prev_stock: int, new_stock: int,
                           prev_add_price: int, new_add_price: int) -> str:
    """단일 옵션의 변동 종류 분류."""
    if int(prev_add_price) != int(new_add_price):
        return 'price'
    if not stock_changed(prev_stock, new_stock):
        return 'no_change'
    if not is_available(prev_stock) and is_available(new_stock):
        return 'restock'
    return 'sold_out'


def detect_real_changes(
    push_data: dict[int, dict],
    live_by_oid: dict,
    *,
    prev_sale_price: int = 0,
    new_sale_price: int = 0,
    prev_discount: int = 0,
    new_discount: int = 0,
) -> dict:
    """전체 push 데이터 vs 라이브 비교 → 실 변동 판정.

    Args:
      push_data:   {oid: {sku, stock, price?, ...}}  (본 시스템 산출 결과)
      live_by_oid: {oid: <option-row>} (라이브 GET 결과, .stock / .add_price 필드)
      prev_sale_price / new_sale_price: base salePrice 변화
      prev_discount / new_discount: 즉시할인액 변화

    Returns:
      {
        'changes': [OptionChange ...],     # 변동 있는 옵션만
        'no_change_count': int,
        'restock_count': int,
        'sold_out_count': int,
        'price_count': int,
        'sale_price_changed': bool,
        'discount_changed': bool,
        'should_push': bool,               # 실 변동 1건이라도 있으면 True
      }
    """
    sale_price_changed = int(prev_sale_price) != int(new_sale_price)
    discount_changed = int(prev_discount) != int(new_discount)
    changes: list[OptionChange] = []
    counts = {'restock': 0, 'sold_out': 0, 'price': 0, 'no_change': 0}
    for oid, d in push_data.items():
        cur = live_by_oid.get(oid)
        if cur is None:
            continue
        prev_stock = int(getattr(cur, 'stock', 0))
        new_stock = int(d.get('stock', 0))
        prev_add = int(getattr(cur, 'add_price', 0))
        new_add = int(d.get('price', 0))
        kind = classify_option_change(prev_stock, new_stock, prev_add, new_add)
        counts[kind] = counts.get(kind, 0) + 1
        if kind != 'no_change':
            changes.append(OptionChange(
                option_id=int(oid), sku=d.get('sku', ''),
                kind=kind,
                prev_stock=prev_stock, new_stock=new_stock,
                prev_add_price=prev_add, new_add_price=new_add,
            ))
    should_push = (
        bool(changes) or sale_price_changed or discount_changed
    )
    return {
        'changes': changes,
        'no_change_count': counts['no_change'],
        'restock_count': counts['restock'],
        'sold_out_count': counts['sold_out'],
        'price_count': counts['price'],
        'sale_price_changed': sale_price_changed,
        'discount_changed': discount_changed,
        'should_push': should_push,
    }
