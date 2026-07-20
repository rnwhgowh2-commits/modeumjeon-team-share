# -*- coding: utf-8 -*-
"""마켓 API 한도 시드 — **공식 문서에서 확인된 것만.**

2026-07-19 조사: `webapp/data/marketplace_api_map.json`(API 610건)에서 실제 인용문을 찾음.

━━ 🔴 추정치를 넣지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  모르는 마켓은 **행을 안 만든다**. 행이 없으면 '한도 미설정'이고 계정 합산만 쓴다.
  임의 숫자를 넣으면 나중에 그게 확인된 값인 줄 알고 쓰게 된다
  (설계서에 「스스 1초에 10개」를 적었다가 지운 전례가 있다).

━━ ⚠️ 이건 전부 「주문 조회」 한도다 ━━━━━━━━━━━━━━━━━━━━━━━━━
  **상품·가격·재고 업로드 한도는 전 마켓 미확인.** 업로드가 더 빡빡할 수도, 느슨할 수도 있다.
  업로드에 이 값을 그대로 쓰는 건 **보수적인 쪽**(더 느리게)이라 안전하지만 정확하진 않다.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

# (market, window_seconds, max_count, note)
CONFIRMED: list[tuple[str, int, int, str]] = [
    ("coupang", 60, 50,
     "공식문서 인용 '분당 50회' — 로켓그로스 주문 조회 (2026-07 확인, 업로드 한도 아님)"),
    ("auction", 5, 1,
     "공식문서 인용 '5초당 1회' — ESM 주문 조회 (2026-07 확인, 업로드 한도 아님)"),
    ("gmarket", 5, 1,
     "공식문서 인용 '5초당 1회' — ESM 주문 조회 (2026-07 확인, 업로드 한도 아님)"),
]

# 모르는 마켓 — 일부러 비워 둔다. 화면이 '미확인'으로 말한다.
UNKNOWN = ("smartstore", "lotteon", "eleven11")


def seed_market_rates(session) -> int:
    """확인된 한도만 넣는다(멱등, insert-if-missing). 호출자가 commit.

    ★ 이미 있는 행은 **건드리지 않는다** — 사장님이 화면에서 고친 값을
      재부팅이 되돌리면 안 된다.
    """
    from lemouton.pricing.settings import MarketUploadPolicy

    added = 0
    for market, window, count, note in CONFIRMED:
        if session.get(MarketUploadPolicy, market) is not None:
            continue
        session.add(MarketUploadPolicy(market=market, window_seconds=window,
                                       max_count=count, enabled=True, note=note))
        added += 1
    if added:
        session.flush()
        _log.info("[market_rate_seed] %d개 마켓 한도 시드", added)
    return added
