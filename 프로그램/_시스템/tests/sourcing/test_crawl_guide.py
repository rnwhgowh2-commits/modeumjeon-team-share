import pytest
from lemouton.sourcing.crawl_guide import empty_skeleton, validate_guide, merge_verification

def test_empty_skeleton_shape():
    sk = empty_skeleton()
    assert sk["version"] == 3
    assert sk["sample_urls"] == []
    assert set(sk["fields"]) == {
        "thumbnail", "title", "price", "benefit", "option_stock", "detail_image"}
    assert sk["pricing"]["benefits"] == []
    assert sk["pricing"]["benefit_collection"] == "per_product"

def test_validate_accepts_minimal_valid():
    data = {
        "version": 3,
        "sample_urls": [{"url": "https://www.musinsa.com/products/1", "is_lead": True}],
        "fields": empty_skeleton()["fields"],
        "pricing": {
            "base_label": "표면 노출가",
            "benefit_collection": "per_product",
            "benefits": [
                {"name": "등급 할인", "apply": "deduct", "rule": "잔액 × 등급 %", "status": "always"}
            ],
            "note": "",
        },
    }
    out = validate_guide(data)
    assert out["pricing"]["benefits"][0]["name"] == "등급 할인"
    assert out["version"] == 3

def test_validate_rejects_bad_benefit_apply():
    data = empty_skeleton()
    data["pricing"]["benefits"] = [
        {"name": "x", "apply": "WRONG", "rule": "r", "status": "always"}]
    with pytest.raises(ValueError):
        validate_guide(data)

def test_validate_rejects_bad_status():
    data = empty_skeleton()
    data["pricing"]["benefits"] = [
        {"name": "x", "apply": "deduct", "rule": "r", "status": "WRONG"}]
    with pytest.raises(ValueError):
        validate_guide(data)

def test_validate_rejects_non_http_url():
    data = empty_skeleton()
    data["sample_urls"] = [{"url": "javascript:alert(1)", "is_lead": True}]
    with pytest.raises(ValueError):
        validate_guide(data)

def test_validate_rejects_empty_benefit_name():
    data = empty_skeleton()
    data["pricing"]["benefits"] = [
        {"name": "  ", "apply": "deduct", "rule": "r", "status": "always"}]
    with pytest.raises(ValueError):
        validate_guide(data)

def test_merge_verification_last_new_check():
    guide = empty_skeleton()
    result = {
        "url": "https://www.musinsa.com/products/4112020",
        "surface_price": 42000, "benefit_total": -2100, "final_price": 39900,
        "option_stock": "그레이/250 재고○",
        "flags": {"benefit": "warn", "surface_price": "ok"},
        "job_id": 1234, "status": "done", "crawled_at": "2026-06-06T00:00:00Z",
    }
    out = merge_verification(guide, "last_new_check", result)
    assert out["verification"]["last_new_check"]["final_price"] == 39900
    assert out["verification"]["last_new_check"]["flags"]["benefit"] == "warn"
    assert out["verification"]["lead_cache"] is None

def test_merge_verification_rejects_bad_kind():
    with pytest.raises(ValueError):
        merge_verification(empty_skeleton(), "WRONG", {})
