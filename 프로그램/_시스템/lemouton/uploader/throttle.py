"""업로드 속도 — 계정(API) 단위가 정본.

판매 계정마다 「1개당 최소 N초」(``seconds_per_item``). 한 마켓의 총 처리량은 그
마켓의 켜진 계정들 시간당 개수 합(= 총 스토어 업로드수)이고, 실제 전송 루프는 그
총량에서 파생한 '1개당 최소 간격'으로 연속 전송을 벌린다(마켓이 막는 것 방지).

계정 5개면 처리량 5배 → 간격 1/5. 정책 저장·조회는 :mod:`lemouton.pricing.settings`
의 ``AccountUploadPolicy`` / ``get_account_policies`` / ``set_account_policy``.

(구 P4 마켓 per_minute 정책 ``MarketUploadPolicy`` · ``market_send_allowance`` 는
폐기 — 이 계정 단위 정본으로 흡수. 업로드 속도 정본은 계정 하나뿐이다.)
"""
import time


def seconds_to_hourly(seconds_per_item) -> int:
    """1개당 초 → 시간당 개수. 0 이하는 1초로 방어."""
    return 3600 // max(1, int(seconds_per_item))


def market_hourly_total(session, market: str) -> int:
    """마켓의 켜진(enabled·활성) 계정들 시간당 개수 합 = 총 스토어 업로드수."""
    from lemouton.pricing.settings import get_account_policies
    return sum(p["per_hour"] for p in get_account_policies(session)
               if p["market"] == market and p["enabled"])


def market_min_interval_seconds(session, market: str) -> float:
    """그 마켓으로 연속 전송할 때 '1개당 최소 초 간격'.

    계정 정본에서 파생: 총 스토어 업로드수(=켜진 계정 시간당 합)로 3600초를 나눈다.
    계정 5개면 처리량 5배 → 간격 1/5. 켜진 계정이 없으면(총 0) 0.0(무대기) — 계정
    미설정 환경은 지금처럼 아무 지연 없이 동작한다.
    """
    total = market_hourly_total(session, market)
    return 3600.0 / total if total > 0 else 0.0


class IntervalPacer:
    """마켓별 '1개당 최소 초 간격'을 전송 사이에 강제하는 페이서.

    같은 마켓으로 연속 전송할 때 직전 전송 이후 흐른 시간이 간격보다 짧으면 그
    모자란 만큼만 대기한다. 첫 전송·간격 0(계정 없음)은 대기하지 않는다. 마켓별로
    직전 전송 시각을 따로 기억한다. ``sleep_fn``·``now_fn`` 주입 가능(테스트·드라이런).
    """

    def __init__(self, intervals: dict, *, sleep_fn=time.sleep, now_fn=time.monotonic):
        self._intervals = dict(intervals or {})
        self._sleep = sleep_fn
        self._now = now_fn
        self._last: dict = {}

    def wait(self, market: str) -> float:
        """``market`` 전송 직전에 호출. 실제로 대기한 초를 반환(없으면 0.0)."""
        interval = float(self._intervals.get(market, 0.0))
        waited = 0.0
        last = self._last.get(market)
        if interval > 0 and last is not None:
            elapsed = self._now() - last
            if elapsed < interval:
                waited = interval - elapsed
                self._sleep(waited)
        self._last[market] = self._now()
        return waited


def build_market_pacer(session, markets=("smartstore", "coupang"), *,
                       sleep_fn=time.sleep, now_fn=time.monotonic) -> IntervalPacer:
    """계정 정본에서 마켓별 최소 간격을 파생해 :class:`IntervalPacer` 생성."""
    intervals = {m: market_min_interval_seconds(session, m) for m in markets}
    return IntervalPacer(intervals, sleep_fn=sleep_fn, now_fn=now_fn)
