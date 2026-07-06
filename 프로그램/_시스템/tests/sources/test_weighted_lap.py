"""연속 모드 가중 라운드로빈 랩 — 각 URL을 계수만큼 크롤(한 랩).

핵심 의도(사용자 못 박음): 시간 기준 없이 최대한 자주 크롤하되,
계수 ×2 = 한 랩에 2번, ×3 = 3번 크롤. 링 100% = 그 '가중 한 바퀴' 완료.
"""
from datetime import datetime

from lemouton.sources.crawl_schedule import (
    weighted_due_products, record_crawl_served, start_new_lap,
    lap_progress, lap_quota, next_lap_products, set_crawl_weight_rule,
)
from lemouton.sources.models import SourceProduct
import lemouton.sourcing.models as M

NOW = datetime(2026, 7, 6, 12, 0, 0)


def _sp(db, site, url):
    """랩 대상은 dispatchable(모음전에 걸린) URL만 → 테스트 URL도 BundleSourceUrl 로 연결."""
    sp = SourceProduct(site=site, url=url, last_fetched_at=None)
    db.add(sp)
    db.add(M.BundleSourceUrl(model_code="LAP-" + site, source_key=site, url=url, sort_order=0))
    db.flush()
    return sp


def _set_weights(db):
    """A=계수1(규칙없음), B=계수2, C=계수3 — 서로 다른 소싱처 규칙으로."""
    a = _sp(db, "s1", "u/a")
    b = _sp(db, "s2", "u/b")
    c = _sp(db, "s3", "u/c")
    set_crawl_weight_rule(db, "source", "s2", 2)
    set_crawl_weight_rule(db, "source", "s3", 3)
    db.flush()
    return a, b, c


def test_orphan_url_excluded_from_lap(db):
    """모음전에 안 걸린 orphan URL 은 랩에서 제외 — 확장이 못 긁어 랩을 영영 막으므로."""
    disp = _sp(db, "s1", "u/disp")                       # 모음전 연결됨
    orph = SourceProduct(site="s1", url="u/orph", last_fetched_at=None)
    db.add(orph); db.flush()                             # BundleSourceUrl 없음(orphan)
    ids = {p.id for p in weighted_due_products(db)}
    assert disp.id in ids
    assert orph.id not in ids
    assert lap_progress(db)["total"] == 1                # dispatchable 1개만 계수 합


def test_error_url_excluded_from_lap_so_it_completes(db):
    """계속 실패(last_status=error)하는 URL은 랩 완료를 막지 않는다(크롤 불가 → 제외)."""
    a = _sp(db, "s1", "u/ok")
    b = _sp(db, "s1", "u/err")
    a.crawl_lap_count = 1            # 정상 크롤됨
    b.last_status = "error"; b.crawl_lap_count = 0   # 매번 실패
    db.flush()
    assert weighted_due_products(db) == []      # b 제외 → a 완료 → 남은 것 없음
    assert lap_progress(db)["pct"] == 100        # 링 100% (a 기준)


def test_overserved_straggler_excluded_so_it_completes(db):
    """재패스(over-serve)에도 한 번도 안 긁힌 URL은 straggler로 제외 → 랩 완료."""
    a = _sp(db, "s1", "u/a")
    b = _sp(db, "s1", "u/b")
    a.crawl_lap_count = 2            # 두 번 긁힘(재패스 발생)
    b.crawl_lap_count = 0            # 한 번도 못 긁힘
    db.flush()
    assert weighted_due_products(db) == []
    assert lap_progress(db)["pct"] == 100


def test_not_yet_crawled_ok_url_still_blocks(db):
    """아직 안 긁혔지만 정상(status ok)인 URL은 랩을 안 끝냄(조기완료 방지)."""
    a = _sp(db, "s1", "u/a")
    b = _sp(db, "s1", "u/b")
    a.crawl_lap_count = 1            # 긁힘
    b.last_status = "ok"; b.crawl_lap_count = 0    # 아직 안 긁힘(정상)
    db.flush()
    ids = {p.id for p in weighted_due_products(db)}
    assert b.id in ids               # b 아직 due → 랩 미완료
    assert lap_progress(db)["pct"] < 100


def test_lap_quota_is_effective_weight(db):
    a, b, c = _set_weights(db)
    assert lap_quota(db, a) == 1
    assert lap_quota(db, b) == 2
    assert lap_quota(db, c) == 3


def test_record_crawl_served_increments(db):
    a = _sp(db, "s1", "u/a")
    assert record_crawl_served(a) == 1
    assert record_crawl_served(a) == 2
    assert a.crawl_lap_count == 2


def test_fresh_lap_returns_all_urls(db):
    a, b, c = _set_weights(db)
    due = weighted_due_products(db)
    ids = {p.id for p in due}
    assert ids == {a.id, b.id, c.id}


def test_url_excluded_once_quota_met(db):
    a, b, c = _set_weights(db)
    # 각 1회 크롤 → A(계수1) 소진, B·C 남음
    for p in (a, b, c):
        record_crawl_served(p)
    db.flush()
    ids = {p.id for p in weighted_due_products(db)}
    assert a.id not in ids       # 계수1 → 이번 랩 끝
    assert b.id in ids and c.id in ids


