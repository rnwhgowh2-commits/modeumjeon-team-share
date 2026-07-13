# -*- coding: utf-8 -*-
"""주문 엑셀 재사용 모듈 — Mock 단위테스트(스마트스토어 매핑·정산조인·xlsx·미지원마켓)."""
import datetime as dt

import pytest

from lemouton.markets import order_export as oe

KST = dt.timezone(dt.timedelta(hours=9))


class FakeSSClient:
    """SmartStoreClient 대역 — 엔드포인트별 응답 라우팅."""
    def request(self, method, path, query="", body=None):
        if "last-changed-statuses" in path:
            return {"data": {"lastChangeStatuses": [{"productOrderId": "P1"}]}}
        if path.endswith("/product-orders/query"):
            return {"data": [{
                "order": {"orderDate": "2026-07-05T09:00:00", "ordererName": "구매자A", "ordererTel": "01000000000"},
                "productOrder": {"productOrderId": "P1", "productName": "코트", "productOption": "블랙/95",
                                 "quantity": 1, "unitPrice": 189000,
                                 "shippingAddress": {"name": "수령자A", "tel1": "01011112222",
                                                     "zipCode": "13105", "baseAddress": "서울 어딘가", "detailedAddress": "101동"}},
            }]}
        if "pay-settle/settle/case" in path:
            return {"elements": [{"productOrderId": "P1", "settleExpectAmount": 169155}],
                    "pagination": {"totalPages": 1}}
        return {"data": {}}


def test_smartstore_rows_map_and_join(monkeypatch):
    since = dt.datetime(2026, 7, 5, tzinfo=KST)
    until = dt.datetime(2026, 7, 5, 23, tzinfo=KST)
    rows = oe.smartstore_order_rows(since, until, client=FakeSSClient())
    assert len(rows) == 1
    r = rows[0]
    assert r["상품명"] == "코트" and r["옵션"] == "블랙/95"
    assert r["수령자"] == "수령자A" and r["구매자"] == "구매자A"
    assert r["단가"] == 189000
    assert r["정산예정금액"] == 169155        # 정산 조인됨
    assert r["판매처"] == "스마트스토어"       # 판매처 열(B)


def test_ss_estimate_settle_formula():
    # 매출 × 0.94 (수수료 6%). 실결제금액 우선, 없으면 단가×수량, 둘 다 없으면 빈칸(폴백 0 금지).
    assert oe._ss_estimate_settle(90000, 100000, 1) == round(90000 * 0.94)   # 실결제 우선
    assert oe._ss_estimate_settle("", 50000, 2) == round(100000 * 0.94)      # 단가×수량 폴백
    assert oe._ss_estimate_settle("", "", 1) == ""                           # 근거 없음 → 빈칸


class FakeSSClientNoSettle:
    """정산 전(최근) 주문 대역 — settle/case 는 빈 응답(오늘 주문=정산 미확정)."""
    def request(self, method, path, query="", body=None):
        if "last-changed-statuses" in path:
            return {"data": {"lastChangeStatuses": [{"productOrderId": "P9"}]}}
        if path.endswith("/product-orders/query"):
            return {"data": [{
                "order": {"orderDate": "2026-07-05T09:00:00", "ordererName": "구매자", "ordererTel": "010"},
                "productOrder": {"productOrderId": "P9", "productName": "코트", "productOption": "블랙/95",
                                 "quantity": 1, "unitPrice": 100000, "totalPaymentAmount": 90000,
                                 "shippingAddress": {"name": "수령", "tel1": "010", "zipCode": "1",
                                                     "baseAddress": "서울", "detailedAddress": "1"}},
            }]}
        if "pay-settle/settle/case" in path:
            return {"elements": [], "pagination": {"totalPages": 1}}   # 정산 없음
        return {"data": {}}


def test_smartstore_estimates_settle_when_unsettled():
    # 정산 전 최근 주문 → 실결제금액 × 0.94 추정 + _settle_source='estimated'(실값과 구분).
    #  빈칸으로 두면 순마진=0-매입=손실로 둔갑(사용자 지적).
    since = dt.datetime(2026, 7, 5, tzinfo=KST)
    until = dt.datetime(2026, 7, 5, 23, tzinfo=KST)
    rows = oe.smartstore_order_rows(since, until, client=FakeSSClientNoSettle())
    assert len(rows) == 1
    r = rows[0]
    assert r["_settle_source"] == "estimated"
    assert r["정산예정금액"] == round(90000 * 0.94)     # 실결제 90000 × 0.94 = 84600


def test_smartstore_real_settle_wins_over_estimate():
    # 실정산 있으면 추정 대신 확정액 사용(_settle_source='real').
    since = dt.datetime(2026, 7, 5, tzinfo=KST)
    until = dt.datetime(2026, 7, 5, 23, tzinfo=KST)
    r = oe.smartstore_order_rows(since, until, client=FakeSSClient())[0]
    assert r["_settle_source"] == "real" and r["정산예정금액"] == 169155


