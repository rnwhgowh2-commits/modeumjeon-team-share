"""업로드 속도 —「X초에 Y개」. 계정별 + 마켓별 두 겹.

사장님 확정 (2026-07-19, 3번 = 나):
  "계정별로 X초에 Y개 해야 함. 그리고 판매처 마켓별로도 API 전송 고려해서 수기로 수정 가능해야 함."

■ 왜 두 겹인가
  · 계정별 — 우리가 그 계정으로 얼마나 빨리 쏠지
  · 마켓별 — **그 마켓 API 자체의 한도**. 계정이 몇 개든 마켓 전체로 묶인다.
    (실제 확인분: 쿠팡 분당 50회 · 옥션·G마켓 5초당 1회)
  실제 속도 = 둘 중 **더 느린 쪽**. 마켓 한도를 계정 수로 뚫으면 차단당한다.
"""
import pytest

from lemouton.uploader.rate_window import (
    RateWindow,
    effective_rate,
    per_second,
    text_of,
)


# ── RateWindow 기본 ─────────────────────────────────────────────

def test_1초에_10개면_초당_10():
    assert per_second(RateWindow(1, 10)) == pytest.approx(10.0)


def test_10초에_30개면_초당_3():
    """짧은 창으로는 표현 못 하는 한도 — 이게 「X초에 Y개」가 필요한 이유다."""
    assert per_second(RateWindow(10, 30)) == pytest.approx(3.0)


def test_60초에_50개는_쿠팡_분당50회():
    assert per_second(RateWindow(60, 50)) == pytest.approx(50 / 60)


def test_5초에_1개는_ESM():
    assert per_second(RateWindow(5, 1)) == pytest.approx(0.2)


def test_창이_0이하면_거부():
    with pytest.raises(ValueError):
        RateWindow(0, 10)
    with pytest.raises(ValueError):
        RateWindow(-1, 10)


def test_개수가_0이하면_거부():
    """0개 = 아예 못 보냄. 속도 설정이 아니라 '끄기'라서 enabled 로 다뤄야 한다."""
    with pytest.raises(ValueError):
        RateWindow(1, 0)


def test_사람이_읽는_문구():
    assert text_of(RateWindow(1, 10)) == "1초에 10개"
    assert text_of(RateWindow(60, 50)) == "60초에 50개"
    assert text_of(RateWindow(5, 1)) == "5초에 1개"


# ── 🔴 계정별 + 마켓별 = 느린 쪽 ────────────────────────────────

def test_마켓_한도가_더_빡빡하면_마켓이_이긴다():
    """계정 5개 × 초당 10개 = 초당 50개인데, 쿠팡 분당 50회(초당 0.83)가 한도다."""
    r = effective_rate(account_rates=[RateWindow(1, 10)] * 5,
                       market_rate=RateWindow(60, 50))
    assert r["per_second"] == pytest.approx(50 / 60)
    assert r["bound_by"] == "market"


def test_계정_합이_더_느리면_계정이_이긴다():
    r = effective_rate(account_rates=[RateWindow(10, 1)],
                       market_rate=RateWindow(1, 100))
    assert r["per_second"] == pytest.approx(0.1)
    assert r["bound_by"] == "account"


def test_계정이_늘면_합산된다():
    r = effective_rate(account_rates=[RateWindow(1, 2), RateWindow(1, 3)],
                       market_rate=None)
    assert r["per_second"] == pytest.approx(5.0)
    assert r["bound_by"] == "account"


def test_마켓_한도가_없으면_계정_합이_그대로():
    r = effective_rate(account_rates=[RateWindow(1, 4)], market_rate=None)
    assert r["per_second"] == pytest.approx(4.0)
    assert r["bound_by"] == "account"


def test_계정이_하나도_없으면_0(다시=None):
    """계정 미설정 = 보낼 수단이 없다. 0 이지 '무제한'이 아니다."""
    r = effective_rate(account_rates=[], market_rate=RateWindow(1, 10))
    assert r["per_second"] == 0.0
    assert r["bound_by"] == "no_account"


def test_같으면_마켓을_적는다():
    """딱 같을 때 어느 쪽이 묶는지 애매하면 안 된다 — 마켓(바깥 제약)으로 고정."""
    r = effective_rate(account_rates=[RateWindow(1, 5)], market_rate=RateWindow(1, 5))
    assert r["bound_by"] == "market"


# ── 간격 환산 ───────────────────────────────────────────────────

def test_초당_개수를_간격초로_바꾼다():
    r = effective_rate(account_rates=[RateWindow(1, 4)], market_rate=None)
    assert r["interval_seconds"] == pytest.approx(0.25)


def test_0이면_간격은_무한대():
    """0으로 나누지 않는다. '못 보냄'을 0초 간격(무한 속도)으로 뒤집으면 사고다."""
    r = effective_rate(account_rates=[], market_rate=None)
    assert r["interval_seconds"] == float("inf")


# ── 옛 설정에서 옮겨오기 ────────────────────────────────────────

def test_옛_seconds_per_item_을_그대로_읽는다():
    """기존 계정 설정(1개당 N초)은 「N초에 1개」와 같은 뜻이다."""
    from lemouton.uploader.rate_window import from_seconds_per_item
    assert from_seconds_per_item(3) == RateWindow(3, 1)
    assert per_second(from_seconds_per_item(3)) == pytest.approx(1 / 3)


def test_옛_값이_0이하여도_안전하게_1초1개():
    from lemouton.uploader.rate_window import from_seconds_per_item
    assert from_seconds_per_item(0) == RateWindow(1, 1)
    assert from_seconds_per_item(None) == RateWindow(1, 1)
