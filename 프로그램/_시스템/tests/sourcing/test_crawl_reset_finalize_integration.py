# -*- coding: utf-8 -*-
"""[2026-06-28] 통합(실DB) 회귀 — 크롤 시작 하드리셋 + 종료 판매차단(crawl_blocked).

배경(S14): _reset_bundle_crawl_state·_finalize_bundle_crawl_block 가 2026-06-22 stale 브랜치
머지(94466889)에서 api_pricing.py 와 함께 유실되고 Option.crawl_blocked 컬럼도 사라졌다.
service.py::crawl_bundle_registered_urls 의 import 가 try/except:pass 로 감싸져 ImportError 가
조용히 삼켜져 → 하드리셋·판매차단이 inert. 결과: 옛 가격/재고로 가짜 '재고있음'(S14) + 업로드
게이트(preview.py:149 crawl_blocked) 무력.

이 테스트는 in-memory SQLite 에 실제 모음전(Model+Option+BundleSourceUrl+SourceProduct)을 시드해
_option_matrix_data(단일 진실 원천) 경로로 두 함수를 실제 DB 에 대고 돌린다:
  · 리셋: SourceProduct 가격/재고/상태 NULL·'pending', 모든 옵션 crawl_blocked=True (pessimistic).
  · 종료: 유효 소싱가(is_crawl_valid) 있는 옵션만 crawl_blocked 해제, 없는 옵션은 차단 유지.
Option.crawl_blocked 컬럼이 create_all 로 생성되는지도 함께 검증(모델 복원 확인).
"""
import os
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

os.environ.setdefault("ENVIRONMENT", "test")

# 전체 모델 등록 (create_all 이 FK 타겟까지 찾도록)
for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M
from lemouton.sources.models import SourceProduct
from shared.db import Base

URL_A = "https://lotteon.com/p/product/LT_BLACK"
URL_B = "https://lotteon.com/p/product/LT_GREY"


def _make_db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.execute(text("PRAGMA foreign_keys=ON"))
    return s


def _seed(s):
    """모음전 LT — 두 옵션, 각 옵션이 별도 URL/SourceProduct 에 연결."""
    s.add(M.Model(model_code="LT", model_name_raw="르무통테스트"))
    # 옵션 A(블랙) — 크롤 성공 예정 / 옵션 B(그레이) — 크롤 실패 예정
    s.add(M.Option(canonical_sku="LT-블랙-260", model_code="LT",
                   color_code="블랙", size_code="260", is_active=True))
    s.add(M.Option(canonical_sku="LT-그레이-270", model_code="LT",
                   color_code="그레이", size_code="270", is_active=True))
    s.commit()  # Model/Option 먼저 커밋(FK 타겟 확정) — 이후 URL/링크 추가

    bsu_a = M.BundleSourceUrl(model_code="LT", source_key="lotteon",
                              url=URL_A, sort_order=0, url_type="단품")
    bsu_b = M.BundleSourceUrl(model_code="LT", source_key="lotteon",
                              url=URL_B, sort_order=1, url_type="단품")
    s.add_all([bsu_a, bsu_b])
    s.flush()
    s.add(M.OptionSourceUrlLink(option_canonical_sku="LT-블랙-260",
                                bundle_source_url_id=bsu_a.id))
    s.add(M.OptionSourceUrlLink(option_canonical_sku="LT-그레이-270",
                                bundle_source_url_id=bsu_b.id))

    # 옛(stale) 크롤값 — 리셋이 비워야 하는 대상
    s.add(SourceProduct(site="lotteon", url=URL_A, last_price=99999,
                        last_stock=5, last_status="ok"))
    s.add(SourceProduct(site="lotteon", url=URL_B, last_price=88888,
                        last_stock=3, last_status="ok"))
    s.commit()


def _opt(s, sku):
    return s.get(M.Option, sku)


def test_reset_nulls_prices_and_pessimistically_blocks():
    s = _make_db()
    _seed(s)
    from webapp.routes.api_pricing import _reset_bundle_crawl_state
    import webapp.routes.api_pricing as _mod

    with patch.object(_mod, "SessionLocal", return_value=s):
        res = _reset_bundle_crawl_state(s, "LT")

    # SourceProduct 가격/재고/상태가 비워짐(NULL/'pending')
    for sp in s.query(SourceProduct).all():
        assert sp.last_price is None
        assert sp.last_stock is None
        assert sp.last_status == "pending"
    # 모든 옵션 pessimistic 차단
    assert _opt(s, "LT-블랙-260").crawl_blocked is True
    assert _opt(s, "LT-그레이-270").crawl_blocked is True
    assert res["reset_products"] == 2
    assert res["blocked_options"] == 2


def test_finalize_unblocks_only_valid_priced_options():
    s = _make_db()
    _seed(s)
    from webapp.routes.api_pricing import (
        _reset_bundle_crawl_state, _finalize_bundle_crawl_block,
    )
    import webapp.routes.api_pricing as _mod

    with patch.object(_mod, "SessionLocal", return_value=s):
        _reset_bundle_crawl_state(s, "LT")

        # 크롤 시뮬레이션: A 는 유효 가격 'ok', B 는 'error'(가격 못 잡음)
        sp_a = s.query(SourceProduct).filter_by(url=URL_A).one()
        sp_a.last_price = 120000
        sp_a.last_status = "ok"
        sp_b = s.query(SourceProduct).filter_by(url=URL_B).one()
        sp_b.last_price = None
        sp_b.last_status = "error"
        s.commit()

        res = _finalize_bundle_crawl_block(s, "LT")

    # 유효 소싱가 있는 A → 판매가능 / 없는 B → 차단 유지
    assert _opt(s, "LT-블랙-260").crawl_blocked is False
    assert _opt(s, "LT-그레이-270").crawl_blocked is True
    assert res == {"blocked": 1, "sellable": 1}


def test_finalize_blocks_when_stale_price_but_error_status():
    """크롤 실패(error)인데 옛 가격이 남아도 절대 판매에 쓰지 않는다(폴백 금지)."""
    s = _make_db()
    _seed(s)
    from webapp.routes.api_pricing import _finalize_bundle_crawl_block
    import webapp.routes.api_pricing as _mod

    # 리셋 없이: A 는 error+옛가격 잔존, B 는 정상
    sp_a = s.query(SourceProduct).filter_by(url=URL_A).one()
    sp_a.last_price = 110300
    sp_a.last_status = "error"
    sp_b = s.query(SourceProduct).filter_by(url=URL_B).one()
    sp_b.last_price = 50000
    sp_b.last_status = "ok"
    s.commit()

    with patch.object(_mod, "SessionLocal", return_value=s):
        _finalize_bundle_crawl_block(s, "LT")

    assert _opt(s, "LT-블랙-260").crawl_blocked is True   # error → 차단(옛가격 무시)
    assert _opt(s, "LT-그레이-270").crawl_blocked is False  # ok → 판매가능
