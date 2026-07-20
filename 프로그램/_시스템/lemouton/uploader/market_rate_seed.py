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

# ── 실측 상한 (2026-07-20 라이브 측정, 안전마진 적용 전) ──────────────────
#   무변화 재고갱신을 동시 호출로 밀어올려 429 가 나기 직전까지 확인한 값.
#   단위는 **API 호출/초**. 1건 업로드에 드는 콜 수는 throttle.calls_per_upload 참조.
#   측정 안 한 마켓은 넣지 않는다 — 추정값을 넣으면 나중에 확인된 값인 줄 알고 쓴다.
MEASURED_MAX: dict[str, float] = {
    # 쿠팡: 동시성 8 에서 9.61 콜/s 무429. 동시성 10 부터 429 발생(161건 중 1건),
    #       동시성 32 에서 429 27/149. → 클린 상한 ≈ 9.6 콜/s
    "coupang": 9.6,
    # 스마트스토어: 동시성 2 에서 1.78 업로드/s(=3.56 콜/s) 무429.
    #       동시성 4 부터 429 24/51, 8 은 74/104, 16 은 170/198 —
    #       동시성을 4배 올려도 **성공 처리량이 ~2 업로드/s 에 고정**됐다.
    #       → 클린 상한 ≈ 3.5 콜/s (1건=2콜이므로 1.78 업로드/s)
    "smartstore": 3.5,
}

# (market, window_seconds, max_count, note)  ※ max_count 는 **API 호출 수**
CONFIRMED: list[tuple[str, int, int, str]] = [
    # 실측 9.6 콜/s × 안전마진 0.7 = 6.7 → 6 콜/s.
    #   종전 값(5 콜/s)은 데이터코드지도의 게이트웨이 문구였는데, 실측이 그보다 넉넉했다.
    ("coupang", 1, 6,
     "업로드 실측 2026-07-20: 동시성8 에서 9.6 콜/s 무429, 동시성10 부터 429 → ×0.7"),
    # 실측 3.5 콜/s × 0.7 = 2.45 → 「2초에 5콜」 = 2.5 콜/s = 1.25 업로드/s.
    #   종전에는 **한도 미설정**이라 계정 수만 늘리면 무제한이었다.
    ("smartstore", 2, 5,
     "업로드 실측 2026-07-20: 동시성2 에서 3.5 콜/s 무429, 동시성4 부터 429 → ×0.7"),
    # ⚠️ 옥션·G마켓은 **업로드 미측정**. 아래는 여전히 「주문조회」 한도를 빌려온 값이라
    #    업로드가 실제로 이만큼 느릴 근거가 없다. 연동된 상품이 없어 측정을 못 했다.
    ("auction", 5, 1,
     "공식문서 인용 '5초당 1회' — ESM 주문 조회 (업로드 한도 아님·미측정)"),
    ("gmarket", 5, 1,
     "공식문서 인용 '5초당 1회' — ESM 주문 조회 (업로드 한도 아님·미측정)"),
]

# 내가 잘못 넣었던 값 → 고칠 값. **정확히 이 값일 때만** 고친다.
#   사장님이 화면에서 손댄 값은 절대 건드리지 않는다.
_CORRECTIONS: list[tuple[str, int, int]] = [
    # (market, 옛 window, 옛 max) — 2026-07-19: 주문조회 한도를 게이트웨이 한도로 오인
    ("coupang", 60, 50),
    # 2026-07-20: 지도 문구(5 콜/s) → 실측 반영(6 콜/s)
    ("coupang", 1, 5),
]

# 모르는 마켓 — 일부러 비워 둔다. 화면이 '미확인'으로 말한다.
#   롯데온·11번가는 **연동된 상품이 없어** 측정 자체를 못 했다(추정 금지).
UNKNOWN = ("lotteon", "eleven11")


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
