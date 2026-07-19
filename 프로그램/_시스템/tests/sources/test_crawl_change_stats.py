# -*- coding: utf-8 -*-
"""[Phase 1B M5] 크롤 변동 통계 — 계수의 근거.

★ 기준선은 **소싱처**다. 변동을 여기서 지어내지 않고, 진짜 크롤 저장 루틴
  (:func:`persist_crawled_options`)을 태워 만들어진 ``CrawlDelta`` 를 센다 —
  detail 문자열을 손으로 흉내내면 detect_changes 가 형식을 바꿨을 때 통계가
  조용히 어긋난 걸 테스트가 못 잡는다.

★ P2 스킵만 마켓 기준(GateDecision)이라, 그 부분은 진짜 ``decide_upload`` 를 부른다.
"""
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from lemouton.sources.crawl_change_stats import (
    OPEN_LAP, UNSPECIFIED_BRAND, MIN_OBSERVATIONS, STATS_RETENTION_LAPS,
    SOURCE_FIELDS, GATE_FIELDS,
    brand_of_skus, brands_of_source_product,
    record_crawl_observation, record_gate_skips,
    seal_open_lap_stats, prune_old_stats,
    recommend_weight, bucket_weight, change_stats, lap_change_report,
)
from lemouton.sources.lap_report import summarize_delta
from lemouton.sources.models import (
    CrawlChangeStat, CrawlDelta, CrawlLapRun, OptionSourceLink,
    SourceOption, SourceProduct,
)
from lemouton.sources.service import persist_crawled_options
from lemouton.uploader.upload_gate import decide_upload


# ── 도구 ───────────────────────────────────────────────────────
def _sp(db, site="musinsa", url="https://x/1"):
    sp = SourceProduct(site=site, url=url)
    db.add(sp)
    db.flush()
    return sp


def _crawl(db, sp, *, price=50000, stock=3, color="블랙", size="260"):
    """진짜 크롤 저장 1회 = CrawlDelta 1행 = 통계 관측 1회."""
    persist_crawled_options(db, source_product=sp, options=[
        {"color_text": color, "size_text": size, "price": price, "stock": stock}])
    db.flush()


def _row(db, *, source_key="musinsa", brand=UNSPECIFIED_BRAND, lap_run_id=OPEN_LAP):
    return (db.query(CrawlChangeStat)
            .filter_by(lap_run_id=lap_run_id, source_key=source_key, brand=brand)
            .first())


def _seed_brand(db):
    from lemouton.sourcing.models import Model, Option
    db.add(Model(model_code="M1", model_name_raw="M1", brand="르무통"))
    db.flush()
    db.add(Option(canonical_sku="skuA", model_code="M1",
                  color_code="블랙", size_code="260", brand="나이키"))
    db.add(Option(canonical_sku="skuB", model_code="M1",
                  color_code="화이트", size_code="270", brand=None))
    db.flush()


def _link_sku(db, sp, sku="skuA"):
    """SourceOption ↔ 우리 옵션 링크 — 브랜드 귀속 경로(마켓을 거치지 않는다)."""
    so = (db.query(SourceOption)
          .filter_by(source_product_id=sp.id, deleted_at=None).first())
    db.add(OptionSourceLink(canonical_sku=sku, source_option_id=so.id))
    db.flush()


# ══ ① 관례 — '처음 수집은 변동이 아니다' (회차 보고서와 같은 규칙) ══════════
def test_summarize_delta_first_seen_is_not_a_change():
    """가격 없음→X · 재고 미크롤→X · 옵션 생김 = 전부 처음 수집."""
    c = summarize_delta("[블랙/260] 옵션 생김 · [블랙/260] 가격 None→50000 "
                        "· [블랙/260] 재고 None→3")
    assert c["first_seen"] == 3
    assert c["price"] == 0 and c["stock"] == 0


def test_summarize_delta_real_changes():
    c = summarize_delta("[블랙/260] 가격 50000→60000 · [블랙/260] 재고 3→0")
    assert c["price"] == 1 and c["stock"] == 1 and c["soldout"] == 1
    assert c["first_seen"] == 0


def test_summarize_delta_option_gone_is_a_change():
    """옵션이 사라지면 그 옵션은 더 못 판다 — 변동이고 품절 전환이다."""
    c = summarize_delta("[블랙/260] 옵션 사라짐")
    assert c["stock"] == 1 and c["soldout"] == 1 and c["first_seen"] == 0


