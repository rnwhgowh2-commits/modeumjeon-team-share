import pytest
from lemouton.sourcing.crawl_guide import empty_skeleton, validate_guide

def test_empty_skeleton_shape():
    sk = empty_skeleton()
    assert sk["version"] == 2
    assert sk["sample_urls"] == []
    assert set(sk["fields"]) == {
        "thumbnail", "title", "price", "benefit", "option_stock", "detail_image"}
    assert sk["pricing"]["benefits"] == []
    assert sk["pricing"]["benefit_collection"] == "per_product"

def test_validate_accepts_minimal_valid():
    data = {
        "version": 2,
        "sample_urls": [{"url": "https://www.musinsa.com/products/1", "is_lead": True}],
        "fields": empty_skeleton()["fields"],
        "pricing": {
            "base_label": "표면 노출가",
            "benefit_collection": "per_product",
            "benefits": [
                {"name": "등급 할인", "method": "rate", "rule": "잔액 × 등급 %", "status": "always"}
            ],
            "note": "",
        },
    }
    out = validate_guide(data)
    assert out["pricing"]["benefits"][0]["name"] == "등급 할인"
    assert out["version"] == 2

def test_validate_rejects_bad_benefit_method():
    data = empty_skeleton()
    data["pricing"]["benefits"] = [
        {"name": "x", "method": "WRONG", "rule": "r", "status": "always"}]
    with pytest.raises(ValueError):
        validate_guide(data)

def test_validate_rejects_bad_status():
    data = empty_skeleton()
    data["pricing"]["benefits"] = [
        {"name": "x", "method": "rate", "rule": "r", "status": "WRONG"}]
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
        {"name": "  ", "method": "rate", "rule": "r", "status": "always"}]
    with pytest.raises(ValueError):
        validate_guide(data)