def test_order_rows_rejects_unsupported():
    for mk in ("gmarket", "auction", "wemakeprice"):
        with pytest.raises(ValueError):
            oe.order_rows(mk, days=7)          # UI 미노출 마켓 — 추측 데이터 안 만듦


def test_order_rows_uses_explicit_range(monkeypatch):
    # since/until 명시 시 days 대신 그 기간을 그대로 빌더에 전달(빠른 기간 버튼·직접 날짜)
    cap = {}
    def fake_builder(since, until, client=None, include_settlement=True):
        cap["since"], cap["until"] = since, until
        return []
    monkeypatch.setitem(oe._BUILDERS, "smartstore", fake_builder)
    monkeypatch.setattr(oe, "_account_client", lambda m: object())
    s = dt.datetime(2026, 6, 1, tzinfo=KST)
    u = dt.datetime(2026, 6, 10, 23, 59, 59, tzinfo=KST)
    oe.order_rows("smartstore", days=7, since=s, until=u)
    assert cap["since"] == s and cap["until"] == u   # days=7 무시, 명시 기간 사용


def test_combined_range_in_cache_key(monkeypatch):
    # 기간이 다르면 캐시 키가 달라 각각 조회(같은 마켓이라도 섞이지 않음)
    oe.clear_cache()
    calls = []
    def fake(mk, days=7, now=None, since=None, until=None, **k):
        calls.append((since, until))
        return []
    monkeypatch.setattr(oe, "order_rows", fake)
    s1 = dt.datetime(2026, 6, 1, tzinfo=KST); u1 = dt.datetime(2026, 6, 2, tzinfo=KST)
    s2 = dt.datetime(2026, 6, 3, tzinfo=KST); u2 = dt.datetime(2026, 6, 4, tzinfo=KST)
    oe.combined_order_rows(["coupang"], use_cache=True, since=s1, until=u1)
    oe.combined_order_rows(["coupang"], use_cache=True, since=s1, until=u1)  # 캐시 히트
    oe.combined_order_rows(["coupang"], use_cache=True, since=s2, until=u2)  # 다른 기간→조회
    assert calls == [(s1, u1), (s2, u2)]
    oe.clear_cache()


def test_rows_to_xlsx_default_columns():
    xlsx = oe.rows_to_xlsx([{"판매처": "쿠팡", "상품명": "코트"}])
    assert xlsx[:2] == b"PK"                    # xlsx = zip
    import io, openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(xlsx)).active
    assert [(c.value or "") for c in ws[1]] == oe.DEFAULT_COLUMNS
    assert ws[1][1].value == "판매처" and ws[1][2].value == "주문상태"   # B열·C열
    assert ws[2][1].value == "쿠팡"             # 판매처 값


def test_rows_to_xlsx_custom_columns_order():
    cols = ["판매처", "주문상태", "상품명"]        # 사용자 지정 부분집합·순서
    xlsx = oe.rows_to_xlsx([{"판매처": "쿠팡", "주문상태": "결제완료", "상품명": "코트", "단가": 9}], columns=cols)
    import io, openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(xlsx)).active
    assert [c.value for c in ws[1]] == cols     # 지정 열만·순서대로
    assert [c.value for c in ws[2]] == ["쿠팡", "결제완료", "코트"]


def test_resolve_columns_filters_unknown():
    assert oe.resolve_columns(["상품명", "없는열", "판매처"]) == ["상품명", "판매처"]
    assert oe.resolve_columns([]) == oe.DEFAULT_COLUMNS
    assert oe.resolve_columns(None) == oe.DEFAULT_COLUMNS


def test_supported_markets():
    # 11번가는 서버 실호출 검증 완료(2026-07-08) → SUPPORTED 포함. 옥션·G마켓은 검증 후 추가.
    assert oe.SUPPORTED == {"smartstore", "lotteon", "coupang", "eleven11"}


def test_cp_estimate_settle_formula():
    # (단가×수량 + 배송비) × 0.8845
    assert oe._cp_estimate_settle(100000, 1, 3000) == round(103000 * 0.8845)
    assert oe._cp_estimate_settle(100000, 2, 0) == round(200000 * 0.8845)
    assert oe._cp_estimate_settle("", 1, 3000) == ""      # 단가 없으면 추정 안 함(폴백 금지)
    assert oe._cp_estimate_settle(None, 1, 0) == ""


def test_coupang_actual_wins_over_estimate():
    # 실 정산액이 있으면 추정 대신 확정액 사용
    class C:
        _cfg = {"vendor_id": "A1"}
        def request(self, method, path, query=""):
            if "ordersheets" in path and "nextToken" not in query:
                return {"data": [{"shipmentBoxId": 1, "orderId": 5, "status": "FINAL_DELIVERY",
                        "orderer": {}, "receiver": {}, "shippingPrice": {"units": 3000},
                        "orderItems": [{"vendorItemId": 9, "sellerProductName": "코트",
                                        "shippingCount": 1, "salesPrice": {"units": 100000}}]}], "nextToken": ""}
            if "revenue-history" in path:
                return {"data": [{"orderId": 5, "items": [{"vendorItemId": 9, "settlementAmount": 99999}]}], "hasNext": False}
            return {"data": [], "nextToken": ""}
    r = oe.coupang_order_rows(dt.datetime(2026,7,5,tzinfo=oe.KST), dt.datetime(2026,7,8,tzinfo=oe.KST), client=C())[0]
    assert r["정산예정금액"] == 99999            # 확정액 우선(추정 아님)


