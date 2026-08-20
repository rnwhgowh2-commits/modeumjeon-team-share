# -*- coding: utf-8 -*-
"""롯데온 등록 직후 자동 판매종료(판매중단) — 스마트스토어·ESM·11번가와 같은 안전장치.

배경: shared/platforms/lotteon/products.py:set_sale_status(spd_no, sl_stat_cd, *,
client) 가 이미 있다(sl_stat_cd: END=판매종료/SOUT=품절). 등록 경로
(_register_lotteon)는 등록 직후 자동으로 호출하지 않아 등록되는 상품이 판매중
(SALE) 상태로 방치된다. 이 시험은 등록(spdNo 수령) 끝난 뒤 set_sale_status 가
'END' 로 반드시 호출되는지, 실패/예외 시 result['raw']['_suspend_failed'] 흔적이
남는지 확인한다.

END 를 고른 이유: SOUT(품절)은 재고 수치에 연동된 상태라, 이후 재고 동기화가
재고를 채우면 자동으로 판매중으로 되돌아갈 위험이 있다. END(판매종료)는 재고와
무관하게 고정되는 상태라 안전하다.

★ 패치 대상 주의(ESM·11번가 태스크에서 겪은 함정과 동일): get_product_detail·
  build_register_payload·register_product 는 send_more.py 최상단이 아니라
  `_register_lotteon` 함수 몸통 안에서 `from shared.platforms.lotteon.products
  import (...)` 로 지역 import 된다. 그래서 `lemouton.registration.send_more.*`
  를 패치하면 이름이 send_more 모듈 네임스페이스에 없어 아무 효과가 없다 —
  실제로 참조하는 `shared.platforms.lotteon.products` 쪽을 패치해야 한다.

★ [재조회 검증 필요 — 직접 확인] shared/platforms/lotteon/products.py:344 의
  set_sale_status 자체 docstring 이 이미 "반환 True 여도 호출부가
  get_product_detail 로 slStatCd 재조회 검증 권장" 이라 명시한다. 코드도 그 말대로다
  — status/change 응답의 최상위 returnCode 만 보고 boolean 을 리턴하며(:344 return
  str(resp.get("returnCode")) in ("0000", "SUCCESS")), register_product 의 「함정2」
  (최상위 0000 이어도 data[] 항목별 resultCode 가 실패일 수 있음, 같은 spdLst 래퍼
  구조)와 동일한 위험을 안고 있다. 그래서 11번가와 같은 패턴으로 get_product_detail
  재조회(spdSlStatCd == 'END' 확인)를 추가한다. get_product_detail 은 이미
  _register_lotteon 안에서 본보기 조회용으로 top-of-function import 돼 있으므로
  재사용한다(별도 로컬 import 불필요).
"""
from unittest.mock import MagicMock, patch

from lemouton.registration.send_more import _register_lotteon

_TEMPLATE = {
    'dmstOvsDvDvsCd': 'DMST', 'spdSlStatCd': 'SALE',
    'itmLst': [{'itmImgLst': [{'origImgFileNm': 'old.jpg'}]}],
}
_SPEC = {
    'template_spd_no': '1', 'spd_nm': '테스트', 'price': 10000, 'stock': 1,
    'image_url': 'new.jpg',
}
_BUILT_PAYLOAD = {'itmLst': [{'itmImgLst': [{'origImgFileNm': 'old.jpg'}]}]}


def _patch_market_fetch(monkeypatch, fake_client):
    monkeypatch.setattr(
        'lemouton.uploader.market_fetch._lotteon_client', lambda prefix: fake_client)


def test_register_lotteon_calls_set_sale_status_after_success(monkeypatch):
    fake_client = MagicMock()
    _patch_market_fetch(monkeypatch, fake_client)

    with patch('shared.platforms.lotteon.products.get_product_detail') as mock_detail, \
         patch('shared.platforms.lotteon.products.build_register_payload',
               return_value=dict(_BUILT_PAYLOAD)), \
         patch('shared.platforms.lotteon.products.register_product',
               return_value={'spdNo': '77701'}), \
         patch('shared.platforms.lotteon.products.set_sale_status') as mock_status:
        mock_detail.side_effect = [
            dict(_TEMPLATE),              # ① 본보기 조회
            {'spdSlStatCd': 'END'},       # ② 판매종료 재조회 검증
        ]
        mock_status.return_value = True
        result = _register_lotteon(dict(_SPEC), '')

    assert result['product_id'] == '77701'
    mock_status.assert_called_once_with('77701', 'END', client=fake_client)
    assert mock_detail.call_count == 2
    mock_detail.assert_called_with('77701', client=fake_client)
    assert result['raw'].get('_suspend_failed') is None


