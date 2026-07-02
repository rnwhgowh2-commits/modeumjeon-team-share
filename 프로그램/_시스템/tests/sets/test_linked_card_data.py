"""P4 Task1 — list_linked_sets 가 카드용 소/판 요약·신호등 상태를 내려주는지."""
import datetime as _dt

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
from lemouton.sets.models import (
    ProductSet, SetProduct, SetOption, SetChannel, SetChannelOption,
)
from lemouton.sets import set_service as svc


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _seed(db, market, mkt_stock):
    ps = ProductSet(model_code="M1", name="르무통 메이트 모음전")
    db.add(ps)
    db.flush()
    sp = SetProduct(set_id=ps.id, model_code="M1", quantity=1)
    db.add(sp)
    db.flush()
    db.add(SetOption(set_product_id=sp.id, canonical_sku="SKU1", sort_order=0))
    ch = SetChannel(set_id=ps.id, market=market, account_key="default",
                    market_product_id="999", status="linked")
    db.add(ch)
    db.flush()
    db.add(SetChannelOption(
        channel_id=ch.id, canonical_sku="SKU1", market_option_id="11",
        status="matched", mkt_stock=mkt_stock, mkt_price=125000,
        mkt_fetched_at=_dt.datetime(2026, 6, 30, 8, 50)))
    db.commit()
    return ps


def test_channel_market_summary_and_signals(db):
    _seed(db, "smartstore", 50)
    rows = svc.list_linked_sets(db)
    assert len(rows) == 1
    ch = rows[0]["channels"][0]
    assert ch["mkt_stock_total"] == 50
    assert ch["mkt_price"] == 125000
    sig = ch["signals"]
    assert sig["send"] == "warn"    # last_sent_at None = 미전송
    assert sig["stock"] == "ok"     # 재고 50 > 0, soldout 알림 없음
    assert sig["price"] == "ok"


def test_market_soldout_makes_stock_sev(db):
    _seed(db, "smartstore", 0)
    ch = svc.list_linked_sets(db)[0]["channels"][0]
    assert ch["mkt_stock_total"] == 0
    assert ch["signals"]["stock"] == "sev"   # mkt_stock 0 → market_soldout → 심각


def test_src_summary_from_injected_provider(db):
    _seed(db, "smartstore", 50)

    def provider(model_codes, skus):
        assert "M1" in model_codes and "SKU1" in skus
        return {"SKU1": {"stock": 53, "source_name": "르무통"}}

    row = svc.list_linked_sets(db, src_provider=provider)[0]
    assert row["src_summary"]["src_stock_total"] == 53
    assert row["src_summary"]["source_name"] == "르무통"


def test_src_summary_none_without_provider(db):
    _seed(db, "smartstore", 50)
    row = svc.list_linked_sets(db)[0]
    assert row["src_summary"]["src_stock_total"] is None
    assert row["src_summary"]["source_url"] is None


def test_src_summary_source_url_from_provider(db):
    """[A] 대표 소싱처 상품 URL이 src_summary.source_url 로 카드까지 실린다(바로가기 ↗)."""
    _seed(db, "smartstore", 50)

    def provider(model_codes, skus):
        return {"SKU1": {"stock": 53, "source_name": "르무통",
                         "source_url": "https://lemouton.com/p/1"}}

    row = svc.list_linked_sets(db, src_provider=provider)[0]
    assert row["src_summary"]["source_name"] == "르무통"
    assert row["src_summary"]["source_url"] == "https://lemouton.com/p/1"


def test_src_summary_source_url_none_for_purchase(db):
    """[A] 사입(대표 소싱처 URL 없음)은 source_url None — 바로가기 링크 안 검."""
    _seed(db, "smartstore", 50)

    def provider(model_codes, skus):
        return {"SKU1": {"stock": 60, "source_name": "사입", "source_url": None}}

    row = svc.list_linked_sets(db, src_provider=provider)[0]
    assert row["src_summary"]["source_name"] == "사입"
    assert row["src_summary"]["source_url"] is None