def test_coupang_settlement_join(monkeypatch):
    # 발주서 조회 → revenue-history 를 (주문번호,옵션ID)로 조인해 정산예정금액 채움
    class C:
        _cfg = {"vendor_id": "A00012345"}
        def request(self, method, path, query=""):
            if "ordersheets" in path:
                if "nextToken" in query:
                    return {"data": [], "nextToken": ""}
                return {"data": [{"shipmentBoxId": 1, "orderId": 777, "status": "FINAL_DELIVERY",
                        "orderer": {}, "receiver": {},
                        "orderItems": [{"vendorItemId": 9, "sellerProductName": "코트",
                                        "shippingCount": 1, "salesPrice": {"units": 189000}}]}],
                        "nextToken": ""}
            if "revenue-history" in path:
                return {"data": [{"orderId": 777, "items": [
                        {"vendorItemId": 9, "settlementAmount": 165155}]}], "hasNext": False}
            return {"data": []}
    since = dt.datetime(2026, 7, 5, tzinfo=oe.KST)
    until = dt.datetime(2026, 7, 8, tzinfo=oe.KST)
    rows = oe.coupang_order_rows(since, until, client=C())
    assert len(rows) == 1
    assert rows[0]["정산예정금액"] == 165155      # revenue-history 조인됨
    assert "_oid" not in rows[0] and "_vid" not in rows[0]   # 임시키 정리됨



def test_coupang_claims_merge():
    """returnRequests(취소/반품)+exchangeRequests(교환) 병합 (MCP 실측 스펙)."""
    class C:
        _cfg = {"vendor_id": "A1"}
        def request(self, method, path, query=""):
            if "ordersheets" in path:
                return {"data": [{"shipmentBoxId": 1, "orderId": 100, "status": "FINAL_DELIVERY",
                        "orderer": {}, "receiver": {}, "orderItems": [{"vendorItemId": 9,
                        "sellerProductName": "활성", "shippingCount": 1,
                        "salesPrice": {"units": 10000}}]}], "nextToken": ""}
            if "returnRequests" in path:
                return {"data": [{"receiptId": 501, "orderId": 200, "receiptType": "CANCEL",
                        "reasonCodeText": "변심", "requesterName": "홍길동",
                        "createdAt": "2026-07-06T10:00:00",
                        "returnItems": [{"sellerProductName": "취소상품", "vendorItemName": "옵A",
                                         "cancelCount": 1}]}]}
            if "exchangeRequests" in path:
                return {"data": [{"exchangeId": 601, "orderId": 300, "reasonCodeText": "불량",
                        "createdAt": "2026-07-06T11:00:00",
                        "exchangeItemDtoV1s": [{"orderItemName": "교환상품", "quantity": 2,
                                                "orderItemUnitPrice": 7000}]}]}
            if "revenue-history" in path:
                return {"data": [], "hasNext": False}
            return {"data": [], "nextToken": ""}
    rows = oe.coupang_order_rows(dt.datetime(2026, 7, 5, tzinfo=oe.KST),
                                 dt.datetime(2026, 7, 8, tzinfo=oe.KST), client=C())
    st = {r["주문상태"] for r in rows}
    # 주문상태 통일(2026-07-10): 접수 단계는 '취소요청·교환요청'(완료와 구분). 옛 '취소·교환' 아님.
    assert {"취소요청", "교환요청"} <= st
    # 행 중복 없음 — 주문1 + 취소1 + 교환1. 중복 시 주문 건수·정산 합계가 부풀려짐(CLAUDE.md).
    assert len(rows) == 3
    cx = [r for r in rows if r["주문상태"] == "취소요청"][0]
    assert cx["오픈마켓주문번호"] == "200" and cx["상품명"] == "취소상품" and cx["수량"] == 1
    ex = [r for r in rows if r["주문상태"] == "교환요청"][0]
    assert ex["오픈마켓주문번호"] == "300" and ex["수량"] == 2


def test_columns_bc_are_market_and_status():
    assert oe.ALL_COLUMNS[0] == "주문일"
    assert oe.ALL_COLUMNS[1] == "판매처"      # 요청: B열 판매처
    assert oe.ALL_COLUMNS[2] == "주문상태"    # 요청: C열 주문상태


def test_amount_columns_order():
    i = oe.ALL_COLUMNS.index("단가")
    assert oe.ALL_COLUMNS[i + 1] == "배송비"       # 단가 다음 = 배송비
    assert oe.ALL_COLUMNS[i + 2] == "상품금액"     # 단가×수량
    assert oe.ALL_COLUMNS[i + 3] == "주문금액"     # 상품금액+배송비
    assert oe.ALL_COLUMNS[i + 4] == "정산예정금액"


