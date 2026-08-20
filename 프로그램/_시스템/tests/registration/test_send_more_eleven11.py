# -*- coding: utf-8 -*-
"""11번가 등록 직후 자동 전시중지(판매중단) — 스마트스토어·ESM과 같은 안전장치.

배경: shared/platforms/eleven11/products.py:stop_display(prdNo, client) 가 이미
있고 webapp/routes/live_send_test.py 수동 버튼에서만 쓰인다. 등록 경로
(_register_eleven11)는 등록 직후 자동으로 호출하지 않아 등록되는 상품이 전시중
(판매중) 상태로 방치된다. 이 시험은 등록(productNo 수령) 끝난 뒤 stop_display 가
반드시 호출되는지, 실패/예외 시 result['raw']['_suspend_failed'] 흔적이 남는지
확인한다.

★ 패치 대상 주의(ESM 태스크에서 겪은 함정과 동일): build_register_xml·
  register_product·stop_display 는 send_more.py 최상단이 아니라
  `_register_eleven11` 함수 몸통 안에서 `from shared.platforms.eleven11.products
  import (...)` 로 지역 import 된다. 그래서 `lemouton.registration.send_more.*`
  를 패치하면 이름이 send_more 모듈 네임스페이스에 없어 아무 효과가 없다 —
  실제로 참조하는 `shared.platforms.eleven11.products` 쪽을 패치해야 한다.

★ [재조회 검증 추가] stop_display 는 HTTP 200/resultCode 만으로도 dict(raw 포함)를
  돌려줘 「거짓 성공」이 나올 수 있다(products.py 의 register_product 주석과 같은
  마켓 특성 — 응답을 못 믿는다). webapp/routes/live_send_test.py:api_suspend_eleven11
  이 이미 쓰는 방식대로, stop_display 가 참을 돌려줘도 get_product_detail 로
  sel_stat_cd == '105'(전시중지) 인지 재조회 확인해야 진짜 성공이다. 확인 안 되면
  (또는 재조회 자체가 예외를 내면) 기존 falsy/exception 분기와 동일하게
  _suspend_failed = True 로 남긴다.
"""
from unittest.mock import MagicMock, patch

from lemouton.registration.send_more import _register_eleven11

_AREA_RESPONSES = [
    '<areaservice><addrSeq>10</addrSeq></areaservice>',  # outboundarea
    '<areaservice><addrSeq>20</addrSeq></areaservice>',  # inboundarea
]


def test_register_eleven11_calls_stop_display_after_success(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._eleven11_client', lambda prefix: fake_client)
    fake_client.request.side_effect = list(_AREA_RESPONSES)

    with patch('shared.platforms.eleven11.products.build_register_xml',
               return_value='<xml/>'), \
         patch('shared.platforms.eleven11.products.register_product',
               return_value={'productNo': '55501'}), \
         patch('shared.platforms.eleven11.products.stop_display') as mock_stop, \
         patch('shared.platforms.eleven11.products.get_product_detail') as mock_detail:
        mock_stop.return_value = {'resultCode': '200'}
        mock_detail.return_value = {'sel_stat_cd': '105', 'sel_stat_nm': '전시중지'}
        result = _register_eleven11({'name': '테스트상품'}, '')

    assert result['product_id'] == '55501'
    mock_stop.assert_called_once_with('55501', client=fake_client)
    mock_detail.assert_called_once_with('55501', client=fake_client)
    assert result['raw'].get('_suspend_failed') is None


def test_register_eleven11_marks_suspend_failed_when_stop_display_falsy(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._eleven11_client', lambda prefix: fake_client)
    fake_client.request.side_effect = list(_AREA_RESPONSES)

    with patch('shared.platforms.eleven11.products.build_register_xml',
               return_value='<xml/>'), \
         patch('shared.platforms.eleven11.products.register_product',
               return_value={'productNo': '55502'}), \
         patch('shared.platforms.eleven11.products.stop_display', return_value=None):
        result = _register_eleven11({'name': '테스트상품'}, '')

    assert result['product_id'] == '55502'
    assert result['raw'].get('_suspend_failed') is True


def test_register_eleven11_marks_suspend_failed_when_stop_display_raises(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._eleven11_client', lambda prefix: fake_client)
    fake_client.request.side_effect = list(_AREA_RESPONSES)

    with patch('shared.platforms.eleven11.products.build_register_xml',
               return_value='<xml/>'), \
         patch('shared.platforms.eleven11.products.register_product',
               return_value={'productNo': '55503'}), \
         patch('shared.platforms.eleven11.products.stop_display',
               side_effect=RuntimeError('boom')):
        result = _register_eleven11({'name': '테스트상품'}, '')

    assert result['product_id'] == '55503'
    assert result['raw'].get('_suspend_failed') is True


def test_register_eleven11_marks_suspend_failed_when_reverify_still_on_sale(monkeypatch):
    """stop_display 가 참을 돌려줘도(거짓 성공) 재조회가 여전히 판매중이면 잡아낸다.

    11번가는 HTTP 200/resultCode 만으로는 실제 전시중지 여부를 못 믿는 마켓이다
    (products.py register_product 의 「거짓 성공 금지」 주석과 같은 특성).
    api_suspend_eleven11 이 쓰는 방식대로 get_product_detail 로 sel_stat_cd 를
    재조회 확인해야, 이 「거짓 성공」을 잡을 수 있다.
    """
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._eleven11_client', lambda prefix: fake_client)
    fake_client.request.side_effect = list(_AREA_RESPONSES)

    with patch('shared.platforms.eleven11.products.build_register_xml',
               return_value='<xml/>'), \
         patch('shared.platforms.eleven11.products.register_product',
               return_value={'productNo': '55504'}), \
         patch('shared.platforms.eleven11.products.stop_display') as mock_stop, \
         patch('shared.platforms.eleven11.products.get_product_detail') as mock_detail:
        mock_stop.return_value = {'resultCode': '200'}  # 거짓 성공 — 응답은 멀쩡
        mock_detail.return_value = {'sel_stat_cd': '103', 'sel_stat_nm': '판매중'}
        result = _register_eleven11({'name': '테스트상품'}, '')

    assert result['product_id'] == '55504'
    mock_detail.assert_called_once_with('55504', client=fake_client)
    assert result['raw'].get('_suspend_failed') is True


def test_register_eleven11_marks_suspend_failed_when_reverify_raises(monkeypatch):
    """stop_display 는 성공했지만 재조회(get_product_detail) 자체가 예외를 내면
    검증을 못 했으니 성공으로 단정하지 않고 실패로 남긴다."""
    fake_client = MagicMock()
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._eleven11_client', lambda prefix: fake_client)
    fake_client.request.side_effect = list(_AREA_RESPONSES)

    with patch('shared.platforms.eleven11.products.build_register_xml',
               return_value='<xml/>'), \
         patch('shared.platforms.eleven11.products.register_product',
               return_value={'productNo': '55505'}), \
         patch('shared.platforms.eleven11.products.stop_display') as mock_stop, \
         patch('shared.platforms.eleven11.products.get_product_detail',
               side_effect=RuntimeError('detail boom')):
        mock_stop.return_value = {'resultCode': '200'}
        result = _register_eleven11({'name': '테스트상품'}, '')

    assert result['product_id'] == '55505'
    assert result['raw'].get('_suspend_failed') is True
