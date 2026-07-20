# -*- coding: utf-8 -*-
"""롯데온 상품별 주문내역(SettleProduct) — **과거 주문 이력 백필용**.

왜 이걸 쓰나: 평소 주문 조회(SellerDeliveryOrdersSearch, apiNo 209)는 **1일 창**
제약이라 1년치가 365번 호출이다. 반면 이 정산 API 는 `startDate`/`endDate` 가
yyyymmdd 범위라 29일 창으로 돈다 → **13번**. 28배 차이.

데이터 코드 지도(`/marketplace-guide/map`) fields 로 확인한 응답 필드:
  odNo(주문번호) · odSeq(**주문순번(단품별)** = 상품라인) · procSeq(처리순번, 클레임시+1)
  odTypCd(주문유형 10주문/20취소/30교환/40반품) · sitmNo(판매자단품번호) · sitmNm(단품명)
  spdNo(판매자상품번호) · spdNm(상품명) · slQty(판매수량) · slUprc(판매단가)
  slAmt(판매금액) · pyDttm(결제일시) · rtngCmptDttm(반품완료일시) · seStdDt(정산기준일자)

즉 우리 `line_uid`(odNo+odSeq)와 화면 열(주문일·상품명·옵션·수량·단가)에 필요한 게 다 있다.

⚠️ **한계 — 정직하게**:
  · 정산 기준이라 **정산 전 최근 주문은 안 나온다**. 최근 구간은 209(1일 창)가 담당한다.
  · 수령자·주소·전화·송장은 **이 API 에 없다**. 과거 이력 조회용이지 발송용이 아니다.
  · 그래서 이건 **백필 전용**이다. 증분 수집 경로를 바꾸지 않는다.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
from typing import Iterator, Optional

from shared.platforms import LOTTEON as _CFG
from shared.platforms.lotteon.claims import _windows
from shared.platforms.lotteon.client import LotteonClient

_PATH = "/v1/openapi/settle/v1/se/SettleProduct"
_FMT = "%Y%m%d"

# odTypCd → 우리 주문상태(한글). 마켓이 준 코드만 쓰고 없으면 비운다(추측 금지).
_TYPE = {"10": "주문", "20": "취소완료", "30": "교환완료", "40": "반품완료"}


def fetch(start_date: str, end_date: str, *,
          client: Optional[LotteonClient] = None) -> dict:
    """1구간(≤29일) 원본 조회. start/end = yyyymmdd."""
    client = client or LotteonClient()
    body = {"trGrpCd": _CFG.get("tr_grp_cd", "SR"),
            "trNo": _CFG.get("tr_no", ""),
            "lrtrNo": _CFG.get("lrtr_no", ""),
            "startDate": start_date,
            "endDate": end_date}
    return client.request(method="POST", path=_PATH, body=body)


def iter_rows(since: _dt.datetime, until: _dt.datetime, *,
              client: Optional[LotteonClient] = None) -> Iterator[dict]:
    """기간을 29일 창으로 나눠 단품 라인을 순회. (odNo,odSeq,procSeq) 중복 제거."""
    client = client or LotteonClient()
    seen = set()
    for w_from, w_to in _windows(since, until):
        resp = fetch(w_from.strftime(_FMT), w_to.strftime(_FMT), client=client) or {}
        for r in (resp.get("data") or []):
            key = (str(r.get("odNo") or ""), str(r.get("odSeq") or ""),
                   str(r.get("procSeq") or ""))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            yield r


def _num(v):
    """숫자 변환. **값이 없으면 0 이 아니라 None** — 0 으로 채우면 '단가 0원'이 되어
    마진이 통째로 틀어진다(이 저장소의 폴백 금지 원칙)."""
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _dt_str(v) -> str:
    """yyyymmddHHMMSS·yyyymmdd → 'YYYY-MM-DD HH:MM:SS'. 못 알아보면 원본."""
    s = str(v or "").strip()
    if not s.isdigit() or len(s) < 8:
        return s
    out = f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) >= 14:
        out += f" {s[8:10]}:{s[10:12]}:{s[12:14]}"
    return out


def to_row(r: dict) -> dict:
    """정산 라인 → 주문 행. 없는 값은 **비운다**(폴백·추측 금지)."""
    qty = _num(r.get("slQty"))
    unit = _num(r.get("slUprc"))
    od_type = str(r.get("odTypCd") or "")
    return {
        "주문일": _dt_str(r.get("pyDttm")) or _dt_str(r.get("seStdDt")),
        "판매처": "롯데온",
        "상품명": _html.unescape(str(r.get("spdNm") or "")),
        "옵션": _html.unescape(str(r.get("sitmNm") or "")),
        "수량": qty if qty is not None else "",
        "단가": unit if unit is not None else "",
        "배송비": 0,
        "정산예정금액": "", "_settle_source": "none",
        "주문상태": _TYPE.get(od_type, ""),
        "주문상태원본": od_type,
        "오픈마켓주문번호": str(r.get("odNo") or ""),
        # 수령자·주소·전화·송장은 이 API 에 없다 → 비운다(지어내지 않는다).
        "수령자": "", "수령자전화번호": "", "주소": "", "우편번호": "",
        "배송메시지": "", "구매자": "", "구매자번호": "",
        "쇼핑몰": "롯데온", "쇼핑몰ID": "",
        "실결제금액": _num(r.get("slAmt")) if r.get("slAmt") is not None else "",
        "송장입력": "",
        # line_uid 조각 — 지도 fields 확인: odSeq=주문순번(단품별), sitmNo=판매자단품번호
        "_send_ids": {"od_no": str(r.get("odNo") or ""),
                      "od_seq": str(r.get("odSeq") or ""),
                      "sitm_no": str(r.get("sitmNo") or "")},
        "_pd_market_product_id": str(r.get("spdNo") or ""),
        # 취소·교환·반품은 클레임 이벤트로 적재되도록 표시(주문 라인을 덮어쓰지 않는다).
        **({"_kind": "change",
            "_change_date": _dt_str(r.get("rtngCmptDttm")) or _dt_str(r.get("seStdDt"))}
           if od_type in ("20", "30", "40") else {}),
    }


def order_rows(since: _dt.datetime, until: _dt.datetime, *,
               client: Optional[LotteonClient] = None) -> list[dict]:
    """백필용 주문 행 목록."""
    return [to_row(r) for r in iter_rows(since, until, client=client)]
