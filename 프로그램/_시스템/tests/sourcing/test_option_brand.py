"""옵션별 브랜드 백엔드 — 유효브랜드(상속)·저장·목록·일괄적용.

한 모음전(Model)에 여러 브랜드가 섞일 수 있게 Option.brand 를 도입.
유효 브랜드 = option.brand(있으면) → model.brand → 미지정(None).
"르무통 자동 채움" 금지: 빈 값은 None(미지정)으로 정규화.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
import lemouton.sourcing.models   # noqa: F401  (register tables)
import lemouton.templates.models  # noqa: F401  (price_templates FK target)
import lemouton.sources.models    # noqa: F401  (source_options FK target)

from lemouton.sourcing.models import Model, Option
from lemouton.sourcing.option_brand import (
    effective_option_brand,
    set_option_brand,
    list_brands,
    bulk_apply_brand,
    brand_summary,
)


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _model(s, code, brand="르무통"):
    m = Model(model_code=code, model_name_raw=code, brand=brand)
    s.add(m)
    s.flush()
    return m


def _opt(s, sku, model_code, *, color="블랙", size="260", brand=None):
    o = Option(canonical_sku=sku, model_code=model_code,
               color_code=color, size_code=size, brand=brand)
    s.add(o)
    s.flush()
    return o


# ── 유효 브랜드(상속) ──────────────────────────────────────────
def test_effective_brand_uses_option_brand_when_set(db):
    _model(db, "M1", brand="르무통")
    o = _opt(db, "sku1", "M1", brand="나이키")
    assert effective_option_brand(o) == "나이키"


def test_effective_brand_inherits_model_when_option_blank(db):
    _model(db, "M1", brand="르무통")
    o = _opt(db, "sku1", "M1", brand=None)
    assert effective_option_brand(o) == "르무통"


def test_effective_brand_is_none_when_both_blank(db):
    _model(db, "M1", brand="")   # 미지정 모델(르무통 기본 제거된 세계)
    o = _opt(db, "sku1", "M1", brand=None)
    assert effective_option_brand(o) is None


def test_effective_brand_treats_whitespace_as_unset(db):
    _model(db, "M1", brand="르무통")
    o = _opt(db, "sku1", "M1", brand="   ")
    assert effective_option_brand(o) == "르무통"   # 공백은 미설정 → 상속


# ── 저장 / 해제 ────────────────────────────────────────────────
def test_set_option_brand_saves(db):
    _model(db, "M1")
    _opt(db, "sku1", "M1")
    set_option_brand(db, "sku1", "아디다스")
    assert db.get(Option, "sku1").brand == "아디다스"


def test_set_option_brand_blank_clears_to_none(db):
    _model(db, "M1")
    _opt(db, "sku1", "M1", brand="아디다스")
    set_option_brand(db, "sku1", "")
    assert db.get(Option, "sku1").brand is None   # 미지정으로 복귀(상속)


def test_set_option_brand_strips_whitespace(db):
    _model(db, "M1")
    _opt(db, "sku1", "M1")
    set_option_brand(db, "sku1", "  구찌  ")
    assert db.get(Option, "sku1").brand == "구찌"


def test_set_option_brand_missing_sku_raises(db):
    with pytest.raises(ValueError):
        set_option_brand(db, "nope", "나이키")


# ── 브랜드 목록(검색 팔레트용) ─────────────────────────────────
def test_list_brands_distinct_nonempty_sorted(db):
    _model(db, "M1", brand="르무통")
    _model(db, "M2", brand="")
    _opt(db, "s1", "M1", brand="나이키")
    _opt(db, "s2", "M1", brand="나이키")   # 중복
    _opt(db, "s3", "M2", brand="아디다스")
    _opt(db, "s4", "M2", brand=None)       # 미지정 제외
    assert list_brands(db) == ["나이키", "르무통", "아디다스"]


# ── 일괄 적용 ──────────────────────────────────────────────────
def test_bulk_apply_all_sets_every_option(db):
    _model(db, "M1")
    _opt(db, "s1", "M1", brand="나이키")
    _opt(db, "s2", "M1", brand=None)
    n = bulk_apply_brand(db, "M1", "르무통", mode="all")
    assert n == 2
    assert db.get(Option, "s1").brand == "르무통"
    assert db.get(Option, "s2").brand == "르무통"


def test_bulk_apply_empty_only_skips_assigned(db):
    _model(db, "M1")
    _opt(db, "s1", "M1", brand="나이키")   # 이미 지정 → 유지
    _opt(db, "s2", "M1", brand=None)       # 미지정 → 채움
    _opt(db, "s3", "M1", brand="  ")       # 공백=미지정 → 채움
    n = bulk_apply_brand(db, "M1", "르무통", mode="empty")
    assert n == 2
    assert db.get(Option, "s1").brand == "나이키"
    assert db.get(Option, "s2").brand == "르무통"
    assert db.get(Option, "s3").brand == "르무통"


def test_bulk_apply_selected_only_given_skus(db):
    _model(db, "M1")
    _opt(db, "s1", "M1", brand=None)
    _opt(db, "s2", "M1", brand=None)
    _opt(db, "s3", "M1", brand=None)
    n = bulk_apply_brand(db, "M1", "구찌", mode="selected", skus=["s1", "s3"])
    assert n == 2
    assert db.get(Option, "s1").brand == "구찌"
    assert db.get(Option, "s2").brand is None
    assert db.get(Option, "s3").brand == "구찌"


def test_bulk_apply_blank_clears(db):
    _model(db, "M1")
    _opt(db, "s1", "M1", brand="나이키")
    bulk_apply_brand(db, "M1", "", mode="all")
    assert db.get(Option, "s1").brand is None


# ── 요약(스마트바 "미지정 N개") ────────────────────────────────
def test_brand_summary_counts_and_distinct(db):
    _model(db, "M1", brand="르무통")
    _opt(db, "s1", "M1", brand="나이키")
    _opt(db, "s2", "M1", brand="아디다스")
    _opt(db, "s3", "M1", brand=None)       # 미지정
    summary = brand_summary(db, "M1")
    assert summary["total"] == 3
    assert summary["assigned"] == 2
    assert summary["unassigned"] == 1
    assert summary["brands"] == ["나이키", "아디다스"]
