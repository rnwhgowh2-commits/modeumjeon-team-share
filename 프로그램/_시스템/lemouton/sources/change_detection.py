"""소싱처 URL 1건의 직전 옵션값 vs 새 옵션값 비교 → 변동 여부 판정 (순수 함수).

키 = (color_text, size_text). 매칭되는 옵션의 재고·가격이 바뀌었는지,
옵션이 새로 생기거나 사라졌는지를 본다. 폴백 없음 — 값 그대로 비교.

주의: 호출자는 키((color_text, size_text)) 중복이 없는 정규화된 옵션 리스트를
넘겨야 한다 — 같은 키가 중복되면 마지막 항목만 남아 변동이 가려질 수 있다.
"""
from typing import Any


def _key(o: dict) -> tuple:
    return (o.get("color_text"), o.get("size_text"))


def detect_changes(old_options: list[dict], new_options: list[dict]) -> dict[str, Any]:
    """반환: {'stock_changed': bool, 'price_changed': bool, 'detail': str}."""
    old_map = {_key(o): o for o in old_options}
    new_map = {_key(o): o for o in new_options}

    stock_changed = False
    price_changed = False
    notes: list[str] = []

    added = set(new_map) - set(old_map)
    removed = set(old_map) - set(new_map)
    if added or removed:
        stock_changed = True
        for k in added:
            notes.append(f"[{k[0]}/{k[1]}] 옵션 생김")
        for k in removed:
            notes.append(f"[{k[0]}/{k[1]}] 옵션 사라짐")

    for k in set(old_map) & set(new_map):
        o, n = old_map[k], new_map[k]
        if o.get("stock") != n.get("stock"):
            stock_changed = True
            notes.append(f"[{k[0]}/{k[1]}] 재고 {o.get('stock')}→{n.get('stock')}")
        if o.get("price") != n.get("price"):
            price_changed = True
            notes.append(f"[{k[0]}/{k[1]}] 가격 {o.get('price')}→{n.get('price')}")

    return {
        "stock_changed": stock_changed,
        "price_changed": price_changed,
        "detail": " · ".join(notes),
    }
