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


def test_parse_itmd_lines_벌별_분리():
    """🔴 네이버 정산은 벌(odSeq)별 pymtAmt — odNo 합산이 아니라 라인 단위로 나눠야
      다품 2배를 막는다(2026-07-25 실측 2026070213054145: odSeq1=odSeq2=41,624)."""
    from shared.platforms.lotteon.settlement import parse_itmd_lines
    resp = {"data": [
        {"odNo": "M1", "odSeq": "1", "procSeq": "1", "pymtAmt": "41624"},
        {"odNo": "M1", "odSeq": "2", "procSeq": "1", "pymtAmt": "41624"},
        {"odNo": "S1", "odSeq": "1", "procSeq": "1", "pymtAmt": "50000"},
    ]}
    m = parse_itmd_lines(resp)
    assert m[("M1", "1")] == 41624      # 벌1 (odNo 총액 83,248 아님)
    assert m[("M1", "2")] == 41624      # 벌2
    assert m[("S1", "1")] == 50000      # 단일라인


def test_parse_itmd_lines_같은벌_procSeq는_합산():
    """같은 (odNo,odSeq) 의 여러 procSeq(부분취소 등)는 합산 — 벌 단위 총액."""
    from shared.platforms.lotteon.settlement import parse_itmd_lines
    resp = {"data": [
        {"odNo": "M1", "odSeq": "1", "procSeq": "1", "pymtAmt": "30000"},
        {"odNo": "M1", "odSeq": "1", "procSeq": "2", "pymtAmt": "11624"},
    ]}
    m = parse_itmd_lines(resp)
    assert m[("M1", "1")] == 41624