def test_summarize_delta_same_state_is_not_a_change():
    """999→1000 은 둘 다 '있음' — 회차 보고서가 같은 상태로 보는 것을 따른다."""
    assert summarize_delta("[블랙/260] 재고 999→1000")["stock"] == 0
    assert summarize_delta("[블랙/260] 재고 3→5")["stock"] == 1   # 한정수량은 다르다


def test_summarize_delta_empty():
    assert summarize_delta("") == {"price": 0, "stock": 0,
                                   "soldout": 0, "first_seen": 0}


# ══ ② 기록 — 진짜 크롤 저장 경로로 ════════════════════════════════════════
def test_first_crawl_is_first_seen_not_an_observation(db):
    """★처음 수집은 변동이 아니고 분모에도 안 들어간다.

    분모에 넣으면 첫 크롤이 전부 '변동률 100%' 로 둔갑해 계수가 폭주한다.
    """
    sp = _sp(db)
    _crawl(db, sp)
    r = _row(db)
    assert r.first_seen == 1
    assert r.observed == 0 and r.changed == 0


def test_unchanged_crawl_is_an_observation_with_no_change(db):
    sp = _sp(db)
    _crawl(db, sp)          # 처음 수집
    _crawl(db, sp)          # 같은 값 → 진짜 '안 바뀜'
    r = _row(db)
    assert r.observed == 1 and r.changed == 0


def test_price_change_counted(db):
    sp = _sp(db)
    _crawl(db, sp, price=50000)
    _crawl(db, sp, price=60000)
    r = _row(db)
    assert (r.observed, r.changed, r.price_changed, r.stock_changed) == (1, 1, 1, 0)


def test_soldout_counted(db):
    sp = _sp(db)
    _crawl(db, sp, stock=3)
    _crawl(db, sp, stock=0)
    r = _row(db)
    assert r.stock_changed == 1 and r.soldout == 1


def test_observation_unit_is_one_crawl_not_one_option(db):
    """관측 단위 = 크롤 1회. 옵션 수만큼 부풀리지 않는다."""
    sp = _sp(db)
    opts = [{"color_text": "블랙", "size_text": s, "price": 50000, "stock": 3}
            for s in ("260", "265", "270")]
    persist_crawled_options(db, source_product=sp, options=opts)
    db.flush()
    persist_crawled_options(db, source_product=sp, options=[
        dict(o, price=60000) for o in opts])
    db.flush()
    r = _row(db)
    assert r.observed == 1 and r.changed == 1 and r.price_changed == 1


def test_crawl_failure_is_not_counted_as_no_change(db):
    """★무결성 — 실패를 안정으로 세면 계수가 잘못 내려간다.

    실패하면 저장 자체가 없어 ``CrawlDelta`` 가 안 생긴다 → 통계 행도 안 생긴다.
    구조적으로 '변동 없음'에 섞일 수 없다.
    """
    sp = _sp(db)
    _crawl(db, sp)
    _crawl(db, sp)                       # 관측 1 / 변동 0
    before = (_row(db).observed, _row(db).changed)

    sp.last_status = "error"             # 다음 바퀴 크롤 실패 — 저장 경로를 안 탄다
    db.flush()

    assert db.query(CrawlDelta).filter_by(source_product_id=sp.id).count() == 2
    assert (_row(db).observed, _row(db).changed) == before


def test_stats_accumulate_into_one_row_per_bucket(db):
    sp = _sp(db)
    for i in range(5):
        _crawl(db, sp, price=50000 + i * 1000)
    assert db.query(CrawlChangeStat).count() == 1        # 행이 안 늘어난다
    assert _row(db).observed == 4                        # 첫 크롤은 처음 수집


def test_brand_comes_from_option_not_market(db):
    """브랜드 귀속은 옵션 링크에서 온다 — 마켓·실전송과 무관하다."""
    _seed_brand(db)
    sp = _sp(db)
    _crawl(db, sp)
    _link_sku(db, sp, "skuA")            # 옵션 브랜드 = 나이키
    _crawl(db, sp, price=60000)
    assert _row(db, brand="나이키").changed == 1


