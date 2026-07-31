# -*- coding: utf-8 -*-
"""[TEST] 스마트스토어 옵션 축 구성 — 1축 합치기 / 2축(기본).

노션 ①「기본적으로 1축 구성 옵션번호지만, 마켓별 업로드 시 2/3축으로 쪼갤 수 있음」
우리 옵션번호는 언제나 하나다. 바뀌는 건 **구매자에게 보이는 갈래 수**뿐이다.
"""
from lemouton.registration.options import build_smartstore_options

OPTS = [{'color': '블랙', 'size': '260', 'stock': 5, 'extra_price': 0, 'sku': 'A'},
        {'color': '블랙', 'size': '270', 'stock': 3, 'extra_price': 1000, 'sku': 'B'}]


def test_기본은_색상_사이즈_두_갈래다():
    groups, combos, _ex = build_smartstore_options(OPTS, sale_price=50000)
    assert groups == {'optionGroupName1': '색상', 'optionGroupName2': '사이즈'}
    assert combos[0]['optionName1'] == '블랙'
    assert combos[0]['optionName2'] == '260'


def test_한_갈래면_색상과_사이즈를_합친다():
    groups, combos, _ex = build_smartstore_options(OPTS, sale_price=50000, axis='one')
    assert groups == {'optionGroupName1': '옵션'}
    assert combos[0]['optionName1'] == '블랙 260'
    assert 'optionName2' not in combos[0], '한 갈래인데 둘째 축이 남았다'


def test_사이즈가_없으면_한_갈래여도_색상만_쓴다():
    """빈 사이즈가 뒤에 붙어 「블랙 」이 되면 구매자 화면에 그대로 보인다."""
    opts = [{'color': '블랙', 'size': '', 'stock': 5, 'extra_price': 0, 'sku': 'A'}]
    _g, combos, _ex = build_smartstore_options(opts, sale_price=50000, axis='one')
    assert combos[0]['optionName1'] == '블랙'


def test_재고와_추가금은_축과_무관하게_그대로다():
    _g, combos, _ex = build_smartstore_options(OPTS, sale_price=50000, axis='one')
    assert [c['stockQuantity'] for c in combos] == [5, 3]
    assert [c['price'] for c in combos] == [0, 1000]
