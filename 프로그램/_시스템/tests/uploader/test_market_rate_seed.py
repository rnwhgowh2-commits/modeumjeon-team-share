"""마켓 API 한도 시드 + 잘못 넣었던 값 교정.

2026-07-19 사장님 "고쳐." — 쿠팡을 「60초에 50개」로 시드했는데 그건
**로켓그로스 주문조회 하나**의 한도였다. 업로드는 다른 API 라
게이트웨이 한도(5 req/s)가 맞다. 실제의 1/6 로 묶여 있었다.

★ 이 파일이 지키는 선: **사장님이 화면에서 고친 값은 재부팅이 되돌리지 않는다.**
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lemouton.pricing.settings import MarketUploadPolicy, get_market_rate
from lemouton.uploader.market_rate_seed import seed_market_rates
from lemouton.uploader.rate_window import RateWindow, text_of
from shared.db import Base


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _put(db, market, window, count, note=""):
    db.add(MarketUploadPolicy(market=market, window_seconds=window,
                              max_count=count, enabled=True, note=note))
    db.flush()


# ── 시드 ────────────────────────────────────────────────────────

def test_쿠팡은_1초에_5개(db):
    """게이트웨이 5 req/s. 주문조회 한도(분당 50회)를 쓰면 안 된다."""
    seed_market_rates(db)
    assert get_market_rate(db, "coupang") == RateWindow(1, 5)
    assert text_of(get_market_rate(db, "coupang")) == "1초에 5개"


def test_옥션_G마켓은_5초에_1개_그대로(db):
    seed_market_rates(db)
    assert get_market_rate(db, "auction") == RateWindow(5, 1)
    assert get_market_rate(db, "gmarket") == RateWindow(5, 1)


def test_모르는_마켓은_행을_안_만든다(db):
    """추정치를 넣으면 나중에 확인된 값인 줄 알고 쓴다."""
    seed_market_rates(db)
    for m in ("smartstore", "lotteon", "eleven11"):
        assert get_market_rate(db, m) is None


def test_두번_돌려도_늘지_않는다(db):
    seed_market_rates(db)
    n = db.query(MarketUploadPolicy).count()
    assert seed_market_rates(db) == 0
    assert db.query(MarketUploadPolicy).count() == n


# ── 🔴 교정 — 내가 넣었던 옛 값만 ────────────────────────────────

def test_내가_넣었던_60초에_50개는_고쳐진다(db):
    """라이브 재현 — 이미 시드가 끝난 DB 에 옛 값이 남아 있는 상태."""
    seed_market_rates(db)
    row = db.get(MarketUploadPolicy, "coupang")
    row.window_seconds, row.max_count = 60, 50      # 옛 값으로 되돌림
    db.flush()

    assert seed_market_rates(db) == 1               # 교정 1건, 신규 0건
    assert get_market_rate(db, "coupang") == RateWindow(1, 5)


def test_교정만_있어도_0이_아닌_값을_돌려준다(db):
    """★ 호출자가 이 값이 0 이면 commit 을 안 한다 — 0 이면 교정이 날아간다."""
    _put(db, "coupang", 60, 50)
    _put(db, "auction", 5, 1)
    _put(db, "gmarket", 5, 1)
    assert seed_market_rates(db) > 0      # 새로 넣은 건 없는데도


def test_사장님이_고친_값은_안_건드린다(db):
    """숫자가 1이라도 다르면 사람이 손댄 것이다."""
    _put(db, "coupang", 60, 40, "사장님이 조정")
    seed_market_rates(db)
    assert get_market_rate(db, "coupang") == RateWindow(60, 40)


def test_이미_고쳐진_값은_그대로(db):
    """교정이 끝난 뒤 재부팅해도 아무 일도 일어나지 않는다."""
    seed_market_rates(db)
    assert seed_market_rates(db) == 0
    assert get_market_rate(db, "coupang") == RateWindow(1, 5)


def test_교정은_쿠팡만_건드린다(db):
    _put(db, "coupang", 60, 50)
    _put(db, "auction", 60, 50)       # 우연히 같은 숫자여도
    seed_market_rates(db)
    assert get_market_rate(db, "auction") == RateWindow(60, 50)


def test_교정_후_note도_바뀐다(db):
    """옛 note 를 남겨두면 '분당 50회'가 근거인 줄 계속 읽는다."""
    _put(db, "coupang", 60, 50, "공식문서 인용 '분당 50회'")
    seed_market_rates(db)
    note = db.get(MarketUploadPolicy, "coupang").note
    assert "5 req/s" in note
    assert "게이트웨이" in note
