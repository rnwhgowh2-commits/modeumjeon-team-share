"""주문 라인 고유키 — 계정 간 중복제거와 DB 적재가 함께 쓰는 키.

여기서 지키려는 두 가지 사고:
  ① 키가 너무 느슨하면(상품명 등 변하는 값) 같은 주문이 두 번 계상된다 = 발송·정산 2배
  ② 키가 너무 넓으면(주문번호 단독) 다품목 주문의 라인이 서로를 덮어쓴다 = 주문 소실
"""
from __future__ import annotations

from lemouton.markets import line_uid as L


# ── 마켓별 키 조립 ──────────────────────────────────────────────
def test_스마트스토어는_productOrderId_로_만든다():
    assert L.line_uid("smartstore", {"오픈마켓주문번호": "P1"}) == "smartstore|P1"


def test_쿠팡은_배송박스와_옵션을_함께_쓴다():
    """orderId 는 주문 단위라 라인을 못 가른다 — 반드시 shipmentBoxId+vendorItemId."""
    row = {"_send_ids": {"shipment_box_id": "B1", "order_sheet_id": "O1"},
           "_pd_market_option_id": "V1"}
    assert L.line_uid("coupang", row) == "coupang|B1|V1"


def test_쿠팡_같은주문_다른옵션은_다른_키다():
    a = {"_send_ids": {"shipment_box_id": "B1"}, "_pd_market_option_id": "V1"}
    b = {"_send_ids": {"shipment_box_id": "B1"}, "_pd_market_option_id": "V2"}
    assert L.line_uid("coupang", a) != L.line_uid("coupang", b)


def test_11번가는_주문번호와_상품seq():
    row = {"_send_ids": {"ord_no": "N1", "ord_prd_seq": "2"}}
    assert L.line_uid("eleven11", row) == "eleven11|N1|2"


def test_11번가_클레임은_clmReqSeq_까지_붙는다():
    """같은 라인이 반품요청→반품완료로 두 번 오면 서로 다른 이벤트다."""
    a = {"_send_ids": {"ord_no": "N1", "ord_prd_seq": "2", "clm_req_seq": "1"}}
    b = {"_send_ids": {"ord_no": "N1", "ord_prd_seq": "2", "clm_req_seq": "2"}}
    assert L.line_uid("eleven11", a) != L.line_uid("eleven11", b)


def test_롯데온은_odNo_odSeq_sitmNo():
    row = {"_send_ids": {"od_no": "D1", "od_seq": "1", "sitm_no": "S1"}}
    assert L.line_uid("lotteon", row) == "lotteon|D1|1|S1"


def test_ESM은_OrderNo_이고_마켓이_구분된다():
    row = {"오픈마켓주문번호": "E1"}
    assert L.line_uid("auction", row) == "auction|E1"
    assert L.line_uid("gmarket", row) == "gmarket|E1"
    assert L.line_uid("auction", row) != L.line_uid("gmarket", row)


# ── 못 만들 때는 지어내지 않는다 ────────────────────────────────
def test_조각이_하나라도_비면_키를_안_만든다():
    """부분키는 서로 다른 라인을 한 줄로 합쳐버린다 — 주문 소실."""
    assert L.line_uid("coupang", {"_send_ids": {"shipment_box_id": "B1"}}) == ""
    assert L.line_uid("lotteon", {"_send_ids": {"od_no": "D1", "od_seq": ""}}) == ""
    assert L.line_uid("smartstore", {"오픈마켓주문번호": ""}) == ""


def test_모르는_마켓은_빈값():
    assert L.line_uid("shopmine", {"오픈마켓주문번호": "X"}) == ""


def test_행이_깨져도_예외를_안_낸다():
    """키 생성 실패가 주문 조회 전체를 깨뜨리면 안 된다."""
    assert L.line_uid("coupang", {"_send_ids": "문자열이라 dict 아님"}) == ""


# ── stamp ─────────────────────────────────────────────────────
def test_stamp_는_만들_수_있는_행에만_심는다():
    rows = [{"오픈마켓주문번호": "P1"}, {"오픈마켓주문번호": ""}]
    L.stamp("smartstore", rows)
    assert rows[0][L.FIELD] == "smartstore|P1"
    assert L.FIELD not in rows[1]


