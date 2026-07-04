import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
import lemouton.sourcing.models    # register models/options FK-target tables
import lemouton.templates.models   # register price_templates FK-target table
import lemouton.sources.models     # register source_products/source_options/crawl_deltas


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()