def test_column_meta_marks_calc_vs_api():
    m = oe.columns_meta()
    assert m["상품금액"]["kind"] == "calc" and "단가" in m["상품금액"]["desc"]
    assert m["주문금액"]["kind"] == "calc"
    assert m["정산예정금액"]["kind"] == "calc"
    assert m["단가"]["kind"] == "api"                    # 마켓 원본
    assert oe.column_meta("없는열")["kind"] == "api"      # 미등록=원본 기본
    assert set(m) == set(oe.ALL_COLUMNS)                 # 전 열 메타 보유


def test_finalize_amounts_and_shipping_dedup():
    rows = [
        {"_shipkey": ("cp", "O1"), "단가": 10000, "수량": 2, "배송비": 3000},
        {"_shipkey": ("cp", "O1"), "단가": 5000, "수량": 1, "배송비": 3000},    # 같은 배송건 → 배송비 0
        {"_shipkey": ("cp", "O2"), "단가": 7000, "수량": 1, "배송비": "0.00"},
    ]
    out = oe._finalize_rows(rows)
    assert out[0]["상품금액"] == 20000 and out[0]["배송비"] == 3000 and out[0]["주문금액"] == 23000
    assert out[1]["상품금액"] == 5000 and out[1]["배송비"] == 0 and out[1]["주문금액"] == 5000
    assert out[2]["상품금액"] == 7000 and out[2]["배송비"] == 0 and out[2]["주문금액"] == 7000
    assert "_shipkey" not in out[0]                # 임시키 정리


def test_coupang_settle_includes_delivery():
    # 실제 정산 = 상품 settlementAmount + 배송비 deliveryFee.settlementAmount
    class C:
        _cfg = {"vendor_id": "A1"}
        def request(self, method, path, query=""):
            if "ordersheets" in path and "nextToken" not in query:
                return {"data": [{"shipmentBoxId": 1, "orderId": 5, "status": "FINAL_DELIVERY",
                        "orderer": {}, "receiver": {}, "shippingPrice": {"units": 3000},
                        "orderItems": [{"vendorItemId": 9, "sellerProductName": "코트",
                                        "shippingCount": 1, "salesPrice": {"units": 100000}}]}], "nextToken": ""}
            if "revenue-history" in path:
                return {"data": [{"orderId": 5, "deliveryFee": {"settlementAmount": 2900},
                        "items": [{"vendorItemId": 9, "settlementAmount": 88450}]}], "hasNext": False}
            return {"data": [], "nextToken": ""}
    r = oe.coupang_order_rows(dt.datetime(2026, 7, 5, tzinfo=oe.KST),
                              dt.datetime(2026, 7, 8, tzinfo=oe.KST), client=C())[0]
    assert r["배송비"] == 3000
    assert r["정산예정금액"] == 88450 + 2900       # 상품정산 + 배송비정산


def test_coupang_estimate_shipping_fee_3pct():
    # 미정산 추정: 상품 11.55%(0.8845) + 배송비 3%(0.97). 배송비 있는 주문.
    class C:
        _cfg = {"vendor_id": "A1"}
        def request(self, method, path, query=""):
            if "ordersheets" in path and "nextToken" not in query:
                return {"data": [{"shipmentBoxId": 1, "orderId": 5, "status": "ACCEPT",
                        "orderer": {}, "receiver": {}, "shippingPrice": {"units": 3000},
                        "orderItems": [{"vendorItemId": 9, "sellerProductName": "코트",
                                        "shippingCount": 1, "salesPrice": {"units": 100000}}]}], "nextToken": ""}
            return {"data": [], "nextToken": "", "hasNext": False}   # 미정산(revenue 빈값)
    r = oe.coupang_order_rows(dt.datetime(2026, 7, 5, tzinfo=oe.KST),
                              dt.datetime(2026, 7, 8, tzinfo=oe.KST), client=C())[0]
    assert r["배송비"] == 3000
    assert r["정산예정금액"] == round(100000 * 0.8845) + round(3000 * 0.97)   # 상품 + 배송비(3%)
    assert oe.CP_SHIP_FEE_FACTOR == 0.97


def test_smartstore_settle_maps_splits_delivery():
    from shared.platforms.smartstore import settlements as ss
    class C:
        def request(self, method, path, query="", body=None):
            return {"elements": [
                {"productOrderType": "PROD_ORDER", "productOrderId": "P1", "orderId": "O1", "settleExpectAmount": 10000},
                {"productOrderType": "DELIVERY", "productOrderId": "SHIP1", "orderId": "O1", "settleExpectAmount": 2500},
            ], "pagination": {"totalPages": 1}}
    prod, deliv = ss.settle_expect_maps(search_date="2026-07-01", client=C())
    assert prod == {"P1": 10000}                  # 상품 정산 = 상품주문번호별
    assert deliv == {"O1": 2500}                  # 배송비 정산 = 주문번호별


