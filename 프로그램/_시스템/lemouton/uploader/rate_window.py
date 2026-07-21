"""업로드 속도 —「X초에 Y개」. 계정별 + 마켓별 두 겹.

사장님 확정 (2026-07-19):
  "계정별로 X초에 Y개 해야 함. 그리고 판매처 마켓별로도 API 전송 고려해서
   수기로 수정 가능해야 함."

━━ 왜 「X초에 Y개」인가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  기존 설정은 계정별 **「1개당 몇 초」**(정수, 최소 1초)였다.
  그래서 한 계정은 **초당 1개가 최대**였고, 「1초에 10개」를 쓸 방법이 없었다.
  반대로 「10초에 30개」처럼 **순간 몰림을 허용하는 한도**도 담지 못했다.
  창(초) + 개수 두 칸이면 둘 다 표현된다.

━━ 왜 두 겹인가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  · 계정별 — 우리가 그 계정으로 얼마나 빨리 쏠지 (계정이 늘면 합산)
  · 마켓별 — **그 마켓 API 자체의 한도.** 계정이 몇 개든 마켓 전체로 묶인다.

  실제 확인된 마켓 한도(2026-07-19 조사):
      쿠팡        60초에 50개   (로켓그로스 주문 조회)
      옥션·G마켓   5초에 1개     (주문 조회)
      나머지      미확인

  ★ 실제 속도 = 둘 중 **더 느린 쪽**. 마켓 한도를 계정 수로 뚫으면 차단당한다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateWindow:
    """「window_seconds 초에 max_count 개」.

    (NamedTuple 이 아니라 frozen dataclass — NamedTuple 은 __new__ 에서 검증을 못 건다.)
    """

    window_seconds: float
    max_count: int

    def __post_init__(self):
        w, n = float(self.window_seconds), int(self.max_count)
        if w <= 0:
            raise ValueError(f"창(초)은 0보다 커야 합니다: {self.window_seconds}")
        if n <= 0:
            # 0개 = 아예 못 보냄. 그건 속도가 아니라 '끄기'라서 enabled 로 다뤄야 한다.
            raise ValueError(
                f"개수는 0보다 커야 합니다: {self.max_count} — 끄려면 enabled 를 쓰세요")
        object.__setattr__(self, "window_seconds", w)
        object.__setattr__(self, "max_count", n)


def per_second(rw: RateWindow) -> float:
    """초당 몇 개."""
    return rw.max_count / rw.window_seconds


def text_of(rw: RateWindow) -> str:
    """사람이 읽는 문구."""
    w = int(rw.window_seconds) if float(rw.window_seconds).is_integer() else rw.window_seconds
    return f"{w}초에 {rw.max_count}개"


def from_seconds_per_item(seconds) -> RateWindow:
    """옛 설정(1개당 N초) → RateWindow. 「N초에 1개」와 같은 뜻이다.

    0 이하·None 은 안전하게 「1초에 1개」 — 옛 코드의 `max(1, int(...))` 와 같은 방향.
    """
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        s = 0
    return RateWindow(max(1, s), 1)


def effective_rate(*, account_rates, market_rate, market_scope="shared") -> dict:
    """실제로 나갈 속도. 계정 합산과 마켓 한도 중 **느린 쪽**.

    Args:
        account_rates: 켜진 계정들의 RateWindow 목록 (없으면 빈 목록).
        market_rate: 그 마켓의 API 한도 RateWindow. 모르면 None.
        market_scope: 마켓 한도의 적용 범위.
            'shared'  — 계정 몇 개든 **마켓 전체**로 묶는 공유 천장(기본, 옛 동작).
            'account' — 마켓 한도가 **계정당 천장**. 계정마다 min(계정속도, 마켓)을 쓰고
                        합산한다(공유 천장 없음).
                        근거: 2026-07-21 라이브 실측 — 쿠팡·스마트스토어는 계정별 한도라
                        두 계정 동시 발사 시 각자 제 속도 유지, 합=2배(계정 수만큼 증가).

    Returns:
        {'per_second', 'interval_seconds', 'bound_by'}
        bound_by ∈ 'account' | 'market' | 'account_capped' | 'no_account'
          account_capped = 계정별 스코프에서 일부 계정이 마켓 계정당 천장에 걸린 경우.
    """
    rates = list(account_rates or [])
    acc_total = sum(per_second(r) for r in rates)
    if acc_total <= 0:
        # 계정이 없으면 보낼 수단이 없다 — 0 이지 '무제한'이 아니다.
        return {"per_second": 0.0, "interval_seconds": float("inf"),
                "bound_by": "no_account"}

    if market_rate is None:
        eff, by = acc_total, "account"
    elif market_scope == "account":
        # 마켓 한도 = 계정당 천장. 계정마다 min 을 취해 합산(공유 천장 없음).
        cap = per_second(market_rate)
        eff = sum(min(per_second(r), cap) for r in rates)
        capped = any(per_second(r) > cap for r in rates)
        by = "account_capped" if capped else "account"
    else:
        mk = per_second(market_rate)
        # 같으면 마켓(바깥 제약)으로 적는다 — 어느 쪽이 묶는지 애매하면 안 된다.
        eff, by = (acc_total, "account") if acc_total < mk else (mk, "market")

    return {"per_second": eff,
            "interval_seconds": (1.0 / eff) if eff > 0 else float("inf"),
            "bound_by": by}
