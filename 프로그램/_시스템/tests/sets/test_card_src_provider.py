"""카드 「소」 대표 소싱처 선정 — 폴백가·stale·품절·매칭실패 누수 방지.

_pick_card_source 는 매트릭스와 동일 게이트(is_crawl_valid + 품절X + 매칭성공)로
대표(최저가) 소싱처를 고른다. 유효 후보 없으면 None(하드코딩 95000·사입가 폴백 금지).
"""
from webapp.routes.sets_api import _pick_card_source


def _s(price, status="ok", stock_out=False, match_failed=False, name="르무통"):
    return {"crawled_price": price, "last_status": status, "stock_out": stock_out,
            "match_failed": match_failed, "source_name": name,
            "product_url": "u", "source_id": 1}


def test_error_stale_price_excluded():
    # 옛 가격(stale)이 더 싸도 error 소싱처는 대표가로 잡히면 안 됨
    win = _pick_card_source([_s(120000, "ok"), _s(50000, "error")])
    assert win["crawled_price"] == 120000


def test_match_failed_excluded():
    win = _pick_card_source([_s(120000, "ok"), _s(40000, "ok", match_failed=True)])
    assert win["crawled_price"] == 120000


def test_buyable_preferred_over_cheaper_soldout():
    win = _pick_card_source([_s(95000, "ok"), _s(90000, "ok", stock_out=True)])
    assert win["crawled_price"] == 95000


def test_soldout_allowed_when_only_option():
    win = _pick_card_source([_s(90000, "ok", stock_out=True)])
    assert win["crawled_price"] == 90000


def test_no_valid_returns_none_no_fallback():
    # 전부 error/0 → None(폴백가 금지). 카드는 '상세 ▾'/미상 으로 정직 표면화.
    assert _pick_card_source([_s(0, "ok"), _s(50000, "error")]) is None
    assert _pick_card_source([]) is None
