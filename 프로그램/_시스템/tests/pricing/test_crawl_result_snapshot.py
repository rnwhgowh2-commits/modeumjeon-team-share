from webapp.routes.api_pricing import _build_crawl_snapshot


def test_snapshot_from_item_with_benefits():
    item = {
        "price": 122900, "is_logged_in": True,
        "benefits_ok": True,
        "benefit_lines": ["상품 쿠폰 5%", "무신사 머니 2,000원 적립"],
        "benefit_amounts": {"상품쿠폰": {"type": "amount", "value": 6145},
                            "무신사머니 결제 적립": {"type": "amount", "value": 2000}},
    }
    snap = _build_crawl_snapshot(item, now_iso="2026-06-14T00:00:00+00:00")
    assert snap["is_logged_in"] is True
    assert snap["benefits_ok"] is True
    assert snap["lines"] == ["상품 쿠폰 5%", "무신사 머니 2,000원 적립"]
    assert snap["amounts"]["무신사머니 결제 적립"]["value"] == 2000
    assert snap["crawled_at"] == "2026-06-14T00:00:00+00:00"


def test_snapshot_benefits_not_ok_when_missing():
    item = {"price": 122900, "is_logged_in": False}
    snap = _build_crawl_snapshot(item, now_iso="2026-06-14T00:00:00+00:00")
    assert snap["benefits_ok"] is False
    assert snap["lines"] == []
    assert snap["amounts"] == {}
