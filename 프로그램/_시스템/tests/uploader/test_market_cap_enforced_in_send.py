"""마켓 API 한도가 **실제 전송 경로**에서도 지켜지는가.

화면(`webapp/routes/bulk/send.py`)은 `market_effective_rate` 로 계정 합산과
마켓 한도 중 느린 쪽을 보여준다. 그런데 실제 전송 루프(`reconcile.py` ·
`scheduler/jobs.py`)는 `build_market_pacer` → `market_min_interval_seconds`
= **계정 합산만** 쓴다. 마켓 한도(MarketUploadPolicy)를 참조하지 않는다.

즉 화면에 「1초에 5개」라고 떠도 계정이 3개면 실제로는 그보다 빠르게 나간다.
이 테스트는 그 간극을 고정한다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _account(db, market: str, name: str):
    """활성 업로드 계정 1개.

    2026-07-20 상류(0f48e712)가 속도 정책의 주인을 ``market_accounts`` →
    ``upload_accounts`` 로 통일했다. 판매처 관리 화면이 쓰는 표가 이쪽이다.
    """
    from lemouton.sourcing.models_v2 import UploadAccount
    a = UploadAccount(account_key=f"{market}_{name}", display_name=name,
                      market=market, env_prefix=f"{market.upper()}_{name}",
                      is_active=True)
    db.add(a)
    db.flush()
    return a


def _account_rate(db, account_id: int, *, window_seconds: int, max_count: int):
    from lemouton.pricing.settings import set_account_rate
    set_account_rate(db, account_id, window_seconds=window_seconds,
                     max_count=max_count)
    db.flush()


def test_화면은_마켓한도로_캡을_씌운다(db):
    """기준선 — 화면 경로는 마켓 한도를 반영한다."""
    from lemouton.pricing.settings import set_market_rate, market_effective_rate

    # 계정 3개, 각 1초에 5개 → 계정 합산 15/s
    for i in range(3):
        a = _account(db, "coupang", f"쿠팡{i}")
        _account_rate(db, a.id, window_seconds=1, max_count=5)
    # 마켓 한도 1초에 5개
    set_market_rate(db, "coupang", window_seconds=1, max_count=5,
                    note="게이트웨이 5 req/s")
    db.flush()

    eff = market_effective_rate(db, "coupang")
    assert eff["per_second"] == pytest.approx(5.0), \
        f"화면 경로가 마켓 한도로 캡을 안 씌움: {eff}"
    assert eff["bound_by"] == "market"


def test_실제전송경로도_마켓한도를_지켜야_한다(db):
    """★ 핵심 — 계정 합산이 마켓 한도를 **넘는** 상황을 만든다.

    계정 속도는 seconds_per_item ≥ 1 로 클램프돼 계정당 최대 1/s 다.
    따라서 한도를 넘기려면 계정 수 > 한도여야 한다.
    롯데온 실제 구성(7계정)에 마켓 한도 1초에 5개를 걸어 재현한다.
    """
    from lemouton.pricing.settings import set_market_rate, market_effective_rate
    from lemouton.uploader.throttle import market_min_interval_seconds

    for i in range(7):                       # 롯데온 실제 계정 수
        a = _account(db, "lotteon", f"롯데온{i}")
        _account_rate(db, a.id, window_seconds=1, max_count=1)   # 계정당 1초에 1개
    set_market_rate(db, "lotteon", window_seconds=1, max_count=5,
                    note="가정: 마켓 한도 1초에 5개")
    db.flush()

    # 화면 경로는 5/s 로 캡을 씌운다 (기준선)
    eff = market_effective_rate(db, "lotteon")
    assert eff["per_second"] == pytest.approx(5.0)
    assert eff["bound_by"] == "market"

    # 실제 전송 경로: 계정 합산 7/s → 간격 0.143초. 한도(0.2초)를 어긴다.
    interval = market_min_interval_seconds(db, "lotteon")
    assert interval >= 0.2 - 1e-9, (
        f"실제 전송 간격이 {interval:.4f}초 — 마켓 한도(1초에 5개=0.2초)를 무시하고 "
        f"계정 합산(7/s)으로 나간다. 화면은 5/s 라고 표시하는데 실제는 7/s. "
        f"마켓이 429 로 막을 속도다."
    )


def test_옥션은_계정_1개만_있어도_이미_한도를_5배_넘는다(db):
    """★ 지금 당장의 실제 위험 — 가정이 아니라 시드된 실제 값으로 재현.

    시드값: 옥션·G마켓 = 5초에 1개(0.2/s, 공식문서 인용).
    계정 속도 최소 단위는 1초에 1개(1/s) 라서, **계정이 하나만 있어도** 실제
    전송은 1/s 로 나간다 = 한도의 5배.
    """
    from lemouton.uploader.market_rate_seed import seed_market_rates
    from lemouton.pricing.settings import market_effective_rate
    from lemouton.uploader.throttle import market_min_interval_seconds

    seed_market_rates(db)                       # 실제 시드값 그대로
    a = _account(db, "auction", "옥션본계")
    _account_rate(db, a.id, window_seconds=1, max_count=1)
    db.flush()

    # 시드는 「5초에 1콜」 = 0.2 콜/s. 옥션은 1건에 2콜이므로 건수로는 0.1건/s.
    from lemouton.pricing.settings import get_market_rate
    from lemouton.uploader.rate_window import per_second
    assert per_second(get_market_rate(db, "auction")) == pytest.approx(0.2), \
        "시드값이 5초에 1콜이 아님"

    eff = market_effective_rate(db, "auction")
    assert eff["per_second"] == pytest.approx(0.1), \
        f"콜↔건 환산이 안 됨 (1건=2콜인데 {eff['per_second']}건/s)"

    interval = market_min_interval_seconds(db, "auction")
    actual_per_sec = 1.0 / interval if interval > 0 else float("inf")
    assert actual_per_sec <= 0.1 + 1e-9, (
        f"옥션 실제 전송 {actual_per_sec:.2f}건/s vs 한도 0.1건/s "
        f"— 계정 1개만으로 이미 {actual_per_sec / 0.1:.0f}배 초과."
    )


def test_2콜_마켓은_한도의_절반_속도로_보낸다(db):
    """스스·ESM 은 1건 업로드에 GET+PUT 2콜 — 한도를 반으로 나눠 써야 한다.

    marketplace 한도는 **API 호출 수** 기준이다. 1건에 2콜이 드는 마켓에서
    한도를 그대로 건수로 쓰면 실제 호출은 2배로 나가 429 를 맞는다.
    """
    from lemouton.pricing.settings import set_market_rate
    from lemouton.uploader.throttle import market_min_interval_seconds

    for i in range(4):                                          # 계정 합산 4/s
        a = _account(db, "smartstore", f"스스{i}")
        _account_rate(db, a.id, window_seconds=1, max_count=1)
    set_market_rate(db, "smartstore", window_seconds=1, max_count=4,
                    note="가정: 1초에 4콜")
    db.flush()

    # 1건 = 2콜 → 업로드 가능 건수는 1초에 2건 → 간격 0.5초.
    # 호출배수를 안 세면 계정 합산 4/s(0.25초)로 나가 실제 호출은 8콜/s = 한도의 2배.
    interval = market_min_interval_seconds(db, "smartstore")
    assert interval >= 0.5 - 1e-9, (
        f"간격 {interval:.4f}초 — 1건당 2콜을 안 세서 한도의 2배로 나간다")


def test_한도가_없는_마켓은_계정_합산_그대로(db):
    """미확인 마켓(행 없음)은 지금 동작을 바꾸지 않는다 — 회귀 방지."""
    from lemouton.uploader.throttle import market_min_interval_seconds

    a = _account(db, "eleven11", "11번가본계")
    _account_rate(db, a.id, window_seconds=1, max_count=1)
    db.flush()

    # MarketUploadPolicy 행이 없으므로 계정 합산(1/s = 1.0초) 그대로여야 한다
    assert market_min_interval_seconds(db, "eleven11") == pytest.approx(1.0)


def test_계정이_없으면_대기하지_않는다(db):
    """계정 미설정 환경은 종전처럼 무대기 — 회귀 방지."""
    from lemouton.pricing.settings import set_market_rate
    from lemouton.uploader.throttle import market_min_interval_seconds

    set_market_rate(db, "coupang", window_seconds=1, max_count=5, note="x")
    db.flush()
    # 계정이 없으면 보낼 것도 없다. 마켓 한도가 있어도 간격을 만들지 않는다.
    assert market_min_interval_seconds(db, "coupang") == 0.0
