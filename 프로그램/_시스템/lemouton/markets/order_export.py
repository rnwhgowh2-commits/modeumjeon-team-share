# -*- coding: utf-8 -*-
"""판매처 주문 → 발송관리 엑셀(샵마인 형식) 재사용 모듈.

책임: 마켓 주문 조회 + 정산예정금액 조인 → 16컬럼 행 → xlsx 바이트.
현재 스마트스토어만 실배선(주문+정산 코드·실계정 검증 완료 2026-07-07).
쿠팡=키/검증 후, 롯데온=주문 API 신규 후. 추측·폴백 금지(CLAUDE.md).
서버(등록 IP)에서 실행. 인증·rate limit 은 각 플랫폼 client 담당.
"""
from __future__ import annotations

import datetime as _dt
import io
from typing import Optional

KST = _dt.timezone(_dt.timedelta(hours=9))

# 선택·순서 조정 가능한 전체 열(사용자 요청: B=판매처, C=주문상태). 기본 순서 = 이 목록.
ALL_COLUMNS = ["주문일", "판매처", "주문상태", "상품명", "옵션", "수량",
               "수령자", "수령자전화번호", "주소", "우편번호", "배송메시지",
               "구매자", "구매자번호", "단가", "배송비", "상품금액", "주문금액",
               "정산예정금액",
               # 샵마인 대조로 추가(2026-07-08) — 판매처관리 계정명·주문번호·수수료·송장 등.
               "오픈마켓주문번호", "쇼핑몰별칭", "송장입력", "실결제금액",
               "총주문금액", "옵션추가금", "마켓수수료", "수수료율", "정산예정금(배송비포함)"]
# 상품금액 = 단가×수량 / 주문금액 = 상품금액 + 배송비(배송건당 1회) / 정산예정금액 = 상품정산+배송비정산.
# 배송비는 배송건(묶음) 단위 → 배송건 첫 행에만 표시(나머지 0, 합계 중복 방지).
# 정산예정금액 = 상품 정산 + 배송비 정산(각자 수수료 차감). 배송비는 별도 정산 라인
# (쿠팡 deliveryFee.settlementAmount·스스 DELIVERY행·롯데온 실결제 포함).
DEFAULT_COLUMNS = list(ALL_COLUMNS)
HEADER = DEFAULT_COLUMNS   # 하위호환 별칭

# 열 구분자(메타): kind=calc(우리가 별도 계산) / api(마켓 원본). desc=계산식·출처.
# 양식 설정에서 열마다 이 구분자를 보여줘 추가/삭제/순서변경을 명확히 한다.
COLUMN_META = {
    "주문상태":     {"kind": "api",  "desc": "마켓 상태코드→한글"},
    "단가":         {"kind": "api",  "desc": "상품 개당가"},
    "배송비":       {"kind": "api",  "desc": "배송건(묶음) 배송비"},
    "상품금액":     {"kind": "calc", "desc": "단가 × 수량"},
    "주문금액":     {"kind": "calc", "desc": "상품금액 + 배송비"},
    "정산예정금액": {"kind": "calc", "desc": "상품정산 + 배송비정산(수수료 차감)"},
    "오픈마켓주문번호": {"kind": "api",  "desc": "마켓 주문번호(ordNo·odNo·orderId 등)"},
    "쇼핑몰별칭":   {"kind": "calc", "desc": "판매처관리 계정명(별칭)"},
    "송장입력":     {"kind": "api",  "desc": "송장번호(없으면 '송장미입력')"},
    "실결제금액":   {"kind": "api",  "desc": "고객 실결제(할인 반영). 없으면 총주문금액"},
    "총주문금액":   {"kind": "calc", "desc": "단가×수량 + 옵션추가금"},
    "옵션추가금":   {"kind": "api",  "desc": "옵션 추가금(마켓 제공 시)"},
    "마켓수수료":   {"kind": "calc", "desc": "실결제 − 정산예정금액(둘 다 있을 때)"},
    "수수료율":     {"kind": "calc", "desc": "마켓수수료 ÷ 총주문금액"},
    "정산예정금(배송비포함)": {"kind": "calc", "desc": "정산예정금액 + 고객배송비"},
}


def column_meta(col: str) -> dict:
    """열의 구분자(kind·desc). 미등록은 마켓 원본으로 간주."""
    return COLUMN_META.get(col, {"kind": "api", "desc": "마켓 원본"})


def columns_meta() -> dict:
    """전체 열 → 구분자 매핑(양식 설정 UI 표시용)."""
    return {c: column_meta(c) for c in ALL_COLUMNS}

# 마켓별 원시 상태코드 → 한글. 미매핑은 원값 그대로(추측 금지).
_STATUS_KO = {
    "smartstore": {"PAYMENT_WAITING": "결제대기", "PAYED": "결제완료", "DELIVERING": "배송중",
                   "DELIVERED": "배송완료", "PURCHASE_DECIDED": "구매확정",
                   "CANCELED": "취소", "RETURNED": "반품", "EXCHANGED": "교환"},
    "coupang": {"ACCEPT": "결제완료", "INSTRUCT": "상품준비중", "DEPARTURE": "배송지시",
                "DELIVERING": "배송중", "FINAL_DELIVERY": "배송완료",
                "NONE_TRACKING": "업체직접배송"},
    "lotteon": {"11": "출고지시", "23": "회수지시"},
    # 옥션·G마켓(ESM 2.0) 공통 — orderStatus 1~5.
    "esm": {"1": "결제완료", "2": "배송준비중", "3": "배송중",
            "4": "배송완료", "5": "구매결정"},
}


def _status_ko(market, raw):
    if raw in (None, ""):
        return ""
    return _STATUS_KO.get(market, {}).get(str(raw), str(raw))

SUPPORTED = {"smartstore", "lotteon", "coupang", "eleven11"}   # UI 엑셀버튼 노출. 실키=서버 UI저장.
# 11번가 = 서버 실호출 검증 완료(2026-07-08): 주문(complete)+정산예정금액(stlPlnAmt) 실응답 확인.
# 옥션·G마켓(auction·gmarket)은 키 입력+실호출 검증 후 추가.
# 마켓 → 계정 시크릿 env_prefix(판매처 계정 기본). load_credentials 로 실키 로드.
_ENV_PREFIX = {"smartstore": "SMARTSTORE_MAIN", "coupang": "COUPANG_MAIN",
               "lotteon": "LOTTEON_MAIN",
               "auction": "AUCTION_MAIN", "gmarket": "GMARKET_MAIN",
               "eleven11": "ELEVEN11_MAIN"}


