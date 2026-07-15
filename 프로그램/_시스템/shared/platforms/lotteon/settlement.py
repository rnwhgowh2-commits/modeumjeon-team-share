# -*- coding: utf-8 -*-
"""롯데온 중개셀러통합정보(SettleItmdSales) — 구매확정 주문의 완전 정산 성분.

POST /v1/openapi/settle/v1/se/SettleItmdSales (startDate/endDate yyyymmdd, 정산기준일=구매확정일).
data[] 단품 라인 → 주문번호별 지급대상금액(pymtAmt) 합 + 제휴 여부(pcsCmsn>0). 폴백·추측 없음.
정산완료 주문은 이 값이 마켓 실지급액 = 계산 불필요.
"""
from datetime import datetime
from typing import Optional

from shared.platforms import LOTTEON as _CFG
from shared.platforms.lotteon.client import LotteonClient
from shared.platforms.lotteon.claims import _windows

_PATH = "/v1/openapi/settle/v1/se/SettleItmdSales"


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
        body = {"trGrpCd": cfg.get("tr_grp_cd", "SR"), "trNo": cfg.get("tr_no", ""),
                "lrtrNo": cfg.get("lrtr_no", ""),
                "startDate": w_from.strftime("%Y%m%d"), "endDate": w_to.strftime("%Y%m%d")}
        resp = client.request(method="POST", path=_PATH, body=body)
        for k, v in parse_itmd(resp).items():
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
        body = {"trGrpCd": cfg.get("tr_grp_cd", "SR"), "trNo": cfg.get("tr_no", ""),
                "lrtrNo": cfg.get("lrtr_no", ""),
                "startDate": w_from.strftime("%Y%m%d"), "endDate": w_to.strftime("%Y%m%d")}
        resp = client.request(method="POST", path=_PATH, body=body)
        for k, v in parse_itmd(resp).items():
            cur = orders.setdefault(k, {"pymtAmt": 0, "pcs_cmsn": 0, "is_affiliate": False})
            cur["pymtAmt"] += v["pymtAmt"]
            cur["pcs_cmsn"] += v["pcs_cmsn"]
            cur["is_affiliate"] = cur["is_affiliate"] or v["is_affiliate"]
        for sp, aff in parse_product_affiliate(resp).items():
            products[sp] = products.get(sp, False) or aff
    return orders, products
