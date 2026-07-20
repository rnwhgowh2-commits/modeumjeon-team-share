"""「3일에 1회」가 실제로 가능해졌는지 — 느리게 배수 캐스케이드.

2026-07-20 발견: `crawl_slowdown` 칸은 만들어 뒀는데 **거기에 값을 쓰는 코드가
없었다.** 읽기만 배선돼 있어서, 기준주기보다 뜸하게 긁는 설정을 저장할 방법이
아예 없었다(정수 계수 1~5 로는 「3일에 1회」를 표현 못 한다).

★ 이 파일이 지키는 선
  ① 계수와 배수는 **같은 규칙**에서 나온다 (따로 뽑으면 엉뚱한 주기가 된다)
  ② 한 URL 만 따로 늦춘 걸 브랜드 규칙이 되돌리지 않는다
  ③ 규칙이 없으면 예전 그대로 (배수 1.0)
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lemouton.sources.crawl_schedule import (
    build_batch_weight_resolver,
    due_products,
    set_crawl_weight_rule,
)
from lemouton.sources.models import CrawlWeightRule, SourceProduct
from shared.db import Base

DAY = 86400.0


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _sp(db, url, *, site="musinsa", slowdown=1.0, last=None, streak=0):
    p = SourceProduct(site=site, url=url, no_change_streak=streak,
                      last_fetched_at=last, crawl_slowdown=slowdown)
    db.add(p)
    db.flush()
    return p


# ── ① 규칙에서 배수를 상속한다 ──────────────────────────────────

def test_소싱처_규칙의_배수를_상속한다(db):
    set_crawl_weight_rule(db, "source", "musinsa", 1, slowdown=3.0)
    p = _sp(db, "https://a/1")
    assert build_batch_weight_resolver(db).slowdown(p) == 3.0


def test_규칙이_없으면_1이다(db):
    """예전 동작 그대로 — 도입 영향 0."""
    p = _sp(db, "https://a/1")
    assert build_batch_weight_resolver(db).slowdown(p) == 1.0


def test_계수와_배수가_같은_규칙에서_나온다(db):
    """따로 뽑으면 계수는 A, 배수는 B 규칙에서 나와 의도한 주기가 안 된다."""
    set_crawl_weight_rule(db, "url", "https://a/1", 4, slowdown=2.5)
    set_crawl_weight_rule(db, "source", "musinsa", 1, slowdown=9.0)
    p = _sp(db, "https://a/1")
    r = build_batch_weight_resolver(db)
    assert r(p) == 4
    assert r.slowdown(p) == 2.5      # 9.0(소싱처)이 섞여 들어오면 안 된다


# ── ② 상품 칸이 규칙을 이긴다 ───────────────────────────────────

def test_상품에_직접_건_배수가_이긴다(db):
    """한 URL 만 따로 늦춰 둔 걸 브랜드·소싱처 규칙이 되돌리면 안 된다."""
    set_crawl_weight_rule(db, "source", "musinsa", 1, slowdown=2.0)
    p = _sp(db, "https://a/1", slowdown=5.0)
    assert build_batch_weight_resolver(db).slowdown(p) == 5.0


def test_상품이_기본이면_규칙을_따른다(db):
    set_crawl_weight_rule(db, "source", "musinsa", 1, slowdown=2.0)
    p = _sp(db, "https://a/1", slowdown=1.0)
    assert build_batch_weight_resolver(db).slowdown(p) == 2.0


# ── ③ 🔴 실제 크롤 대상 선정에 반영되는가 ───────────────────────

def test_3일에_1회가_실제로_동작한다(db):
    """이게 이번 배선의 핵심 — 전에는 저장할 방법 자체가 없었다."""
    now = dt.datetime(2026, 7, 20, 12, 0)
    set_crawl_weight_rule(db, "source", "musinsa", 1, slowdown=3.0)

    # 2일 전에 긁음 → 3일 주기라 아직 아니다
    young = _sp(db, "https://a/1", last=now - dt.timedelta(days=2))
    assert young not in due_products(db, base_interval_seconds=DAY, now=now)

    # 4일 전에 긁음 → 지났다
    old = _sp(db, "https://a/2", last=now - dt.timedelta(days=4))
    assert old in due_products(db, base_interval_seconds=DAY, now=now)


def test_배수가_없으면_기준주기대로다(db):
    now = dt.datetime(2026, 7, 20, 12, 0)
    p = _sp(db, "https://a/1", last=now - dt.timedelta(days=2))
    assert p in due_products(db, base_interval_seconds=DAY, now=now)


# ── 저장 경로 ───────────────────────────────────────────────────

def test_규칙에_배수가_저장된다(db):
    set_crawl_weight_rule(db, "brand", "나이키", 2, slowdown=3.0)
    r = db.query(CrawlWeightRule).filter_by(scope_type="brand").one()
    assert (r.weight, r.slowdown) == (2, 3.0)


def test_배수를_안_주면_기존_값을_안_건드린다(db):
    """계수만 고치러 왔다가 배수가 조용히 1.0 으로 리셋되면 안 된다."""
    set_crawl_weight_rule(db, "brand", "나이키", 2, slowdown=3.0)
    set_crawl_weight_rule(db, "brand", "나이키", 4)
    r = db.query(CrawlWeightRule).filter_by(scope_type="brand").one()
    assert (r.weight, r.slowdown) == (4, 3.0)


def test_1_미만_배수는_거부(db):
    """방향이 반대다 — 자주 긁는 건 계수가 맡는다."""
    with pytest.raises(ValueError):
        set_crawl_weight_rule(db, "brand", "나이키", 2, slowdown=0.5)


def test_적용계획이_배수를_나른다():
    from lemouton.sources.grade_apply import plan_apply
    plan = plan_apply(source_key="musinsa", brand="나이키", proposed_weight=1,
                      proposed_slowdown=3.0, brands_by_source={})
    assert plan.slowdown == 3.0
    assert plan.to_dict()["slowdown"] == 3.0


def test_적용계획이_저장까지_이어진다(db):
    from lemouton.sources.grade_apply import apply_plan, plan_apply
    plan = plan_apply(source_key="musinsa", brand="나이키", proposed_weight=1,
                      proposed_slowdown=3.0, brands_by_source={})
    apply_plan(db, plan)
    r = db.query(CrawlWeightRule).filter_by(scope_key="나이키").one()
    assert r.slowdown == 3.0
