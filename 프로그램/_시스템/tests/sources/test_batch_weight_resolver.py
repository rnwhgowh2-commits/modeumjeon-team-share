"""배치 계수 리졸버 — per-product resolve_crawl_weight 와 100% 동치 + 쿼리 폭주 제거.

라이브 장애(2026-07-12): due_crawl_payload → due_products 가 제품마다
resolve_crawl_weight 를 호출(제품마다 BundleSourceUrl 테이블 통째 재로드 등)
→ 449쿼리/5~13초 → DB·워커 마비. 배치 리졸버는 한 번만 preload 하고 in-memory
로 같은 5단계 로직을 재현한다. 이 테스트가 '값이 완전히 같다 + 쿼리 몇 개뿐'을 지킨다.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from lemouton.sources.models import SourceProduct
from lemouton.sourcing.models import Model, BundleSourceUrl
from lemouton.sources.crawl_schedule import (
    resolve_crawl_weight,
    build_batch_weight_resolver,
    set_crawl_weight_rule,
    due_products,
)


class _QueryCounter:
    """세션 엔진의 실행 SQL 개수 카운터 (before_cursor_execute)."""

    def __init__(self, session):
        self.engine = session.get_bind()
        self.count = 0

    def _on_exec(self, *a, **k):
        self.count += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on_exec)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._on_exec)
        return False


def _sp(db, site, url, **kw):
    sp = SourceProduct(site=site, url=url, no_change_streak=0, **kw)
    db.add(sp)
    db.flush()
    return sp


def _bundle(db, code, url, brand="르무통", source_key="musinsa"):
    if db.query(Model).filter_by(model_code=code).first() is None:
        db.add(Model(model_code=code, model_name_raw=code, brand=brand))
    db.add(BundleSourceUrl(model_code=code, source_key=source_key, url=url, url_type="단품"))
    db.flush()


def _realistic_fixture(db):
    """현실적 혼합: 여러 소싱처·url/model/brand/source 규칙·매칭 없음(기본1) 다 포함."""
    # 1) url 규칙이 최우선 (다른 규칙 다 있어도 이김)
    u1 = "https://www.musinsa.com/products/1"
    _bundle(db, "M1", u1, brand="나이키")
    set_crawl_weight_rule(db, "source", "musinsa", 2)
    set_crawl_weight_rule(db, "brand", "나이키", 3)
    set_crawl_weight_rule(db, "model", "M1", 4)
    set_crawl_weight_rule(db, "url", u1, 5)
    _sp(db, "musinsa", u1)

    # 2) model 규칙 (url 규칙 없음, 여러 모음전 공유 → 최고)
    u2 = "https://www.musinsa.com/products/2"
    _bundle(db, "A2", u2, brand="아디다스")
    _bundle(db, "B2", u2, brand="아디다스")
    set_crawl_weight_rule(db, "model", "A2", 2)
    set_crawl_weight_rule(db, "model", "B2", 5)
    _sp(db, "musinsa", u2)

    # 3) brand 규칙 (url/model 규칙 없음 → 브랜드 최고)
    u3 = "https://www.ssfshop.com/products/3"
    _bundle(db, "M3", u3, brand="구찌", source_key="ssf")
    set_crawl_weight_rule(db, "brand", "구찌", 4)
    _sp(db, "ssf", u3)

    # 4) source 규칙 (url/model/brand 규칙 없음)
    u4 = "https://www.lotteon.com/products/4"
    _bundle(db, "M4", u4, brand="발렌시아가", source_key="lotteon")
    set_crawl_weight_rule(db, "source", "lotteon", 3)
    _sp(db, "lotteon", u4)

    # 5) 아무 규칙도 안 걸림 → 기본 1
    _sp(db, "lemouton", "https://lemouton.com/products/5")

    # 6) 트래킹 파라미터 정규화 매칭 (등록은 utm 붙음, 크롤 url 은 깨끗)
    clean6 = "https://www.musinsa.com/products/6"
    _bundle(db, "M6", clean6 + "?utm_source=x", brand="나이키")
    set_crawl_weight_rule(db, "model", "M6", 2)
    _sp(db, "musinsa", clean6)

    # 7) 어떤 BundleSourceUrl 에도 없는 orphan URL → source 규칙만 (없으면 1)
    _sp(db, "musinsa", "https://www.musinsa.com/orphan/7")   # source musinsa=2

    # 8) 0계수 규칙(크롤 제외) — url 규칙 0 이 정확히 0 을 돌려줘야
    u8 = "https://www.musinsa.com/products/8"
    _bundle(db, "M8", u8, brand="나이키")
    set_crawl_weight_rule(db, "url", u8, 0)
    _sp(db, "musinsa", u8)

    db.flush()


def test_batch_equals_per_product(db):
    """모든 제품에 대해 batch_weight[p] == resolve_crawl_weight(session, p)."""
    _realistic_fixture(db)
    products = db.query(SourceProduct).all()
    resolve = build_batch_weight_resolver(db)
    for p in products:
        assert resolve(p) == resolve_crawl_weight(db, p), (
            f"불일치: {p.site} {p.url}: batch={resolve(p)} "
            f"per-product={resolve_crawl_weight(db, p)}"
        )


def test_batch_issues_few_queries_perproduct_issues_many(db):
    """배치 경로는 preload 몇 개(≤6)뿐, per-product 경로는 제품수 이상 쿼리."""
    _realistic_fixture(db)
    products = db.query(SourceProduct).all()
    n = len(products)
    assert n >= 8

    # 배치: 빌드에 드는 쿼리 + 제품당 0쿼리(in-memory)
    with _QueryCounter(db) as qc_batch:
        resolve = build_batch_weight_resolver(db)
        for p in products:
            resolve(p)
    assert qc_batch.count <= 6, f"배치 쿼리 {qc_batch.count} 개 (≤6 기대)"

    # per-product: 제품마다 여러 쿼리 → 최소 제품 수 이상
    with _QueryCounter(db) as qc_old:
        for p in products:
            resolve_crawl_weight(db, p)
    assert qc_old.count >= n, f"per-product 쿼리 {qc_old.count} (≥{n} 기대)"
    assert qc_old.count > qc_batch.count * 2


def test_due_products_uses_batch_and_matches_semantics(db):
    """due_products(벽시계) 결과가 배치 전환 후에도 동일 + 쿼리 폭주 없음."""
    base = 6 * 3600
    now = datetime(2026, 7, 5, 12, 0, 0)
    # musinsa 계수2 → 유효간격 3h. 3h 전 크롤 = 딱 due. 1h 전 = 아직.
    set_crawl_weight_rule(db, "source", "musinsa", 2)
    due_sp = _sp(db, "musinsa", "https://m/due",
                 last_fetched_at=now - timedelta(hours=3))
    _sp(db, "musinsa", "https://m/fresh", last_fetched_at=now - timedelta(hours=1))
    never = _sp(db, "musinsa", "https://m/never", last_fetched_at=None)
    db.flush()

    ids = [p.id for p in due_products(db, base_interval_seconds=base, now=now)]
    assert due_sp.id in ids
    assert never.id in ids
    # fresh 는 아직 아님
    fresh_id = db.query(SourceProduct).filter_by(url="https://m/fresh").first().id
    assert fresh_id not in ids

    # 제품 40개로 늘려도 쿼리는 상수에 가까움(폭주 없음)
    for i in range(40):
        _sp(db, "musinsa", f"https://m/bulk/{i}", last_fetched_at=None)
    db.flush()
    with _QueryCounter(db) as qc:
        due_products(db, base_interval_seconds=base, now=now)
    assert qc.count <= 10, f"due_products 쿼리 {qc.count} 개 (제품 43개인데 ≤10 기대)"


def test_due_products_order_identical_to_per_product_reference(db):
    """due_products(배치) 결과 순서가 옛 per-product 로직 기준과 **완전히 동일**.

    페이로드 items/순서가 안 바뀌었음을 증명(계수 로딩 방식만 바꿈)."""
    from lemouton.sources.crawl_schedule import overdue_seconds
    base = 6 * 3600
    now = datetime(2026, 7, 5, 12, 0, 0)
    _realistic_fixture(db)
    # 다양한 last_fetched 로 연체량을 섞는다(정렬이 실제로 작동하도록)
    for i, p in enumerate(db.query(SourceProduct).all()):
        p.last_fetched_at = now - timedelta(hours=(i * 3) % 40)
    db.flush()

    # 배치 경로(실제)
    batch_ids = [p.id for p in due_products(db, base_interval_seconds=base, now=now)]

    # 참조 경로: 옛 per-product resolve_crawl_weight 로 같은 점수·정렬 재현
    ref = []
    for p in db.query(SourceProduct).filter(SourceProduct.deleted_at.is_(None)).all():
        od = overdue_seconds(now, p.last_fetched_at, base,
                             resolve_crawl_weight(db, p), p.no_change_streak)
        if od >= 0:
            ref.append((od, p))
    ref.sort(key=lambda t: t[0], reverse=True)
    ref_ids = [p.id for _, p in ref]

    assert batch_ids == ref_ids