def _g(o, *keys, default=""):
    """중첩 dict 후보 키 탐색(값 있으면 반환)."""
    for k in keys:
        cur, ok = o, True
        for p in k.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return default


def smartstore_order_rows(since: _dt.datetime, until: _dt.datetime,
                          client=None) -> list:
    """스마트스토어 [since,until] 주문 → 16컬럼 행(dict) 리스트.

    변경 상품주문 내역 조회(정식 코드) → 상세 → 정산예정금액(결제일 기준) 조인.
    정산 없는 주문은 빈칸(폴백 0 금지).
    """
    from shared.platforms.smartstore.orders import (
        iter_changed_product_order_ids, fetch_order_detail)
    from shared.platforms.smartstore import settlements as _settle
    from shared.platforms.smartstore.client import SmartStoreClient

    client = client or SmartStoreClient()

    ids = iter_changed_product_order_ids(since, until, client=client)
    detail = []
    for i in range(0, len(ids), 300):
        d = fetch_order_detail(ids[i:i + 300], client=client)
        detail += (d.get("data", d) if isinstance(d, dict) else d) or []

    # 정산(결제일 기준, 하루씩): 상품(productOrderId) + 배송비(DELIVERY→orderId) 별도 맵.
    prod_settle, deliv_settle = {}, {}
    day = since
    while day <= until:
        try:
            p, d = _settle.settle_expect_maps(
                search_date=day.strftime("%Y-%m-%d"),
                period_type="SETTLE_CASEBYCASE_PAY_DATE", client=client)
            prod_settle.update(p)
            for k, v in d.items():
                deliv_settle[k] = deliv_settle.get(k, 0) + v
        except Exception:
            pass
        day += _dt.timedelta(days=1)

    rows = []
    _deliv_used = set()   # 배송비 정산은 주문당 1회만 더함
    for it in detail:
        po = it.get("productOrder", {}) if isinstance(it, dict) else {}
        od = it.get("order", {}) if isinstance(it, dict) else {}
        sa = po.get("shippingAddress", {}) if isinstance(po, dict) else {}
        poid = _g(po, "productOrderId")
        oid = _g(od, "orderId")
        prod_amt = prod_settle.get(poid)
        settle_val = ""
        if prod_amt is not None:                       # 상품 정산 있으면 = 상품정산 + 배송비정산(1회)
            settle_val = prod_amt
            if oid and oid not in _deliv_used and oid in deliv_settle:
                settle_val += deliv_settle[oid]
                _deliv_used.add(oid)
        rows.append({
            "_shipkey": ("smartstore", oid),   # 배송건(주문) 단위 배송비 정규화용
            "주문일": _g(od, "orderDate", "paymentDate"),   # 시간 포함(_finalize 에서 통일)
            "판매처": "스마트스토어",
            "상품명": _g(po, "productName"),
            "옵션": _g(po, "productOption"),
            "수량": _g(po, "quantity", default=""),
            "주소": (str(_g(sa, "baseAddress")) + " " + str(_g(sa, "detailedAddress"))).strip(),
            "우편번호": _g(sa, "zipCode"),
            "수령자": _g(sa, "name"),
            "배송메시지": _g(po, "shippingMemo") or _g(od, "shippingMemo"),
            "구매자": _g(od, "ordererName"),
            "수령자전화번호": _g(sa, "tel1", "tel2"),
            "구매자번호": _g(od, "ordererTel"),
            "쇼핑몰": "04.스마트스토어",
            "쇼핑몰ID": "",
            "단가": _g(po, "unitPrice", "totalPaymentAmount", default=""),
            "배송비": _g(po, "deliveryFeeAmount", default=""),
            "정산예정금액": settle_val,
            "주문상태": _status_ko("smartstore", _g(po, "productOrderStatus")),
            "오픈마켓주문번호": poid or oid,
            "실결제금액": _g(po, "totalPaymentAmount", default=""),   # 할인 반영 실결제
            "옵션추가금": _g(po, "optionPrice", default=""),
        })
    return rows


