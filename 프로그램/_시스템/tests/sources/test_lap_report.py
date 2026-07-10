from datetime import datetime, timedelta

from lemouton.sources.lap_report import (
    parse_detail, _stock_word, _price_word, lap_report, lap_bounds,
)


# ── 변동 문장 파싱 ──────────────────────────────────────────────
def test_parse_detail_price_and_stock():
    d = "[블랙/265] 가격 115000→119900 · [블랙/265] 재고 3→0"
    items = parse_detail(d)
    price = [x for x in items if x["kind"] == "price"]
    stock = [x for x in items if x["kind"] == "stock"]
    assert price == [{"kind": "price", "option": "블랙/265", "from": "115000", "to": "119900"}]
    assert stock == [{"kind": "stock", "option": "블랙/265", "from": "3", "to": "0"}]


def test_parse_detail_option_added_removed():
    items = parse_detail("[화이트/270] 옵션 생김 · [블랙/280] 옵션 사라짐")
    assert {(x["option"], x["to"]) for x in items} == {("화이트/270", "생김"), ("블랙/280", "사라짐")}


def test_parse_detail_empty():
    assert parse_detail("") == [] and parse_detail(None) == []


# ── 사람 말 변환 (재고 센티넬) ──────────────────────────────────
def test_stock_word_sentinels():
    assert _stock_word("0") == "품절"
    assert _stock_word("999") == "있음"
    assert _stock_word("-1") == "확인불가"
    assert _stock_word("3") == "3개"
    assert _stock_word("None") == "미크롤"


def test_price_word():
    assert _price_word("119900") == "119,900"
    assert _price_word("None") == "없음"


# ── 회차 보고서 (합성 DB) ───────────────────────────────────────
def _seed(db):
    from lemouton.sources.models import SourceProduct, CrawlLapRun, CrawlDelta
    sp = SourceProduct(site="musinsa", url="https://www.musinsa.com/products/1")
    db.add(sp); db.flush()
    t0 = datetime(2026, 7, 10, 1, 0, 0)     # naive UTC (KST 10:00)
    t1 = t0 + timedelta(minutes=8)
    t2 = t1 + timedelta(minutes=7)
    db.add(CrawlLapRun(completed_at=t1))    # 1회차 끝
    db.add(CrawlLapRun(completed_at=t2))    # 2회차 끝
    # 2회차 구간(t1<x<=t2) 안의 변동 1건
    db.add(CrawlDelta(source_product_id=sp.id, crawled_at=t1 + timedelta(minutes=2),
                      price_changed=True, stock_changed=True,
                      detail="[블랙/265] 가격 115000→119900 · [블랙/265] 재고 3→0"))
    # 1회차 구간 안의 변동 없음 크롤 1건(성공 카운트에는 들어감)
    db.add(CrawlDelta(source_product_id=sp.id, crawled_at=t0 + timedelta(minutes=1),
                      price_changed=False, stock_changed=False, detail=""))
    db.commit()
    return sp, t0, t1, t2


def test_lap_report_second_lap_has_changes(db):
    sp, t0, t1, t2 = _seed(db)
    now = t2 + timedelta(minutes=1)
    r = lap_report(db, lap_no=2, now=now)
    assert r is not None
    assert r["lap"]["no"] == 2 and r["lap"]["minutes"] == 7
    assert r["summary"]["urls"] == 1
    # 가격 = 오름(+4900), 재고 = 품절 전환
    p = r["changes"]["price"]
    assert len(p) == 1
    assert p[0]["site"] == "musinsa"          # 원문 키(호환)
    assert p[0]["site_label"]                  # 사람이 읽는 이름(hmall→현대H몰)
    assert (p[0]["option"], p[0]["from"], p[0]["to"], p[0]["delta"], p[0]["dir"]) \
        == ("블랙/265", "115,000", "119,900", 4900, "up")
    assert r["changes"]["stock"][0]["to"] == "품절"
    assert r["changes"]["stock"][0]["dir"] == "so"
    assert r["result"]["saved"] == 1


def test_lap_report_first_lap_no_changes(db):
    sp, t0, t1, t2 = _seed(db)
    r = lap_report(db, lap_no=1, now=t2 + timedelta(minutes=1))
    assert r["changes"]["price"] == [] and r["changes"]["stock"] == []
    assert r["result"]["saved"] == 1          # 변동 없어도 크롤은 됨


def test_lap_report_out_of_range(db):
    _seed(db)
    assert lap_report(db, lap_no=99, now=datetime(2026, 7, 10, 2, 0, 0)) is None