def test_least_served_ratio_first(db):
    a, b, c = _set_weights(db)
    # A·B·C 각 1회 → 채움비 A 1/1=끝(제외), B 1/2=0.5, C 1/3=0.33 → C 가 B 보다 앞
    for p in (a, b, c):
        record_crawl_served(p)
    db.flush()
    ids = [p.id for p in weighted_due_products(db)]
    assert ids.index(c.id) < ids.index(b.id)


def test_empty_when_lap_complete(db):
    a, b, c = _set_weights(db)
    # 계수만큼 전부 채움
    for p, n in ((a, 1), (b, 2), (c, 3)):
        for _ in range(n):
            record_crawl_served(p)
    db.flush()
    assert weighted_due_products(db) == []


def test_start_new_lap_resets_counts(db):
    a, b, c = _set_weights(db)
    for p in (a, b, c):
        record_crawl_served(p)
    db.flush()
    n = start_new_lap(db)
    assert n == 3
    assert a.crawl_lap_count == 0
    assert {p.id for p in weighted_due_products(db)} == {a.id, b.id, c.id}


def test_full_lap_crawls_each_url_weight_times(db):
    """한 랩 = A 1번, B 2번, C 3번 크롤 (계수만큼)."""
    a, b, c = _set_weights(db)
    tally = {a.id: 0, b.id: 0, c.id: 0}
    for _ in range(20):
        due = weighted_due_products(db)
        if not due:
            break
        for p in due:
            tally[p.id] += 1
            record_crawl_served(p)
            p.last_fetched_at = NOW
        db.flush()
    assert tally[a.id] == 1
    assert tally[b.id] == 2
    assert tally[c.id] == 3


def test_lap_progress_climbs_to_full(db):
    a, b, c = _set_weights(db)          # 총 quota = 1+2+3 = 6
    assert lap_progress(db)["pct"] == 0
    for p, n in ((a, 1), (b, 2), (c, 3)):
        for _ in range(n):
            record_crawl_served(p)
    db.flush()
    prog = lap_progress(db)
    assert prog["served"] == 6 and prog["total"] == 6
    assert prog["pct"] == 100


def test_due_products_uses_weighted_lap_when_continuous(db):
    """기준주기 0(연속) → due_products 가 가중 랩으로 위임(계수만큼 자주)."""
    from lemouton.sources.crawl_schedule import due_products
    a, b, c = _set_weights(db)
    tally = {a.id: 0, b.id: 0, c.id: 0}
    for _ in range(20):
        due = due_products(db, base_interval_seconds=0, now=NOW)
        # 연속모드는 절대 안 쉼: 항상 뭔가 반환(리셋 포함)
        assert due, "연속모드는 빈손이면 안 됨"
        for p in due:
            tally[p.id] += 1
            record_crawl_served(p)
            p.last_fetched_at = NOW
        db.flush()
        # 한 랩(A 1·B 2·C 3) 완료 감지
        if tally[c.id] >= 3:
            break
    assert tally[a.id] == 1 and tally[b.id] == 2 and tally[c.id] == 3


def test_due_products_keeps_interval_mode_when_base_positive(db):
    """기준주기>0 이면 기존 벽시계 간격 로직 유지(회귀 방지)."""
    from datetime import timedelta
    from lemouton.sources.crawl_schedule import due_products
    base = 6 * 3600
    fresh = _sp(db, "s1", "u/fresh")
    fresh.last_fetched_at = NOW - timedelta(hours=1)   # 1h < 6h → 아직 아님
    old = _sp(db, "s2", "u/old")
    old.last_fetched_at = NOW - timedelta(hours=10)    # 10h > 6h → due
    db.flush()
    ids = {p.id for p in due_products(db, base_interval_seconds=base, now=NOW)}
    assert old.id in ids and fresh.id not in ids


def test_next_lap_products_never_idle(db):
    """연속모드 핵심: 랩 다 채워도 빈손 금지 → 자동 리셋 후 다음 랩 즉시 시작."""
    a, b, c = _set_weights(db)
    for p, n in ((a, 1), (b, 2), (c, 3)):
        for _ in range(n):
            record_crawl_served(p)
    db.flush()
    # weighted_due 는 [] 지만 next_lap_products 는 리셋 후 전부 반환
    assert weighted_due_products(db) == []
    due = next_lap_products(db)
    assert {p.id for p in due} == {a.id, b.id, c.id}


def test_lap_reset_persists_across_session_close():
    """읽기 라우트는 commit 안 하므로 랩 리셋은 next_lap_products 가 영속해야.

    안 그러면 close() 에서 롤백 → served 가 quota 에 붙박여 매 폴링 전체랩(배수 무력).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from shared.db import Base
    import lemouton.sourcing.models  # noqa
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)

    s1 = _S(eng)
    a = SourceProduct(site="s1", url="u/a", last_fetched_at=None)
    s1.add(a)
    s1.add(M.BundleSourceUrl(model_code="LAP", source_key="s1", url="u/a", sort_order=0))
    s1.flush()
    record_crawl_served(a)          # 계수1 → quota 소진
    s1.commit()
    # 라우트처럼: next_lap_products 호출 후 세션 닫음(commit 안 함)
    next_lap_products(s1)
    s1.close()
    # 새 세션에서 확인: 리셋이 영속됐나
    s2 = _S(eng)
    got = s2.query(SourceProduct).filter_by(url="u/a").first().crawl_lap_count
    s2.close()
    assert got == 0, "랩 리셋이 영속 안 됨 → 연속모드 배수 깨짐"
