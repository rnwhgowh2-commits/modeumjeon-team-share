"""롯데온 SettleItmdSales 파서.

★[2026-08-04] 아래 픽스처에 spdNo 를 넣었다. parse_itmd/parse_itmd_lines 가
  **상품 판매대금 라인만** 세도록 바뀌었기 때문이다(상품번호 없는 별도 항목 10,000원이
  정산예정금으로 둔갑하던 것 수정 — 라이브 정합성 검사 4건).
  ★이건 「코드에 맞춰 테스트를 구부린 것」이 아니다: 같은 파일의
    test_parse_product_affiliate 가 **이미 예전부터** `spdNo` 없는 행을 제외한다
    (`{"spdNo": "", ...}` → 제외). 나머지 두 함수만 그 규약에서 빠져 있었을 뿐이다.
    라이브 전수(833행)도 procSeq 1·2·3 = 760행 전부 상품번호 있음으로 갈렸다.
  각 테스트가 지키려는 것(주문 단위 합산 · 벌별 분리 · procSeq 합산)은 그대로다.
"""
from shared.platforms.lotteon.settlement import parse_itmd, parse_product_affiliate


def test_aggregates_pymt_and_affiliate_per_order():
    resp = {"data": [
        {"odNo": "A1", "pymtAmt": "41475.00", "pcsCmsn": "0.00", "spdNo": "SP1"},
        {"odNo": "A1", "pymtAmt": "1000.00", "pcsCmsn": "20.00", "spdNo": "SP1"},
        {"odNo": "B2", "pymtAmt": "54238.00", "pcsCmsn": "0.00", "spdNo": "SP2"},
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
        {"odNo": "M1", "odSeq": "1", "procSeq": "1", "pymtAmt": "41624", "spdNo": "SP1"},
        {"odNo": "M1", "odSeq": "2", "procSeq": "1", "pymtAmt": "41624", "spdNo": "SP2"},
        {"odNo": "S1", "odSeq": "1", "procSeq": "1", "pymtAmt": "50000", "spdNo": "SP3"},
    ]}
    m = parse_itmd_lines(resp)
    assert m[("M1", "1")] == 41624      # 벌1 (odNo 총액 83,248 아님)
    assert m[("M1", "2")] == 41624      # 벌2
    assert m[("S1", "1")] == 50000      # 단일라인


def test_parse_itmd_lines_같은벌_procSeq는_합산():
    """같은 (odNo,odSeq) 의 여러 procSeq(부분취소 등)는 합산 — 벌 단위 총액."""
    from shared.platforms.lotteon.settlement import parse_itmd_lines
    resp = {"data": [
        {"odNo": "M1", "odSeq": "1", "procSeq": "1", "pymtAmt": "30000", "spdNo": "SP1"},
        {"odNo": "M1", "odSeq": "1", "procSeq": "2", "pymtAmt": "11624", "spdNo": "SP1"},
    ]}
    m = parse_itmd_lines(resp)
    assert m[("M1", "1")] == 41624
