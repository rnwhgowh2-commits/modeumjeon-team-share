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
    assert r["changes"]["price"] == [{
        "site": "musinsa", "option": "블랙/265",
        "from": "115,000", "to": "119,900", "delta": 4900, "dir": "up",
    }]
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


def test_excluded_sites_lists_weight_zero(db):
    from lemouton.sources.crawl_schedule import set_crawl_weight_rule
    from lemouton.sources.lap_report import excluded_sites
    set_crawl_weight_rule(db, "source", "lotteon", 0)
    set_crawl_weight_rule(db, "source", "musinsa", 2)
    db.commit()
    assert excluded_sites(db) == ["lotteon"]
