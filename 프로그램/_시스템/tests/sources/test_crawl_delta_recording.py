import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.sources import models
# FK 대상 테이블(models·options·price_templates) 등록 — create_all 이 참조를 찾게.
import lemouton.sourcing.models  # noqa: F401
import lemouton.templates.models  # noqa: F401
from lemouton.sources.models import SourceProduct, CrawlDelta


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def test_new_columns_and_delta_table_exist(db):
    sp = SourceProduct(site="musinsa", url="https://x/1")
    db.add(sp)
    db.flush()
    assert sp.crawl_weight == 1
    assert sp.no_change_streak == 0
    d = CrawlDelta(source_product_id=sp.id, stock_changed=True,
                   price_changed=False, detail="test")
    db.add(d)
    db.flush()
    assert d.id is not None
