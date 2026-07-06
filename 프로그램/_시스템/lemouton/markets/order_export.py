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

# 샵마인 발송대기 엑셀과 동일한 16컬럼(빈 열 포함).
HEADER = ["주문일", "상품명", "옵션", "수량", "주소", "", "우편번호", "수령자",
          "배송메시지", "구매자", "수령자전화번호", "구매자번호", "쇼핑몰",
          "쇼핑몰ID", "단가", "정산예정금액"]

SUPPORTED = {"smartstore"}   # 실제 뽑기 가능한 마켓(코드+검증). 늘어나면 여기에 추가.


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

    # 정산예정금액(결제일 기준, 하루씩) — 실패해도 주문은 나오게 방어.
    settle_map = {}
    day = since
    while day <= until:
        try:
            settle_map.update(_settle.settle_expect_by_product_order(
                search_date=day.strftime("%Y-%m-%d"),
                period_type="SETTLE_CASEBYCASE_PAY_DATE", client=client))
        except Exception:
            pass
        day += _dt.timedelta(days=1)

    rows = []
    for it in detail:
        po = it.get("productOrder", {}) if isinstance(it, dict) else {}
        od = it.get("order", {}) if isinstance(it, dict) else {}
        sa = po.get("shippingAddress", {}) if isinstance(po, dict) else {}
        poid = _g(po, "productOrderId")
        rows.append({
            "주문일": str(_g(od, "orderDate", "paymentDate"))[:10],
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
            "정산예정금액": settle_map.get(poid, ""),
        })
    return rows


def lotteon_order_rows(since: _dt.datetime, until: _dt.datetime,
                       client=None) -> list:
    """롯데온 출고/회수지시(주문정보) → 16컬럼 행(dict) 리스트.

    apiNo=209 SellerDeliveryOrdersSearch(하루 윈도우) 응답 deliveryOrderList 매핑.
    정산예정금액은 주문 API엔 없음(실결제 actualAmt 로 근사) — 정밀 정산은 정산 그룹 API 후속.
    """
    from shared.platforms.lotteon.orders import iter_delivery_orders

    rows = []
    for od in iter_delivery_orders(since, until, client=client):
        opt = _g(od, "sitmNm") or (
            (str(_g(od, "adtnOptNm")) + " " + str(_g(od, "adtnOptVal"))).strip())
        addr = (str(_g(od, "dvpStnmZipAddr")) + " " + str(_g(od, "dvpStnmDtlAddr"))).strip()
        odc = str(_g(od, "odCmptDttm"))
        rows.append({
            "주문일": (odc[:4] + "-" + odc[4:6] + "-" + odc[6:8]) if len(odc) >= 8 else odc,
            "상품명": _g(od, "spdNm"),
            "옵션": opt,
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
            "정산예정금액": _g(od, "actualAmt", default=""),   # 실결제 근사(정밀 정산은 후속)
        })
    return rows


# 마켓별 행 빌더(코드 존재). SUPPORTED = 그중 실계정 검증까지 끝나 UI 노출 가능한 것.
_BUILDERS = {"smartstore": smartstore_order_rows, "lotteon": lotteon_order_rows}


def order_rows(market: str, days: int = 7, client=None,
               now: Optional[_dt.datetime] = None) -> list:
    """마켓별 최근 days일 주문 행. 미지원(UI) 마켓은 ValueError(추측 데이터 안 만듦).

    SUPPORTED 만 UI(엑셀 버튼)에 노출. _BUILDERS 에 있으나 SUPPORTED 아닌 마켓
    (예: 롯데온 — 코드 준비됨·키/검증 대기)은 서버/검증용으로 allow_unverified=True 시만.
    """
    if market not in SUPPORTED:
        raise ValueError(f"'{market}' 주문 엑셀 미지원(UI) — 코드/키/검증 필요")
    until = now or _dt.datetime.now(KST)
    since = until - _dt.timedelta(days=days)
    return _BUILDERS[market](since, until, client=client)


def rows_to_xlsx(rows: list) -> bytes:
    """행(dict) → 샵마인 형식 xlsx 바이트."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "주문"
    ws.append(HEADER)
    for r in rows:
        ws.append([r.get(h, "") for h in HEADER])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