# ── ★첫 수집은 '변동'이 아니다 (라이브서 921건 둔갑했던 버그) ─────────
def _seed_first(db, detail):
    from lemouton.sources.models import SourceProduct, CrawlLapRun, CrawlDelta
    sp = SourceProduct(site="ssg", url="https://www.ssg.com/item/1")
    db.add(sp); db.flush()
    t0 = datetime(2026, 7, 10, 1, 0, 0)
    t1 = t0 + timedelta(minutes=5)
    t2 = t1 + timedelta(minutes=5)
    db.add(CrawlLapRun(completed_at=t1)); db.add(CrawlLapRun(completed_at=t2))
    db.add(CrawlDelta(source_product_id=sp.id, crawled_at=t1 + timedelta(minutes=1),
                      price_changed=True, stock_changed=True, detail=detail))
    db.commit()
    return t2


def test_first_seen_price_is_not_a_change(db):
    # 이전 가격 없음(None) → 값이 처음 잡힘 = 변동 아님
    t2 = _seed_first(db, "[블랙/265] 가격 None→120320")
    r = lap_report(db, lap_no=2, now=t2 + timedelta(minutes=1))
    assert r["changes"]["price"] == []
    assert r["summary"]["first_seen"] == 1


def test_first_seen_stock_is_not_a_change(db):
    # 미크롤(None) → 30개 = 처음 수집
    t2 = _seed_first(db, "[블랙/265] 재고 None→30")
    r = lap_report(db, lap_no=2, now=t2 + timedelta(minutes=1))
    assert r["changes"]["stock"] == []
    assert r["summary"]["first_seen"] == 1


def test_option_added_is_first_seen_removed_is_change(db):
    t2 = _seed_first(db, "[화이트/270] 옵션 생김 · [블랙/280] 옵션 사라짐")
    r = lap_report(db, lap_no=2, now=t2 + timedelta(minutes=1))
    assert r["summary"]["first_seen"] == 1                    # 생김 = 신규
    assert len(r["changes"]["stock"]) == 1                    # 사라짐 = 변동
    assert r["changes"]["stock"][0]["to"] == "옵션 사라짐"
    assert r["changes"]["stock"][0]["dir"] == "so"


def test_lap_no_beyond_50_still_found(db):
    """★today_laps 는 최근 50개만 잘라 보낸다 → 51번째 이후 회차가 404 나던 버그(라이브)."""
    from lemouton.sources.models import CrawlLapRun
    base = datetime(2026, 7, 10, 0, 10, 0)          # naive UTC(=KST 09:10) → 오늘
    for i in range(60):                              # 오늘 60바퀴
        db.add(CrawlLapRun(completed_at=base + timedelta(minutes=5 * i)))
    db.commit()
    now = base + timedelta(minutes=5 * 60)
    assert lap_bounds(db, lap_no=55, now=now) is not None      # 잘린 50개 밖
    r = lap_report(db, lap_no=55, now=now)
    assert r is not None and r["lap"]["no"] == 55
    assert lap_report(db, lap_no=61, now=now) is None          # 진짜 범위 밖


def test_stock_to_unknown_is_change_not_dropped(db):
    # 3개 → 확인불가(-1) : 크롤 불확실 — 변동으로 표면화(숨기지 않음)
    t2 = _seed_first(db, "[블랙/265] 재고 3→-1")
    r = lap_report(db, lap_no=2, now=t2 + timedelta(minutes=1))
    assert r["changes"]["stock"][0]["to"] == "확인불가"
    assert r["changes"]["stock"][0]["dir"] == "unk"


def test_excluded_sites_lists_weight_zero(db):
    """계수 0 소싱처만, 사람이 읽는 이름으로(hmall→현대H몰)."""
    from lemouton.sources.crawl_schedule import set_crawl_weight_rule
    from lemouton.sources.lap_report import excluded_sites, site_labels
    set_crawl_weight_rule(db, "source", "lotteon", 0)
    set_crawl_weight_rule(db, "source", "musinsa", 2)
    db.commit()
    expected = site_labels().get("lotteon", "lotteon")
    assert excluded_sites(db) == [expected]     # 계수 2 인 무신사는 안 들어감


