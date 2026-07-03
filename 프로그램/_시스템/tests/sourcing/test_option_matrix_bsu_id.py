# -*- coding: utf-8 -*-
"""[TEST] option-matrix 소싱처 항목에 bundle_source_url_id 노출.

배경: 매트릭스 소싱처 컬럼을 "등록된 7개 고정 소싱처"에서 "(소싱처 × URL) 콤보"
로 전환하기 위해, 백엔드가 각 소싱처 항목에 BundleSourceUrl.id 를 노출해야 한다.
같은 source_key 의 URL 이 여러 개일 때 프론트가 별도 컬럼으로 나눌 수 있도록.

검증:
  1. NEW PATH (OptionSourceUrlLink 경로): 항목에 bundle_source_url_id 가 있고 non-null.
  2. 같은 source_key 의 두 URL 항목이 서로 다른 (distinct) bundle_source_url_id 를 갖는다.
  3. LEGACY+DEDUP PATH: BundleSourceUrl URL 과 일치하는 legacy 항목에 dedup 경로가 bsu.id 주입.
"""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("ENVIRONMENT", "test")

# 전체 모델 등록 (Base.metadata.create_all 이 FK 타겟 테이블을 찾도록)
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
from shared.db import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    from sqlalchemy import text
    s.execute(text("PRAGMA foreign_keys=ON"))
    return s


def _seed_base(s, model_code="LT", sku="LT-블랙-260"):
    """Model + Option 기본 시드."""
    s.add(M.Model(model_code=model_code, model_name_raw="르무통테스트"))
    s.add(M.Option(canonical_sku=sku, model_code=model_code,
                   color_code="블랙", size_code="260", is_active=True))
    s.commit()


def _get_opt_entry(result, sku):
    """result['options'] 에서 sku 로 항목 찾기. options 항목 key 는 'sku'."""
    return next((o for o in result.get("options", []) if o.get("sku") == sku), None)


# ---------------------------------------------------------------------------
# Test: NEW PATH — bundle_source_url_id is exposed
# ---------------------------------------------------------------------------

def test_new_path_single_url_has_bsu_id():
    """NEW PATH (OptionSourceUrlLink): bundle_source_url_id 가 항목에 있고 non-null."""
    s = _make_db()
    _seed_base(s)

    bsu = M.BundleSourceUrl(model_code="LT", source_key="lotteon",
                            url="https://lotteon.com/p/product/LT_BLACK",
                            sort_order=0, url_type="단품")
    s.add(bsu)
    s.flush()

    s.add(M.OptionSourceUrlLink(option_canonical_sku="LT-블랙-260",
                                bundle_source_url_id=bsu.id))
    s.commit()

    from webapp.routes.api_pricing import _option_matrix_data
    import webapp.routes.api_pricing as _mod
    from unittest.mock import patch

    with patch.object(_mod, "SessionLocal", return_value=s):
        result = _option_matrix_data("LT")

    assert result.get("ok"), f"API failed: {result}"
    opts = result.get("options", [])
    assert opts, "옵션이 없음"

    opt_entry = _get_opt_entry(result, "LT-블랙-260")
    assert opt_entry is not None, f"LT-블랙-260 항목 없음. 실제 skus: {[o.get('sku') for o in opts]}"

    sources = opt_entry.get("sources", [])
    lotteon_entries = [e for e in sources if e.get("source_key") == "lotteon"]
    assert lotteon_entries, f"lotteon 소싱처 항목 없음. sources: {sources}"

    entry = lotteon_entries[0]
    assert "bundle_source_url_id" in entry, (
        f"bundle_source_url_id 키 없음. 실제 키: {list(entry.keys())}"
    )
    assert entry["bundle_source_url_id"] is not None, "bundle_source_url_id 가 None"
    assert entry["bundle_source_url_id"] == bsu.id


