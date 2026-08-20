# -*- coding: utf-8 -*-
"""ESM(옥션·G마켓) 등록 직후 자동 판매중지 — 스마트스토어와 같은 안전장치.

배경: service.py:_send_live 는 스마트스토어만 등록 직후 mark_suspension() 을 부른다.
ESM 은 shared/platforms/esm/inventory.py:set_sold_out(goods_no, market, *, client) 가
이미 있는데 등록 경로(_register_esm)에서 안 불렀다 — 등록 즉시 판매중(11)으로 뜬
채 아무도 안 내렸다. 이 시험은 등록(+옵션부착 있으면 그것까지) 끝난 뒤에 set_sold_out
이 반드시 호출되는지를 확인한다.
"""
from unittest.mock import MagicMock, patch

from lemouton.registration.send_more import _register_esm

_SPEC = {
    'goods_name': '테스트상품', 'cat_code': '100', 'site_cat_code': '200',
    'price': 10000, 'stock': 1, 'image_url': 'http://img.example/1.jpg',
    'detail_html': '<p>상세</p>', 'is_vat_free': False, 'model_no': 'MD1',
    'bar_code': '8800000000001', 'is_adult_product': False,
    # options 키를 안 넣어 spec.get('options') 가 falsy → 옵션 부착 분기는 안 탄다
    # (옵션 분기 자체는 이 테스트의 관심사가 아니라 별도 시험에서 다룬다 —
    #  tests/registration/test_esm_option_attach_message.py).
}
_PREREQ = {'place_no': '1', 'dispatch_policy_no': '2', 'return_addr_no': '3',
           'delivery_company_no': '4', 'official_notice_no': '5',
           'official_notice_details': {}}


def test_register_esm_calls_set_sold_out_after_success(monkeypatch):
    """등록(+옵션부착 있으면 그것까지) 끝난 뒤에 판매중지(set_sold_out) 를 호출해야 한다.

    ★ 패치 대상 주의: search_goods·get_goods_detail·extract_register_prereq·
      build_esm_register_payload·register_goods 는 send_more.py 최상단이 아니라
      `_register_esm` 함수 몸통 안에서
      `from shared.platforms.esm.products import (...)` 로 지역 import 된다.
      그래서 `lemouton.registration.send_more.search_goods` 를 패치하면 이름이
      send_more 모듈 네임스페이스에 없어 아무 효과가 없다(AttributeError 는 안 나도
      실제 호출은 원본 함수로 나간다) — 실제로 참조하는
      `shared.platforms.esm.products` 쪽을 패치해야 한다. set_sold_out 도 같은
      이유로 `shared.platforms.esm.inventory` 에서 지역 import 되므로 그쪽을 패치한다.
    """
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._esm_client', lambda market, prefix: fake_client)

    with patch('shared.platforms.esm.products.search_goods',
               return_value={'items': [{'goodsNo': '111'}]}), \
         patch('shared.platforms.esm.products.get_goods_detail',
               return_value={'itemAddtionalInfo': {}}), \
         patch('shared.platforms.esm.products.extract_register_prereq',
               return_value=_PREREQ), \
         patch('shared.platforms.esm.products.build_esm_register_payload',
               return_value={}), \
         patch('shared.platforms.esm.products.register_goods',
               return_value={'goodsNo': '999888'}), \
         patch('shared.platforms.esm.inventory.set_sold_out') as mock_suspend:
        mock_suspend.return_value = True
        result = _register_esm('auction', dict(_SPEC), '')

    assert result['product_id'] == '999888'
    mock_suspend.assert_called_once_with('999888', 'auction', client=fake_client)


def test_register_esm_marks_suspend_failed_when_set_sold_out_returns_false(monkeypatch):
    """set_sold_out 이 False 를 돌려주면(전환 실패) — 스마트스토어(service.py:_send_live)와
    같이 result['raw']['_suspend_failed'] = True 를 남겨야 한다.

    이 흔적이 없으면 등록은 성공(goodsNo 확보)했는데 상품이 판매중 상태로 남았다는
    사실이 DB(row.raw_json) 어디에도 안 남는다 — 로그만 찍고 아무도 안 본다.
    """
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._esm_client', lambda market, prefix: fake_client)

    with patch('shared.platforms.esm.products.search_goods',
               return_value={'items': [{'goodsNo': '111'}]}), \
         patch('shared.platforms.esm.products.get_goods_detail',
               return_value={'itemAddtionalInfo': {}}), \
         patch('shared.platforms.esm.products.extract_register_prereq',
               return_value=_PREREQ), \
         patch('shared.platforms.esm.products.build_esm_register_payload',
               return_value={}), \
         patch('shared.platforms.esm.products.register_goods',
               return_value={'goodsNo': '999888'}), \
         patch('shared.platforms.esm.inventory.set_sold_out') as mock_suspend:
        mock_suspend.return_value = False
        result = _register_esm('auction', dict(_SPEC), '')

    assert result['product_id'] == '999888'
    assert result['raw'].get('_suspend_failed') is True


def test_register_esm_marks_suspend_failed_when_set_sold_out_raises(monkeypatch):
    """set_sold_out 이 예외를 던져도(전환 실패) 같은 흔적을 남겨야 한다.

    등록 자체는 이미 성공했으므로(goodsNo 확보) 예외를 삼키는 것 자체는 맞다
    (best-effort) — 다만 삼킨 뒤 아무 흔적도 안 남기면 안 된다.
    """
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._esm_client', lambda market, prefix: fake_client)

    with patch('shared.platforms.esm.products.search_goods',
               return_value={'items': [{'goodsNo': '111'}]}), \
         patch('shared.platforms.esm.products.get_goods_detail',
               return_value={'itemAddtionalInfo': {}}), \
         patch('shared.platforms.esm.products.extract_register_prereq',
               return_value=_PREREQ), \
         patch('shared.platforms.esm.products.build_esm_register_payload',
               return_value={}), \
         patch('shared.platforms.esm.products.register_goods',
               return_value={'goodsNo': '999888'}), \
         patch('shared.platforms.esm.inventory.set_sold_out') as mock_suspend:
        mock_suspend.side_effect = RuntimeError('네트워크 오류')
        result = _register_esm('auction', dict(_SPEC), '')

    assert result['product_id'] == '999888'
    assert result['raw'].get('_suspend_failed') is True
