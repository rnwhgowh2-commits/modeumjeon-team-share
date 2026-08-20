"""업로드 속도 저장 — 계정별 「X초에 Y개」 + 마켓별 API 한도.

사장님 확정 (2026-07-19): "계정별로 X초에 Y개. 마켓별로도 API 전송 고려해 수기 수정 가능."
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lemouton.pricing.settings import (
    AccountUploadPolicy,
    account_rate_window,
    get_market_rate,
    set_account_rate,
    set_market_rate,
)
from lemouton.uploader.rate_window import RateWindow, per_second
from shared.db import Base


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


# ── 계정별 ──────────────────────────────────────────────────────

def test_계정_속도를_X초에_Y개로_저장한다(db):
    set_account_rate(db, 1, window_seconds=1, max_count=10)
    db.flush()
    assert account_rate_window(db.get(AccountUploadPolicy, 1)) == RateWindow(1, 10)


def test_10초에_30개도_담긴다(db):
    """옛 구조로는 표현 못 하던 「순간 몰림 허용」."""
    set_account_rate(db, 1, window_seconds=10, max_count=30)
    db.flush()
    assert per_second(account_rate_window(db.get(AccountUploadPolicy, 1))) == pytest.approx(3.0)


def test_새_칸이_비면_옛_칸에서_읽는다(db):
    """기존 행은 window/max 가 NULL 이다 — 그래도 그대로 돌아야 한다."""
    db.add(AccountUploadPolicy(account_id=9, seconds_per_item=3, enabled=True))
    db.flush()
    assert account_rate_window(db.get(AccountUploadPolicy, 9)) == RateWindow(3, 1)


def test_옛_칸도_같이_맞춰_둔다(db):
    """둘이 어긋나면 어느 게 진짜인지 알 수 없게 된다."""
    set_account_rate(db, 1, window_seconds=1, max_count=4)   # 초당 4개
    db.flush()
    assert db.get(AccountUploadPolicy, 1).seconds_per_item == 1   # round(1/4)=0 → 최소 1


def test_느린_설정은_옛_칸에_그대로_반영(db):
    set_account_rate(db, 1, window_seconds=10, max_count=1)   # 10초에 1개
    db.flush()
    assert db.get(AccountUploadPolicy, 1).seconds_per_item == 10


def test_잘못된_값은_저장_거부(db):
    with pytest.raises(ValueError):
        set_account_rate(db, 1, window_seconds=0, max_count=10)
    with pytest.raises(ValueError):
        set_account_rate(db, 1, window_seconds=1, max_count=0)


def test_거부되면_행이_안_생긴다(db):
    """검증이 쓰기 전에 끝나야 한다 — 반쪽 행이 남으면 안 된다."""
    with pytest.raises(ValueError):
        set_account_rate(db, 77, window_seconds=1, max_count=0)
    assert db.get(AccountUploadPolicy, 77) is None


# ── 마켓별 ──────────────────────────────────────────────────────

def test_마켓_한도를_저장한다(db):
    set_market_rate(db, "coupang", window_seconds=60, max_count=50,
                    note="공식문서 확인 2026-07")
    db.flush()
    assert get_market_rate(db, "coupang") == RateWindow(60, 50)


def test_ESM_5초에_1개도_담긴다(db):
    set_market_rate(db, "auction", window_seconds=5, max_count=1)
    db.flush()
    assert per_second(get_market_rate(db, "auction")) == pytest.approx(0.2)


def test_한도가_없는_마켓은_None(db):
    """모르는 걸 '무제한'이 아니라 '미설정'으로 돌려준다."""
    assert get_market_rate(db, "smartstore") is None


def test_끄면_None(db):
    set_market_rate(db, "coupang", window_seconds=60, max_count=50, enabled=False)
    db.flush()
    assert get_market_rate(db, "coupang") is None


def test_다시_저장하면_덮어쓴다(db):
    set_market_rate(db, "coupang", window_seconds=60, max_count=50)
    db.flush()
    set_market_rate(db, "coupang", window_seconds=60, max_count=30)
    db.flush()
    assert get_market_rate(db, "coupang") == RateWindow(60, 30)


def test_마켓키가_비면_거부(db):
    with pytest.raises(ValueError):
        set_market_rate(db, "  ", window_seconds=1, max_count=1)


def test_깨진_값이_저장돼_있어도_화면이_안_죽는다(db):
    """직접 DB 를 건드린 경우 등. None(미설정)으로 다뤄 화면을 살린다."""
    from lemouton.pricing.settings import MarketUploadPolicy
    db.add(MarketUploadPolicy(market="broken", window_seconds=0, max_count=0, enabled=True))
    db.flush()
    assert get_market_rate(db, "broken") is None
