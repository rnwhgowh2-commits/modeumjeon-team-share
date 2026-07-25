# -*- coding: utf-8 -*-
"""롯데온 중개셀러통합정보(SettleItmdSales) — 구매확정 주문의 완전 정산 성분.

POST /v1/openapi/settle/v1/se/SettleItmdSales (startDate/endDate yyyymmdd, 정산기준일=구매확정일).
data[] 단품 라인 → 주문번호별 지급대상금액(pymtAmt) 합 + 제휴 여부(pcsCmsn>0). 폴백·추측 없음.
정산완료 주문은 이 값이 마켓 실지급액 = 계산 불필요.
"""
import logging
from datetime import datetime
from typing import Optional

from shared.platforms import LOTTEON as _CFG
from shared.platforms.lotteon.client import LotteonClient
from shared.platforms.lotteon.claims import _windows

_log = logging.getLogger(__name__)

_PATH = "/v1/openapi/settle/v1/se/SettleItmdSales"

PAGE_SIZE = 100          # 롯데온 목록 API 의 rowsPerPage 상한(settle_orders 와 동일 실측)

#  롯데온 정산 계열 성공 코드(settle_orders 실측과 동일) — 화이트리스트가 좁으면
#  성공 응답을 실패로 읽는다. "SUCCESS"·"0000" 둘 다 성공.
_OK_CODES = {"", "0", "00", "0000", "success", "ok"}


def _ok(resp: dict) -> bool:
    return str((resp or {}).get("returnCode") or "").strip().lower() in _OK_CODES


def _fetch_itmd_rows(cfg: dict, w_from: datetime, w_to: datetime, *, client) -> list:
    """한 창(≤29일)의 **전체** data 행. 페이징을 먼저 시도하고 거부되면 무페이징으로 되돌린다.

    🔴 페이징이 필요한데 안 넣으면 첫 100건만 조용히 오고 나머지가 사라진다
      (settle_orders._fetch_window 의 실측 사고와 동형). dataCount 로 끝을 판정한다.
    """
    base = {"trGrpCd": cfg.get("tr_grp_cd", "SR"), "trNo": cfg.get("tr_no", ""),
            "lrtrNo": cfg.get("lrtr_no", ""),
            "startDate": w_from.strftime("%Y%m%d"), "endDate": w_to.strftime("%Y%m%d")}

    def _req(page=None):
        body = dict(base)
        if page is not None:
            body["pageNo"] = page
            body["rowsPerPage"] = PAGE_SIZE
        return client.request(method="POST", path=_PATH, body=body) or {}

    # 🔴 중복 제거로 블로업 방지 — 서버가 pageNo 를 무시하고 같은 100건을 계속 주는데
    #   dataCount 마저 없으면(이 endpoint 는 참조 SettleProduct 와 다를 수 있다) 끝 판정이
    #   안 걸려 page 1000 까지 append → parse_itmd 가 pymtAmt 를 최대 1000배 부풀린다.
    #   참조 _fetch_window 는 호출부(iter_rows)가 (odNo,odSeq,procSeq)로 dedup 해 면역이지만
    #   여기 소비자(parse_itmd)는 dedup 이 없으므로 수집 단계에서 직접 접는다.
    seen: set = set()

    def _extend(dst: list, got: list) -> int:
        added = 0
        for r in got:
            key = (str(r.get("odNo") or ""), str(r.get("odSeq") or ""),
                   str(r.get("procSeq") or ""))
            if key in seen:
                continue
            seen.add(key)
            dst.append(r)
            added += 1
        return added

    first = _req(page=1)
    if not _ok(first):
        # 페이징 파라미터를 안 받는 API 일 수 있다 → 원래 방식(무페이징)으로 1회.
        plain = _req(page=None)
        if not _ok(plain):
            # 조용한 실패 금지 — 부분/빈 수집을 성공처럼 넘기지 않고 예외로 올린다
            #   (참조 _fetch_window 규약과 동일 → 스윕 stat['errors']·인라인 추정 폴백).
            raise RuntimeError(
                f"SettleItmdSales 실패 {base['startDate']}~{base['endDate']}: "
                f"paged={first.get('returnCode')} plain={plain.get('returnCode')} "
                f"{plain.get('returnMessage') or first.get('returnMessage') or ''}")
        return list(plain.get("data") or [])

    rows: list = []
    _extend(rows, list(first.get("data") or []))
    total = first.get("dataCount")
    try:
        total = int(total) if total is not None else None
    except (TypeError, ValueError):
        total = None

    page = 1
    while True:
        if len(rows) < PAGE_SIZE * page:              # 마지막 페이지가 상한 미만 → 끝
            break
        if total is not None and len(rows) >= total:  # dataCount 를 다 채움 → 끝
            break
        page += 1
        if page > 1000:                               # 무한 페이징 방지
            _log.warning("SettleItmdSales 페이지 상한 도달 %s~%s",
                         base["startDate"], base["endDate"])
            break
        nxt = _req(page=page)
        if not _ok(nxt):
            # 중간 페이지 실패 = 부분 수집. 조용히 넘기면 정산액이 과소 → 예외로 올린다.
            raise RuntimeError(
                f"SettleItmdSales 페이지 {page} 실패 {base['startDate']}~{base['endDate']}: "
                f"{nxt.get('returnCode')} {nxt.get('returnMessage') or ''}")
        got = list(nxt.get("data") or [])
        if not got or _extend(rows, got) == 0:        # 새 행이 없으면(서버가 pageNo 무시) 끝
            break
    if total is not None and len(rows) < total:
        _log.warning("SettleItmdSales 수집 부족 %s~%s: %d/%d",
                     base["startDate"], base["endDate"], len(rows), total)
    return rows


