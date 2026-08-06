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


def suspended_from_search(page: dict) -> list[dict]:
    """`POST /external/v1/products/search` 응답 → 판매중지 후보 목록.

    한 원상품에 채널상품이 여럿이면 **전부** 판매중지여야 고른다 — 하나라도
    팔리고 있으면 그 원상품을 건드리는 순간 그 채널 상품도 같이 바뀐다.
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
        from lemouton.uploader.roundtrip.sale_status import is_stopped
        if not all(is_stopped("smartstore", c.get("statusType")) for c in channels):
            continue                      # 하나라도 판매중지가 아니면 제외
        first = channels[0]
        out.append({
            "origin_product_no": int(origin),
            "channel_product_no": first.get("channelProductNo"),
            "name": first.get("name"),
            "status": _SUSPENDED,
            "sale_price": first.get("salePrice"),
        })
    return out
