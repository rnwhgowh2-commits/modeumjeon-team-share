# -*- coding: utf-8 -*-
"""옵션 빌더 — 순수 함수. DB·네트워크 없음."""
import pytest

from lemouton.registration.options import (
    build_smartstore_options, build_coupang_items, NoSellableOption,
)


OPTS = [
    {'color': '블랙', 'size': '260', 'stock': 2, 'extra_price': 1000, 'sku': 'BK-260'},
    {'color': '블랙', 'size': '250', 'stock': 3, 'extra_price': 0, 'sku': 'BK-250'},
    {'color': '화이트', 'size': '250', 'stock': 0, 'extra_price': 0, 'sku': 'WH-250'},
]


def test_smartstore_group_names():
    groups, _ = build_smartstore_options(OPTS)
    assert groups == {'optionGroupName1': '색상', 'optionGroupName2': '사이즈'}


def test_smartstore_excludes_sold_out():
    """재고 0 옵션은 등록 제외 (설계서 §7-9)."""
    _, combos = build_smartstore_options(OPTS)
    names = [(c['optionName1'], c['optionName2']) for c in combos]
    assert ('화이트', '250') not in names
    assert len(combos) == 2


def test_smartstore_sorted_size_ascending():
    """사이즈 작은→큰 순 (설계서 §7-9)."""
    _, combos = build_smartstore_options(OPTS)
    assert [c['optionName2'] for c in combos] == ['250', '260']


def test_smartstore_combo_shape():
    _, combos = build_smartstore_options(OPTS)
    assert combos[0] == {
        'optionName1': '블랙', 'optionName2': '250',
        'stockQuantity': 3, 'price': 0, 'usable': True,
        'sellerManagerCode': 'BK-250',
    }
    assert combos[1]['price'] == 1000, '옵션 추가금은 그대로 실린다'


def test_smartstore_all_sold_out_raises():
    """전부 품절이면 조용히 빈 목록을 보내지 말고 실패한다."""
    with pytest.raises(NoSellableOption):
        build_smartstore_options([{'color': 'X', 'size': '1', 'stock': 0}])


def test_smartstore_unknown_stock_excluded():
    """재고 -1 = 확인불가 → 등록 제외 (오버셀 방지. 999 폴백 금지)."""
    _, combos = build_smartstore_options(
        OPTS + [{'color': '레드', 'size': '270', 'stock': -1}])
    assert all(c['optionName1'] != '레드' for c in combos)


def test_coupang_items_shape():
    items = build_coupang_items(OPTS, sale_price=75800, image_url='https://img/x.jpg')
    assert len(items) == 2
    it = items[0]
    assert it['itemName'] == '블랙-250'
    assert it['originalPrice'] == 75800
    assert it['salePrice'] == 75800
    assert it['maximumBuyCount'] == 3
    assert it['externalVendorSku'] == 'BK-250'
    assert it['images'] == [{'imageOrder': 0, 'imageType': 'REPRESENTATION',
                             'vendorPath': 'https://img/x.jpg'}]


def test_coupang_extra_price_added_to_sale_price():
    """쿠팡은 옵션 추가금을 절대가에 더해 넣는다 (옵션가 필드가 없음)."""
    items = build_coupang_items(OPTS, sale_price=75800, image_url='')
    assert items[1]['salePrice'] == 76800   # 260 = extra 1000
    assert items[1]['images'] == []
