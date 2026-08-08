# -*- coding: utf-8 -*-
"""왕복 시험 대상 고르기 — **판매중지 상품만**.

사장님 확정(2026-08-06): 진짜 판매중 상품은 잠깐이라도 이름·사진이 바뀌면
노출·판매지수·재심사 위험이 있다. 그래서 시험은 이미 판매중지된 상품에만 한다.

⚠️ 수정 API 가 요구하는 번호는 **originProductNo** 다. 저장·조회 키인 channelProductNo
   를 그대로 넣으면 수정이 실패한다(2026-07-17 과거이력). 둘 다 실어 보낸다.
"""
from __future__ import annotations

#: 이 값으로 후보 목록에 표시한다(판정 자체는 정본 unify_status 가 한다).
_SUSPENDED = "SUSPENSION"


#: ESM 판매상태 — 11=판매중 · 21=판매중지 · 22=직권중지 · 31=SKU품절 (지도 원문).
#: 🔴 **22(직권중지)는 마켓이 강제로 세운 상품**이다. 지재권 등의 사유라 수정 API 가
#:    거부한다 — 시험 대상으로 잡으면 되돌릴 수 없는 변경이 남는다(2026-08-07 사고 2건).
_ESM_STOPPED = "21"
_ESM_ON_SALE = "11"
_ESM_SITE_KEY = {"auction": "iac", "gmarket": "gmkt"}


def esm_suspended_from_search(rows, *, market: str, want: str = "stopped") -> list[dict]:
    """ESM 목록 행 → **우리가 세운** 판매중지(21) 후보만.

    🔴 지도 원문(2026-08-02 라이브 실측): 「`sellStatus` 요청 파라미터가 **무시된다**
       — 조건과 무관하게 전체가 반환됨. 이름/상태 검색은 전 페이지 순회 후
       **클라이언트 필터**로」 · 「응답 행의 sellStatus 는 사이트별 {gmkt,iac}
       (11=판매중/21=판매중지/22=직권중지) — **행 값이 진실**」

       요청 필터를 믿고 전부 「판매중지」로 표시했다가 직권중지 상품을 집었다.
    """
    # 🔴 esm.186 원문: 「판매중지 상품은 가격 수정되지 않습니다」 →
    #    가격 왕복은 판매중(11) 상품에만 성립한다.
    target = _ESM_ON_SALE if want == "sale" else _ESM_STOPPED
    site = _ESM_SITE_KEY.get(market)
    if not site:
        raise ValueError(f"ESM 마켓은 auction/gmarket 만: {market!r}")
    out = []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        gn = r.get("goodsNo")
        if not gn:
            continue                      # 번호를 모르면 후보에서 뺀다(추측 금지)
        st = r.get("sellStatus")
        val = str((st or {}).get(site) or "").strip() if isinstance(st, dict) else ""
        if val != target:
            continue                      # 모르는 값·직권중지·판매중은 전부 제외
        out.append({
            "origin_product_no": str(gn),
            "channel_product_no": (r.get("siteGoodsNo") or {}).get(site),
            "name": r.get("goodsName") or r.get("managedCode"),
            "status": val,
        })
    return out


def suspended_from_search(page: dict, *, want: str = "stopped") -> list[dict]:
    """`POST /external/v1/products/search` 응답 → 후보 목록.

    Args:
        want: 'stopped'(기본·판매중지) 또는 'sale'(판매중).
              🔴 판매중은 사장님이 명시적으로 고를 때만 — 가격 +100원·재고 +1 처럼
              폭이 아주 작은 왕복에 한정한다(2026-08-07 확정).

    한 원상품에 채널상품이 여럿이면 **전부** 같은 상태여야 고른다 — 하나라도
    다르면 그 원상품을 건드리는 순간 다른 채널 상품도 같이 바뀐다.
    """
    out: list[dict] = []
    for item in ((page or {}).get("contents") or []):
        if not isinstance(item, dict):
            continue
        origin = item.get("originProductNo")
        if not origin:
            continue                      # 번호를 모르면 후보에서 뺀다(추측 금지)
        channels = [c for c in (item.get("channelProducts") or []) if isinstance(c, dict)]
        if not channels:
            continue
        # 판정은 정본 하나로 — 손수 만든 낱말·코드 비교는 마켓이 값을 바꾸면 조용히 0건이 된다.
        from lemouton.uploader.roundtrip.sale_status import is_on_sale, is_stopped
        check = is_on_sale if want == "sale" else is_stopped
        if not all(check("smartstore", c.get("statusType")) for c in channels):
            continue                      # 하나라도 상태가 다르면 제외
        first = channels[0]
        out.append({
            "origin_product_no": int(origin),
            "channel_product_no": first.get("channelProductNo"),
            "name": first.get("name"),
            # 무엇을 보고 골랐는지 그대로 남긴다(가공하지 않는다).
            "status": str(first.get("statusType") or "").strip().upper() or _SUSPENDED,
            "sale_price": first.get("salePrice"),
        })
    return out
