# -*- coding: utf-8 -*-
"""롯데온 문의(상품QnA·판매자문의) 목록조회 — CS 고객문의용.

공식 스펙(API 센터 실측 2026-07-16 · api.lotteon.com):
  상품QnA apiNo99: POST /v1/openapi/product/v1/product/qna/list
    body: trGrpCd/trNo/lrtrNo + regStrDttm/regEndDttm(yyyyMMddHHmmss)
          + qnaStatCd(NPROC 미처리/PROC 처리완료/CC_TCTL 고객센터이관/ALL 전체) + pageNo/rowsPerPage(MAX 100)
    응답: data[]{ pdQnaNo, qstTypCd, qnaStatCd, spdNo, sitmNo, qstCnts(질문내용), regDttm }
  판매자문의 apiNo179: POST /v1/openapi/customer/v1/getSellerInquiryList
    body: scStrtDt/scEndDt(yyyymmdd) + vocLcsfCd(유형·공란=전체) + slrInqProcStatCd(공란=전체/ANS 답변/UNANS 미답변) + pageNo/rowsPerPage
    응답: rsltList[]{ slrInqNo, vocTypNm, slrInqProcStatCd(ANS/UNANS), inqTtl, inqCnts(문의내용),
          odNo, pdNm(상품명), spdNm, ansCnts(답변내용), accpDttm(접수일시), procDttm(처리일시) }
    ※ 판매자문의는 trNo 불필요(인증키가 판매자 식별).
인증·rate limit·재시도 는 LotteonClient(Bearer+IP). 이 모듈은 body/파싱만.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator, Optional

from shared.platforms import LOTTEON as _CFG
from shared.platforms.lotteon.client import LotteonClient

_PATH_PRODUCT_QNA = "/v1/openapi/product/v1/product/qna/list"
_PATH_SELLER_INQ = "/v1/openapi/customer/v1/getSellerInquiryList"


def _cfg_of(client) -> dict:
    return getattr(client, "_cfg", None) or _CFG


def iter_product_qna(since: datetime, until: datetime, *,
                     client: Optional[LotteonClient] = None) -> Iterator[dict]:
    """상품QnA 목록(전체 상태). data[] 를 페이지네이션하며 yield."""
    client = client or LotteonClient()
    cfg = _cfg_of(client)
    page = 1
    for _ in range(50):   # 안전 상한
        body = {
            "trGrpCd": cfg.get("tr_grp_cd", "SR"),
            "trNo": cfg.get("tr_no", ""),
            "lrtrNo": cfg.get("lrtr_no", ""),
            "regStrDttm": since.strftime("%Y%m%d%H%M%S"),
            "regEndDttm": until.strftime("%Y%m%d%H%M%S"),
            "qnaStatCd": "ALL",
            "pageNo": page,
            "rowsPerPage": 100,
        }
        resp = client.request(method="POST", path=_PATH_PRODUCT_QNA, body=body)
        data = (resp.get("data") if isinstance(resp, dict) else None) or []
        for it in data:
            yield it
        if len(data) < 100:
            break
        page += 1


def iter_seller_inquiries(since: datetime, until: datetime, *,
                          client: Optional[LotteonClient] = None) -> Iterator[dict]:
    """판매자문의 목록(전체 상태). rsltList[] 를 페이지네이션하며 yield."""
    client = client or LotteonClient()
    page = 1
    for _ in range(50):
        body = {
            "scStrtDt": since.strftime("%Y%m%d"),
            "scEndDt": until.strftime("%Y%m%d"),
            "vocLcsfCd": "",
            "slrInqProcStatCd": "",
            "pageNo": page,
            "rowsPerPage": 50,
        }
        resp = client.request(method="POST", path=_PATH_SELLER_INQ, body=body)
        data = (resp.get("rsltList") if isinstance(resp, dict) else None) or []
        for it in data:
            yield it
        if len(data) < 50:
            break
        page += 1