def test_register_lotteon_marks_suspend_failed_when_set_sale_status_falsy(monkeypatch):
    fake_client = MagicMock()
    _patch_market_fetch(monkeypatch, fake_client)

    with patch('shared.platforms.lotteon.products.get_product_detail',
               return_value=dict(_TEMPLATE)), \
         patch('shared.platforms.lotteon.products.build_register_payload',
               return_value=dict(_BUILT_PAYLOAD)), \
         patch('shared.platforms.lotteon.products.register_product',
               return_value={'spdNo': '77702'}), \
         patch('shared.platforms.lotteon.products.set_sale_status', return_value=False):
        result = _register_lotteon(dict(_SPEC), '')

    assert result['product_id'] == '77702'
    assert result['raw'].get('_suspend_failed') is True


def test_register_lotteon_marks_suspend_failed_when_set_sale_status_raises(monkeypatch):
    fake_client = MagicMock()
    _patch_market_fetch(monkeypatch, fake_client)

    with patch('shared.platforms.lotteon.products.get_product_detail',
               return_value=dict(_TEMPLATE)), \
         patch('shared.platforms.lotteon.products.build_register_payload',
               return_value=dict(_BUILT_PAYLOAD)), \
         patch('shared.platforms.lotteon.products.register_product',
               return_value={'spdNo': '77703'}), \
         patch('shared.platforms.lotteon.products.set_sale_status',
               side_effect=RuntimeError('boom')):
        result = _register_lotteon(dict(_SPEC), '')

    assert result['product_id'] == '77703'
    assert result['raw'].get('_suspend_failed') is True


def test_register_lotteon_marks_suspend_failed_when_reverify_still_on_sale(monkeypatch):
    """set_sale_status 가 참을 돌려줘도(거짓 성공) 재조회가 여전히 판매중이면 잡아낸다.

    set_sale_status 는 최상위 returnCode 만 보고 boolean 을 만든다 — register_product
    의 「함정2」(최상위 0000 이어도 항목별 resultCode 는 실패일 수 있음)와 같은 위험을
    안고 있어, get_product_detail 로 spdSlStatCd 를 재조회 확인해야 이 「거짓 성공」을
    잡을 수 있다.
    """
    fake_client = MagicMock()
    _patch_market_fetch(monkeypatch, fake_client)

    with patch('shared.platforms.lotteon.products.get_product_detail') as mock_detail, \
         patch('shared.platforms.lotteon.products.build_register_payload',
               return_value=dict(_BUILT_PAYLOAD)), \
         patch('shared.platforms.lotteon.products.register_product',
               return_value={'spdNo': '77704'}), \
         patch('shared.platforms.lotteon.products.set_sale_status', return_value=True):
        mock_detail.side_effect = [
            dict(_TEMPLATE),
            {'spdSlStatCd': 'SALE'},   # 거짓 성공 — 여전히 판매중
        ]
        result = _register_lotteon(dict(_SPEC), '')

    assert result['product_id'] == '77704'
    assert mock_detail.call_count == 2
    assert result['raw'].get('_suspend_failed') is True


def test_register_lotteon_marks_suspend_failed_when_reverify_raises(monkeypatch):
    """set_sale_status 는 성공했지만 재조회(get_product_detail) 자체가 예외를 내면
    검증을 못 했으니 성공으로 단정하지 않고 실패로 남긴다."""
    fake_client = MagicMock()
    _patch_market_fetch(monkeypatch, fake_client)

    with patch('shared.platforms.lotteon.products.get_product_detail') as mock_detail, \
         patch('shared.platforms.lotteon.products.build_register_payload',
               return_value=dict(_BUILT_PAYLOAD)), \
         patch('shared.platforms.lotteon.products.register_product',
               return_value={'spdNo': '77705'}), \
         patch('shared.platforms.lotteon.products.set_sale_status', return_value=True):
        mock_detail.side_effect = [dict(_TEMPLATE), RuntimeError('detail boom')]
        result = _register_lotteon(dict(_SPEC), '')

    assert result['product_id'] == '77705'
    assert result['raw'].get('_suspend_failed') is True
