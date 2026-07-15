from shared.platforms.lotteon.settlement import parse_itmd, parse_product_affiliate


def test_aggregates_pymt_and_affiliate_per_order():
    resp = {"data": [
        {"odNo": "A1", "pymtAmt": "41475.00", "pcsCmsn": "0.00"},
        {"odNo": "A1", "pymtAmt": "1000.00", "pcsCmsn": "20.00"},
        {"odNo": "B2", "pymtAmt": "54238.00", "pcsCmsn": "0.00"},
    ]}
    m = parse_itmd(resp)
    assert m["A1"] == {"pymtAmt": 42475, "pcs_cmsn": 20, "is_affiliate": True}
    assert m["B2"] == {"pymtAmt": 54238, "pcs_cmsn": 0, "is_affiliate": False}


def test_empty_and_bad_values():
    assert parse_itmd({}) == {}
    assert parse_itmd({"data": [{"odNo": "", "pymtAmt": "9"}]}) == {}


def test_parse_product_affiliate():
    resp = {"data": [
        {"spdNo": "P1", "pcsCmsn": "0.00"},
        {"spdNo": "P1", "pcsCmsn": "20.00"},   # 같은 상품에 제휴 라인 → True
        {"spdNo": "P2", "pcsCmsn": "0.00"},
        {"spdNo": "", "pcsCmsn": "5.00"},       # spdNo 없음 → 제외
    ]}
    m = parse_product_affiliate(resp)
    assert m == {"P1": True, "P2": False}