def test_combined_rows_sorted_desc(monkeypatch):
    # 두 마켓 행을 합쳐 주문일 내림차순 정렬
    monkeypatch.setattr(oe, "order_rows", lambda mk, days=7, **k: {
        "coupang": [{"주문일": "2026-07-01", "판매처": "쿠팡"}],
        "lotteon": [{"주문일": "2026-07-05", "판매처": "롯데온"}],
    }[mk])
    out = oe.combined_order_rows(["coupang", "lotteon"], days=7)
    assert [r["주문일"] for r in out] == ["2026-07-05", "2026-07-01"]   # 최신 먼저


def test_combined_filters_by_order_date(monkeypatch):
    # 기간(since/until) 명시 시 주문일이 범위 밖인 행은 제외(기간=주문일 통일).
    monkeypatch.setattr(oe, "order_rows", lambda mk, **k: [
        {"주문일": "2026-07-03 10:00:00", "판매처": "11번가"},   # 범위 안
        {"주문일": "2026-06-28 20:22:54", "판매처": "11번가"},   # 범위 밖(구매확정만 오늘)
        {"주문일": "값없음", "판매처": "11번가"},                 # 파싱 실패 → 남김
    ])
    since = dt.datetime(2026, 7, 1, tzinfo=KST)
    until = dt.datetime(2026, 7, 5, 23, 59, tzinfo=KST)
    out = oe.combined_order_rows(["eleven11"], since=since, until=until)
    days = [r["주문일"] for r in out]
    assert "2026-07-03 10:00:00" in days          # 주문일 범위 안 → 포함
    assert "2026-06-28 20:22:54" not in days       # 주문일 범위 밖 → 제외
    assert "값없음" in days                          # 파싱 실패 → 데이터 손실 방지 위해 남김


def test_combined_parallel_error_propagates(monkeypatch):
    # 한 마켓이 실패하면 전체 실패로 전파(부분 성공 숨김 금지) — warnings 채널 없음(엑셀)
    def _fake(mk, days=7, **k):
        if mk == "coupang":
            raise RuntimeError("쿠팡 인증 실패")
        return [{"주문일": "2026-07-05", "판매처": "롯데온"}]
    monkeypatch.setattr(oe, "order_rows", _fake)
    with pytest.raises(RuntimeError):
        oe.combined_order_rows(["coupang", "lotteon"], days=7)


def test_smartstore_never_queries_future_dates(monkeypatch):
    """기간추론(+3일 마진)이 period_to 를 미래로 만들면(예: 오늘 07-13, until 07-15),
    naver last-changed API 가 HTTP 400 [104139] '조회 가능한 날짜 범위를 초과'로 거절 →
    스마트스토어 매출 통째 누락 → 마진 마이너스(라이브 실측 id2). until 을 now 로 캡한다."""
    import shared.platforms.smartstore.orders as _sso
    cap = {}
    def fake_iter(since, until, client=None, **k):
        cap["since"], cap["until"] = since, until
        return []                                   # 상세·정산 경로 안 타게 빈 목록
    monkeypatch.setattr(_sso, "iter_changed_product_order_ids", fake_iter)
    now = dt.datetime.now(oe.KST)
    future_until = now + dt.timedelta(days=2)        # 미래 period_to (기간추론 마진)
    since = now - dt.timedelta(days=11)
    oe.smartstore_order_rows(since, future_until, client=object(),
                             include_settlement=False)
    # 조회 끝(lastChangedTo)이 미래로 나가면 안 됨 — now 이하로 캡
    assert cap["until"] <= now + dt.timedelta(seconds=2)


def test_order_rows_coerces_naive_dates_to_aware(monkeypatch):
    """라이브 마진 경로는 naive since/until(_parse_dt)을 넘긴다. 빌더(smartstore 등)가
    now=datetime.now(KST)(aware)와 비교하므로 naive 면 'offset-naive vs offset-aware' TypeError 로
    그 마켓 조회가 통째 실패한다 → 스마트스토어 제외 → 매출 누락·마진 마이너스(라이브 실측).
    order_rows 가 KST-aware 로 강제해 어느 호출부가 넘겨도 안전하게 한다."""
    cap = {}
    def fake_builder(since, until, client=None, include_settlement=True):
        cap["since"], cap["until"] = since, until
        return []
    monkeypatch.setitem(oe._BUILDERS, "smartstore", fake_builder)
    oe.order_rows("smartstore", client=object(),
                  since=dt.datetime(2026, 7, 2), until=dt.datetime(2026, 7, 15))
    assert cap["since"].tzinfo is not None and cap["until"].tzinfo is not None  # aware 로 강제
    # 이미 aware 면 시각 이동 없이 그대로
    cap.clear()
    aware_s = dt.datetime(2026, 7, 2, tzinfo=oe.KST)
    aware_u = dt.datetime(2026, 7, 15, tzinfo=oe.KST)
    oe.order_rows("smartstore", client=object(), since=aware_s, until=aware_u)
    assert cap["since"] == aware_s and cap["until"] == aware_u


