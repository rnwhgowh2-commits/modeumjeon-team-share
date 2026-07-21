# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) 판매대금 정산조회 — getsettleorder.

근거(공개문서 etapi.gmarket.com/41, 2026-07-07 실측):
  POST /account/v1/settle/getsettleorder
  요청: SiteType(A/G)·SrchType(D1~D10 기준일)·SrchStartDate/SrchEndDate("YYYY-MM-DD")
        ·ContrNo(선택)·PageNo·PageRowCnt
  응답: {ResultCode, TotalCount, Data:[{ContrNo, SettlementPrice(정산액), SellOrderPrice(판매액),
        TotCommission(수수료), RemitDate, Kind(1:원거래 2:환불·부호반전)}]}

주문(OrderNo) ↔ 정산(ContrNo) 조인용 맵을 만든다. 환불(Kind=2)은 응답이 이미 부호 반전이라
그대로 합산. 미정산 주문은 맵에 없음 → 정산예정금액 공란(폴백 금지, CLAUDE.md).
"""
from __future__ import annotations

import datetime as _dt

_SITE = {"auction": "A", "gmarket": "G"}
_MAX_WINDOW_DAYS = 31
_PAGE_ROWS = 500


def _fmt(d: _dt.datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _windows(since: _dt.datetime, until: _dt.datetime):
    cur = since
    step = _dt.timedelta(days=_MAX_WINDOW_DAYS)
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def _to_int(v):
    """정산 금액·수량 → int(반올림). 값 없음·파싱 실패는 None(0 대체 금지)."""
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _is_origin(row) -> bool:
    """원주문(Kind=1) 행인가. Kind 미제공이면 원주문으로 본다(환불만 명시적으로 배제)."""
    k = row.get("Kind")
    if k in (None, ""):
        return True
    try:
        return int(k) == 1
    except (TypeError, ValueError):
        return True


def settle_detail_map(market: str, since: _dt.datetime, until: _dt.datetime, *,
                      client, srch_type: str = "D1",
                      page_rows: int = _PAGE_ROWS) -> dict:
    """{str(ContrNo): {정산예정금액·단가·수량·실결제금액·SiteGoodsNo}} — 주문번호별 정산 상세.

    ★ 왜 상세까지 뽑나 — 옥션·G마켓 클레임(취소·반품·교환) 응답은 **주문번호와 상태뿐**이라
      상품명·단가·수량·판매가가 통째로 빈다. 그런데 그 값들은 이미 부르는 '판매대금 정산조회'
      응답 안에 들어 있다(OrderUnitPrice=단가, OrderQty=수량, BuyerPayAmt=구매자 실결제).
      **주문 시점 실값**이라 상품 API 의 '지금 판매가' 폴백과 다르다(정합성 원칙 위배 아님).

    - `정산예정금액` = SettlementPrice 합(원주문 Kind=1 + 환불 Kind=2, 부호 그대로 합산).
    - `단가`·`수량`·`실결제금액`·`SiteGoodsNo` = **원주문(Kind=1)** 행 기준. 환불(Kind=2)은
      금액이 부호반전이라 단가·수량에 쓰면 음수가 섞인다 → 원주문 행에서만 취한다.
    - 파싱 실패 값은 담지 않는다(0·폴백 금지). 정산에 없는 주문은 맵에 없음(미정산 = 빈칸 유지).

    srch_type = 정산 조회 기준일(D1~D10). 주문일 기준 조회와 완전 일치 안 할 수 있어(정산 시차)
    라이브에서 튜닝.
    """
    site = _SITE.get(market)
    if site is None:
        raise ValueError(f"ESM 마켓 아님: {market}")
    out: dict = {}
    for w_from, w_to in _windows(since, until):
        page = 1
        while True:
            body = {
                "SiteType": site,
                "SrchType": srch_type,
                "SrchStartDate": _fmt(w_from),
                "SrchEndDate": _fmt(w_to),
                "PageNo": page,
                "PageRowCnt": page_rows,
            }
            resp = client.request_settlement(body) or {}
            if resp.get("ResultCode") not in (0, None):
                raise RuntimeError(f"ESM 정산조회 실패 ResultCode={resp.get('ResultCode')} "
                                   f"{resp.get('Message') or ''}")
            data = resp.get("Data") or []
            if not data:
                break
            for row in data:
                cn = row.get("ContrNo")
                if cn is None:
                    continue
                key = str(cn)
                ent = out.setdefault(key, {"정산예정금액": None, "단가": None,
                                           "수량": None, "실결제금액": None,
                                           "SiteGoodsNo": None})
                amt = _to_int(row.get("SettlementPrice"))
                if amt is not None:                # 정산액은 원주문+환불 합산(기존 동작)
                    ent["정산예정금액"] = (ent["정산예정금액"] or 0) + amt
                # 단가·수량·실결제는 원주문(Kind=1) 행에서만, 이미 담았으면 유지(첫 원주문 값).
                if _is_origin(row):
                    unit = _to_int(row.get("OrderUnitPrice"))
                    if unit is not None and ent["단가"] is None:
                        ent["단가"] = unit
                    qty = _to_int(row.get("OrderQty"))
                    if qty is not None and ent["수량"] is None:
                        ent["수량"] = qty
                    paid = _to_int(row.get("BuyerPayAmt"))
                    if paid is not None and ent["실결제금액"] is None:
                        ent["실결제금액"] = paid
                    sgn = row.get("SiteGoodsNo")
                    if sgn and ent["SiteGoodsNo"] is None:
                        ent["SiteGoodsNo"] = str(sgn)
            total = resp.get("TotalCount") or 0
            if page * page_rows >= total or len(data) < page_rows:
                break
            page += 1
    return out


def settle_price_map(market: str, since: _dt.datetime, until: _dt.datetime, *,
                     client, srch_type: str = "D1", page_rows: int = _PAGE_ROWS) -> dict:
    """{str(ContrNo): 정산액 합계(int)} — 주문번호별 SettlementPrice 합.

    settle_detail_map 의 얇은 래퍼(하위호환). 정산액이 있는 주문만 담는다.
    """
    detail = settle_detail_map(market, since, until, client=client,
                               srch_type=srch_type, page_rows=page_rows)
    return {k: v["정산예정금액"] for k, v in detail.items()
            if v.get("정산예정금액") is not None}
