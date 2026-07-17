# -*- coding: utf-8 -*-
"""옵션 빌더 — 순수 함수. DB·네트워크 없음."""
import pytest

from lemouton.registration.options import (
    build_smartstore_options, build_coupang_items,
    OptionError, NoSellableOption, OptionValueInvalid,
)


OPTS = [
    {'color': '블랙', 'size': '260', 'stock': 2, 'extra_price': 1000, 'sku': 'BK-260'},
    {'color': '블랙', 'size': '250', 'stock': 3, 'extra_price': 0, 'sku': 'BK-250'},
    {'color': '화이트', 'size': '250', 'stock': 0, 'extra_price': 0, 'sku': 'WH-250'},
]


def test_smartstore_group_names():
    groups, _, _ = build_smartstore_options(OPTS)
    assert groups == {'optionGroupName1': '색상', 'optionGroupName2': '사이즈'}


def test_smartstore_excludes_sold_out():
    """재고 0 옵션은 등록 제외 (설계서 §7-9)."""
    _, combos, _ = build_smartstore_options(OPTS)
    names = [(c['optionName1'], c['optionName2']) for c in combos]
    assert ('화이트', '250') not in names
    assert len(combos) == 2


def test_smartstore_sorted_size_ascending():
    """사이즈 작은→큰 순 (설계서 §7-9)."""
    _, combos, _ = build_smartstore_options(OPTS)
    assert [c['optionName2'] for c in combos] == ['250', '260']


def test_smartstore_combo_shape():
    _, combos, _ = build_smartstore_options(OPTS)
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
    _, combos, _ = build_smartstore_options(
        OPTS + [{'color': '레드', 'size': '270', 'stock': -1}])
    assert all(c['optionName1'] != '레드' for c in combos)


def test_coupang_items_shape():
    items, _ = build_coupang_items(OPTS, sale_price=75800, image_url='https://img/x.jpg')
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
    items, _ = build_coupang_items(OPTS, sale_price=75800, image_url='')
    assert items[1]['salePrice'] == 76800   # 260 = extra 1000
    assert items[1]['images'] == []


# ─────────────────────────────────────────────────────────────────────────────
# 제외는 보고한다 — 조용한 실패 금지
# ─────────────────────────────────────────────────────────────────────────────

def test_excluded_rows_are_reported_with_reason():
    """빠진 행은 사유와 함께 돌려준다. 사용자가 폼에 직접 넣은 행이다."""
    opts = OPTS + [
        {'color': '레드', 'size': '270', 'stock': -1},
        {'color': '네이비', 'size': '250'},          # stock 키 자체가 없음
    ]
    _, _, excluded = build_smartstore_options(opts)
    assert [(e['color'], e['reason']) for e in excluded] == [
        ('화이트', '품절'), ('레드', '확인불가'), ('네이비', '재고미입력'),
    ]


def test_coupang_reports_the_same_exclusions():
    items, excluded = build_coupang_items(OPTS, sale_price=1000, image_url='')
    assert len(items) == 2
    assert [e['reason'] for e in excluded] == ['품절']


# ─────────────────────────────────────────────────────────────────────────────
# 입력 경계 — opts 는 UI 폼에서 온 자유형 JSON 이다
# ─────────────────────────────────────────────────────────────────────────────

def test_numeric_size_does_not_crash():
    """신발 사이즈는 숫자로 온다. str 취급하면 AttributeError → 500."""
    _, combos, _ = build_smartstore_options([{'color': '블랙', 'size': 250, 'stock': 3}])
    assert combos[0]['optionName2'] == '250'


def test_stock_string_float_is_valid_stock():
    """'3.0' 은 엑셀 붙여넣기·toFixed 의 정상 출력. 재고 3이지 크래시가 아니다."""
    _, combos, _ = build_smartstore_options([{'color': '블랙', 'size': '250', 'stock': '3.0'}])
    assert combos[0]['stockQuantity'] == 3


def test_stock_garbage_raises_option_error_not_bare_value_error():
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([{'color': '블랙', 'size': '250', 'stock': 'abc'}])


def test_stock_bool_rejected():
    """파이썬에서 True == 1 — 그냥 두면 재고 1개로 등록된다."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([{'color': '블랙', 'size': '250', 'stock': True}])


def test_missing_stock_is_not_sold_out():
    """재고 미입력 ≠ 품절. 배선 버그를 '전부 품절' 이라 거짓 보고하면 안 된다."""
    with pytest.raises(NoSellableOption) as ei:
        build_smartstore_options([{'color': '블랙', 'size': '250'}])
    assert '재고미입력' in str(ei.value)
    assert '품절 ' not in str(ei.value)


def test_duplicate_option_raises():
    """같은 색상/사이즈 2행 — 재고를 합치지 않는다 (없던 의도를 지어내는 셈)."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([
            {'color': '블랙', 'size': '250', 'stock': 3},
            {'color': '블랙', 'size': '250', 'stock': 5},
        ])


def test_empty_color_raises_instead_of_emitting_blank_required_field():
    """optionName1 은 스스 필수 — 빈 값을 보내면 불투명한 400 이 돌아온다."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([{'color': '', 'size': 'FREE', 'stock': 2}])


def test_nan_size_raises():
    """nan 은 비교가 전부 False 라 정렬을 조용히 뒤섞는다."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([{'color': '블랙', 'size': 'nan', 'stock': 3}])


def test_decimal_size_still_works():
    """1.5 는 진짜 사이즈다. nan 막느라 같이 막으면 안 된다."""
    _, combos, _ = build_smartstore_options([
        {'color': '블랙', 'size': '2', 'stock': 1},
        {'color': '블랙', 'size': '1.5', 'stock': 1},
    ])
    assert [c['optionName2'] for c in combos] == ['1.5', '2']


def test_all_errors_share_one_base():
    """상위 컴파일러가 OptionError 하나만 잡으면 되게."""
    assert issubclass(NoSellableOption, OptionError)
    assert issubclass(OptionValueInvalid, OptionError)


# ─────────────────────────────────────────────────────────────────────────────
# 정렬 = 구매자 드롭다운 순서 (optionCombinationSortType 미입력 → 등록순 CREATE)
# ─────────────────────────────────────────────────────────────────────────────

def test_alpha_sizes_sorted_by_garment_order_not_alphabet():
    """['XL','S','M','L','XS'] 를 문자순으로 두면 L,M,S,XL,XS 로 나온다."""
    _, combos, _ = build_smartstore_options([
        {'color': '블랙', 'size': s, 'stock': 1} for s in ('XL', 'S', 'M', 'L', 'XS')
    ])
    assert [c['optionName2'] for c in combos] == ['XS', 'S', 'M', 'L', 'XL']