def _num(v) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def parse_itmd(resp: dict) -> dict:
    out: dict = {}
    for r in ((resp or {}).get("data") or []):
        od = str(r.get("odNo") or "")
        if not od:
            continue
        cur = out.setdefault(od, {"pymtAmt": 0, "pcs_cmsn": 0, "is_affiliate": False})
        cur["pymtAmt"] += _num(r.get("pymtAmt"))
        pcs = _num(r.get("pcsCmsn"))
        cur["pcs_cmsn"] += pcs
        if pcs > 0:
            cur["is_affiliate"] = True
    return out


def itmd_map(since: datetime, until: datetime, *,
             client: Optional[LotteonClient] = None) -> dict:
    """[since, until] 구매확정 주문의 {odNo:{pymtAmt,pcs_cmsn,is_affiliate}}."""
    client = client or LotteonClient()
    cfg = getattr(client, "_cfg", None) or _CFG
    out: dict = {}
    for w_from, w_to in _windows(since, until):
        rows = _fetch_itmd_rows(cfg, w_from, w_to, client=client)
        for k, v in parse_itmd({"data": rows}).items():
            cur = out.setdefault(k, {"pymtAmt": 0, "pcs_cmsn": 0, "is_affiliate": False})
            cur["pymtAmt"] += v["pymtAmt"]
            cur["pcs_cmsn"] += v["pcs_cmsn"]
            cur["is_affiliate"] = cur["is_affiliate"] or v["is_affiliate"]
    return out


def parse_product_affiliate(resp: dict) -> dict:
    """{spdNo: bool} — 그 상품 라인에 제휴(pcsCmsn>0)가 하나라도 있으면 True."""
    out: dict = {}
    for r in ((resp or {}).get("data") or []):
        sp = str(r.get("spdNo") or "")
        if not sp:
            continue
        out[sp] = out.get(sp, False) or (_num(r.get("pcsCmsn")) > 0)
    return out


def scan(since: datetime, until: datetime, *,
         client: Optional[LotteonClient] = None):
    """한 번 순회로 (주문별 정산맵, 상품별 제휴여부맵) 반환.

    주문맵 = itmd_map 과 동일({odNo:{pymtAmt,pcs_cmsn,is_affiliate}}) — 구매확정 실지급액.
    상품맵 = {spdNo: bool} — 미정산 주문의 제휴 여부를 상품 이력으로 추정하는 데 쓴다(판매경로는
    고객 유입경로라 주문 API엔 없음 → 상품별 제휴 이력이 최선 추정).
    """
    client = client or LotteonClient()
    cfg = getattr(client, "_cfg", None) or _CFG
    orders: dict = {}
    products: dict = {}
    for w_from, w_to in _windows(since, until):
        rows = _fetch_itmd_rows(cfg, w_from, w_to, client=client)
        resp = {"data": rows}
        for k, v in parse_itmd(resp).items():
            cur = orders.setdefault(k, {"pymtAmt": 0, "pcs_cmsn": 0, "is_affiliate": False})
            cur["pymtAmt"] += v["pymtAmt"]
            cur["pcs_cmsn"] += v["pcs_cmsn"]
            cur["is_affiliate"] = cur["is_affiliate"] or v["is_affiliate"]
        for sp, aff in parse_product_affiliate(resp).items():
            products[sp] = products.get(sp, False) or aff
    return orders, products
