# -*- coding: utf-8 -*-
"""판매처 확장 기능 커넥터 — 마스터 게이트 OFF + 레지스트리 전수 import 검증."""
import pytest

from lemouton.markets import capabilities as cap


def test_gate_default_off(monkeypatch):
    monkeypatch.delenv("MOUM_MARKET_EXTRA", raising=False)
    assert cap.market_extra_enabled() is False


def test_gate_on_when_flag(monkeypatch):
    monkeypatch.setenv("MOUM_MARKET_EXTRA", "1")
    assert cap.market_extra_enabled() is True


def test_supported_markets():
    assert set(cap.supported_markets()) == {"coupang", "smartstore", "lotteon"}


def test_extended_capabilities_registered():
    ck = {c.key for c in cap.list_capabilities("coupang")}
    for k in ["order_fetch", "settlement_fetch", "claim_list",
              "inquiry_fetch", "category_meta", "shipping_outbound"]:
        assert k in ck
    sk = {c.key for c in cap.list_capabilities("smartstore")}
    for k in ["order_fetch", "claim_handle", "inquiry_reply", "product_delete"]:
        assert k in sk


def test_resolve_disabled_when_off(monkeypatch):
    monkeypatch.delenv("MOUM_MARKET_EXTRA", raising=False)
    with pytest.raises(cap.CapabilityDisabled):
        cap.resolve("coupang", "order_fetch")       # 미검증 확장 → 차단


def test_verified_bypasses_gate(monkeypatch):
    monkeypatch.delenv("MOUM_MARKET_EXTRA", raising=False)
    fn = cap.resolve("coupang", "price_update")     # 이미 실사용 → 게이트 무관
    assert callable(fn)


def test_unknown_capability_raises():
    with pytest.raises(KeyError):
        cap.resolve("coupang", "nope")


def test_all_wrappers_import_when_enabled(monkeypatch):
    """게이트 ON → 등록된 모든 (마켓×기능)의 함수가 실제로 import·존재해야 한다.
    레지스트리 경로·함수명 오타를 잡는 전수 검증."""
    monkeypatch.setenv("MOUM_MARKET_EXTRA", "1")
    for m in cap.supported_markets():
        for c in cap.list_capabilities(m):
            fn = cap.resolve(m, c.key)
            assert callable(fn), f"{m}/{c.key} -> {c.module}.{c.func}"