def lotteon_order_rows(since: _dt.datetime, until: _dt.datetime,
                       client=None) -> list:
    """롯데온 출고/회수지시(주문정보) → 16컬럼 행(dict) 리스트.

    apiNo=209 SellerDeliveryOrdersSearch(하루 윈도우) 응답 deliveryOrderList 매핑.
    정산예정금액은 주문 API엔 없음(실결제 actualAmt 로 근사) — 정밀 정산은 정산 그룹 API 후속.
    """
    import html as _html
    from shared.platforms.lotteon.orders import iter_delivery_orders

    rows = []
    for od in iter_delivery_orders(since, until, client=client):
        opt = _g(od, "sitmNm") or (
            (str(_g(od, "adtnOptNm")) + " " + str(_g(od, "adtnOptVal"))).strip())
        addr = (str(_g(od, "dvpStnmZipAddr")) + " " + str(_g(od, "dvpStnmDtlAddr"))).strip()
        odc = str(_g(od, "odCmptDttm"))
        rows.append({
            "_shipkey": ("lotteon", _g(od, "odNo")),   # 배송건(주문) 단위 배송비 정규화용
            "주문일": odc,   # YYYYMMDDHHMMSS — _finalize 에서 시간 포함 통일
            "판매처": "롯데온",
            "상품명": _html.unescape(str(_g(od, "spdNm"))),   # &lt;매장정품&gt; → <매장정품>
            "옵션": _html.unescape(str(opt)),
            "수량": _g(od, "odQty", default=""),
            "주소": addr,
            "우편번호": _g(od, "dvpZipNo"),
            "수령자": _g(od, "dvpCustNm"),
            "배송메시지": _g(od, "dvMsg"),
            "구매자": _g(od, "odrNm"),
            "수령자전화번호": _g(od, "dvpMphnNo", "dvpTelNo"),
            "구매자번호": _g(od, "mphnNo", "telNo"),
            "쇼핑몰": "롯데온",
            "쇼핑몰ID": "",
            "단가": _g(od, "slPrc", default=""),
            "배송비": _g(od, "dvCst", default=""),
            "정산예정금액": _g(od, "actualAmt", default=""),   # 실결제(상품+배송비-할인) 근사
            "주문상태": _status_ko("lotteon", _g(od, "odPrgsStepCd")),
            "오픈마켓주문번호": _g(od, "odNo"),
            "실결제금액": _g(od, "actualAmt", default=""),   # 실결제(정산예상은 주문API 없음→수수료 공란)
            "송장입력": _g(od, "invNo", "dvInvNo", default=""),
        })

    # ── 취소/반품/교환 병합(claimservice, MCP 실측 2026-07-09) ──
    #  활성(출고/회수지시)에 없는 주문만 추가(취소는 출고목록에 없음). 조회 실패는 활성 유지(부가).
    from shared.platforms.lotteon import claims as _clm

    def _claim_row(it, status, qty_key):
        addr = (str(_g(it, "rtrvStnmZipAddr")) + " " + str(_g(it, "rtrvStnmDtlAddr"))).strip()
        return {
            "주문일": str(_g(it, "odAccpDttm", "clmReqDttm")),   # 주문접수일(기간=주문일)
            "판매처": "롯데온",
            "상품명": _html.unescape(str(_g(it, "spdNm"))),
            "옵션": _html.unescape(str(_g(it, "sitmNm"))),
            "수량": _g(it, qty_key, "odQty", default=""),
            "주소": addr,
            "우편번호": _g(it, "rtrvZipNo", default=""),
            "수령자": _g(it, "rtrvCustNm", default=""),
            "배송메시지": _g(it, "clmRsnCnts", default=""),   # 클레임 사유
            "구매자": _g(it, "rtrvCustNm", default=""),
            "수령자전화번호": _g(it, "rtrvMphnNo", "rtrvTelNo", default=""),
            "구매자번호": "",
            "쇼핑몰": "롯데온", "쇼핑몰ID": "",
            "단가": _g(it, "itmSlPrc", default=""),
            "배송비": 0, "정산예정금액": "",
            "주문상태": status,
            "오픈마켓주문번호": _g(it, "odNo"),
            "실결제금액": "", "송장입력": "",
        }

    seen = {r["오픈마켓주문번호"] for r in rows if r.get("오픈마켓주문번호")}
    for fn, status, qkey in ((_clm.iter_cancel, "취소", "cnclQty"),
                             (_clm.iter_return, "반품", "rtngQty"),
                             (_clm.iter_exchange, "교환", "xchgQty")):
        try:
            for it in fn(since, until, client=client):
                on = _g(it, "odNo")
                if on and on in seen:
                    continue
                if on:
                    seen.add(on)
                rows.append(_claim_row(it, status, qkey))
        except Exception:   # noqa: BLE001 — 클레임 조회 실패는 활성 주문 유지
            pass
    return rows


def _won(obj):
    """쿠팡 금액 객체 {currencyCode,units,nanos} → 정수 원. 없으면 ''(폴백 0 금지)."""
    if isinstance(obj, dict) and obj.get("units") is not None:
        try:
            return int(obj["units"])
        except (TypeError, ValueError):
            return ""
    return ""


