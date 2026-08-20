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

# 「1건 업로드」에 실제로 나가는 API 호출 수.
#   스스(edit_options)·ESM(update_stock) 은 현재값을 GET 한 뒤 **전체를 PUT** 한다
#   → 1건에 2콜. 마켓 한도는 호출 수 기준이라 이걸 안 세면 한도의 2배로 나간다.
#   근거: shared/platforms/smartstore/edit_product.py:49 · esm/inventory.py:57
#   ★ scripts/ratelimit_probe/config.py 의 _CALLS_PER_UPLOAD 와 값이 같아야 한다
#     (tests/scripts/test_ratelimit_probe.py 가 일치를 고정한다).
_CALLS_PER_UPLOAD = {
    "coupang": 1,      # PUT .../vendor-items/{id}/quantities/{qty}
    "lotteon": 1,      # POST stock_change {itmStkLst:[...]}
    "eleven11": 1,     # update_stock_by_stock_no
    "smartstore": 2,   # GET 원상품 전체 → PUT 원상품 전체
    "auction": 2,      # GET recommended-options → PUT details 전체
    "gmarket": 2,
}


def calls_per_upload(market: str) -> int:
    """1건 업로드에 드는 API 호출 수. 모르는 마켓은 보수적으로 1."""
    return _CALLS_PER_UPLOAD.get(market, 1)


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

    ★ **계정 합산과 마켓 API 한도 중 느린 쪽** (2026-07-20 교정).
      전에는 계정 합산만 봤다. 그래서 화면은 "둘 중 느린 쪽으로 나갑니다"라고
      말하는데 실제 전송은 마켓 한도를 무시하고 **계정 수로 뚫고** 있었다.
      쿠팡 7계정이면 계정 합산이 마켓 한도를 넘는 순간 차단당한다.

    켜진 계정이 없으면 0.0(무대기) — 어차피 보낼 게 없고, 여기서 막으면
    호출부가 무한정 기다린다.
    """
    from lemouton.pricing.settings import market_effective_rate
    eff = market_effective_rate(session, market)
    iv = eff.get("interval_seconds")
    if iv is None or iv == float("inf"):
        return 0.0
    return float(iv)


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


def paced_markets(session) -> tuple:
    """페이서를 걸 마켓 = **계정이 등록된 모든 마켓**.

    ★ 2026-07-20: 전에는 ("smartstore","coupang") 로 **박혀 있었다**.
      롯데온·11번가·옥션·G마켓은 계정이 있어도 속도 제한 대상이 아니었다.
      마켓을 늘릴 때마다 여기를 고치는 걸 잊으면 그 마켓만 무제한이 된다
      → 계정에서 자동으로 뽑는다.
    """
    from lemouton.pricing.settings import get_account_policies
    return tuple(sorted({p["market"] for p in get_account_policies(session)}))


def build_market_pacer(session, markets=None, *,
                       sleep_fn=time.sleep, now_fn=time.monotonic) -> IntervalPacer:
    """마켓별 최소 간격(계정 합산 ∧ 마켓 한도)을 파생해 :class:`IntervalPacer` 생성.

    ``markets`` 를 안 주면 계정이 등록된 마켓 전부를 대상으로 한다.
    """
    if markets is None:
        markets = paced_markets(session)
    intervals = {m: market_min_interval_seconds(session, m) for m in markets}
    return IntervalPacer(intervals, sleep_fn=sleep_fn, now_fn=now_fn)
