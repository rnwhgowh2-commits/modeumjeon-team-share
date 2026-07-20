"""계정 배선 통일 — 속도 정책의 주인 = 판매처 관리의 upload_accounts.

2026-07-20 사장님 「가」. 라이브에서 판매처 관리 계정 **30개**인데 속도 정책이
**0개**로 보이던 문제. 원인은 표가 둘로 갈라진 것:

    판매처 관리 화면  →  upload_accounts   (실제 API 키가 붙은 계정)
    속도 정책        →  market_accounts   (일회성 스크립트만 채움 = 영원히 0)

★ 이 파일이 지키는 선 3가지
  ① 판매처 관리에 계정을 넣으면 속도 정책이 그걸 본다
  ② 계정 0개일 때 무제한으로 쏘지 않는다는 걸 명시 (지금은 무대기가 의도된 동작)
  ③ **마켓 API 한도를 계정 수로 뚫지 않는다** — 전에는 뚫고 있었다
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lemouton.pricing.settings import (
    AccountUploadPolicy,
    get_account_policies,
    market_effective_rate,
    set_market_rate,
)
from lemouton.sourcing.models_v2 import UploadAccount
from lemouton.uploader.throttle import (
    build_market_pacer,
    market_hourly_total,
    market_min_interval_seconds,
    paced_markets,
)
from shared.db import Base


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _acc(db, market, name, *, active=True):
    a = UploadAccount(account_key=f"{market}_{name}", display_name=name,
                      market=market, env_prefix=f"{market}_{name}".upper(),
                      is_active=active)
    db.add(a)
    db.flush()
    return a


# ── ① 판매처 관리 계정을 본다 ───────────────────────────────────

def test_판매처관리_계정이_속도정책에_잡힌다(db):
    """이게 깨져 있었다 — 계정 30개인데 정책 0개."""
    _acc(db, "coupang", "브랜드박스")
    pols = get_account_policies(db)
    assert [p["market"] for p in pols] == ["coupang"]
    assert pols[0]["account_name"] == "브랜드박스"


def test_옛_market_accounts_는_이제_안_본다(db):
    """옛 표에 행이 있어도 속도 정책에 영향이 없어야 한다."""
    from lemouton.multitenancy.models import MarketAccount
    db.add(MarketAccount(market="coupang", account_name="옛계정",
                         credentials_encrypted="x", is_active=True))
    db.flush()
    assert get_account_policies(db) == []


def test_꺼진_계정은_빠진다(db):
    _acc(db, "coupang", "쓰는계정")
    _acc(db, "coupang", "안쓰는계정", active=False)
    assert [p["account_name"] for p in get_account_policies(db)] == ["쓰는계정"]


def test_롯데온_11번가도_대상이다(db):
    """페이서 대상이 스스·쿠팡으로 박혀 있어서 나머지는 무제한이었다."""
    for m in ("smartstore", "coupang", "lotteon", "eleven11", "auction", "gmarket"):
        _acc(db, m, "계정")
    assert paced_markets(db) == ("auction", "coupang", "eleven11",
                                 "gmarket", "lotteon", "smartstore")
    pacer = build_market_pacer(db)
    for m in ("lotteon", "eleven11"):
        assert pacer._intervals[m] > 0, f"{m} 이 무제한이다"


# ── ② 계정이 없을 때 ────────────────────────────────────────────

def test_계정이_없으면_무대기다(db):
    """★ 의도된 동작이지만 **브레이크가 없다는 뜻**이다.

    계정 0 + 실전송 ON 이면 속도 제한 없이 나간다. 여기서 막으면 호출부가
    무한정 기다리므로 0 을 유지하되, 이 사실을 테스트로 드러내 둔다.
    """
    assert market_hourly_total(db, "coupang") == 0
    assert market_min_interval_seconds(db, "coupang") == 0.0


# ── ③ 🔴 마켓 한도를 계정 수로 뚫지 않는다 ──────────────────────

def test_계정이_많아도_마켓_한도를_못_넘는다(db):
    """전에는 계정 합산만 봐서 뚫고 있었다 — 화면 문구와 실제가 달랐다.

    쿠팡 한도 1초에 5개인데 계정 10개(각 6초에 1개)면 합산 10/6 ≈ 1.67개/초
    → 한도 안. 계정을 60개로 늘리면 합산 10개/초 > 한도 5개/초 → 한도가 이긴다.
    """
    set_market_rate(db, "coupang", window_seconds=1, max_count=5)
    for i in range(60):
        a = _acc(db, "coupang", f"계정{i}")
        db.add(AccountUploadPolicy(account_id=a.id, seconds_per_item=6, enabled=True))
    db.flush()

    eff = market_effective_rate(db, "coupang")
    assert eff["bound_by"] == "market"
    assert eff["per_second"] == pytest.approx(5.0)
    # 1초에 5개 = 1개당 0.2초
    assert market_min_interval_seconds(db, "coupang") == pytest.approx(0.2)


def test_한도가_느슨하면_계정_합산이_이긴다(db):
    set_market_rate(db, "coupang", window_seconds=1, max_count=100)
    for i in range(2):
        a = _acc(db, "coupang", f"계정{i}")
        db.add(AccountUploadPolicy(account_id=a.id, seconds_per_item=6, enabled=True))
    db.flush()
    eff = market_effective_rate(db, "coupang")
    assert eff["bound_by"] == "account"
    assert market_min_interval_seconds(db, "coupang") == pytest.approx(3.0)


def test_정책행이_아직_없어도_계정있음으로_친다(db):
    """정책 행이 없다고 빼버리면 계정이 있는데 '보낼 수 없음'으로 보인다."""
    _acc(db, "lotteon", "새계정")
    eff = market_effective_rate(db, "lotteon")
    assert eff["bound_by"] != "no_account"
    # 시드될 기본값(6초에 1개)과 같아야 한다 — 시드 전후로 숫자가 달라지면 안 된다
    assert eff["per_second"] == pytest.approx(1 / 6)
    get_account_policies(db)          # 시드
    assert market_effective_rate(db, "lotteon")["per_second"] == pytest.approx(1 / 6)
