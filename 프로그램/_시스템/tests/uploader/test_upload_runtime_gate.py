# -*- coding: utf-8 -*-
"""[TEST] a번 — 판매처 실전송 배선 (전송 기본 OFF).

핵심 안전 보증:
  · MOUM_LIVE_UPLOAD 미설정/거짓 → 항상 DryRunAdapter (외부 호출 0)
  · 플래그가 참일 때만 실제 어댑터 선택
  · sku_by_option 매핑은 matched 채널옵션만, (market, option_id)→canonical_sku
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models", "lemouton.sets.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

from lemouton.uploader.runtime import (
    live_upload_enabled, live_invoice_enabled, select_adapters,
    build_sku_by_option, DryRunAdapter,
)
from lemouton.uploader.adapters.smartstore import SmartStoreAdapter
from lemouton.uploader.adapters.coupang import CoupangAdapter
from lemouton.uploader.adapters.lotteon import LotteonAdapter


class TestLiveUploadFlag:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
        assert live_upload_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "on", "yes"])
    def test_truthy(self, monkeypatch, val):
        monkeypatch.setenv("MOUM_LIVE_UPLOAD", val)
        assert live_upload_enabled() is True

    @pytest.mark.parametrize("val", ["0", "", "false", "off", "no"])
    def test_falsy(self, monkeypatch, val):
        monkeypatch.setenv("MOUM_LIVE_UPLOAD", val)
        assert live_upload_enabled() is False


class TestLiveInvoiceFlag:
    """송장 실전송은 가격·재고 업로드와 별개 스위치(MOUM_LIVE_INVOICE).

    송장 = 사람이 버튼을 눌러 1건씩. 가격·재고 = 스케줄러가 무인 반복.
    위험도가 달라 같은 스위치로 묶으면 안 된다.
    """

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("MOUM_LIVE_INVOICE", raising=False)
        monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
        assert live_invoice_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "on", "yes"])
    def test_truthy(self, monkeypatch, val):
        monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
        monkeypatch.setenv("MOUM_LIVE_INVOICE", val)
        assert live_invoice_enabled() is True

    @pytest.mark.parametrize("val", ["0", "", "false", "off", "no"])
    def test_falsy(self, monkeypatch, val):
        monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
        monkeypatch.setenv("MOUM_LIVE_INVOICE", val)
        assert live_invoice_enabled() is False

    def test_live_upload_implies_invoice(self, monkeypatch):
        """기존 동작 보존 — LIVE_UPLOAD 만 켜 두면 송장도 실전송."""
        monkeypatch.delenv("MOUM_LIVE_INVOICE", raising=False)
        monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")
        assert live_invoice_enabled() is True

    def test_invoice_on_does_not_arm_price_stock_upload(self, monkeypatch):
        """★ 격리 보증 — 송장을 켜도 가격·재고는 드라이런에 잠겨 있어야 한다."""
        monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
        monkeypatch.setenv("MOUM_LIVE_INVOICE", "1")

        assert live_invoice_enabled() is True
        assert live_upload_enabled() is False
        ad = select_adapters()
        for market in ("smartstore", "coupang", "lotteon",
                       "eleven11", "auction", "gmarket"):
            assert isinstance(ad[market], DryRunAdapter), market


class TestSelectAdapters:
    def test_default_is_dryrun(self, monkeypatch):
        monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
        ad = select_adapters()
        assert isinstance(ad["smartstore"], DryRunAdapter)
        assert isinstance(ad["coupang"], DryRunAdapter)
        assert isinstance(ad["lotteon"], DryRunAdapter)

    def test_dryrun_no_external_call(self, monkeypatch):
        monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
        ss = select_adapters()["smartstore"]
        r = ss.update_price_and_stock(canonical_sku="X", market_product_id="1",
                                      market_option_id="2", new_price=1000, new_stock=5)
        assert r.success is True
        assert "dry-run" in (r.error or "")

    def test_live_flag_selects_real(self, monkeypatch):
        monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")
        ad = select_adapters()
        assert isinstance(ad["smartstore"], SmartStoreAdapter)
        assert isinstance(ad["coupang"], CoupangAdapter)
        assert isinstance(ad["lotteon"], LotteonAdapter)

    def test_explicit_live_false_overrides_env(self, monkeypatch):
        monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")
        ad = select_adapters(live=False)
        assert isinstance(ad["smartstore"], DryRunAdapter)
        assert isinstance(ad["coupang"], DryRunAdapter)
        assert isinstance(ad["lotteon"], DryRunAdapter)


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


class TestBuildSkuByOption:
    def _seed(self, s):
        from lemouton.sets.models import ProductSet, SetChannel, SetChannelOption
        ps = ProductSet(model_code="AF", name="세트1")
        s.add(ps)
        s.flush()
        ch = SetChannel(set_id=ps.id, market="smartstore", account_key="default",
                        market_product_id="P100", status="linked")
        s.add(ch)
        s.flush()
        s.add(SetChannelOption(channel_id=ch.id, canonical_sku="AF-블랙-260",
                               market_option_id="555", status="matched"))
        s.add(SetChannelOption(channel_id=ch.id, canonical_sku="AF-블루-270",
                               market_option_id=None, status="unmatched"))
        s.commit()

    def test_matched_only(self, db):
        self._seed(db)
        m = build_sku_by_option(db)
        assert m.get(("smartstore", "555")) == "AF-블랙-260"
        # 옵션ID 없는 unmatched 는 제외
        assert all(k[1] is not None for k in m)

    def test_numeric_key_both_forms(self, db):
        self._seed(db)
        m = build_sku_by_option(db)
        # C 페이로드 option_id 가 int/str 어느 쪽이어도 매칭되도록 두 형태 등록
        assert m.get(("smartstore", "555")) == "AF-블랙-260"
        assert m.get(("smartstore", 555)) == "AF-블랙-260"