def test_brand_inherits_model_when_option_brand_missing(db):
    _seed_brand(db)
    sp = _sp(db)
    _crawl(db, sp)
    _link_sku(db, sp, "skuB")            # Option.brand 없음 → Model.brand 상속
    _crawl(db, sp, price=60000)
    assert _row(db, brand="르무통").changed == 1


def test_unlinked_product_still_counted_under_sentinel(db):
    """링크가 없다고 관측을 통째로 버리면 그 소싱처는 영원히 통계에 안 잡힌다."""
    sp = _sp(db)
    _crawl(db, sp)
    _crawl(db, sp, price=60000)
    assert _row(db, brand=UNSPECIFIED_BRAND).changed == 1


def test_brands_of_source_product_falls_back_to_sentinel(db):
    sp = _sp(db)
    assert brands_of_source_product(db, sp) == {UNSPECIFIED_BRAND}


def test_brand_of_skus_prefers_option_brand_then_inherits_model(db):
    _seed_brand(db)
    got = brand_of_skus(db, ["skuA", "skuB"])
    assert got["skuA"] == "나이키"
    assert got["skuB"] == "르무통"


def test_record_ignores_site_less_product(db):
    assert record_crawl_observation(
        db, source_product=SimpleNamespace(id=None, site=""), detail="") == {}


# ══ ③ P2 스킵 — 여기만 마켓 기준(GateDecision) ══════════════════════════════
D_PLENTY = dict(prev_price=1000, prev_stock=5, new_price=1000, new_stock=4)
D_PRICE = dict(prev_price=1000, prev_stock=5, new_price=2000, new_stock=5)


def _plan(sku, decision):
    return SimpleNamespace(link=SimpleNamespace(canonical_sku=sku),
                           decision=decision)


def test_gate_contract_for_p2_skip():
    """★계약 — 우리가 'P2 스킵'이라 부르는 그 판정이 게이트에서 그대로 나오는가."""
    d = decide_upload(**D_PLENTY)
    assert d.priority == "P2" and d.stock_changed and not d.should_upload


def test_p2_skipped_comes_from_gate_decision(db):
    """재고가 바뀌었는데 P2 로 스킵된 건 — 묻히면 안 된다."""
    _seed_brand(db)
    record_gate_skips(db, source_product=SimpleNamespace(id=1, site="musinsa"),
                      plans=[_plan("skuA", decide_upload(**D_PLENTY))])
    assert _row(db, brand="나이키").p2_skipped == 1


def test_gate_skips_do_not_touch_volatility_counters(db):
    """★출처 분리 — 게이트 판정이 변동률 숫자를 건드리면 안 된다(기준선이 다르다)."""
    _seed_brand(db)
    record_gate_skips(db, source_product=SimpleNamespace(id=1, site="musinsa"),
                      plans=[_plan("skuA", decide_upload(**D_PLENTY)),
                             _plan("skuA", decide_upload(**D_PRICE))])
    r = _row(db, brand="나이키")
    assert r.p2_skipped == 1
    assert all(getattr(r, f) == 0 for f in SOURCE_FIELDS)


def test_gate_skips_ignore_empty(db):
    sp = SimpleNamespace(id=1, site="musinsa")
    assert record_gate_skips(db, source_product=sp, plans=[]) == {}


def test_reconcile_records_only_gate_skips(db, monkeypatch):
    """reconcile 은 P2 스킵만 적립한다 — 변동성 통계는 크롤 쪽에서 온다."""
    from lemouton.uploader import reconcile as rc
    _seed_brand(db)
    plans = [SimpleNamespace(
        link=SimpleNamespace(canonical_sku="skuA", stock=5),
        target=SimpleNamespace(market="smartstore", account_key="default",
                               market_product_id="P1", market_option_id="O1"),
        recomputed=SimpleNamespace(upload_price=1000, warnings=()),
        decision=decide_upload(**D_PLENTY), prev_price=1000, prev_stock=5)]
    monkeypatch.setattr(rc, "plan_uploads", lambda *a, **k: plans)
    monkeypatch.setattr(rc, "_record", lambda *a, **k: None)
    monkeypatch.setattr(rc, "unlinked_sku_count", lambda *a, **k: 0)

    rc.reconcile_after_crawl(db, source_product=SimpleNamespace(id=1, site="musinsa"),
                             armed=False, min_margin_amount=0, commit=False)
    r = _row(db, brand="나이키")
    assert r.p2_skipped == 1 and r.observed == 0