def test_coupang_claims_iso_formats_differ_by_endpoint():
    """서버 프로브 실측: returnRequests 는 'yyyy-MM-ddTHH:mm'(초 금지),
    exchangeRequests 는 'yyyy-MM-ddTHH:mm:ss'(초 필수). 틀리면 HTTP 400 전체 실패."""
    import shared.platforms.coupang.claims as _cc
    t = dt.datetime(2026, 7, 3, 9, 5, 30)
    assert _cc._iso_min(t) == "2026-07-03T09:05"      # returnRequests: 초 없음
    assert _cc._iso(t) == "2026-07-03T09:05:30"       # exchangeRequests: 초 있음


def test_coupang_claim_window_extends_to_now(monkeypatch):
    """쿠팡 취소/반품/교환은 '클레임 생성일' 기준 조회 → 기간 안 주문이 나중에 취소되면
    [since,until] 밖이라 통째 누락(라이브: 62건). 조회 끝을 now 로 넓혀야 잡힌다."""
    import shared.platforms.coupang.orders as _co
    import shared.platforms.coupang.claims as _cc
    monkeypatch.setattr(_co, "fetch_orders", lambda *a, **k: {"data": [], "nextToken": ""})
    monkeypatch.setattr(oe, "_coupang_settle_map", lambda *a, **k: ({}, {}))
    cap = {}
    monkeypatch.setattr(_cc, "iter_returns",
                        lambda s, u, client=None: cap.__setitem__("ret", u) or iter([]))
    monkeypatch.setattr(_cc, "iter_exchanges",
                        lambda s, u, client=None: cap.__setitem__("exc", u) or iter([]))
    now = dt.datetime.now(oe.KST)
    oe.coupang_order_rows(dt.datetime(2026, 7, 3, tzinfo=oe.KST),
                          dt.datetime(2026, 7, 5, tzinfo=oe.KST), client=object())
    assert cap["ret"] >= now - dt.timedelta(seconds=5)   # 과거 until 이 아니라 now 로 확장
    assert cap["exc"] >= now - dt.timedelta(seconds=5)


def test_lotteon_delivery_window_extends_to_now(monkeypatch):
    """롯데온 출고지시(209)는 '배송지시생성일시' 기준 → 기간 안 주문이 나중에 배송지시되면
    [since,until] 밖이라 누락(라이브: 07-12 신규주문 6건). 조회 끝을 now 로 넓혀야 잡힌다."""
    import shared.platforms.lotteon.orders as _lo
    import shared.platforms.lotteon.claims as _lc
    monkeypatch.setattr(_lc, "commission_map", lambda *a, **k: {})
    for nm in ("iter_cancel", "iter_return", "iter_exchange"):
        monkeypatch.setattr(_lc, nm, lambda *a, **k: iter([]))
    cap = {}
    monkeypatch.setattr(_lo, "iter_delivery_orders",
                        lambda s, u, **k: cap.__setitem__("until", u) or iter([]))
    now = dt.datetime.now(oe.KST)
    oe.lotteon_order_rows(dt.datetime(2026, 7, 3, tzinfo=oe.KST),
                          dt.datetime(2026, 7, 5, tzinfo=oe.KST), client=object())
    assert cap["until"] >= now - dt.timedelta(seconds=5)   # 과거 until 이 아니라 now 로 확장


def test_lotteon_claim_window_extends_to_now(monkeypatch):
    """롯데온 클레임도 접수일 기준 → 기간 밖 취소 누락(라이브: 4건). 조회 끝을 now 로 넓힌다."""
    import shared.platforms.lotteon.orders as _lo
    import shared.platforms.lotteon.claims as _lc
    monkeypatch.setattr(_lo, "iter_delivery_orders", lambda *a, **k: iter([]))
    monkeypatch.setattr(_lc, "commission_map", lambda *a, **k: {})
    cap = {}
    for nm in ("iter_cancel", "iter_return", "iter_exchange"):
        monkeypatch.setattr(_lc, nm,
                            (lambda name: (lambda s, u, client=None:
                                           cap.__setitem__(name, u) or iter([])))(nm))
    now = dt.datetime.now(oe.KST)
    oe.lotteon_order_rows(dt.datetime(2026, 7, 3, tzinfo=oe.KST),
                          dt.datetime(2026, 7, 5, tzinfo=oe.KST), client=object())
    assert cap["iter_cancel"] >= now - dt.timedelta(seconds=5)
    assert cap["iter_return"] >= now - dt.timedelta(seconds=5)


def test_combined_partial_failure_warns_and_proceeds_with_warnings(monkeypatch):
    # ★ warnings 채널이 있으면(화면·마진 분석) 한 마켓이 통째로 실패해도 502 로 죽지 않고
    #   그 마켓을 '제외'로 표면화(warnings)한 뒤 나머지 마켓 결과를 반환한다.
    def _fake(mk, days=7, **k):
        if mk == "coupang":
            raise RuntimeError("쿠팡 인증 실패")
        return [{"주문일": "2026-07-05", "판매처": "롯데온"}]
    monkeypatch.setattr(oe, "order_rows", _fake)
    warns: list = []
    out = oe.combined_order_rows(["coupang", "lotteon"], days=7, warnings=warns)
    assert [r["판매처"] for r in out] == ["롯데온"]      # 성공 마켓 결과는 유지
    assert any("쿠팡" in w for w in warns)               # 실패 마켓은 제외 배너로 표면화
    assert any("제외" in w for w in warns)


