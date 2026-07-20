# -*- coding: utf-8 -*-
"""마켓 API 한도 시드 — **공식 문서에서 확인된 것만.**

2026-07-19 조사: `webapp/data/marketplace_api_map.json`(API 610건)에서 실제 인용문을 찾음.

━━ 🔴 추정치를 넣지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  모르는 마켓은 **행을 안 만든다**. 행이 없으면 '한도 미설정'이고 계정 합산만 쓴다.
  임의 숫자를 넣으면 나중에 그게 확인된 값인 줄 알고 쓰게 된다
  (설계서에 「스스 1초에 10개」를 적었다가 지운 전례가 있다).

━━ ⚠️ 두 종류가 섞여 있다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  쿠팡      = **게이트웨이 전체** 한도 (5 req/s) — 업로드도 여기 걸린다. 맞는 값이다.
  옥션·G마켓 = **주문 조회** 한도 (5초에 1회) — 업로드 한도는 아직 모른다.
              보수적인 쪽(더 느리게)이라 안전하지만 정확하진 않다.

  2026-07-19 교정: 쿠팡을 「분당 50회」로 넣었는데 그건 **로켓그로스 주문조회 하나**의
  한도였다. 업로드는 다른 API 라 게이트웨이 한도가 맞다 — 실제의 1/6 로 묶여 있었다.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

# (market, window_seconds, max_count, note)
CONFIRMED: list[tuple[str, int, int, str]] = [
    # 데이터코드지도 markets[coupang].concurrency = "5 req/s 토큰버킷, 429 Retry-After 존중".
    #   ★ 이게 쿠팡 API **게이트웨이 전체** 한도다. 업로드도 여기 걸린다.
    #   (별도로 '로켓그로스 주문조회'는 분당 50회 = 초당 0.83 로 더 좁다 — 그 API 한정.
    #    업로드는 다른 API 라 게이트웨이 한도를 쓴다.)
    ("coupang", 1, 5,
     "게이트웨이 5 req/s 토큰버킷 (데이터코드지도). ※ 로켓그로스 주문조회는 분당 50회로 더 좁음"),
    ("auction", 5, 1,
     "공식문서 인용 '5초당 1회' — ESM 주문 조회 (2026-07 확인, 업로드 한도 아님)"),
    ("gmarket", 5, 1,
     "공식문서 인용 '5초당 1회' — ESM 주문 조회 (2026-07 확인, 업로드 한도 아님)"),
]

# 내가 잘못 넣었던 값 → 고칠 값. **정확히 이 값일 때만** 고친다.
#   사장님이 화면에서 손댄 값은 절대 건드리지 않는다.
_CORRECTIONS: list[tuple[str, int, int]] = [
    # (market, 옛 window, 옛 max) — 2026-07-19: 주문조회 한도를 게이트웨이 한도로 오인
    ("coupang", 60, 50),
]

# 모르는 마켓 — 일부러 비워 둔다. 화면이 '미확인'으로 말한다.
UNKNOWN = ("smartstore", "lotteon", "eleven11")


def seed_market_rates(session) -> int:
    """확인된 한도만 넣는다(멱등). 호출자가 commit. 바뀐 행 수를 돌려준다.

    ★ 이미 있는 행은 **건드리지 않는다** — 사장님이 화면에서 고친 값을
      재부팅이 되돌리면 안 된다.
      단 하나의 예외: `_CORRECTIONS` 에 적힌 **내가 넣었던 잘못된 값과 정확히 같을 때만**
      고친다. 숫자가 1이라도 다르면 사장님이 손댄 것이므로 그대로 둔다.
    """
    from lemouton.pricing.settings import MarketUploadPolicy

    by_key = {m: (w, c, n) for m, w, c, n in CONFIRMED}

    fixed = 0
    # ① 내가 잘못 넣었던 값 교정 — **정확히 옛 값일 때만** 고친다.
    #    사장님이 화면에서 손댄 값이면 건드리지 않는다(값이 다르면 그냥 넘어감).
    for market, old_w, old_c in _CORRECTIONS:
        row = session.get(MarketUploadPolicy, market)
        if row is None or market not in by_key:
            continue
        if int(row.window_seconds) == old_w and int(row.max_count) == old_c:
            w, c, n = by_key[market]
            row.window_seconds, row.max_count, row.note = w, c, n
            fixed += 1
            _log.info("[market_rate_seed] %s 한도 교정 %ss/%s → %ss/%s",
                      market, old_w, old_c, w, c)

    # ② 없는 것만 넣는다.
    added = 0
    for market, window, count, note in CONFIRMED:
        if session.get(MarketUploadPolicy, market) is not None:
            continue
        session.add(MarketUploadPolicy(market=market, window_seconds=window,
                                       max_count=count, enabled=True, note=note))
        added += 1
    session.flush()
    if added:
        _log.info("[market_rate_seed] %d개 마켓 한도 시드", added)
    # ★ 호출자는 이 값이 0 이 아닐 때만 commit 한다.
    #   교정만 있고 추가가 없으면 0 을 돌려주던 탓에 교정이 날아갔었다 → 합쳐서 돌려준다.
    return added + fixed
