# -*- coding: utf-8 -*-
"""[TEST] 마켓 송신 직전 가격 안전 게이트 (#1, 2026-06-13).

배경: 쿠팡 송신부엔 price<=0 가드가 있었으나 스마트스토어 송신부엔 없어,
      상위 폴백(대표가·95000·정가대체)으로 0/비정상 가격이 생기면 그대로 네이버에
      PUT 될 수 있었다. 이 게이트가 라이브 전송을 abort 한다.
"""
import pytest

from shared.platforms.price_guard import assert_live_sale_price, UnsafePriceError


class TestAssertLiveSalePrice:
    def test_positive_ok(self):
        assert assert_live_sale_price(119900) == 119900
        assert assert_live_sale_price("128900") == 128900

    def test_zero_blocked(self):
        with pytest.raises(UnsafePriceError):
            assert_live_sale_price(0)

    def test_negative_blocked(self):
        with pytest.raises(UnsafePriceError):
            assert_live_sale_price(-100)

    def test_none_blocked(self):
        with pytest.raises(UnsafePriceError):
            assert_live_sale_price(None)

    def test_non_int_blocked(self):
        with pytest.raises(UnsafePriceError):
            assert_live_sale_price("abc")


class TestEditOptionsAbortsBeforeHttp:
    """edit_options 가 0원 sale_price 면 HTTP(클라이언트 생성/요청) 전에 abort 하는지."""

    def test_zero_sale_price_raises_before_any_request(self):
        # client 를 넘기지 않아도(=실제 SmartStoreClient 생성 전) 가드에서 먼저 raise.
        from shared.platforms.smartstore.edit_product import edit_options
        with pytest.raises(UnsafePriceError):
            edit_options(123456, sale_price=0)

    def test_negative_sale_price_raises(self):
        from shared.platforms.smartstore.edit_product import edit_options
        with pytest.raises(UnsafePriceError):
            edit_options(123456, sale_price=-5000)

    def test_none_sale_price_allowed_to_proceed(self):
        # sale_price=None('현재값 유지')은 가드 통과 → 이후 단계로 진행(HTTP 시도).
        #   여기선 가드만 검증: UnsafePriceError 가 안 나는 것으로 확인(다른 예외는 무관).
        from shared.platforms.smartstore.edit_product import edit_options
        try:
            edit_options(123456, sale_price=None,
                         client=_StubClient())
        except UnsafePriceError:
            pytest.fail("sale_price=None 은 게이트를 통과해야 한다")
        except Exception:
            pass  # 네트워크/스텁 관련 다른 예외는 이 테스트 관심사 아님


class _StubClient:
    """HTTP 안 나가는 스텁 — None 케이스가 가드를 통과하는지만 확인용."""
    def request(self, *a, **k):
        return {"originProduct": {}}
