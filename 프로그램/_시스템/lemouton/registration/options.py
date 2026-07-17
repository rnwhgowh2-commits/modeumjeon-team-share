# -*- coding: utf-8 -*-
"""옵션(색상×사이즈) → 마켓별 옵션 구조.

스스 공식 규격 (marketplace_api_map.json → smartstore.create-product-product):
    optionCombinationGroupNames: {optionGroupName1..4}
    optionCombinations: [{optionName1..4, stockQuantity, price, usable, sellerManagerCode}]
    · price 는 '옵션가'(추가금)지 절대 판매가가 아니다.
    · 조합형 옵션 그룹은 최대 3개.

쿠팡은 옵션가 개념이 없어 items[] 마다 절대가(salePrice)를 싣는다.

재고 규칙 (프로젝트 원칙):
    stock > 0  → 등록
    stock == 0 → 품절 → 등록 제외 (설계서 §7-9)
    stock < 0  → '확인불가' → 등록 제외. 999 같은 폴백을 넣지 않는다 (오버셀 방지).
"""
# [2026-07-17] 대량등록 Phase 1A Task 4

_SIZE_GROUP = '사이즈'
_COLOR_GROUP = '색상'


class NoSellableOption(ValueError):
    """판매 가능한 옵션이 하나도 없음. 빈 옵션 목록을 조용히 보내지 않는다."""


def _size_key(size: str):
    """사이즈 정렬 키 — 숫자면 숫자로, 아니면 문자로. 숫자를 문자보다 앞에 둔다."""
    s = (size or '').strip()
    try:
        return (0, float(s), '')
    except ValueError:
        return (1, 0.0, s)


def _sellable(opts):
    out = [o for o in opts if int(o.get('stock') or 0) > 0]
    if not out:
        raise NoSellableOption(
            '판매 가능한 옵션이 없습니다 — 재고 0(품절) 또는 -1(확인불가)뿐입니다.')
    return sorted(out, key=lambda o: (o.get('color') or '', _size_key(o.get('size'))))


def build_smartstore_options(opts):
    """옵션 목록 → (optionCombinationGroupNames, optionCombinations).

    Raises:
        NoSellableOption: 판매 가능한 옵션 0개
    """
    rows = _sellable(opts)
    groups = {'optionGroupName1': _COLOR_GROUP, 'optionGroupName2': _SIZE_GROUP}
    combos = []
    for o in rows:
        combo = {
            'optionName1': o.get('color') or '',
            'optionName2': o.get('size') or '',
            'stockQuantity': int(o.get('stock') or 0),
            'price': int(o.get('extra_price') or 0),
            'usable': True,
        }
        if o.get('sku'):
            combo['sellerManagerCode'] = o['sku']
        combos.append(combo)
    return groups, combos


def build_coupang_items(opts, *, sale_price: int, image_url: str):
    """옵션 목록 → 쿠팡 items[]. 옵션 추가금은 절대가에 가산한다."""
    rows = _sellable(opts)
    items = []
    for o in rows:
        price = int(sale_price) + int(o.get('extra_price') or 0)
        images = ([{'imageOrder': 0, 'imageType': 'REPRESENTATION', 'vendorPath': image_url}]
                  if image_url else [])
        items.append({
            'itemName': f"{o.get('color') or ''}-{o.get('size') or ''}",
            'originalPrice': price,
            'salePrice': price,
            'maximumBuyCount': int(o.get('stock') or 0),
            'externalVendorSku': o.get('sku') or '',
            'images': images,
            'attributes': [
                {'attributeTypeName': '색상', 'attributeValueName': o.get('color') or ''},
                {'attributeTypeName': '사이즈', 'attributeValueName': o.get('size') or ''},
            ],
        })
    return items