def coupang_order_rows(since: _dt.datetime, until: _dt.datetime,
                       client=None) -> list:
    """쿠팡 발주서 목록 → 16컬럼 행(dict). status별(공식 필수) 순회 + nextToken 페이징.

    발주서(shipmentBox) 하위 orderItems[] 평탄화(옵션 단위 1행). 정산예정금액은 발주서엔
    없어 revenue-history(별도 API)를 (주문번호,옵션ID)로 조인 — 미정산(최근주문)은 빈칸
    (폴백 금지). 스펙=GET_ORDERSHEET v5.
    """
    from shared.platforms.coupang.orders import fetch_orders

    statuses = ["ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY"]
    seen, rows = set(), []
    for st in statuses:
        token = None
        for _ in range(50):   # nextToken 페이징 안전 상한
            resp = fetch_orders(since, until, client=client, status=st, next_token=token)
            for box in (resp.get("data") or []):
                orderer = box.get("orderer") or {}
                rcv = box.get("receiver") or {}
                addr = (str(rcv.get("addr1") or "") + " " + str(rcv.get("addr2") or "")).strip()
                ordered = str(box.get("orderedAt") or box.get("paidAt") or "")   # 시간 포함
                for it in (box.get("orderItems") or []):
                    key = (box.get("shipmentBoxId"), it.get("vendorItemId"))
                    if key in seen:
                        continue
                    seen.add(key)
                    ship = _won(box.get("shippingPrice"))
                    rows.append({
                        "_oid": box.get("orderId"), "_vid": it.get("vendorItemId"),  # 정산 조인용
                        "_shipkey": ("coupang", box.get("orderId")),   # 배송건 단위 배송비 정규화
                        "주문일": ordered,
                        "판매처": "쿠팡",
                        "상품명": it.get("sellerProductName") or it.get("vendorItemName") or "",
                        "옵션": it.get("sellerProductItemName") or "",
                        "수량": it.get("shippingCount", ""),
                        "주소": addr,
                        "우편번호": rcv.get("postCode") or "",
                        "수령자": rcv.get("name") or "",
                        "배송메시지": box.get("parcelPrintMessage") or "",
                        "구매자": orderer.get("name") or "",
                        "수령자전화번호": rcv.get("receiverNumber") or rcv.get("safeNumber") or "",
                        "구매자번호": orderer.get("ordererNumber") or orderer.get("safeNumber") or "",
                        "쇼핑몰": "쿠팡",
                        "쇼핑몰ID": "",
                        "단가": _won(it.get("salesPrice")),
                        "배송비": ship,
                        "정산예정금액": "",
                        "주문상태": _status_ko("coupang", box.get("status") or st),
                        "오픈마켓주문번호": box.get("orderId") or "",
                        "송장입력": it.get("invoiceNumber") or box.get("invoiceNumber") or "",
                    })
            token = resp.get("nextToken")
            if not token:
                break

    # 정산예정금액 = 상품 정산 + 배송비 정산(주문당 1회).
    #  1) 실제(revenue-history): items.settlementAmount + deliveryFee.settlementAmount.
    #  2) 미정산(최근): 추정 = round(단가×수량×0.8845) + round(배송비×0.8845).
    #     ⚠️ 배송비 실수수료율은 상품과 달라(문서 확인) 추정의 배송비분은 근사.
    try:
        item_settle, deliv_settle = _coupang_settle_map(since, until, client)
    except Exception:
        item_settle, deliv_settle = {}, {}
    _deliv_used = set()
    for r in rows:
        oid, vid = str(r.pop("_oid", "")), r.pop("_vid", None)
        ship = r.get("배송비") or 0
        actual = item_settle.get((oid, vid))
        if actual is not None:                        # 확정: 상품정산 + 배송비정산(주문당 1회)
            val = actual
            if oid not in _deliv_used and oid in deliv_settle:
                val += deliv_settle[oid]
                _deliv_used.add(oid)
            r["정산예정금액"] = val
        else:                                          # 미정산: 상품추정 + 배송비추정(주문당 1회)
            prod_est = _cp_estimate_settle(r.get("단가"), r.get("수량"), 0)
            if prod_est == "":
                r["정산예정금액"] = ""
            else:
                deliv_est = 0
                if oid not in _deliv_used and str(ship).lstrip("-").isdigit():
                    deliv_est = round(int(ship) * CP_SHIP_FEE_FACTOR)
                    _deliv_used.add(oid)
                r["정산예정금액"] = prod_est + deliv_est

    # ── 취소/반품/교환 병합(returnRequests + exchangeRequests, MCP 실측 2026-07-09) ──
    #  활성 발주서에 없는 주문만 추가. 쿠팡 주문번호는 날짜 미인코딩 → 주문일=접수일(createdAt) 근사.
    from shared.platforms.coupang import claims as _cc

    def _cp_claim_row(odno, status, name, opt, qty, unit, reason, buyer, cdt):
        return {
            "주문일": str(cdt or ""), "판매처": "쿠팡",
            "상품명": name or "", "옵션": opt or "",
            "수량": qty if qty not in (None, "") else "",
            "주소": "", "우편번호": "", "수령자": buyer or "",
            "배송메시지": reason or "", "구매자": buyer or "",
            "수령자전화번호": "", "구매자번호": "",
            "쇼핑몰": "쿠팡", "쇼핑몰ID": "",
            "단가": unit if unit not in (None, "") else "",
            "배송비": 0, "정산예정금액": "",
            "주문상태": status, "오픈마켓주문번호": str(odno or ""),
            "실결제금액": "", "송장입력": "",
        }

    seen_ord = {r.get("오픈마켓주문번호") for r in rows if r.get("오픈마켓주문번호")}
    try:
        for rq in _cc.iter_returns(since, until, client=client):
            odno = str(rq.get("orderId") or "")
            if odno and odno in seen_ord:
                continue
            st = "취소" if rq.get("receiptType") == "CANCEL" else "반품"
            for it in (rq.get("returnItems") or [{}]):
                rows.append(_cp_claim_row(
                    odno, st, it.get("sellerProductName"), it.get("vendorItemName"),
                    it.get("cancelCount"), None, rq.get("reasonCodeText"),
                    rq.get("requesterName"), rq.get("createdAt")))
    except Exception:   # noqa: BLE001 — 클레임 조회 실패는 활성 주문 유지
        pass
    try:
        for ex in _cc.iter_exchanges(since, until, client=client):
            odno = str(ex.get("orderId") or "")
            if odno and odno in seen_ord:
                continue
            for it in (ex.get("exchangeItemDtoV1s") or [{}]):
                rows.append(_cp_claim_row(
                    odno, "교환", it.get("orderItemName") or it.get("targetItemName"),
                    None, it.get("quantity"), it.get("orderItemUnitPrice"),
                    ex.get("reasonCodeText"), None, ex.get("createdAt")))
    except Exception:   # noqa: BLE001
        pass
    return rows


CP_FEE_FACTOR = 0.8845        # 1 - 0.1155 (쿠팡 상품 판매수수료 11.55%)
CP_SHIP_FEE_FACTOR = 0.97     # 1 - 0.03  (쿠팡 배송비 수수료 3% — 상품과 별도 요율)


def _cp_estimate_settle(unit, qty, ship):
    """미정산 쿠팡 주문 정산예정금액 추정 = round((단가×수량 + 배송비) × 0.8845).

    단가 없으면 빈칸(폴백 0 금지). 확정액 아님(추정) — 실제 정산으로 검증 필요.
    """
    try:
        u = int(unit)
    except (TypeError, ValueError):
        return ""            # 단가 없음 → 추정 안 함
    q = int(qty) if str(qty).strip().isdigit() else 1
    s = int(ship) if str(ship).strip().lstrip("-").isdigit() else 0
    return round((u * q + s) * CP_FEE_FACTOR)


def _coupang_settle_map(since, until, client):
    """쿠팡 revenue-history →
       (상품정산 {(orderId, vendorItemId): items.settlementAmount 합},
        배송비정산 {orderId: deliveryFee.settlementAmount 합}).

    배송비는 주문 레벨 deliveryFee.settlementAmount(총배송비−배송비수수료−VAT) 별도 필드라
    페이지를 직접 순회해 뽑는다(iter_revenue_items 는 items 만 평탄화).
    """
    from shared.platforms.coupang.settlements import fetch_revenue_page
    rec_to = (until - _dt.timedelta(days=1)).strftime("%Y-%m-%d")   # 종료는 전일까지
    rec_from = since.strftime("%Y-%m-%d")
    item_map, deliv_map = {}, {}
    token = ""
    for _ in range(200):   # 페이징 안전 상한
        resp = fetch_revenue_page(rec_from, rec_to, token=token, max_per_page=50, client=client)
        for order in (resp.get("data") or []):
            oid = str(order.get("orderId") or "")
            damt = (order.get("deliveryFee") or {}).get("settlementAmount")
            if damt is not None:
                try:
                    deliv_map[oid] = deliv_map.get(oid, 0) + int(damt)
                except (TypeError, ValueError):
                    pass
            for it in (order.get("items") or []):
                vid, amt = it.get("vendorItemId"), it.get("settlementAmount")
                if amt is None:
                    continue
                try:
                    item_map[(oid, vid)] = item_map.get((oid, vid), 0) + int(amt)
                except (TypeError, ValueError):
                    pass
        if not resp.get("hasNext"):
            break
        token = resp.get("nextToken") or ""
        if not token:
            break
    return item_map, deliv_map


