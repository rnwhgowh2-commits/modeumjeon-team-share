from shared.platforms.lotteon.settlement import parse_itmd


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
