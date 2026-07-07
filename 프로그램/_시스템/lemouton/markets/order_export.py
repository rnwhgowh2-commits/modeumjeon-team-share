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
               "구매자", "구매자번호", "단가", "배송비", "정산예정금액"]
# 정산예정금액 = 상품 정산 + 배송비 정산(각자 수수료 차감). 배송비는 별도 정산 라인
# (쿠팡 deliveryFee.settlementAmount·스스 DELIVERY행·롯데온 실결제 포함) 이라 합산한다.
DEFAULT_COLUMNS = list(ALL_COLUMNS)
HEADER = DEFAULT_COLUMNS   # 하위호환 별칭

# 마켓별 원시 상태코드 → 한글. 미매핑은 원값 그대로(추측 금지).
_STATUS_KO = {
    "smartstore": {"PAYMENT_WAITING": "결제대기", "PAYED": "결제완료", "DELIVERING": "배송중",
                   "DELIVERED": "배송완료", "PURCHASE_DECIDED": "구매확정",
                   "CANCELED": "취소", "RETURNED": "반품", "EXCHANGED": "교환"},
    "coupang": {"ACCEPT": "결제완료", "INSTRUCT": "상품준비중", "DEPARTURE": "배송지시",
                "DELIVERING": "배송중", "FINAL_DELIVERY": "배송완료",
                "NONE_TRACKING": "업체직접배송"},
    "lotteon": {"11": "출고지시", "23": "회수지시"},
}


def _status_ko(market, raw):
    if raw in (None, ""):
        return ""
    return _STATUS_KO.get(market, {}).get(str(raw), str(raw))

SUPPORTED = {"smartstore", "lotteon", "coupang"}   # UI 엑셀버튼 노출. 실키=서버 UI저장.
# 마켓 → 계정 시크릿 env_prefix(판매처 계정 기본). load_credentials 로 실키 로드.
_ENV_PREFIX = {"smartstore": "SMARTSTORE_MAIN", "coupang": "COUPANG_MAIN",
               "lotteon": "LOTTEON_MAIN"}


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
            "주문일": str(_g(od, "orderDate", "paymentDate"))[:10],
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
            "주문일": (odc[:4] + "-" + odc[4:6] + "-" + odc[6:8]) if len(odc) >= 8 else odc,
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
        })
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
                ordered = str(box.get("orderedAt") or box.get("paidAt") or "")[:10]
                for it in (box.get("orderItems") or []):
                    key = (box.get("shipmentBoxId"), it.get("vendorItemId"))
                    if key in seen:
                        continue
                    seen.add(key)
                    ship = _won(box.get("shippingPrice"))
                    rows.append({
                        "_oid": box.get("orderId"), "_vid": it.get("vendorItemId"),  # 정산 조인용
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
        else:                                          # 미정산: 상품추정 + 배송비추정
            prod_est = _cp_estimate_settle(r.get("단가"), r.get("수량"), 0)
            if prod_est == "":
                r["정산예정금액"] = ""
            else:
                deliv_est = round(int(ship) * CP_SHIP_FEE_FACTOR) if str(ship).lstrip("-").isdigit() else 0
                r["정산예정금액"] = prod_est + deliv_est
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


# 마켓별 행 빌더(코드 존재). SUPPORTED = 그중 실계정 검증까지 끝나 UI 노출 가능한 것.
_BUILDERS = {"smartstore": smartstore_order_rows, "lotteon": lotteon_order_rows,
             "coupang": coupang_order_rows}


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
                   "lotteon": _mf._lotteon_client}.get(market)
        return builder(prefix) if builder else None
    except Exception:
        return None   # 키 미설정 등 → row builder 가 기본 클라(app.env)로 폴백


def order_rows(market: str, days: int = 7, client=None,
               now: Optional[_dt.datetime] = None) -> list:
    """마켓별 최근 days일 주문 행. 미지원(UI) 마켓은 ValueError(추측 데이터 안 만듦).

    client 미지정 시 서버 UI 저장 실키로 계정 클라이언트를 만들어 사용.
    """
    if market not in SUPPORTED:
        raise ValueError(f"'{market}' 주문 엑셀 미지원(UI) — 코드/키/검증 필요")
    until = now or _dt.datetime.now(KST)
    since = until - _dt.timedelta(days=days)
    if client is None:
        client = _account_client(market)
    return _BUILDERS[market](since, until, client=client)


def combined_order_rows(markets, days: int = 7,
                        now: Optional[_dt.datetime] = None) -> list:
    """여러 마켓 주문을 합쳐 최신순(주문일 내림차순)으로. 판매처 열로 마켓 구분.

    미지원 마켓이 섞이면 ValueError(추측 데이터 안 만듦). 한 마켓 조회 실패는 전체 실패로
    전파(부분 성공을 조용히 숨기지 않음 — 호출부가 어느 마켓 문제인지 표면화).
    """
    all_rows = []
    for mk in markets:
        all_rows += order_rows(mk, days=days, now=now)
    all_rows.sort(key=lambda r: str(r.get("주문일", "")), reverse=True)  # 최신 먼저
    return all_rows


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
