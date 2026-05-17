# -*- coding: utf-8 -*-
"""originProductNo → channelProductNo 추출.

엑셀 "상품번호" 컬럼 = channelProductNo (= STOREFARM 채널의 channel-specific ID).
사용자가 셀러센터에서 검색·관리할 때 보는 ID.

Naver Commerce API 의 origin-products GET 엔드포인트엔 channelProductNo 안 옴.
대신 POST /external/v1/products/search 의 응답 contents[].channelProducts[].channelProductNo 에 있음.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_product_ids(user_input: int, *, client=None) -> Optional[dict]:
    """user_input(originProductNo 또는 channelProductNo) 양쪽 모두 인식 → 둘 다 반환.

    Returns: {origin_product_no, channel_product_no, product_name} or None if 매칭 0건.
    """
    if client is None:
        from shared.platforms.smartstore.client import SmartStoreClient
        client = SmartStoreClient()

    target = int(user_input)
    page = 1
    size = 100
    while True:
        try:
            resp = client.request("POST", "/external/v1/products/search",
                                  body={"page": page, "size": size})
        except Exception as e:
            logger.warning("[resolve_product_ids] search api 실패: %s", e)
            return None
        if not isinstance(resp, dict):
            return None
        contents = resp.get("contents") or []
        for item in contents:
            origin = int(item.get("originProductNo") or 0)
            cps = item.get("channelProducts") or []
            for cp in cps:
                channel = int(cp.get("channelProductNo") or 0)
                # user_input 이 origin 이거나 channel 이거나 어느 쪽이든 매칭
                if target == origin or target == channel:
                    if cp.get("channelServiceType") == "STOREFARM":
                        return {
                            "origin_product_no": origin,
                            "channel_product_no": channel,
                            "product_name": cp.get("name"),
                        }
        if resp.get("last") or len(contents) < size:
            break
        page += 1
        if page > 30:
            break
    return None


def fetch_channel_product_no(origin_product_no: int, *, client=None) -> Optional[int]:
    """originProductNo 의 STOREFARM 채널 channelProductNo 반환.

    구현: 전체 상품 검색 (14개 정도) → originProductNo 일치 항목 찾음 → channelProductNo 반환.
    """
    if client is None:
        from shared.platforms.smartstore.client import SmartStoreClient
        client = SmartStoreClient()

    target = int(origin_product_no)
    page = 1
    size = 100  # 한 번에 최대한 많이
    while True:
        try:
            resp = client.request(
                "POST", "/external/v1/products/search",
                body={"page": page, "size": size},
            )
        except Exception as e:
            logger.warning("[fetch_channel_product_no] search api 실패: %s", e)
            return None
        if not isinstance(resp, dict):
            return None
        contents = resp.get("contents") or []
        for item in contents:
            if int(item.get("originProductNo") or 0) == target:
                cps = item.get("channelProducts") or []
                for cp in cps:
                    if cp.get("channelServiceType") == "STOREFARM":
                        cpn = cp.get("channelProductNo")
                        if cpn:
                            return int(cpn)
                # STOREFARM 없으면 첫번째 channel
                if cps:
                    cpn = cps[0].get("channelProductNo")
                    if cpn:
                        return int(cpn)
                return None  # 매칭 origin 인데 channel 없음
        # 다음 페이지
        if resp.get("last") or len(contents) < size:
            break
        page += 1
        if page > 20:  # 안전 가드 (2000건)
            break
    return None