def _esm_option(lst) -> str:
    """ESM ItemOptionSelectList → 옵션 문자열. 옵션 dict 의 문자열 값 결합(방어적).

    정확한 하위 필드명은 라이브 검증에서 확정(공개문서 미명시). 실데이터만 표시, 날조 없음.
    """
    if not lst:
        return ""
    parts = []
    for it in lst:
        if isinstance(it, dict):
            vals = [str(v).strip() for v in it.values()
                    if isinstance(v, (str, int)) and str(v).strip()]
            if vals:
                parts.append(" ".join(vals))
        elif it:
            parts.append(str(it))
    return " / ".join(p for p in parts if p)


def esm_order_rows(market: str, since: _dt.datetime, until: _dt.datetime,
                   client=None) -> list:
    """옥션·G마켓(ESM 2.0) 주문조회 → 행(dict) 리스트. RequestOrders 응답 매핑.

    market = "auction" | "gmarket". 정산예정금액 = 판매대금 정산조회(getsettleorder)를 주문번호
    (OrderNo↔ContrNo)로 조인. 미정산(최근 주문)은 공란(폴백 금지, 스스·쿠팡과 동일 정직성).
    ⚠️ 라이브 미검증(키 입력 후 서버 검증 필요). 검증 전 SUPPORTED 미포함.
    """
    from shared.platforms.esm.orders import iter_orders
    label = {"auction": "옥션", "gmarket": "G마켓"}.get(market, market)
    rows = []
    for od in iter_orders(market, since, until, client=client):
        addr = (str(_g(od, "DelFrontAddress")) + " " + str(_g(od, "DelBackAddress"))).strip()
        rows.append({
            "_shipkey": (market, _g(od, "OrderNo")),   # 배송건(주문) 단위 배송비 정규화용
            "_ono": str(_g(od, "OrderNo")),            # 정산 조인용(ContrNo)
            "주문일": _g(od, "OrderDate"),
            "판매처": label,
            "상품명": _g(od, "GoodsName"),
            "옵션": _esm_option(od.get("ItemOptionSelectList")),
            "수량": _g(od, "ContrAmount", default=""),
            "주소": addr,
            "우편번호": _g(od, "ZipCode"),
            "수령자": _g(od, "ReceiverName"),
            "배송메시지": _g(od, "DelMemo"),
            "구매자": _g(od, "BuyerName"),
            "수령자전화번호": _g(od, "HpNo", "TelNo"),
            "구매자번호": _g(od, "BuyerId"),
            "쇼핑몰": label,
            "쇼핑몰ID": "",
            "단가": _g(od, "SalePrice", default=""),
            "배송비": _g(od, "ShippingFee", default=""),
            "정산예정금액": "",   # 아래 정산 조인으로 채움(미정산=공란)
            "주문상태": _status_ko("esm", _g(od, "OrderStatus")),
            "오픈마켓주문번호": _g(od, "OrderNo"),
        })

    # 정산예정금액 = 판매대금 정산조회(getsettleorder) SettlementPrice 를 ContrNo(=OrderNo)로 조인.
    #  미정산(최근 주문)은 맵에 없어 공란(폴백 금지). 정산 API 실패는 조용히 공란(주문은 살림).
    try:
        from shared.platforms.esm.settlements import settle_price_map
        srch = (getattr(client, "_cfg", {}) or {}).get("settle_srch_type", "D1") if client else "D1"
        smap = settle_price_map(market, since, until, client=client, srch_type=srch)
    except Exception:   # noqa: BLE001 — 정산 조회 실패는 정산액만 공란(주문 데이터는 유지)
        smap = {}
    for r in rows:
        ono = r.pop("_ono", "")
        if ono in smap:
            r["정산예정금액"] = smap[ono]
    return rows


def auction_order_rows(since: _dt.datetime, until: _dt.datetime, client=None) -> list:
    return esm_order_rows("auction", since, until, client=client)


def gmarket_order_rows(since: _dt.datetime, until: _dt.datetime, client=None) -> list:
    return esm_order_rows("gmarket", since, until, client=client)