# ── 중복제거 키 ────────────────────────────────────────────────
def test_상품명이_바뀌어도_같은_주문으로_잡힌다():
    """이 테스트가 버그의 본체다 — 예전 키는 상품명이 바뀌면 중복을 놓쳐 2배 계상했다."""
    a = {L.FIELD: "smartstore|P1", "상품명": "원래 이름", "옵션": "M"}
    b = {L.FIELD: "smartstore|P1", "상품명": "바뀐 이름", "옵션": "M"}
    assert L.dedupe_key(a) == L.dedupe_key(b)


def test_다른_라인은_상품명이_같아도_안_합쳐진다():
    a = {L.FIELD: "coupang|B1|V1", "상품명": "같은 상품", "옵션": ""}
    b = {L.FIELD: "coupang|B1|V2", "상품명": "같은 상품", "옵션": ""}
    assert L.dedupe_key(a) != L.dedupe_key(b)


def test_uid_없는_행은_옛_방식으로_폴백한다():
    a = {"오픈마켓주문번호": "X", "상품명": "A", "옵션": "M"}
    assert L.dedupe_key(a) == ("legacy", "X", "A", "M")
    assert L.dedupe_key(a) == L.dedupe_key(dict(a))


def test_uid_있는_행과_없는_행은_절대_같은_키가_아니다():
    """폴백 키와 uid 키가 우연히 충돌하면 서로 다른 주문이 합쳐진다."""
    with_uid = {L.FIELD: "smartstore|P1", "오픈마켓주문번호": "P1", "상품명": "", "옵션": ""}
    without = {"오픈마켓주문번호": "P1", "상품명": "", "옵션": ""}
    assert L.dedupe_key(with_uid) != L.dedupe_key(without)


# ── 클레임 이벤트 키 ───────────────────────────────────────────
def test_같은_라인의_다른_클레임단계는_다른_이벤트다():
    base = {L.FIELD: "coupang|B1|V1", "_change_date": "2026-07-01"}
    req = L.claim_event_uid({**base, "주문상태원본": "UC"})
    done = L.claim_event_uid({**base, "주문상태원본": "CC"})
    assert req and done and req != done


def test_같은_클레임을_두번_조회하면_같은_이벤트키():
    row = {L.FIELD: "coupang|B1|V1", "_change_date": "2026-07-01", "주문상태원본": "UC"}
    assert L.claim_event_uid(row) == L.claim_event_uid(dict(row))


def test_식별할게_아무것도_없으면_이벤트키도_빈값():
    assert L.claim_event_uid({"_change_date": "2026-07-01"}) == ""


# ── 데이터 코드 지도 fields 로 확정된 정의 (2026-07-20) ──────────
def test_롯데온은_sitmNo가_없어도_키를_만든다():
    """지도 확인: odSeq = '주문순번(단품별)' = 상품라인 seq.
    따라서 (odNo, odSeq) 만으로 라인이 갈린다 — sitmNo 가 없다고 키를 포기하면
    그 행들이 전부 적재에서 빠진다."""
    row = {"_send_ids": {"od_no": "D1", "od_seq": "2"}}
    assert L.line_uid("lotteon", row) == "lotteon|D1|2"


def test_롯데온_클레임은_clmNo로_갈린다():
    """지도 확인: clmNo = '클레임번호'. 같은 라인의 취소·반품을 서로 구분한다."""
    a = {"_send_ids": {"od_no": "D1", "od_seq": "1", "clm_no": "C1"}}
    b = {"_send_ids": {"od_no": "D1", "od_seq": "1", "clm_no": "C2"}}
    assert L.line_uid("lotteon", a) != L.line_uid("lotteon", b)


def test_롯데온_odSeq가_비면_여전히_키를_안_만든다():
    """odSeq 는 라인을 가르는 축이라 이게 없으면 합쳐질 위험이 있다."""
    assert L.line_uid("lotteon", {"_send_ids": {"od_no": "D1", "od_seq": ""}}) == ""


def test_ESM_같은_결제의_다른_라인은_다른_키다():
    """지도 확인: PayNo = '대표 장바구니번호'(상위 묶음), OrderNo = 라인.
    한 결제(PayNo)에 OrderNo 가 여러 개이므로 OrderNo 로 갈라도 라인이 안 사라진다."""
    a = {"오픈마켓주문번호": "E1", "_payno": "P1"}
    b = {"오픈마켓주문번호": "E2", "_payno": "P1"}
    assert L.line_uid("auction", a) != L.line_uid("auction", b)
