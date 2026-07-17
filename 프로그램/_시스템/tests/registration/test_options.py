# -*- coding: utf-8 -*-
"""옵션 빌더 — 순수 함수. DB·네트워크 없음."""
import pytest

from lemouton.registration.options import (
    build_smartstore_options, build_coupang_items,
    OptionError, NoSellableOption, OptionValueInvalid,
)


SALE = 75800

OPTS = [
    {'color': '블랙', 'size': '260', 'stock': 2, 'extra_price': 1000, 'sku': 'BK-260'},
    {'color': '블랙', 'size': '250', 'stock': 3, 'extra_price': 0, 'sku': 'BK-250'},
    {'color': '화이트', 'size': '250', 'stock': 0, 'extra_price': 0, 'sku': 'WH-250'},
]


def test_smartstore_group_names():
    groups, _, _ = build_smartstore_options(OPTS, sale_price=SALE)
    assert groups == {'optionGroupName1': '색상', 'optionGroupName2': '사이즈'}


def test_smartstore_excludes_sold_out():
    """재고 0 옵션은 등록 제외 (설계서 §7-9)."""
    _, combos, _ = build_smartstore_options(OPTS, sale_price=SALE)
    names = [(c['optionName1'], c['optionName2']) for c in combos]
    assert ('화이트', '250') not in names
    assert len(combos) == 2


def test_smartstore_sorted_size_ascending():
    """사이즈 작은→큰 순 (설계서 §7-9)."""
    _, combos, _ = build_smartstore_options(OPTS, sale_price=SALE)
    assert [c['optionName2'] for c in combos] == ['250', '260']


def test_smartstore_combo_shape():
    _, combos, _ = build_smartstore_options(OPTS, sale_price=SALE)
    assert combos[0] == {
        'optionName1': '블랙', 'optionName2': '250',
        'stockQuantity': 3, 'price': 0, 'usable': True,
        'sellerManagerCode': 'BK-250',
    }
    assert combos[1]['price'] == 1000, '옵션 추가금은 그대로 실린다'


def test_smartstore_all_sold_out_raises():
    """전부 품절이면 조용히 빈 목록을 보내지 말고 실패한다."""
    with pytest.raises(NoSellableOption):
        build_smartstore_options([{'color': 'X', 'size': '1', 'stock': 0}],
                                 sale_price=SALE)


def test_smartstore_unknown_stock_excluded():
    """재고 -1 = 확인불가 → 등록 제외 (오버셀 방지. 999 폴백 금지)."""
    _, combos, _ = build_smartstore_options(
        OPTS + [{'color': '레드', 'size': '270', 'stock': -1}], sale_price=SALE)
    assert all(c['optionName1'] != '레드' for c in combos)


def test_coupang_items_shape():
    items, _ = build_coupang_items(OPTS, sale_price=SALE, image_url='https://img/x.jpg')
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
    items, _ = build_coupang_items(OPTS, sale_price=SALE, image_url='')
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
    _, _, excluded = build_smartstore_options(opts, sale_price=SALE)
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
    _, combos, _ = build_smartstore_options(
        [{'color': '블랙', 'size': 250, 'stock': 3}], sale_price=SALE)
    assert combos[0]['optionName2'] == '250'


def test_stock_string_float_is_valid_stock():
    """'3.0' 은 엑셀 붙여넣기·toFixed 의 정상 출력. 재고 3이지 크래시가 아니다."""
    _, combos, _ = build_smartstore_options(
        [{'color': '블랙', 'size': '250', 'stock': '3.0'}], sale_price=SALE)
    assert combos[0]['stockQuantity'] == 3


def test_stock_garbage_raises_option_error_not_bare_value_error():
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([{'color': '블랙', 'size': '250', 'stock': 'abc'}],
                                 sale_price=SALE)


