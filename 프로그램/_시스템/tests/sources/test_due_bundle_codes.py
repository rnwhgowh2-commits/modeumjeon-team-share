# -*- coding: utf-8 -*-
"""[TEST] 마감난 URL → 그 URL이 든 모음전(번들) 코드 매핑 (정규화 매칭)."""
from datetime import datetime, timedelta

from lemouton.sources.crawl_schedule import due_bundle_codes
from lemouton.sources.models import SourceProduct
from lemouton.sourcing.models import Model, BundleSourceUrl
from lemouton.pricing.settings import get_or_init

NOW = datetime(2026, 7, 4, 12, 0, 0)


def _enable(db, on=True):
    s = get_or_init(db)
    s.crawl_auto_enabled = on
    s.crawl_interval_hours = 6
    s.crawl_interval_minutes = 0
    db.flush()


def _bundle_with_url(db, code, url):
    db.add(Model(model_code=code, model_name_raw=code))
    db.flush()
    db.add(BundleSourceUrl(model_code=code, source_key="musinsa", url=url,
                           url_type="단품"))
    db.flush()


def _due_sp(db, url):
    # SourceProduct.url 은 파이프라인이 normalize_url 로 정규화해 저장한다.
    from lemouton.sources.service import normalize_url
    sp = SourceProduct(site="musinsa", url=normalize_url(url), crawl_weight=1,
                       no_change_streak=0, last_fetched_at=None)  # 미크롤=마감
    db.add(sp)
    db.flush()
    return sp


def test_due_url_maps_to_its_bundle_code(db):
    _enable(db, on=True)
    url = "https://www.musinsa.com/products/123"
    _bundle_with_url(db, "M001", url)
    _due_sp(db, url)
    codes = due_bundle_codes(db, now=NOW)
    assert "M001" in codes


def test_disabled_returns_empty(db):
    _enable(db, on=False)
    url = "https://www.musinsa.com/products/123"
    _bundle_with_url(db, "M001", url)
    _due_sp(db, url)
    assert due_bundle_codes(db, now=NOW) == []


def test_not_due_url_excluded(db):
    _enable(db, on=True)
    url = "https://www.musinsa.com/products/999"
    _bundle_with_url(db, "M999", url)
    sp = _due_sp(db, url)
    sp.last_fetched_at = NOW - timedelta(hours=1)  # 6h 미만 → 아직
    db.flush()
    assert "M999" not in due_bundle_codes(db, now=NOW)


def test_codes_deduped(db):
    # 한 번들에 같은 due URL 두 번 등록돼도 코드 1개
    _enable(db, on=True)
    url = "https://www.musinsa.com/products/1"
    db.add(Model(model_code="D1", model_name_raw="D1"))
    db.flush()
    db.add(BundleSourceUrl(model_code="D1", source_key="musinsa", url=url, url_type="단품"))
    db.add(BundleSourceUrl(model_code="D1", source_key="musinsa", url=url, url_type="색상모음전"))
    db.flush()
    _due_sp(db, url)
    codes = due_bundle_codes(db, now=NOW)
    assert codes.count("D1") == 1


def test_normalized_match_when_bundle_url_has_tracking_param(db):
    """등록 URL에 트래킹 파라미터(?ref=...)가 붙어도 정규화 매칭으로 코드가 나온다.

    조용한 누락 방지 핵심: SourceProduct.url(정규화) vs BundleSourceUrl.url(원본, 트래킹 포함)
    를 같은 normalize_url 로 통과시켜 비교해야 due URL이 빠지지 않는다.
    """
    _enable(db, on=True)
    clean = "https://www.musinsa.com/products/777"
    registered = clean + "?utm_source=kakao&NaPm=abc"  # 등록값(트래킹 포함)
    # 번들에는 트래킹 붙은 원본 URL 등록
    db.add(Model(model_code="T1", model_name_raw="T1"))
    db.flush()
    db.add(BundleSourceUrl(model_code="T1", source_key="musinsa", url=registered,
                           url_type="단품"))
    db.flush()
    # SourceProduct 는 파이프라인 정규화된 URL 로 저장(clean)
    _due_sp(db, clean)
    codes = due_bundle_codes(db, now=NOW)
    assert "T1" in codes