def test_combined_all_markets_fail_raises_even_with_warnings(monkeypatch):
    # 전부 실패면 보여줄 게 없으므로 warnings 유무와 무관하게 전파(거짓 빈결과 금지).
    def _fake(mk, days=7, **k):
        raise RuntimeError(f"{mk} 실패")
    monkeypatch.setattr(oe, "order_rows", _fake)
    with pytest.raises(RuntimeError):
        oe.combined_order_rows(["coupang", "lotteon"], days=7, warnings=[])


def test_order_rows_no_credentials_warns_and_excludes(monkeypatch):
    # ★ 계정이 하나도 연동 안 된 마켓 — warnings 있으면 'API 연동 없음'으로 표면화 + 빈 결과
    #   (raise 하지 않음 → 다른 마켓 분석은 계속). warnings 없으면(엑셀) 전파.
    monkeypatch.setattr(oe, "_active_accounts", lambda m: [])
    monkeypatch.setattr(oe, "_account_client", lambda m, prefix=None: None)
    warns: list = []
    out = oe.order_rows("coupang", days=7, warnings=warns)
    assert out == []
    assert any("연동" in w for w in warns)
    # warnings 없이(엑셀 다운로드) 호출하면 조용한 빈 파일 대신 전파
    with pytest.raises(Exception):
        oe.order_rows("coupang", days=7)


def test_combined_cache_reuses_fetch(monkeypatch):
    # use_cache=True: 같은 (마켓,기간) 두 번째 호출은 실조회 없이 캐시 재사용(다운로드 즉시)
    oe.clear_cache()
    calls = {"n": 0}
    def _fake(mk, days=7, **k):
        calls["n"] += 1
        return [{"주문일": "2026-07-05", "판매처": "쿠팡"}]
    monkeypatch.setattr(oe, "order_rows", _fake)
    a = oe.combined_order_rows(["coupang"], days=7, use_cache=True)
    b = oe.combined_order_rows(["coupang"], days=7, use_cache=True)
    assert calls["n"] == 1          # 두 번째는 캐시 히트 → order_rows 재호출 없음
    assert a is b                   # 같은 결과 객체 재사용
    oe.clear_cache()


def test_combined_no_cache_by_default(monkeypatch):
    # 기본(use_cache=False): 매번 실조회(직접 호출·테스트 결정성 유지)
    oe.clear_cache()
    calls = {"n": 0}
    def _fake(mk, days=7, **k):
        calls["n"] += 1
        return []
    monkeypatch.setattr(oe, "order_rows", _fake)
    oe.combined_order_rows(["coupang"], days=7)
    oe.combined_order_rows(["coupang"], days=7)
    assert calls["n"] == 2          # 캐시 미사용 → 매번 조회


def test_status_ko_mapping():
    assert oe._status_ko("coupang", "INSTRUCT") == "상품준비중"
    assert oe._status_ko("smartstore", "DELIVERED") == "배송완료"
    assert oe._status_ko("lotteon", "11") == "출고지시"
    assert oe._status_ko("coupang", "UNKNOWN_X") == "UNKNOWN_X"   # 미매핑=원값(추측금지)
    assert oe._status_ko("coupang", None) == ""


class FakeCoupangClient:
    def __init__(self):
        self.calls = 0
        self._cfg = {"vendor_id": "A00012345"}   # 계정 클라이언트가 주입하는 vendor_id
        self.paths = []

    def request(self, method, path, query=""):
        self.calls += 1
        self.paths.append(path)
        # 첫 status 첫 페이지에만 1건, 나머지는 빈 목록(nextToken 없음)
        if self.calls == 1:
            return {"code": 200, "data": [{
                "shipmentBoxId": 1, "orderedAt": "2026-07-05T09:00:00+09:00",
                "parcelPrintMessage": "문앞",
                "orderer": {"name": "구매자A", "ordererNumber": "01000000000"},
                "receiver": {"name": "수령자A", "receiverNumber": "01011112222",
                             "addr1": "서울", "addr2": "101동", "postCode": "04315"},
                "orderItems": [{"vendorItemId": 9, "sellerProductName": "코트",
                                "sellerProductItemName": "블랙/95", "shippingCount": 1,
                                "salesPrice": {"units": 189000, "nanos": 0}}]}],
                "nextToken": ""}
        return {"code": 200, "data": [], "nextToken": ""}


