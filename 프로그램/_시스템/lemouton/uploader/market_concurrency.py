# -*- coding: utf-8 -*-
"""마켓별 동시 호출 규칙 — 판매처 데이터코드지도(`markets[].concurrency`)를 그대로 읽는다.

2026-07-19 사장님 지시로 지도를 다시 뒤져 찾은 정보다.
앞서는 API 본문 문구만 훑어서 **주문 조회 한도 3건**만 봤는데,
`markets` 블록에 **마켓 단위 규칙**이 따로 적혀 있었다.

━━ 왜 속도(RateWindow)와 따로 두나 ━━━━━━━━━━━━━━━━━━━━━━━━━━
  「초당 몇 개」와 「동시에 몇 개」는 다른 제약이다.
      쿠팡    5 req/s 토큰버킷      → 속도 제한 (RateWindow 로 표현됨)
      스스    계정 순차 조회        → **동시 1개**. 초당 몇 개인지는 안 나온다
      11번가  계정 순차 조회 필수    → 병렬로 쏘면 429 로 전체가 죽는다

  「순차」를 초당 N개로 바꿔 쓰면 **없는 숫자를 지어내는 것**이다.
  그래서 문구를 있는 그대로 보여주고, 병렬 금지 여부만 따로 판정한다.
"""
from __future__ import annotations

import functools
import io
import json
import os
import re

_MAP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "webapp", "data", "marketplace_api_map.json")

# 「순차」·「병렬 시 429」류 문구 = 동시 호출 금지
_SEQUENTIAL = re.compile(r"순차|병렬\s*시|병렬로")


@functools.lru_cache(maxsize=1)
def _markets() -> dict:
    try:
        d = json.load(io.open(_MAP, encoding="utf-8"))
    except Exception:       # noqa: BLE001  — 지도를 못 읽어도 화면은 살아야 한다
        return {}
    out = {}
    for m in d.get("markets") or []:
        mid = (m.get("id") or "").strip()
        if mid:
            out[mid] = m
    return out


def concurrency_note(market: str) -> str:
    """그 마켓의 동시 호출 규칙 문구. 없으면 빈 문자열."""
    m = _markets().get((market or "").strip()) or {}
    return (m.get("concurrency") or "").strip()


def must_be_sequential(market: str) -> bool:
    """병렬로 쏘면 안 되는 마켓인가 (동시 1개).

    ★ 「순차 필수」를 어기면 11번가는 **전체가 429 로 죽는다**(지도 기록).
      속도를 아무리 낮춰도 동시에 두 개를 쏘면 소용없다 — 별개 제약이다.
    """
    return bool(_SEQUENTIAL.search(concurrency_note(market)))


def market_info(market: str) -> dict:
    """화면에 넘길 한 벌."""
    note = concurrency_note(market)
    return {
        "concurrency_note": note or None,
        "must_be_sequential": must_be_sequential(market),
        "known": bool(note),
    }