# ── 변동 없던 소싱처의 '지금 값' — ★상품(URL) 단위 ────────────────────
def test_keep_sources_is_per_product_no_price_fallback(db):
    """★한 소싱처에 상품 2개. 최저가로 뭉개지 말고 상품마다 제 값을 낸다."""
    from lemouton.sources.models import SourceProduct, SourceOption
    from lemouton.sources.lap_report import keep_sources
    a = SourceProduct(site="ssf", url="https://www.ssfshop.com/p/1",
                      product_name="클래식 블랙", last_price=119900)
    b = SourceProduct(site="ssf", url="https://www.ssfshop.com/p/2",
                      product_name="클래식 아이보리", last_price=129000)
    db.add_all([a, b]); db.flush()
    db.add(SourceOption(source_product_id=a.id, color_text="블랙", size_text="250", current_stock=999))
    db.add(SourceOption(source_product_id=a.id, color_text="블랙", size_text="260", current_stock=0))
    db.add(SourceOption(source_product_id=b.id, color_text="아이보리", size_text="250", current_stock=3))
    db.commit()

    ks = keep_sources(db, crawled_sites={"ssf"}, changed_sites=set())
    assert len(ks) == 1 and ks[0]["product_count"] == 2
    ps = {p["name"]: p for p in ks[0]["products"]}
    # 값이 상품마다 따로 (min() 폴백이면 둘 다 119900 이 된다)
    assert ps["클래식 블랙"]["surface_price"] == 119900
    assert ps["클래식 아이보리"]["surface_price"] == 129000
    # 격자·요약도 상품 안에서만 (섞이면 블랙 상품에 아이보리가 들어온다)
    assert ps["클래식 블랙"]["stock_summary"] == {"ample": 1, "limited": 0, "soldout": 1, "unknown": 0}
    assert len(ps["클래식 블랙"]["stock_grid"]) == 2
    assert ps["클래식 아이보리"]["stock_summary"] == {"ample": 0, "limited": 1, "soldout": 0, "unknown": 0}
    assert {g["color"] for g in ps["클래식 아이보리"]["stock_grid"]} == {"아이보리"}


def test_keep_sources_grid_and_summary_never_disagree(db):
    """★격자 칸 수 = 요약 합계. (뭉치면 색·사이즈가 덮어써 154칸인데 400개라 말한다)"""
    from lemouton.sources.models import SourceProduct, SourceOption
    from lemouton.sources.lap_report import keep_sources
    sp = SourceProduct(site="ssf", url="https://www.ssfshop.com/p/9", last_price=1000)
    db.add(sp); db.flush()
    for c, z, q in [("블랙", "250", 999), ("블랙", "260", 3), ("아이보리", "250", 0), ("아이보리", "260", None)]:
        db.add(SourceOption(source_product_id=sp.id, color_text=c, size_text=z, current_stock=q))
    db.commit()
    p = keep_sources(db, crawled_sites={"ssf"}, changed_sites=set())[0]["products"][0]
    assert len(p["stock_grid"]) == sum(p["stock_summary"].values()) == 4
    assert p["stock_summary"] == {"ample": 1, "limited": 1, "soldout": 1, "unknown": 1}


def test_keep_sources_keys_come_from_link_not_site_name(db):
    """★최종매입가 열쇠(sku·source_id)는 상품 URL에 걸린 연결에서 온다.
    연결이 없으면 None → 화면은 「확인불가」. (소싱처 이름으로 짐작하면 늘 None 이었다)"""
    from lemouton.sources.models import SourceProduct
    from lemouton.sourcing.models_pricing import OptionSourceUrl
    from lemouton.sources.lap_report import keep_sources
    a = SourceProduct(site="ssf", url="https://www.ssfshop.com/p/1", last_price=1)
    b = SourceProduct(site="ssf", url="https://www.ssfshop.com/p/2", last_price=2)
    db.add_all([a, b]); db.flush()
    db.add(OptionSourceUrl(canonical_sku="SKU-A", source_id=7,
                           product_url="https://www.ssfshop.com/p/1"))
    db.commit()
    ps = {p["url"]: p for p in keep_sources(db, crawled_sites={"ssf"}, changed_sites=set())[0]["products"]}
    assert (ps["https://www.ssfshop.com/p/1"]["sku"], ps["https://www.ssfshop.com/p/1"]["source_id"]) == ("SKU-A", 7)
    assert ps["https://www.ssfshop.com/p/2"]["sku"] is None      # 연결 없음 = 확인불가
    assert ps["https://www.ssfshop.com/p/2"]["source_id"] is None


def test_keep_sources_empty_when_all_changed(db):
    from lemouton.sources.lap_report import keep_sources
    assert keep_sources(db, crawled_sites={"ssf"}, changed_sites={"ssf"}) == []
