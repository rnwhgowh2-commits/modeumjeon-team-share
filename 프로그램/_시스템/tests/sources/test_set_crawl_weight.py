import pytest
from lemouton.sources.crawl_schedule import set_crawl_weight
from lemouton.sources.models import SourceProduct


def _sp(db):
    sp = SourceProduct(site="musinsa", url="https://x/1", crawl_weight=1)
    db.add(sp); db.flush(); return sp


def test_set_weight_ok(db):
    sp = _sp(db)
    r = set_crawl_weight(db, sp.id, 3); db.flush()
    assert r == 3 and sp.crawl_weight == 3


def test_weight_clamped_1_to_5(db):
    sp = _sp(db)
    set_crawl_weight(db, sp.id, 9); db.flush()
    assert sp.crawl_weight == 5      # 상한
    set_crawl_weight(db, sp.id, 0); db.flush()
    assert sp.crawl_weight == 1      # 하한
    set_crawl_weight(db, sp.id, -3); db.flush()
    assert sp.crawl_weight == 1


def test_missing_product_raises(db):
    with pytest.raises(ValueError):
        set_crawl_weight(db, 99999, 3)