def test_new_path_two_urls_same_source_have_distinct_bsu_ids():
    """핵심: 같은 source_key 의 두 URL → 각자 다른 bundle_source_url_id."""
    s = _make_db()
    _seed_base(s)

    bsu1 = M.BundleSourceUrl(model_code="LT", source_key="lotteon",
                              url="https://lotteon.com/p/product/LT_ALL",
                              sort_order=0, url_type="통합")
    bsu2 = M.BundleSourceUrl(model_code="LT", source_key="lotteon",
                              url="https://lotteon.com/p/product/LT_BLACK",
                              sort_order=1, url_type="단품")
    s.add_all([bsu1, bsu2])
    s.flush()

    s.add(M.OptionSourceUrlLink(option_canonical_sku="LT-블랙-260",
                                bundle_source_url_id=bsu1.id))
    s.add(M.OptionSourceUrlLink(option_canonical_sku="LT-블랙-260",
                                bundle_source_url_id=bsu2.id))
    s.commit()

    from webapp.routes.api_pricing import _option_matrix_data
    import webapp.routes.api_pricing as _mod
    from unittest.mock import patch

    with patch.object(_mod, "SessionLocal", return_value=s):
        result = _option_matrix_data("LT")

    assert result.get("ok"), f"API failed: {result}"

    opt_entry = _get_opt_entry(result, "LT-블랙-260")
    assert opt_entry is not None

    lotteon_entries = [e for e in opt_entry.get("sources", [])
                       if e.get("source_key") == "lotteon"]
    assert len(lotteon_entries) == 2, (
        f"lotteon 항목이 2개여야 하는데 {len(lotteon_entries)}개: "
        f"{[e.get('product_url') for e in lotteon_entries]}"
    )

    ids = [e.get("bundle_source_url_id") for e in lotteon_entries]
    assert None not in ids, f"bundle_source_url_id 에 None 있음: {ids}"
    assert len(set(ids)) == 2, f"두 URL 의 id 가 같음(distinct 아님): {ids}"
    assert set(ids) == {bsu1.id, bsu2.id}, (
        f"예상 ids={{{bsu1.id},{bsu2.id}}}, 실제={set(ids)}"
    )


# ---------------------------------------------------------------------------
# Test: LEGACY PATH — dedup 경로가 bsu.id 를 주입한다
# ---------------------------------------------------------------------------

def test_legacy_dedup_injects_bsu_id():
    """LEGACY PATH(OptionSourceUrl)와 BundleSourceUrl URL 일치 시 dedup 경로가 bsu.id 주입."""
    s = _make_db()
    _seed_base(s)

    URL = "https://lotteon.com/p/product/LT_BLACK_LEGACY"

    # SourceRegistry FK 대상 행 생성 (OptionSourceUrl.source_id FK)
    from lemouton.sourcing.models_pricing import OptionSourceUrl, SourceRegistry
    sr = SourceRegistry(name="롯데온", main_url="https://lotteon.com", sort_order=0)
    s.add(sr)
    s.flush()

    # legacy OptionSourceUrl 항목 (models_pricing)
    s.add(OptionSourceUrl(canonical_sku="LT-블랙-260", source_id=sr.id,
                          product_url=URL))

    # 같은 URL 로 BundleSourceUrl 도 등록 (dedup 경로에서 매칭됨)
    bsu = M.BundleSourceUrl(model_code="LT", source_key="lotteon",
                            url=URL, sort_order=0, url_type="단품")
    s.add(bsu)
    s.flush()

    s.add(M.OptionSourceUrlLink(option_canonical_sku="LT-블랙-260",
                                bundle_source_url_id=bsu.id))
    s.commit()

    from webapp.routes.api_pricing import _option_matrix_data
    import webapp.routes.api_pricing as _mod
    from unittest.mock import patch

    with patch.object(_mod, "SessionLocal", return_value=s):
        result = _option_matrix_data("LT")

    assert result.get("ok"), f"API failed: {result}"

    opt_entry = _get_opt_entry(result, "LT-블랙-260")
    assert opt_entry is not None

    sources = opt_entry.get("sources", [])
    # URL 이 같으므로 dedup 후 항목 1개여야 함
    url_entries = [e for e in sources if e.get("product_url") == URL]
    assert len(url_entries) == 1, (
        f"dedup 후 1개여야 함. 현재: {len(url_entries)}"
    )

    entry = url_entries[0]
    assert entry.get("bundle_source_url_id") == bsu.id, (
        f"dedup 경로가 bsu.id({bsu.id}) 주입 안 함. "
        f"실제 bundle_source_url_id={entry.get('bundle_source_url_id')}"
    )