def test_rep_source_url_matches_representative_name(db):
    """[A] _rep_source_url = 대표(최다 등장) 소싱처명에 해당하는 URL만 취한다."""
    from lemouton.sets.set_service import _rep_source_url
    smap = {
        "A": {"source_name": "르무통", "source_url": "https://lemouton.com/a"},
        "B": {"source_name": "르무통", "source_url": "https://lemouton.com/b"},
        "C": {"source_name": "SSF", "source_url": "https://ssf.com/c"},
    }
    assert _rep_source_url(smap, "르무통") == "https://lemouton.com/a"
    assert _rep_source_url(smap, None) is None
    assert _rep_source_url({}, "르무통") is None


def test_src_summary_price_2values_from_provider(db):
    """[가격 2값] 표면노출가·최종매입가가 src_summary.surface/final 로 카드까지 실린다."""
    _seed(db, "smartstore", 50)

    def provider(model_codes, skus):
        return {"SKU1": {"stock": 53, "source_name": "르무통",
                         "surface": 133900, "final": 126380}}

    ss = svc.list_linked_sets(db, src_provider=provider)[0]["src_summary"]
    assert ss["surface"] == 133900
    assert ss["final"] == 126380


def test_src_summary_price_none_without_provider(db):
    """[가격 2값] provider 없으면 표면·최종 None(지연 — '상세 ▾' 폴백)."""
    _seed(db, "smartstore", 50)
    ss = svc.list_linked_sets(db)[0]["src_summary"]
    assert ss["surface"] is None and ss["final"] is None


def test_rep_price_picks_min_surface_coherent(db):
    """[가격 2값] _rep_price = 표면 최저 옵션의 (표면, 최종, 영수증) 코히런트 3값."""
    from lemouton.sets.set_service import _rep_price
    rcB = {"surface": 133900, "final": 126380, "steps": []}
    smap = {
        "A": {"surface": 140000, "final": 132000, "receipt": {"final": 132000}},
        "B": {"surface": 133900, "final": 126380, "receipt": rcB},   # 표면 최저 → 이 쌍
        "C": {"surface": 150000, "final": 141000, "receipt": {"final": 141000}},
    }
    assert _rep_price(smap) == (133900, 126380, rcB)


def test_rep_price_purchase_only_no_surface(db):
    """[가격 2값] 표면 없는 사입-only 세트 = (None, 최저 최종매입가, 그 영수증)."""
    from lemouton.sets.set_service import _rep_price
    smap = {"A": {"surface": None, "final": 90000, "receipt": None},
            "B": {"surface": None, "final": 85000, "receipt": {"final": 85000}}}
    assert _rep_price(smap) == (None, 85000, {"final": 85000})
    assert _rep_price({}) == (None, None, None)


def test_src_summary_receipt_from_provider(db):
    """[상세 영수증] 대표 옵션의 영수증이 src_summary.receipt 로 카드까지 실린다."""
    _seed(db, "smartstore", 50)
    rc = {"source_name": "롯데아이몰", "surface": 138000, "final": 126380,
          "steps": [{"name": "신용카드 청구할인", "deduct": 6900, "base_after": 131100},
                    {"name": "적립 혜택", "deduct": 4720, "base_after": 126380}]}

    def provider(model_codes, skus):
        return {"SKU1": {"stock": 53, "source_name": "롯데아이몰",
                         "surface": 138000, "final": 126380, "receipt": rc}}

    ss = svc.list_linked_sets(db, src_provider=provider)[0]["src_summary"]
    assert ss["receipt"] == rc
    assert ss["receipt"]["steps"][0]["deduct"] == 6900


def _prov(model_codes, skus):
    return {"SKU1": {"stock": 53, "source_name": "르무통",
                     "ss_price": 125000, "cp_price": 129000}}


def test_channel_planned_price_smartstore(db):
    _seed(db, "smartstore", 50)
    ch = svc.list_linked_sets(db, src_provider=_prov)[0]["channels"][0]
    assert ch["planned_price"] == 125000   # 스마트스토어 → ss_price


def test_channel_planned_price_coupang(db):
    _seed(db, "coupang", 50)
    ch = svc.list_linked_sets(db, src_provider=_prov)[0]["channels"][0]
    assert ch["planned_price"] == 129000   # 쿠팡 → cp_price


def test_planned_price_none_without_provider(db):
    _seed(db, "smartstore", 50)
    ch = svc.list_linked_sets(db)[0]["channels"][0]
    assert ch["planned_price"] is None