def eleven11_order_rows(since: _dt.datetime, until: _dt.datetime, client=None) -> list:
    """11번가 주문 → 행(dict). 상태별 API 3종 병합(전체 라이프사이클).

    11번가는 주문을 상태별 API로 나눠 줌 → 3종을 합쳐 전체 상태 표시:
    · 결제완료(발송대기, complete): 전체 필드(수령자·주소·단가 selPrc·정산예정 stlPlnAmt).
    · 배송완료(dlvcompleted): 전체 필드(수령자·주소·단가·송장·dlvEndDt). 정산예정 없음→공란.
    · 구매확정(completed): 배송정보·단가 미제공(완료·정산 단계) → 해당 열 공란(폴백 금지).
    (ordNo,ordPrdSeq) 상태 간 중복 제거. 배송비는 묶음배송(bndlDlvYN=Y)이면 bmDlvCst,
    아니면 dlvCst; 배송건(_shipkey=bndlDlvSeq) 단위 1회 정규화.
    배송준비중=packaging(전체), 배송중=shipping(송장만), 취소/반품/교환=claimservice 병합.
    """
    from shared.platforms.eleven11.orders import (
        iter_orders, iter_delivered, iter_completed, iter_preparing, iter_shipping,
        iter_cancel, iter_return, iter_exchange)

    def _g11(od, *keys):
        for k in keys:
            v = od.get(k)
            if v not in (None, "", "null"):
                return v
        return ""

    def _row(od, status):
        addr = (str(_g11(od, "rcvrBaseAddr")) + " " + str(_g11(od, "rcvrDtlsAddr"))).strip()
        ship = _g11(od, "bmDlvCst") if od.get("bndlDlvYN") == "Y" else _g11(od, "dlvCst")
        # 주문일: ordDt(있으면). 배송중(shipping) 목록은 ordDt 미제공 → ordNo 앞 8자리(YYYYMMDD)로 보정.
        ordno = str(_g11(od, "ordNo"))
        ord_dt = _g11(od, "ordDt") or (ordno[:8] if ordno[:2] == "20" and len(ordno) >= 8 else "")
        return {
            "_shipkey": ("eleven11", _g11(od, "bndlDlvSeq") or _g11(od, "ordNo")),
            "주문일": ord_dt,
            "판매처": "11번가",
            "상품명": _g11(od, "prdNm"),
            "옵션": _g11(od, "slctPrdOptNm"),
            "수량": _g11(od, "ordQty"),
            "주소": addr,
            "우편번호": _g11(od, "rcvrMailNo"),
            "수령자": _g11(od, "rcvrNm"),
            "배송메시지": _g11(od, "ordDlvReqCont"),
            "구매자": _g11(od, "ordNm", "memID"),
            "수령자전화번호": _g11(od, "rcvrPrtblNo", "rcvrTlphn"),
            "구매자번호": _g11(od, "ordPrtblTel", "ordTlphnNo"),
            "쇼핑몰": "11번가",
            "쇼핑몰ID": "",
            "단가": _g11(od, "selPrc"),   # 구매확정 목록엔 없음 → 공란(폴백 금지)
            "배송비": ship,
            # 정산예정금액 = 주문 응답의 stlPlnAmt(정산예정금액) — 서버 실호출로 확인(2026-07-08).
            #  구매확정 목록엔 없어 공란. 실정산액(정산완료분)은 settlementList.stlAmt(후속).
            "정산예정금액": _g11(od, "stlPlnAmt"),
            "주문상태": status,
            "오픈마켓주문번호": _g11(od, "ordNo"),
            "실결제금액": _g11(od, "ordPayAmt"),   # 결제금액 = 주문금액+배송비-할인(공문 확인)
            "송장입력": _g11(od, "invcNo"),
        }

    def _claim_row(od, status):
        """취소/반품/교환 목록 → 행. 클레임 목록은 상품명·단가 미제공(주문번호·옵션·수량·사유·상태만)."""
        ordno = str(_g11(od, "ordNo"))
        addr = (str(_g11(od, "rcvrBaseAddr")) + " " + str(_g11(od, "rcvrDtlsAddr"))).strip()
        return {
            "주문일": ordno[:8] if ordno[:2] == "20" and len(ordno) >= 8 else "",
            "판매처": "11번가",
            "상품명": "",   # 클레임 목록 미제공
            "옵션": _g11(od, "slctPrdOptNm", "optName"),
            "수량": _g11(od, "ordCnQty", "clmReqQty", "ordQty"),
            "주소": addr,
            "우편번호": _g11(od, "rcvrMailNo"),
            "수령자": _g11(od, "rcvrNm"),
            "배송메시지": _g11(od, "ordCnDtlsRsn", "clmReqCont", "clmReqRsn"),   # 클레임 사유
            "구매자": _g11(od, "ordNm"),
            "수령자전화번호": _g11(od, "rcvrPrtblNo", "rcvrTlphn"),
            "구매자번호": _g11(od, "ordPrtblTel", "ordTlphnNo"),
            "쇼핑몰": "11번가", "쇼핑몰ID": "",
            "단가": "", "배송비": 0, "정산예정금액": "",
            "주문상태": status,
            "오픈마켓주문번호": ordno,
            "실결제금액": "",
            "송장입력": _g11(od, "twPrdInvcNo"),
        }

    # 활성 5상태 + 클레임 3종 병합(전체 라이프사이클). (ordNo,ordPrdSeq) 로 중복 제거.
    #  발송대기(complete)는 필수(오류 전파), 나머지는 부가(실패 시 조용히 스킵). 클레임은 활성에
    #  없는 건(취소 등)만 추가 — 이미 활성에 있으면 그 상태 유지(중복 방지).
    rows, seen = [], set()
    # 발송·배송완료·정산은 주문일보다 늦게 찍혀, 주문일이 창 안이어도 그 상태일이 창 밖이면
    # 상태별 API가 안 준다(배송준비중→배송중→배송완료 진행). 조회 끝을 +14일 넉넉히 잡고
    # combined_order_rows 가 최종적으로 주문일 기준으로 트리밍한다(기간=주문일 유지).
    f_until = until + _dt.timedelta(days=14)

    def _collect(iter_fn, status, required, builder=_row):
        try:
            for od in iter_fn(since, f_until, client=client):
                key = (od.get("ordNo"), od.get("ordPrdSeq"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(builder(od, status))
        except Exception:   # noqa: BLE001
            if required:
                raise

    _collect(iter_orders, "결제완료", True)       # 발송대기(필수)
    _collect(iter_preparing, "배송준비중", False)  # 배송준비중 전체(packaging)
    _collect(iter_shipping, "배송중", False)      # 배송중(송장·주문번호만 — 상세 미제공)
    _collect(iter_delivered, "배송완료", False)   # 배송완료
    _collect(iter_completed, "구매확정", False)   # 구매확정
    _collect(iter_cancel, "취소", False, _claim_row)     # 취소요청
    _collect(iter_return, "반품", False, _claim_row)     # 반품요청
    _collect(iter_exchange, "교환", False, _claim_row)   # 교환요청
    return rows


# 마켓별 행 빌더(코드 존재). SUPPORTED = 그중 실계정 검증까지 끝나 UI 노출 가능한 것.
# 옥션·G마켓·11번가 = 빌더/조회 코드 준비됨(공개문서 스펙). 실키 입력+서버 라이브검증 후 SUPPORTED 추가.
_BUILDERS = {"smartstore": smartstore_order_rows, "lotteon": lotteon_order_rows,
             "coupang": coupang_order_rows,
             "auction": auction_order_rows, "gmarket": gmarket_order_rows,
             "eleven11": eleven11_order_rows}


def _account_client(market: str):
    """서버 UI(판매처 계정)에 저장된 실키로 마켓 클라이언트 생성.

    핵심: 마켓 config dict 는 import 시 env 를 한 번만 읽어(모듈 전역) UI 저장 키를
    못 본다. market_fetch 의 빌더가 refresh_env()+load_credentials 로 최신 시크릿을
    설정에 주입한다(멀티워커 불일치 해소, 롯데온 선례). 키 없으면 None → 기본 클라 폴백.
    """
    prefix = _ENV_PREFIX.get(market)
    if not prefix:
        return None
    try:
        from lemouton.auth import secrets as S
        S.refresh_env()
        from lemouton.uploader import market_fetch as _mf
        builder = {"smartstore": _mf._smartstore_client,
                   "coupang": _mf._coupang_client,
                   "lotteon": _mf._lotteon_client,
                   "auction": _mf._auction_client,
                   "gmarket": _mf._gmarket_client,
                   "eleven11": _mf._eleven11_client}.get(market)
        return builder(prefix) if builder else None
    except Exception:
        return None   # 키 미설정 등 → row builder 가 기본 클라(app.env)로 폴백


def _account_alias(market: str) -> str:
    """판매처관리(UploadAccount)에 등록된 그 마켓 계정의 표시명(쇼핑몰별칭).

    없으면 빈 문자열(추측 금지). market 의 활성 계정 중 첫 번째 display_name.
    """
    try:
        from shared.db import SessionLocal
        from lemouton.sourcing.models_v2 import UploadAccount
        with SessionLocal() as s:
            acc = (s.query(UploadAccount)
                   .filter(UploadAccount.market == market,
                           UploadAccount.is_active == True)  # noqa: E712
                   .order_by(UploadAccount.id).first())
            return acc.display_name if acc else ""
    except Exception:
        return ""


def order_rows(market: str, days: int = 7, client=None,
               now: Optional[_dt.datetime] = None,
               since: Optional[_dt.datetime] = None,
               until: Optional[_dt.datetime] = None) -> list:
    """마켓별 주문 행. 미지원(UI) 마켓은 ValueError(추측 데이터 안 만듦).

    기간 = since~until 명시 시 그대로 사용(빠른 기간 버튼·직접 날짜), 아니면 최근 days일.
    client 미지정 시 서버 UI 저장 실키로 계정 클라이언트를 만들어 사용.
    """
    if market not in SUPPORTED:
        raise ValueError(f"'{market}' 주문 엑셀 미지원(UI) — 코드/키/검증 필요")
    if until is None:
        until = now or _dt.datetime.now(KST)
    if since is None:
        since = until - _dt.timedelta(days=days)
    if client is None:
        client = _account_client(market)
    rows = _finalize_rows(_BUILDERS[market](since, until, client=client))
    alias = _account_alias(market)   # 쇼핑몰별칭 = 판매처관리 계정명
    if alias:
        for r in rows:
            r["쇼핑몰별칭"] = alias
    return rows


def _to_int(v, default=None):
    """'4,000'·'4000.00'·4000 → 4000. 실패 시 default."""
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return default


import re as _re_dt


def _norm_order_dt(v) -> str:
    """주문일을 'YYYY-MM-DD HH:MM:SS'(시간 없으면 'YYYY-MM-DD')로 통일.

    마켓별 형식(ISO·공백구분·YYYYMMDDHHMMSS 등)을 정규화 → 시간 표시 + 문자열 정렬=시간순.
    못 알아보면 원본 유지.
    """
    s = str(v or "").strip()
    if not s:
        return ""
    # 순수 숫자(YYYYMMDD[HHMM[SS]]) — 롯데온 등
    if s.isdigit():
        d = s
        if len(d) >= 8:
            out = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
            if len(d) >= 12:
                out += f" {d[8:10]}:{d[10:12]}" + (f":{d[12:14]}" if len(d) >= 14 else ":00")
            return out
        return s
    dm = _re_dt.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", s)
    if not dm:
        return s
    date = f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
    tm = _re_dt.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if tm:
        return f"{date} {int(tm.group(1)):02d}:{tm.group(2)}:{tm.group(3) or '00'}"
    return date


def _finalize_rows(rows: list) -> list:
    """상품금액(단가×수량)·주문금액(상품+배송비)·배송비 배송건당 1회 정규화 + 주문일 시간 통일.

    배송비는 배송건(_shipkey=주문번호) 단위라, 같은 배송건의 두 번째 행부터 배송비 0
    (합계 중복 방지). 정산예정금액 delivery 는 빌더에서 이미 배송건당 1회 처리.
    주문일은 'YYYY-MM-DD HH:MM:SS' 로 통일(마켓 간 형식 차이 제거 → 시간 표시·정렬 정확).
    """
    seen = set()
    for r in rows:
        r["주문일"] = _norm_order_dt(r.get("주문일"))
        unit = _to_int(r.get("단가"))
        qty = _to_int(r.get("수량"), 1) or 1
        prod = unit * qty if unit is not None else ""
        r["상품금액"] = prod
        sk = r.pop("_shipkey", None)
        ship = _to_int(r.get("배송비"), 0) or 0
        if sk is not None and sk in seen:
            ship = 0                       # 이미 계산한 배송건 → 0
        elif sk is not None:
            seen.add(sk)
        r["배송비"] = ship
        r["주문금액"] = (prod + ship) if prod != "" else ""

        # ── 샵마인 대조 파생(2026-07-08): 총주문금액·마켓수수료·수수료율 ──
        opt_add = _to_int(r.get("옵션추가금"), 0) or 0
        total = (prod + opt_add) if prod != "" else ""   # 총주문금액 = 단가×수량 + 옵션추가금
        r["총주문금액"] = total
        settle = _to_int(r.get("정산예정금액"))
        paid = _to_int(r.get("실결제금액"))
        if paid is None and isinstance(total, int):
            paid = total                     # 실결제 미제공(쿠팡 등) → 총주문금액(할인 없음 가정)
        # 마켓수수료 = 실결제 − 정산예정금액(둘 다 있고 양수일 때만). 아니면 공란(폴백 금지).
        if paid is not None and settle is not None and paid - settle > 0:
            fee = paid - settle
            r["마켓수수료"] = fee
            r["수수료율"] = (f"{round(fee / total * 100, 2)}%"
                             if isinstance(total, int) and total > 0 else "")
        else:
            r["마켓수수료"] = ""
            r["수수료율"] = ""
        # 정산예정금(배송비포함) = 정산예정금액 + 고객배송비(무료배송이면 동일)
        r["정산예정금(배송비포함)"] = (settle + ship) if settle is not None else ""
        # 새 열 기본값 보장(빌더 미설정 시): 송장 없으면 '송장미입력'.
        r.setdefault("실결제금액", "")
        r.setdefault("옵션추가금", "")
        r.setdefault("오픈마켓주문번호", "")
        r.setdefault("쇼핑몰별칭", "")
        r["송장입력"] = r.get("송장입력") or "송장미입력"
    return rows


# ── 성능: 마켓 병렬 조회 + 단기 캐시 ──────────────────────────────────
# 대시보드(preview.json)와 엑셀(export.xlsx)이 각각 3마켓 API를 처음부터 다시
# 조회해 느렸음. (1) 마켓별 조회를 병렬로(합계→최댓값) (2) 짧은 TTL 캐시로 대시보드
# 조회를 다운로드가 재사용(→ 즉시). 캐시는 웹 라우트만 opt-in(use_cache=True);
# 직접 호출·테스트는 기존대로 항상 실조회(결정적).
import threading as _threading
import time as _time
from concurrent.futures import ThreadPoolExecutor as _ThreadPool

CACHE_TTL = 90.0                      # 초 — 이 안에서 같은 (마켓,기간) 재조회는 캐시 히트
_CACHE: dict = {}                     # (markets, days) -> (monotonic_ts, rows)
_CACHE_LOCK = _threading.Lock()


def _fetch_combined(markets, days, now, since=None, until=None) -> list:
    """마켓별 주문을 병렬 조회 후 최신순 통합. 한 마켓 실패는 전파(부분 성공 숨김 금지)."""
    def _one(mk):
        return order_rows(mk, days=days, now=now, since=since, until=until)
    if len(markets) == 1:             # 단일 마켓은 스레드 오버헤드 불필요
        results = {markets[0]: _one(markets[0])}
    else:
        results, errors = {}, []
        with _ThreadPool(max_workers=min(4, len(markets))) as ex:
            futs = {ex.submit(_one, mk): mk for mk in markets}
            for fut, mk in futs.items():
                try:
                    results[mk] = fut.result()
                except Exception as e:   # noqa: BLE001 — 대표 오류로 전파(어느 마켓인지 호출부가 표면화)
                    errors.append(e)
        if errors:
            raise errors[0]
    all_rows = []
    for mk in markets:                # 입력 순서 유지 후 정렬
        all_rows += results.get(mk, [])
    all_rows.sort(key=lambda r: str(r.get("주문일", "")), reverse=True)  # 최신 먼저
    return all_rows


def clear_cache() -> None:
    """캐시 비우기(테스트·강제 새로고침용)."""
    with _CACHE_LOCK:
        _CACHE.clear()


import re as _re


def _row_order_date(r):
    """행의 '주문일'에서 날짜(date) 추출. 형식 무관(YYYY-MM-DD, YYYY.MM.DD, ISO 등)."""
    m = _re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", str(r.get("주문일") or ""))
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _filter_by_order_date(rows, since, until):
    """주문일이 [since, until] 안에 든 행만 남김(기간 = 주문일 기준 통일).

    마켓·상태별 API 는 기준일이 제각각(결제완료일·배송완료일·변경일 등)이라, 화면의 '기간'을
    사용자 기대대로 '주문일' 기준으로 맞추기 위해 최종 행을 주문일로 다시 거른다.
    주문일 파싱 실패 행은 남긴다(데이터 손실 방지).
    """
    if not since or not until:
        return rows
    lo, hi = since.date(), until.date()
    out = []
    for r in rows:
        d = _row_order_date(r)
        if d is None or (lo <= d <= hi):
            out.append(r)
    return out


def combined_order_rows(markets, days: int = 7,
                        now: Optional[_dt.datetime] = None,
                        use_cache: bool = False,
                        since: Optional[_dt.datetime] = None,
                        until: Optional[_dt.datetime] = None) -> list:
    """여러 마켓 주문을 합쳐 최신순(주문일 내림차순)으로. 판매처 열로 마켓 구분.

    기간 = since~until 명시(빠른 기간 버튼·직접 날짜) 또는 최근 days일. 미지원 마켓이
    섞이면 ValueError. 한 마켓 조회 실패는 전체 실패로 전파. use_cache=True(웹 라우트) +
    now 미지정이면 TTL 캐시 사용(대시보드↔다운로드 공유, 캐시 키에 기간 포함).
    """
    markets = list(markets)

    def _build():
        rows = _fetch_combined(markets, days, now, since=since, until=until)
        # 기간 명시(빠른 버튼·직접 날짜) 시 주문일 기준으로 최종 필터 → '기간=주문일' 통일.
        return _filter_by_order_date(rows, since, until)

    if use_cache and now is None:
        key = (tuple(markets), days,
               since.isoformat() if since else None,
               until.isoformat() if until else None)
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
            if hit and (_time.monotonic() - hit[0]) < CACHE_TTL:
                return hit[1]
        rows = _build()
        with _CACHE_LOCK:
            _CACHE[key] = (_time.monotonic(), rows)
        return rows
    return _build()


def resolve_columns(columns=None) -> list:
    """사용자 지정 열(순서 유지)을 유효 열로 필터. 비면 기본 전체."""
    if not columns:
        return list(DEFAULT_COLUMNS)
    seen, out = set(), []
    for c in columns:
        c = (c or "").strip()
        if c in ALL_COLUMNS and c not in seen:
            seen.add(c)
            out.append(c)
    return out or list(DEFAULT_COLUMNS)


def rows_to_xlsx(rows: list, columns=None) -> bytes:
    """행(dict) → xlsx 바이트. columns 로 열 구성·순서 지정(A5 양식 설정)."""
    import openpyxl
    cols = resolve_columns(columns)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "주문"
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
