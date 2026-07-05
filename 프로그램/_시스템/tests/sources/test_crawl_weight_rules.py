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