def test_stock_bool_rejected():
    """파이썬에서 True == 1 — 그냥 두면 재고 1개로 등록된다."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([{'color': '블랙', 'size': '250', 'stock': True}],
                                 sale_price=SALE)


def test_missing_stock_is_not_sold_out():
    """재고 미입력 ≠ 품절. 배선 버그를 '전부 품절' 이라 거짓 보고하면 안 된다."""
    with pytest.raises(NoSellableOption) as ei:
        build_smartstore_options([{'color': '블랙', 'size': '250'}], sale_price=SALE)
    assert '재고미입력' in str(ei.value)
    assert '품절 ' not in str(ei.value)


def test_duplicate_option_raises():
    """같은 색상/사이즈 2행 — 재고를 합치지 않는다 (없던 의도를 지어내는 셈)."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([
            {'color': '블랙', 'size': '250', 'stock': 3},
            {'color': '블랙', 'size': '250', 'stock': 5},
        ], sale_price=SALE)


def test_empty_color_raises_instead_of_emitting_blank_required_field():
    """optionName1 은 스스 필수 — 빈 값을 보내면 불투명한 400 이 돌아온다."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([{'color': '', 'size': 'FREE', 'stock': 2}],
                                 sale_price=SALE)


def test_color_only_smartstore_uses_one_group():
    """색상만 있는 상품 → optionGroupName1 만, optionName2 없음."""
    g, c, ex = build_smartstore_options(
        [{'color': '블랙', 'size': '', 'stock': 3, 'sku': 'BK'},
         {'color': '베이지', 'stock': 2}], sale_price=SALE)
    assert g == {'optionGroupName1': '색상'}
    assert all('optionName2' not in x for x in c)
    assert c[0]['optionName1'] == '베이지'   # 색상 가나다 정렬
    assert c[0]['stockQuantity'] == 2 and c[0]['price'] == 0


def test_color_only_coupang_omits_size_attr():
    """색상만 → itemName=색상, attributes 에 사이즈 없음."""
    it, ex = build_coupang_items([{'color': '블랙', 'stock': 3}],
                                 sale_price=SALE, image_url='')
    assert it[0]['itemName'] == '블랙'
    assert [a['attributeTypeName'] for a in it[0]['attributes']] == ['색상']


def test_two_axis_still_works():
    """색상×사이즈 2축은 그대로."""
    g, c, ex = build_smartstore_options(
        [{'color': '블랙', 'size': '250', 'stock': 3},
         {'color': '블랙', 'size': '260', 'stock': 1}], sale_price=SALE)
    assert g == {'optionGroupName1': '색상', 'optionGroupName2': '사이즈'}
    assert [x['optionName2'] for x in c] == ['250', '260']


def test_mixed_size_presence_rejected():
    """한 상품에 사이즈 있는 행과 없는 행이 섞이면 거부 (마켓이 payload 거부)."""
    mix = [{'color': '블랙', 'size': '250', 'stock': 3},
           {'color': '베이지', 'stock': 2}]
    for fn, kw in [(build_smartstore_options, {'sale_price': SALE}),
                   (build_coupang_items, {'sale_price': SALE, 'image_url': ''})]:
        with pytest.raises(OptionValueInvalid) as ei:
            fn(mix, **kw)
        assert '섞을 수 없습니다' in str(ei.value)


def test_color_only_duplicate_rejected():
    """색상만일 때 같은 색상 2번은 중복."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([{'color': '블랙', 'stock': 3},
                                  {'color': '블랙', 'stock': 1}], sale_price=SALE)


def test_color_still_required():
    """색상은 여전히 필수 — 색상도 사이즈도 없으면 거부."""
    with pytest.raises(OptionValueInvalid) as ei:
        build_smartstore_options([{'stock': 3}], sale_price=SALE)
    assert '색상' in str(ei.value)


def test_color_only_reports_exclusions():
    """색상만이어도 품절·확인불가 제외를 그대로 보고한다."""
    g, c, ex = build_smartstore_options(
        [{'color': '화이트', 'stock': 0}, {'color': '블랙', 'stock': 3},
         {'color': '베이지', 'stock': -1}], sale_price=SALE)
    assert [x['optionName1'] for x in c] == ['블랙']
    assert {(e['color'], e['reason']) for e in ex} == \
        {('화이트', '품절'), ('베이지', '확인불가')}


