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

def test_쿠팡은_1초에_6개_실측(db):
    """2026-07-20 실측: 동시성8 에서 9.6 콜/s 무429 → ×0.7 = 6 콜/s.

    종전 5 는 데이터코드지도 문구였는데 실측이 더 넉넉했다.
    """
    seed_market_rates(db)
    assert get_market_rate(db, "coupang") == RateWindow(1, 6)
    assert text_of(get_market_rate(db, "coupang")) == "1초에 6개"


def test_스마트스토어는_2초에_5콜_실측(db):
    """실측: 동시성2 에서 3.5 콜/s 무429, 4 부터 429 → ×0.7 = 2.5 콜/s.

    1건 업로드 = 2콜(GET+PUT)이므로 건수로는 1.25 업로드/s.
    종전에는 한도 미설정이라 계정 수만 늘리면 무제한이었다.
    """
    seed_market_rates(db)
    assert get_market_rate(db, "smartstore") == RateWindow(2, 5)


def test_옥션_G마켓은_5초에_1개_그대로(db):
    seed_market_rates(db)
    assert get_market_rate(db, "auction") == RateWindow(5, 1)
    assert get_market_rate(db, "gmarket") == RateWindow(5, 1)


def test_모르는_마켓은_행을_안_만든다(db):
    """추정치를 넣으면 나중에 확인된 값인 줄 알고 쓴다."""
    seed_market_rates(db)
    # 롯데온·11번가는 **연동된 상품이 없어 측정 자체를 못 했다** → 여전히 미확인.
    for m in ("lotteon", "eleven11"):
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
    assert get_market_rate(db, "coupang") == RateWindow(1, 6)


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
    assert get_market_rate(db, "coupang") == RateWindow(1, 6)


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
    assert "실측" in note
    assert "2026-07-20" in note


# ── 한도 적용 범위(2026-07-21 계정별 실측 반영) ──────────────────────────

def test_쿠팡_스스는_계정별_스코프로_시드된다(db):
    """두 마켓은 라이브에서 계정별 확정 → limit_scope='account'.

    이래야 계정을 늘리면 총 처리량이 계정 수만큼 는다(전엔 마켓 전체로 묶여 손해).
    """
    from lemouton.pricing.settings import MarketUploadPolicy
    seed_market_rates(db)
    assert db.get(MarketUploadPolicy, "coupang").limit_scope == "account"
    assert db.get(MarketUploadPolicy, "smartstore").limit_scope == "account"


def test_옥션_G마켓은_공유_스코프_유지(db):
    """업로드 한도 미측정·계정별 여부 미확인 → 보수적으로 shared."""
    from lemouton.pricing.settings import MarketUploadPolicy
    seed_market_rates(db)
    assert db.get(MarketUploadPolicy, "auction").limit_scope == "shared"
    assert db.get(MarketUploadPolicy, "gmarket").limit_scope == "shared"


def test_이미_있는_쿠팡행도_스코프만_올린다(db):
    """사장님이 속도를 손댔어도 scope 는 새 칸이라 실측 사실로 올린다(속도는 보존)."""
    from lemouton.pricing.settings import MarketUploadPolicy
    db.add(MarketUploadPolicy(market="coupang", window_seconds=3, max_count=2,
                              enabled=True, limit_scope="shared", note="사장님 수기"))
    db.flush()
    seed_market_rates(db)
    row = db.get(MarketUploadPolicy, "coupang")
    assert row.limit_scope == "account"          # 실측 사실로 올림
    assert (row.window_seconds, row.max_count) == (3, 2)  # 사장님 속도는 보존


def test_계정별_스코프면_계정수만큼_총량_증가(db):
    """end-to-end: 쿠팡 계정 3개면 실효 속도가 마켓 천장의 3배까지 오른다."""
    from lemouton.pricing.settings import (
        MarketUploadPolicy, AccountUploadPolicy, market_effective_rate)
    from lemouton.sourcing.models_v2 import UploadAccount
    seed_market_rates(db)
    # 쿠팡 계정 3개 + 각 계정 정책을 마켓 천장 이상(1초 10개)으로
    for i in range(3):
        db.add(UploadAccount(market="coupang", env_prefix=f"COUPANG_{i}",
                             account_key=f"ck{i}", display_name=f"c{i}", is_active=True))
    db.flush()
    for a in db.query(UploadAccount).filter_by(market="coupang").all():
        db.add(AccountUploadPolicy(account_id=a.id, window_seconds=1, max_count=10,
                                   enabled=True))
    db.flush()
    eff = market_effective_rate(db, "coupang")
    # 계정당 천장 6 × 3계정 = 18 (공유였다면 6 으로 묶였을 것)
    assert eff["per_second"] == pytest.approx(18.0)
    assert eff["bound_by"] == "account_capped"
