# -*- coding: utf-8 -*-
"""[TEST] 계수 드릴다운 트리 — 소싱처/브랜드/모음전 3기준 노드의 weight·direct.

정본=백엔드. resolve 의미(most-specific-wins: url>model>brand>source>기본1) 그대로.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
import lemouton.sourcing.models   # noqa
import lemouton.templates.models  # noqa
import lemouton.sources.models    # noqa

from lemouton.sourcing.models import Model, Option, BundleSourceUrl
from lemouton.sources.models import SourceProduct
from lemouton.sources.crawl_schedule import set_crawl_weight_rule
from lemouton.sources.crawl_weight_tree import build_weight_tree, DEFAULT_WEIGHT


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _seed(s):
    """무신사에 에어맥스(나이키) 모음전 1개, URL 1개, 옵션 2개."""
    s.add(Model(model_code="airmax", model_name_raw="에어맥스 모음전", brand="나이키"))
    s.add(Option(canonical_sku="airmax-블랙-270", model_code="airmax",
                 color_code="블랙", size_code="270"))
    s.add(Option(canonical_sku="airmax-블랙-280", model_code="airmax",
                 color_code="블랙", size_code="280"))
    s.add(BundleSourceUrl(model_code="airmax", source_key="musinsa",
                          url="https://musinsa.com/products/123", url_type="단품"))
    s.add(SourceProduct(site="musinsa", url="https://musinsa.com/products/123"))
    s.commit()


def _find(nodes, key):
    return next((n for n in nodes if n["scope_key"] == key), None)


def test_default_weight_when_no_rules(db):
    _seed(db)
    tree = build_weight_tree(db)
    assert tree["default_weight"] == DEFAULT_WEIGHT
    src = _find(tree["src"], "musinsa")
    assert src is not None
    assert src["weight"] == 1 and src["direct"] is False


def test_source_rule_direct(db):
    _seed(db)
    set_crawl_weight_rule(db, "source", "musinsa", 2); db.commit()
    tree = build_weight_tree(db)
    src = _find(tree["src"], "musinsa")
    assert src["weight"] == 2 and src["direct"] is True


def test_brand_inherits_source_then_overrides(db):
    _seed(db)
    set_crawl_weight_rule(db, "source", "musinsa", 2); db.commit()
    src = _find(build_weight_tree(db)["src"], "musinsa")
    brand = _find(src["children"], "나이키")
    assert brand["weight"] == 2 and brand["direct"] is False   # 소싱처 상속

    set_crawl_weight_rule(db, "brand", "나이키", 3); db.commit()
    src = _find(build_weight_tree(db)["src"], "musinsa")
    brand = _find(src["children"], "나이키")
    assert brand["weight"] == 3 and brand["direct"] is True     # 브랜드 직접(우선)


def test_model_inherits_brand(db):
    _seed(db)
    set_crawl_weight_rule(db, "brand", "나이키", 3); db.commit()
    src = _find(build_weight_tree(db)["src"], "musinsa")
    brand = _find(src["children"], "나이키")
    model = _find(brand["children"], "airmax")
    assert model["weight"] == 3 and model["direct"] is False    # 브랜드 상속


def test_url_resolves_full_chain(db):
    _seed(db)
    set_crawl_weight_rule(db, "brand", "나이키", 3); db.commit()
    # src mode: source>brand>model>option>url
    src = _find(build_weight_tree(db)["src"], "musinsa")
    model = _find(_find(src["children"], "나이키")["children"], "airmax")
    opt = model["children"][0]
    url = opt["children"][0]
    assert url["scope_type"] == "url"
    assert url["weight"] == 3 and url["direct"] is False         # 브랜드 상속
    assert url["source_product_id"] is not None

    # url 직접 지정 → 우선
    set_crawl_weight_rule(db, "url", url["scope_key"], 5); db.commit()
    src = _find(build_weight_tree(db)["src"], "musinsa")
    model = _find(_find(src["children"], "나이키")["children"], "airmax")
    url = model["children"][0]["children"][0]
    assert url["weight"] == 5 and url["direct"] is True


def test_options_listed_under_model(db):
    _seed(db)
    src = _find(build_weight_tree(db)["src"], "musinsa")
    model = _find(_find(src["children"], "나이키")["children"], "airmax")
    opts = model["children"]
    assert len(opts) == 2
    assert all(o["scope_type"] == "option" and o["editable"] is False for o in opts)


def test_brand_mode_root_has_no_source_fallback(db):
    _seed(db)
    set_crawl_weight_rule(db, "source", "musinsa", 2); db.commit()
    # 브랜드 기준: 소싱처 문맥 없음 → 브랜드 미설정이면 기본1 (소싱처 폴백 아님)
    brand = _find(build_weight_tree(db)["brd"], "나이키")
    assert brand["weight"] == 1 and brand["direct"] is False


def test_model_mode_root_lists_models_with_brand_tag(db):
    _seed(db)
    mdl = build_weight_tree(db)["mdl"]
    m = _find(mdl, "airmax")
    assert m is not None and m["brand"] == "나이키"
    assert m["scope_type"] == "model"