def test_stats_failure_does_not_break_upload_pipeline(db, monkeypatch):
    """통계가 터져도 업로드 파이프라인은 계속 돌아야 한다."""
    from lemouton.uploader import reconcile as rc
    import lemouton.sources.crawl_change_stats as ccs
    plans = [SimpleNamespace(
        link=SimpleNamespace(canonical_sku="skuA", stock=5),
        target=SimpleNamespace(market="smartstore", account_key="default",
                               market_product_id="P1", market_option_id="O1"),
        recomputed=SimpleNamespace(upload_price=1000, warnings=()),
        decision=decide_upload(**D_PRICE), prev_price=1000, prev_stock=5)]
    monkeypatch.setattr(rc, "plan_uploads", lambda *a, **k: plans)
    monkeypatch.setattr(rc, "_record", lambda *a, **k: None)
    monkeypatch.setattr(rc, "unlinked_sku_count", lambda *a, **k: 0)

    def _boom(*a, **k):
        raise RuntimeError("통계 폭발")
    monkeypatch.setattr(ccs, "record_gate_skips", _boom)

    out = rc.reconcile_after_crawl(db, source_product=SimpleNamespace(id=1, site="x"),
                                   armed=False, min_margin_amount=0, commit=False)
    assert out["planned"] == 1        # 예외가 새어나오지 않았다


def test_stats_failure_does_not_break_crawl_save(db, monkeypatch):
    """통계가 터져도 크롤 저장은 계속 돌아야 한다."""
    import lemouton.sources.crawl_change_stats as ccs

    def _boom(*a, **k):
        raise RuntimeError("통계 폭발")
    monkeypatch.setattr(ccs, "record_crawl_observation", _boom)
    sp = _sp(db)
    _crawl(db, sp)
    assert db.query(CrawlDelta).filter_by(source_product_id=sp.id).count() == 1


