# -*- coding: utf-8 -*-
"""롯데온 클레임(취소·반품·교환) 목록조회 — 발송관리 대조용.

공식 스펙(API 센터 MCP 실측 2026-07-09):
  취소 apiNo50: POST /v1/openapi/claim/v1/cancellationOpenApi/getCancellationRequestAndComplateList
  반품 apiNo51: POST /v1/openapi/claim/v1/returningOpenApi/returnRequestSearch
  교환 apiNo69: POST /v1/openapi/claim/v1/exchangeOpenApi/exchangeSearch
  body: srchStrtDttm/srchEndDttm(yyyyMMddHHmmss·최대 30일) + trGrpCd/trNo/lrtrNo(주문 API와 동일).
  응답: data[]{ odNo, clmNo, itemList[]{ spdNm(상품명)·sitmNm(단품명)·odQty·itmSlPrc(판매가)·
        cnclQty/rtngQty/xchgQty(취소·반품·교환 수량)·clmReqDttm·clmRsnCd(사유코드)·clmRsnCnts·
        odPrgsStepCd(진행단계) }}.
  → itemList 평탄화하며 odNo/clmNo 를 각 item 에 병합(주문번호 기준 대조).
인증·rate limit·재시도 는 LotteonClient(Bearer). 이 모듈은 body/파싱만.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterator, Optional

from shared.platforms import LOTTEON as _CFG
from shared.platforms.lotteon.client import LotteonClient

_PATH_CANCEL = "/v1/openapi/claim/v1/cancellationOpenApi/getCancellationRequestAndComplateList"
_PATH_RETURN = "/v1/openapi/claim/v1/returningOpenApi/returnRequestSearch"
_PATH_EXCHANGE = "/v1/openapi/claim/v1/exchangeOpenApi/exchangeSearch"
_FMT = "%Y%m%d%H%M%S"       # yyyyMMddHHmmss
_MAX_WINDOW_DAYS = 29       # 문서: 최대 30일 → 29일 윈도우로 분할(경계 안전)


def _windows(since: datetime, until: datetime):
    cur = since
    step = timedelta(days=_MAX_WINDOW_DAYS)
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def _fetch(path: str, srch_start: str, srch_end: str,
           client: LotteonClient, extra: Optional[dict] = None) -> dict:
    body = {
        "trGrpCd": _CFG.get("tr_grp_cd", "SR"),
        "trNo": _CFG.get("tr_no", ""),
        "lrtrNo": _CFG.get("lrtr_no", ""),
        "srchStrtDttm": srch_start,
        "srchEndDttm": srch_end,
    }
    if extra:
        body.update(extra)
    return client.request(method="POST", path=path, body=body)


def _iter_claim(path: str, since: datetime, until: datetime, *,
                client: Optional[LotteonClient] = None) -> Iterator[dict]:
    """클레임 목록 → data[].itemList[] 평탄화(odNo/clmNo 병합). 29일 윈도우 분할·중복 제거."""
    client = client or LotteonClient()
    seen = set()
    for w_from, w_to in _windows(since, until):
        resp = _fetch(path, w_from.strftime(_FMT), w_to.strftime(_FMT), client)
        data = (resp.get("data") if isinstance(resp, dict) else None) or []
        for od in data:
            od_no = od.get("odNo")
            clm_no = od.get("clmNo")
            for it in (od.get("itemList") or []):
                key = (od_no, it.get("odSeq"), it.get("procSeq"))
                if key in seen:
                    continue
                seen.add(key)
                row = dict(it)
                row["odNo"] = od_no
                row["clmNo"] = clm_no
                yield row


def iter_cancel(since: datetime, until: datetime, *, client=None) -> Iterator[dict]:
    """취소요청(완료) 목록. cnclQty(취소수량)·clmRsnCd(101~139)."""
    return _iter_claim(_PATH_CANCEL, since, until, client=client)


def iter_return(since: datetime, until: datetime, *, client=None) -> Iterator[dict]:
    """반품요청/접수 목록. rtngQty(반품수량)·clmRsnCd(301~406)·회수지(rtrv*)."""
    return _iter_claim(_PATH_RETURN, since, until, client=client)


def iter_exchange(since: datetime, until: datetime, *, client=None) -> Iterator[dict]:
    """교환요청/접수 목록. xchgQty(교환수량)·clmRsnCd(201~207)."""
    return _iter_claim(_PATH_EXCHANGE, since, until, client=client)


def commission_map(since: datetime, until: datetime, *,
                   client: Optional[LotteonClient] = None) -> dict:
    """상품별 수수료내역(SettleCommission) → {odNo: 마켓수수료 합}.

    POST /v1/openapi/settle/v1/se/SettleCommission (startDate/endDate yyyymmdd).
    data[]{odNo, cmsnAmt(수수료금액)} 를 주문번호별 합산. 매출유형 중개=구매확정 기준.
    실패·빈 응답은 빈 dict(폴백 금지 — 수수료 없으면 파생값 유지).
    """
    client = client or LotteonClient()
    cfg = getattr(client, "_cfg", None) or _CFG
    path = "/v1/openapi/settle/v1/se/SettleCommission"
    out: dict = {}
    for w_from, w_to in _windows(since, until):
        body = {"trGrpCd": cfg.get("tr_grp_cd", "SR"), "trNo": cfg.get("tr_no", ""),
                "lrtrNo": cfg.get("lrtr_no", ""),
                "startDate": w_from.strftime("%Y%m%d"), "endDate": w_to.strftime("%Y%m%d")}
        resp = client.request(method="POST", path=path, body=body)
        for r in ((resp.get("data") if isinstance(resp, dict) else None) or []):
            od_no = r.get("odNo")
            try:
                amt = float(r.get("cmsnAmt") or 0)
            except (TypeError, ValueError):
                amt = 0
            if od_no:
                out[od_no] = out.get(od_no, 0) + amt
    return out