def test_coupang_rows_flatten_and_map(monkeypatch):
    # 전역 COUPANG_VENDOR_ID 없어도 계정 클라이언트 _cfg.vendor_id 로 동작해야 함(버그수정)
    monkeypatch.delenv("COUPANG_VENDOR_ID", raising=False)
    since = dt.datetime(2026, 7, 5, tzinfo=oe.KST)
    until = dt.datetime(2026, 7, 6, tzinfo=oe.KST)
    fc = FakeCoupangClient()
    rows = oe.coupang_order_rows(since, until, client=fc)
    assert len(rows) == 1
    r = rows[0]
    assert r["상품명"] == "코트" and r["옵션"] == "블랙/95" and r["수량"] == 1
    assert r["수령자"] == "수령자A" and r["구매자"] == "구매자A"
    assert r["단가"] == 189000                 # 금액 객체 units 추출
    # 실 정산 없음 → 추정 = round(189000 × 0.8845) = 167170 (배송비 0)
    assert r["정산예정금액"] == round(189000 * oe.CP_FEE_FACTOR)
    assert r["쇼핑몰"] == "쿠팡"
    assert "/vendors/A00012345/ordersheets" in fc.paths[0]   # 클라 config vendor_id 사용
    assert "/api/v5/" in fc.paths[0]           # v5 정정 반영


class FakeLotteonClient:
    def request(self, method, path, body=None):
        # 실제 209 처럼: 배송지시일시(20260705120000)를 포함하는 하루창에서만 1회 반환.
        #  (창을 now 로 넓혀 여러 날 순회해도 주문은 자기 날짜 창에서만 나옴 = 중복 없음)
        if "SellerDeliveryOrdersSearch" in path:
            b = body or {}
            s, e = str(b.get("srchStrtDt", "")), str(b.get("srchEndDt", ""))
            if not (s <= "20260705120000" <= e):
                return {"returnCode": "0000", "data": {"deliveryOrderList": []}}
            return {"returnCode": "0000", "data": {"deliveryOrderList": [{
                "odCmptDttm": "20260705120000", "spdNm": "코트", "sitmNm": "블랙/95",
                "odQty": 1, "slPrc": 189000, "actualAmt": 170000,
                "dvpCustNm": "수령자A", "dvpMphnNo": "01011112222", "odrNm": "구매자A",
                "dvpZipNo": "04315", "dvpStnmZipAddr": "서울 어딘가", "dvpStnmDtlAddr": "101동",
                "dvMsg": "문앞", "mphnNo": "01000000000"}]}}
        return {"returnCode": "0000", "data": {}}


def test_lotteon_rows_map_from_delivery_orders():
    since = dt.datetime(2026, 7, 5, tzinfo=oe.KST)
    until = dt.datetime(2026, 7, 6, tzinfo=oe.KST)
    rows = oe.lotteon_order_rows(since, until, client=FakeLotteonClient())
    assert len(rows) == 1
    r = rows[0]
    # 빌더는 원본(odCmptDttm) 방출 → _finalize/order_rows 에서 'YYYY-MM-DD HH:MM:SS' 통일.
    assert r["주문일"] == "20260705120000" and r["상품명"] == "코트" and r["옵션"] == "블랙/95"
    assert r["수령자"] == "수령자A" and r["구매자"] == "구매자A"
    assert r["단가"] == 189000 and r["정산예정금액"] == 170000
    assert r["판매처"] == "롯데온"


def test_lotteon_unescapes_html_entities():
    class C:
        def request(self, method, path, body=None):
            return {"data": {"deliveryOrderList": [{
                "odCmptDttm": "20260705", "spdNm": "&lt;매장정품&gt; 코트",
                "sitmNm": "R&amp;B / 100", "odQty": 1}]}}
    r = oe.lotteon_order_rows(dt.datetime(2026, 7, 5, tzinfo=oe.KST),
                              dt.datetime(2026, 7, 6, tzinfo=oe.KST), client=C())[0]
    assert r["상품명"] == "<매장정품> 코트"        # &lt; &gt; 해제
    assert r["옵션"] == "R&B / 100"                # &amp; 해제


def test_norm_order_dt_formats():
    # 마켓별 주문일 형식 → 'YYYY-MM-DD HH:MM:SS' 통일(시간 표시·정렬용)
    assert oe._norm_order_dt("2026-07-08 20:22:54") == "2026-07-08 20:22:54"   # 11번가
    assert oe._norm_order_dt("2026-07-05T09:00:00+09:00") == "2026-07-05 09:00:00"  # ISO(쿠팡·스스·ESM)
    assert oe._norm_order_dt("20260705093012") == "2026-07-05 09:30:12"         # 롯데온 14자리
    assert oe._norm_order_dt("20260705") == "2026-07-05"                        # 날짜만
    assert oe._norm_order_dt("2026-07-05") == "2026-07-05"                      # 시간 없으면 날짜만
    assert oe._norm_order_dt("") == ""


def test_finalize_normalizes_order_datetime():
    rows = oe._finalize_rows([{"주문일": "20260708202254", "단가": 1000, "수량": 1}])
    assert rows[0]["주문일"] == "2026-07-08 20:22:54"       # 시간 포함 통일


def test_lotteon_ready_in_builders_and_supported():
    assert "lotteon" in oe._BUILDERS and "lotteon" in oe.SUPPORTED   # 코드+UI 노출
    assert oe._ENV_PREFIX["lotteon"] == "LOTTEON_MAIN"               # 실키 로드용 prefix