# ══ ④ ★실전송 잠금(OFF) 상태에서도 변동률이 나온다 — 이번 교정의 핵심 ══════
def test_rate_is_real_while_live_upload_is_disarmed(db, monkeypatch):
    """★교정의 목적 — 실전송이 잠겨 있어도 오늘부터 숫자가 나온다.

    (이 테스트가 이전 ``test_disarmed_mode_yields_no_baseline_not_fake_100pct``
     를 대체한다. 그 테스트는 '기준선이 마켓이라 잠금 중엔 통계가 빈다'를 정직하게
     못 박은 것이었는데, 기준선을 소싱처로 옮긴 지금은 **빈다는 것 자체가 틀렸다**.
     대신 그 테스트가 지키던 것 — 기준선 없는 건을 변동으로 세지 않는다 — 는
     ``first_seen`` 으로 남았고 위 ①·②에서 따로 지킨다.)

    잠금 상태의 현실을 그대로 만든다: 마켓 확정 스냅샷이 영원히 None →
    게이트는 매번 'first_upload'. 그래도 변동률은 크롤 기록에서 나와야 한다.
    """
    from lemouton.uploader import reconcile as rc
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
    monkeypatch.setattr(rc, "last_confirmed_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(rc, "_record", lambda *a, **k: None)
    monkeypatch.setattr(rc, "unlinked_sku_count", lambda *a, **k: 0)

    sp = _sp(db)
    _crawl(db, sp, price=50000)                    # 1회차 = 처음 수집
    for i in range(1, 41):                         # 40 관측 중 10회 가격 변동
        _crawl(db, sp, price=50000 + (1000 * (i // 4)))
        # 매 크롤 뒤 업로드 판정 패스도 돈다(잠금 상태) — 여기선 아무 숫자도 안 만든다
        rc.reconcile_after_crawl(db, source_product=sp, armed=False,
                                 min_margin_amount=0, commit=False)

    row = change_stats(db, laps=10)["rows"][0]
    assert row["observed"] == 40
    assert row["changed"] == 10
    assert row["rate_pct"] == 25.0                 # 진짜 숫자가 나온다
    assert row["recommended_weight"] == 5          # 권장도 보류되지 않는다
    assert "변동률 25.0%" in row["recommend_reason"]


# ══ ⑤ 랩 확정 · 정리(prune) ════════════════════════════════════════════════
def test_seal_stamps_open_rows(db):
    sp = _sp(db)
    _crawl(db, sp)
    _crawl(db, sp, price=60000)
    assert seal_open_lap_stats(db, 7) == 1
    assert _row(db, lap_run_id=OPEN_LAP) is None
    assert _row(db, lap_run_id=7).observed == 1


def test_seal_rejects_open_sentinel(db):
    with pytest.raises(ValueError):
        seal_open_lap_stats(db, OPEN_LAP)


def test_next_lap_accumulates_separately(db):
    sp = _sp(db)
    _crawl(db, sp)
    _crawl(db, sp, price=60000)
    seal_open_lap_stats(db, 7)
    _crawl(db, sp, price=60000)          # 무변동
    assert _row(db, lap_run_id=7).changed == 1
    assert _row(db, lap_run_id=OPEN_LAP).changed == 0


def test_start_new_lap_seals_stats(db):
    """★기존 랩 로직에 얹은 훅 — 바퀴가 끝나면 그 바퀴로 확정된다."""
    from lemouton.sources.crawl_schedule import start_new_lap
    sp = _sp(db)
    _crawl(db, sp)
    _crawl(db, sp, price=60000)
    start_new_lap(db, now=datetime(2026, 7, 10, 1, 0, 0))
    db.commit()
    run = db.query(CrawlLapRun).one()
    assert _row(db, lap_run_id=OPEN_LAP) is None
    assert _row(db, lap_run_id=run.id).observed == 1


def test_start_new_lap_without_record_does_not_seal(db):
    from lemouton.sources.crawl_schedule import start_new_lap
    sp = _sp(db)
    _crawl(db, sp)
    start_new_lap(db, record=False)
    assert _row(db, lap_run_id=OPEN_LAP) is not None


def _seed_laps(db, n, *, start=datetime(2026, 7, 10, 0, 0, 0)):
    """n 바퀴 + 바퀴마다 통계 1행."""
    for i in range(1, n + 1):
        db.add(CrawlLapRun(id=i, completed_at=start + timedelta(minutes=8 * i)))
        db.add(CrawlChangeStat(lap_run_id=i, source_key="musinsa",
                               brand=UNSPECIFIED_BRAND, observed=1))
    db.flush()


def test_prune_keeps_recent_n_laps(db):
    """★정리 정책 — 최근 N랩만 남는다. (소싱처×브랜드)/랩 로 늘어 무료 500MB 를 태운다."""
    _seed_laps(db, 10)
    assert prune_old_stats(db, keep_laps=3) == 7
    left = sorted(r.lap_run_id for r in db.query(CrawlChangeStat).all())
    assert left == [8, 9, 10]


def test_prune_never_touches_open_lap(db):
    """진행 중(0) 버킷은 아직 어느 바퀴인지 정해지지도 않았다 — 절대 안 지운다."""
    _seed_laps(db, 5)
    sp = _sp(db)
    _crawl(db, sp)
    prune_old_stats(db, keep_laps=1)
    assert _row(db, lap_run_id=OPEN_LAP) is not None


def test_prune_is_noop_when_within_retention(db):
    _seed_laps(db, 3)
    assert prune_old_stats(db, keep_laps=STATS_RETENTION_LAPS) == 0
    assert db.query(CrawlChangeStat).count() == 3


def test_prune_logs_what_it_deleted(db, caplog):
    """★조용히 지우지 않는다 — 무엇을 얼마나 지웠는지 로그로 남긴다."""
    _seed_laps(db, 6)
    with caplog.at_level(logging.INFO,
                         logger="lemouton.sources.crawl_change_stats"):
        prune_old_stats(db, keep_laps=2)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "오래된 변동 통계 정리" in msg and "4행" in msg


def test_retention_covers_the_widest_screen_window(db):
    """보관 기간은 화면이 고를 수 있는 가장 긴 구간(최근 100바퀴)을 덮어야 한다."""
    from lemouton.sources.crawl_change_stats import MAX_REPORT_LAPS
    assert STATS_RETENTION_LAPS >= MAX_REPORT_LAPS


def test_seal_also_prunes(db, monkeypatch):
    """랩이 끝나는 순간이 '랩이 하나 늘었다'가 확정되는 유일한 자리 → 거기서 정리한다."""
    import lemouton.sources.crawl_change_stats as ccs
    monkeypatch.setattr(ccs, "STATS_RETENTION_LAPS", 2)
    _seed_laps(db, 4)
    sp = _sp(db)
    _crawl(db, sp)
    seal_open_lap_stats(db, 5)
    left = sorted(r.lap_run_id for r in db.query(CrawlChangeStat).all())
    assert 1 not in left and 2 not in left       # 오래된 건 정리됐고
    assert 5 in left                             # 방금 확정한 바퀴는 남는다


def test_prune_holds_off_until_retention_is_filled(db):
    """랩이 보관 기간만큼도 안 쌓였으면 지울 게 없다 — 애매하면 안 지운다."""
    _seed_laps(db, 2)
    assert prune_old_stats(db, keep_laps=5) == 0
    assert db.query(CrawlChangeStat).count() == 2


# ══ ⑥ 권장 계수 ════════════════════════════════════════════════════════════
@pytest.mark.parametrize("rate,expected", [
    (0.00, 1), (0.019, 1),
    (0.02, 2), (0.049, 2),
    (0.05, 3), (0.099, 3),
    (0.10, 4), (0.199, 4),
    (0.20, 5), (0.95, 5),
])
def test_recommend_weight_bands(rate, expected):
    w, why = recommend_weight(rate=rate, observed=100)
    assert w == expected and "변동률" in why


def test_recommend_holds_when_sample_too_small():
    """★신규 브랜드가 한두 번 관측으로 계수 5가 되면 안 된다."""
    w, why = recommend_weight(rate=1.0, observed=MIN_OBSERVATIONS - 1)
    assert w is None and "표본 부족" in why


def test_recommend_at_min_observations_is_allowed():
    w, _ = recommend_weight(rate=1.0, observed=MIN_OBSERVATIONS)
    assert w == 5


def test_recommend_holds_when_rate_unknown():
    w, why = recommend_weight(rate=None, observed=999)
    assert w is None and "보류" in why


def test_recommend_reason_shows_evidence():
    _, why = recommend_weight(rate=0.25, observed=200)
    assert "200회" in why and "50회" in why


def test_bucket_weight_brand_beats_source():
    rules = {"brand": {"나이키": 4}, "source": {"musinsa": 2}}
    assert bucket_weight(rules, "musinsa", "나이키") == 4


def test_bucket_weight_falls_back_to_source_then_default():
    rules = {"brand": {}, "source": {"musinsa": 2}}
    assert bucket_weight(rules, "musinsa", "나이키") == 2
    assert bucket_weight({}, "musinsa", "나이키") == 1


# ══ ⑦ 집계 ════════════════════════════════════════════════════════════════
def _bulk(db, sp, *, n_changed, n_same):
    """관측 n_changed + n_same 회. (첫 크롤은 처음 수집이라 따로 태운다)"""
    _crawl(db, sp, price=50000)
    for i in range(n_changed):
        _crawl(db, sp, price=51000 + i)
    for _ in range(n_same):
        _crawl(db, sp, price=51000 + max(0, n_changed - 1))


def test_change_stats_computes_rate_and_recommendation(db):
    sp = _sp(db)
    _bulk(db, sp, n_changed=25, n_same=75)
    row = change_stats(db, laps=10)["rows"][0]
    assert row["observed"] == 100 and row["changed"] == 25
    assert row["rate_pct"] == 25.0
    assert row["recommended_weight"] == 5
    assert row["current_weight"] == 1
    assert row["differs"] is True


def test_change_stats_orders_by_rate_desc(db):
    a = _sp(db, site="musinsa", url="https://a")
    b = _sp(db, site="ssf", url="https://b")
    _bulk(db, a, n_changed=5, n_same=95)      # 5%
    _bulk(db, b, n_changed=40, n_same=60)     # 40%
    rows = change_stats(db, laps=10)["rows"]
    assert [r["source_key"] for r in rows] == ["ssf", "musinsa"]


def test_change_stats_excludes_weight_zero(db):
    """★계수 0 = 크롤 제외. 사용자가 일부러 끈 것 → 통계·권장에서 뺀다."""
    from lemouton.sources.crawl_schedule import set_crawl_weight_rule
    sp = _sp(db)
    _bulk(db, sp, n_changed=50, n_same=50)
    set_crawl_weight_rule(db, "source", "musinsa", 0)
    db.commit()
    out = change_stats(db, laps=10)
    assert out["rows"] == []
    assert out["excluded_zero"][0]["source_key"] == "musinsa"


def test_change_stats_holds_recommendation_on_small_sample(db):
    sp = _sp(db)
    _bulk(db, sp, n_changed=1, n_same=1)
    row = change_stats(db, laps=10)["rows"][0]
    assert row["recommended_weight"] is None
    assert "표본 부족" in row["recommend_reason"]
    assert row["differs"] is False       # 보류는 '다름'으로 표시하지 않는다


def test_change_stats_first_seen_does_not_deflate_rate(db):
    """★처음 수집이 분모에 들어가면 변동률이 낮아져 계수가 잘못 내려간다."""
    sp = _sp(db)
    _crawl(db, sp, price=50000)                 # 처음 수집만
    for i in range(30):
        _crawl(db, sp, price=51000 + i)
    row = change_stats(db, laps=10)["rows"][0]
    assert row["first_seen"] == 1
    assert row["observed"] == 30 and row["rate_pct"] == 100.0


def test_change_stats_window_limits_to_recent_laps(db):
    sp = _sp(db)
    _bulk(db, sp, n_changed=50, n_same=0)
    seal_open_lap_stats(db, 1)
    _crawl(db, sp, price=99000)                 # 변동 1
    for _ in range(49):
        _crawl(db, sp, price=99000)             # 무변동 49
    seal_open_lap_stats(db, 2)
    t = datetime(2026, 7, 10, 1, 0, 0)
    db.add(CrawlLapRun(id=1, completed_at=t))
    db.add(CrawlLapRun(id=2, completed_at=t + timedelta(minutes=8)))
    db.commit()
    row = change_stats(db, laps=1, include_open=False)["rows"][0]
    assert row["observed"] == 50 and row["changed"] == 1


def test_change_stats_totals(db):
    sp = _sp(db)
    _bulk(db, sp, n_changed=10, n_same=10)
    t = change_stats(db, laps=10)["totals"]
    assert t["observed"] == 20 and t["changed"] == 10 and t["rate_pct"] == 50.0
    assert t["buckets"] == 1


def test_change_stats_empty_db_is_safe(db):
    out = change_stats(db, laps=10)
    assert out["rows"] == [] and out["totals"]["observed"] == 0


def test_change_stats_declares_where_each_number_came_from(db):
    """★화면이 출처를 지어내지 않게 서버가 지표별 기준선을 그대로 알려준다."""
    out = change_stats(db, laps=10)
    src = out["sources"]
    assert set(src["crawl_delta"]["fields"]) == set(SOURCE_FIELDS)
    assert set(src["gate_decision"]["fields"]) == set(GATE_FIELDS)
    assert "p2_skipped" not in SOURCE_FIELDS      # 섞이면 안 된다
    assert "CrawlDelta" in src["crawl_delta"]["label"]
    assert "GateDecision" in src["gate_decision"]["label"]


def test_lap_change_report_reuses_lap_stats(db):
    """소요시간·오늘 바퀴 수는 기존 CrawlLapRun 을 재사용한다(새로 세지 않는다)."""
    from lemouton.sources.crawl_schedule import lap_stats
    sp = _sp(db)
    _bulk(db, sp, n_changed=10, n_same=10)
    now = datetime(2026, 7, 10, 5, 0, 0)
    db.add(CrawlLapRun(completed_at=datetime(2026, 7, 10, 1, 0, 0)))
    db.add(CrawlLapRun(completed_at=datetime(2026, 7, 10, 1, 8, 0)))
    db.commit()
    rep = lap_change_report(db, laps=10, now=now)
    assert rep["lap"] == lap_stats(db, now=now)
    assert rep["lap"]["laps_today"] == 2
    assert rep["rows"]


def test_lap_change_report_reports_failures_as_now_not_per_lap(db):
    """랩별 실패 건수는 존재하지 않는다(성공한 크롤만 기록) → '지금 실패 중'만 싣는다."""
    rep = lap_change_report(db, laps=10, now=datetime(2026, 7, 10, 5, 0, 0))
    assert isinstance(rep["failing_now"], list)
