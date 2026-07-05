import pytest
from lemouton.sources.models import CrawlWeightRule
from lemouton.sources.crawl_schedule import set_crawl_weight_rule


def test_set_and_clamp(db):
    r = set_crawl_weight_rule(db, "source", "musinsa", 3); db.flush()
    assert r == 3
    assert db.query(CrawlWeightRule).filter_by(scope_type="source", scope_key="musinsa").first().weight == 3
    set_crawl_weight_rule(db, "source", "musinsa", 9); db.flush()   # 상한
    assert db.query(CrawlWeightRule).filter_by(scope_type="source", scope_key="musinsa").first().weight == 5
    set_crawl_weight_rule(db, "source", "musinsa", 0); db.flush()   # 하한
    assert db.query(CrawlWeightRule).filter_by(scope_type="source", scope_key="musinsa").first().weight == 1


def test_none_deletes_rule_inherit(db):
    set_crawl_weight_rule(db, "brand", "나이키", 4); db.flush()
    set_crawl_weight_rule(db, "brand", "나이키", None); db.flush()   # 해제
    assert db.query(CrawlWeightRule).filter_by(scope_type="brand", scope_key="나이키").first() is None


def test_bad_scope_type_raises(db):
    with pytest.raises(ValueError):
        set_crawl_weight_rule(db, "지역", "x", 3)


from lemouton.sources.crawl_schedule import resolve_crawl_weight
from lemouton.sources.models import SourceProduct
from lemouton.sourcing.models import Model, BundleSourceUrl


def _sp(db, site, url):
    sp = SourceProduct(site=site, url=url); db.add(sp); db.flush(); return sp


def _bundle(db, code, url, brand="나이키"):
    db.add(Model(model_code=code, model_name_raw=code, brand=brand)); db.flush()
    db.add(BundleSourceUrl(model_code=code, source_key="musinsa", url=url, url_type="단품")); db.flush()


def test_default_is_1(db):
    sp = _sp(db, "musinsa", "https://m/1")
    assert resolve_crawl_weight(db, sp) == 1


def test_priority_url_beats_all(db):
    url = "https://www.musinsa.com/products/1"
    _bundle(db, "M1", url, brand="나이키")
    sp = _sp(db, "musinsa", url)
    set_crawl_weight_rule(db, "source", "musinsa", 2)
    set_crawl_weight_rule(db, "brand", "나이키", 3)
    set_crawl_weight_rule(db, "model", "M1", 4)
    set_crawl_weight_rule(db, "url", url, 5); db.flush()
    assert resolve_crawl_weight(db, sp) == 5


def test_falls_through_source(db):
    sp = _sp(db, "ssf", "https://s/9")
    set_crawl_weight_rule(db, "source", "ssf", 2); db.flush()
    assert resolve_crawl_weight(db, sp) == 2


def test_model_then_brand_then_source(db):
    url = "https://www.musinsa.com/products/7"
    _bundle(db, "M7", url, brand="아디다스")
    sp = _sp(db, "musinsa", url)
    set_crawl_weight_rule(db, "source", "musinsa", 2)
    set_crawl_weight_rule(db, "brand", "아디다스", 3); db.flush()
    assert resolve_crawl_weight(db, sp) == 3        # 브랜드 > 소싱처
    set_crawl_weight_rule(db, "model", "M7", 4); db.flush()
    assert resolve_crawl_weight(db, sp) == 4        # 모음전 > 브랜드


def test_shared_url_takes_highest_model(db):
    url = "https://www.musinsa.com/products/8"
    _bundle(db, "A", url, brand="나이키")
    _bundle(db, "B", url, brand="나이키")           # 같은 URL 두 모음전
    sp = _sp(db, "musinsa", url)
    set_crawl_weight_rule(db, "model", "A", 2)
    set_crawl_weight_rule(db, "model", "B", 5); db.flush()
    assert resolve_crawl_weight(db, sp) == 5         # 최고


def test_normalized_match(db):
    # 등록 URL에 tracking 붙어도 매칭
    clean = "https://www.musinsa.com/products/9"
    _bundle(db, "N", clean + "?utm_source=x", brand="나이키")
    sp = _sp(db, "musinsa", clean)
    set_crawl_weight_rule(db, "model", "N", 4); db.flush()
    assert resolve_crawl_weight(db, sp) == 4


from datetime import datetime, timedelta
from lemouton.sources.crawl_schedule import due_products

NOW = datetime(2026, 7, 5, 12, 0, 0)


def test_due_products_reflects_source_rule(db):
    base = 6 * 3600
    # 3시간 전 크롤. 소싱처 계수 규칙 ×2 → 유효간격 3h → 딱 due
    sp = SourceProduct(site="musinsa", url="https://m/due",
                       last_fetched_at=NOW - timedelta(hours=3), no_change_streak=0)
    db.add(sp); db.flush()
    # 규칙 없으면(계수1) 6h 미달이라 아직 아님
    assert sp.id not in [p.id for p in due_products(db, base_interval_seconds=base, now=NOW)]
    set_crawl_weight_rule(db, "source", "musinsa", 2); db.flush()
    assert sp.id in [p.id for p in due_products(db, base_interval_seconds=base, now=NOW)]