def test_color_only_negative_final_price_still_blocked():
    """색상만이어도 최종가 0원 이하는 차단."""
    with pytest.raises(OptionValueInvalid):
        build_coupang_items([{'color': '블랙', 'stock': 1, 'extra_price': -SALE}],
                            sale_price=SALE, image_url='')


def test_nan_size_raises():
    """nan 은 비교가 전부 False 라 정렬을 조용히 뒤섞는다."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([{'color': '블랙', 'size': 'nan', 'stock': 3}],
                                 sale_price=SALE)


def test_decimal_size_still_works():
    """1.5 는 진짜 사이즈다. nan 막느라 같이 막으면 안 된다."""
    _, combos, _ = build_smartstore_options([
        {'color': '블랙', 'size': '2', 'stock': 1},
        {'color': '블랙', 'size': '1.5', 'stock': 1},
    ], sale_price=SALE)
    assert [c['optionName2'] for c in combos] == ['1.5', '2']


def test_all_errors_share_one_base():
    """상위 컴파일러가 OptionError 하나만 잡으면 되게."""
    assert issubclass(NoSellableOption, OptionError)
    assert issubclass(OptionValueInvalid, OptionError)


# ─────────────────────────────────────────────────────────────────────────────
# 그릇도 믿지 않는다 — options_json 은 제약 없는 Text 컬럼이다
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('bad', [None, {'a': 1}, '블랙', 42])
def test_opts_not_a_list_raises_option_error(bad):
    """TypeError 는 상위 except OptionError 를 그냥 통과해 500 이 된다."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options(bad, sale_price=SALE)
    with pytest.raises(OptionValueInvalid):
        build_coupang_items(bad, sale_price=SALE, image_url='')


@pytest.mark.parametrize('bad', ['블랙', None, 42, ['블랙']])
def test_opts_entry_not_a_dict_raises_option_error(bad):
    """{"options": ["블랙"]} 은 저장은 멀쩡히 되고 등록 시점에 터진다."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options([bad], sale_price=SALE)
    with pytest.raises(OptionValueInvalid):
        build_coupang_items([bad], sale_price=SALE, image_url='')


# ─────────────────────────────────────────────────────────────────────────────
# 돈 — 최종가 0원 이하 금지 (음수 옵션가 자체는 정상)
# ─────────────────────────────────────────────────────────────────────────────

def test_negative_extra_price_is_legitimate():
    """더 싼 변형 = 할인 옵션가. 합계가 멀쩡하면 통과해야 한다."""
    items, _ = build_coupang_items(
        [{'color': '블랙', 'size': '250', 'stock': 1, 'extra_price': -5000}],
        sale_price=75800, image_url='')
    assert items[0]['salePrice'] == 70800


def test_coupang_final_price_zero_or_less_raises():
    with pytest.raises(OptionValueInvalid):
        build_coupang_items(
            [{'color': '블랙', 'size': '250', 'stock': 1, 'extra_price': -5000}],
            sale_price=1000, image_url='')


def test_smartstore_final_price_zero_or_less_raises():
    """스스는 절대가를 안 보내지만 서버가 같은 덧셈을 한다 — 구멍은 동일."""
    with pytest.raises(OptionValueInvalid):
        build_smartstore_options(
            [{'color': '블랙', 'size': '250', 'stock': 1, 'extra_price': -5000}],
            sale_price=1000)


# ─────────────────────────────────────────────────────────────────────────────
# 정렬 = 구매자 드롭다운 순서 (optionCombinationSortType 미입력 → 등록순 CREATE)
# ─────────────────────────────────────────────────────────────────────────────

def test_alpha_sizes_sorted_by_garment_order_not_alphabet():
    """['XL','S','M','L','XS'] 를 문자순으로 두면 L,M,S,XL,XS 로 나온다."""
    _, combos, _ = build_smartstore_options([
        {'color': '블랙', 'size': s, 'stock': 1} for s in ('XL', 'S', 'M', 'L', 'XS')
    ], sale_price=SALE)
    assert [c['optionName2'] for c in combos] == ['XS', 'S', 'M', 'L', 'XL']