# ---------------------------------------------------------------------------
# Test: ★합계 폴백 금지 (2026-07-03) — 매칭된 SO + current_stock=None
# ---------------------------------------------------------------------------

def test_matched_so_null_stock_no_aggregate_fallback():
    """★버그방지: 색·사이즈 SourceOption 이 매칭됐는데 current_stock=None(그 사이즈 미수집)이면,
    상품 SourceProduct.last_stock(=전 사이즈 합계)로 폴백하면 안 된다.

    실사례: SSG 단품 블랙 — 13사이즈 중 일부 current_stock 이 NULL → 매트릭스가 last_stock(380,
    전 사이즈 합계)로 그 칸만 둔갑 → '없는 재고'가 떠 금전 위험. 매칭됐으면 None(미상/크롤실패)로
    정직하게 표면화해야 한다(가격 폴백금지와 동일 원칙).
    """
    s = _make_db()
    _seed_base(s)  # 블랙 260 옵션

    URL = "https://www.ssg.com/item/itemView.ssg?itemId=1000526347285"
    bsu = M.BundleSourceUrl(model_code="LT", source_key="ssg",
                            url=URL, sort_order=0, url_type="단품")
    s.add(bsu)
    s.flush()
    s.add(M.OptionSourceUrlLink(option_canonical_sku="LT-블랙-260",
                                bundle_source_url_id=bsu.id))

    from lemouton.sources.models import SourceProduct, SourceOption
    sp = SourceProduct(site="ssg", url=URL, last_stock=380, last_status="ok")
    s.add(sp)
    s.flush()
    # 색·사이즈 SO 행은 존재(=매칭됨) 하지만 그 사이즈 재고 미수집 → current_stock=None
    s.add(SourceOption(source_product_id=sp.id, color_text="블랙",
                       size_text="260", current_stock=None, current_price=119900))
    s.commit()

    from webapp.routes.api_pricing import _option_matrix_data
    import webapp.routes.api_pricing as _mod
    from unittest.mock import patch

    with patch.object(_mod, "SessionLocal", return_value=s):
        result = _option_matrix_data("LT")

    assert result.get("ok"), f"API failed: {result}"
    opt_entry = _get_opt_entry(result, "LT-블랙-260")
    assert opt_entry is not None

    ssg_entries = [e for e in opt_entry.get("sources", [])
                   if e.get("source_key") == "ssg"]
    assert ssg_entries, f"ssg 소싱처 항목 없음. sources: {opt_entry.get('sources')}"
    entry = ssg_entries[0]

    # 매칭 자체는 성공(안 파는 조합 아님) — match_failed 는 False 여야 이 케이스가 성립
    assert entry.get("match_failed") is False, (
        f"이 테스트는 '매칭됨' 케이스여야 함. match_failed={entry.get('match_failed')}"
    )
    # ★핵심: 합계(380)로 폴백하지 않고 None(미상)
    assert entry.get("crawled_stock") is None, (
        f"매칭된 SO 의 current_stock=None → crawled_stock 은 None(미상)이어야 하는데 "
        f"{entry.get('crawled_stock')} (=last_stock 합계 380 폴백 = 버그)"
    )
