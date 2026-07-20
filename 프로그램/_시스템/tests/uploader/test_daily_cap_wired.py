"""하루 상한이 **실제 전송 경로에** 붙었는지.

2026-07-20 발견: decide_cap·coalesce_pending 을 만들어 뒀는데 **부르는 곳이
0개**였다. 즉 변동이 생길 때마다 전부 마켓에 나가고 있었다.

━━ 사장님 확정 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  "여유가 되면 바로바로. 다만 너무 많으면 상품별로 하루 최대 2회까지."
  "품절은 빠르게 무조건 빼야 함."

★ 막힌 건 **버리는 게 아니라 대기**(hold)다. 다음 슬롯에 최신 값으로 나간다.
"""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lemouton.uploader.daily_cap import CapConfig
from lemouton.uploader.daily_cap_service import (
    KST,
    decide_for_plan,
    is_sold_out,
    kst_day_start_utc,
    used_today,
)
from lemouton.uploader.models import PriceSnapshot
from shared.db import Base


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _snap(db, *, sku="SKU1", market="coupang", account="default",
          uploaded_at=None, action="upload"):
    db.add(PriceSnapshot(canonical_sku=sku, market=market, account_key=account,
                         action=action, uploaded_at=uploaded_at))
    db.flush()


# ── 「하루」는 한국 날짜 ─────────────────────────────────────────

def test_한국_자정부터_센다():
    """UTC 자정으로 세면 한국 오전 9시에 상한이 풀린다 — 사장님이 보는 하루와 다르다."""
    now = _dt.datetime(2026, 7, 20, 8, 0, tzinfo=KST)       # 한국 오전 8시
    start = kst_day_start_utc(now)
    assert start == _dt.datetime(2026, 7, 19, 15, 0)         # = 7/20 00:00 KST


def test_한국_새벽_1시도_오늘이다():
    now = _dt.datetime(2026, 7, 20, 1, 0, tzinfo=KST)
    assert kst_day_start_utc(now) == _dt.datetime(2026, 7, 19, 15, 0)


def test_어제_업로드는_안_센다(db):
    now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=KST)
    _snap(db, uploaded_at=_dt.datetime(2026, 7, 19, 14, 0))   # = 7/19 23시 KST
    _snap(db, uploaded_at=_dt.datetime(2026, 7, 19, 16, 0))   # = 7/20 01시 KST
    assert used_today(db, canonical_sku="SKU1", market="coupang", now=now) == 1


# ── 무엇을 세는가 ───────────────────────────────────────────────

def test_안_나간_건은_안_센다(db):
    """skip·hold 는 마켓을 건드린 적이 없다 → 상한을 쓰지 않았다."""
    now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=KST)
    _snap(db, action="skip", uploaded_at=None)
    _snap(db, action="hold", uploaded_at=None)
    assert used_today(db, canonical_sku="SKU1", market="coupang", now=now) == 0


def test_마켓별로_따로_센다(db):
    now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=KST)
    t = _dt.datetime(2026, 7, 20, 1, 0)
    _snap(db, market="coupang", uploaded_at=t)
    _snap(db, market="smartstore", uploaded_at=t)
    assert used_today(db, canonical_sku="SKU1", market="coupang", now=now) == 1


def test_계정별로_따로_센다(db):
    now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=KST)
    t = _dt.datetime(2026, 7, 20, 1, 0)
    _snap(db, account="A", uploaded_at=t)
    _snap(db, account="B", uploaded_at=t)
    assert used_today(db, canonical_sku="SKU1", market="coupang",
                      account_key="A", now=now) == 1


# ── 🔴 재고 센티넬 — 확인불가를 품절로 오인하면 멀쩡한 상품이 내려간다 ──

def test_0만_품절이다():
    assert is_sold_out(0) is True


def test_확인불가는_품절이_아니다():
    """-1 = 확인 불가. 크롤 실패를 품절로 읽으면 팔 수 있는 걸 뺀다."""
    assert is_sold_out(-1) is None
    assert is_sold_out(None) is None


def test_있음은_품절이_아니다():
    assert is_sold_out(999) is False
    assert is_sold_out(3) is False


# ── 상한 판정 (이력 기반) ───────────────────────────────────────

def test_상한_안이면_통과(db):
    now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=KST)
    _snap(db, uploaded_at=_dt.datetime(2026, 7, 20, 1, 0))
    d = decide_for_plan(db, canonical_sku="SKU1", market="coupang",
                        stock=999, now=now)
    assert d.allowed is True


def test_상한을_다_쓰면_막고_대기(db):
    now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=KST)
    for _ in range(2):
        _snap(db, uploaded_at=_dt.datetime(2026, 7, 20, 1, 0))
    d = decide_for_plan(db, canonical_sku="SKU1", market="coupang",
                        stock=999, now=now)
    assert d.allowed is False
    assert d.held is True            # ★ 버리는 게 아니다
    assert d.reason_code == "daily_cap_reached"


def test_품절은_상한을_넘겨도_나간다(db):
    """계속 팔면 주문 받고 취소 → 마켓 페널티."""
    now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=KST)
    for _ in range(5):
        _snap(db, uploaded_at=_dt.datetime(2026, 7, 20, 1, 0))
    d = decide_for_plan(db, canonical_sku="SKU1", market="coupang",
                        stock=0, now=now)
    assert d.allowed is True
    assert d.exempt is True
    assert d.over_limit is True


def test_확인불가는_상한을_못_뚫는다(db):
    """품절 예외는 '진짜 품절'에만 준다."""
    now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=KST)
    for _ in range(2):
        _snap(db, uploaded_at=_dt.datetime(2026, 7, 20, 1, 0))
    d = decide_for_plan(db, canonical_sku="SKU1", market="coupang",
                        stock=-1, now=now)
    assert d.allowed is False


def test_상한을_사장님이_올릴_수_있다(db):
    now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=KST)
    for _ in range(2):
        _snap(db, uploaded_at=_dt.datetime(2026, 7, 20, 1, 0))
    d = decide_for_plan(db, canonical_sku="SKU1", market="coupang", stock=999,
                        config=CapConfig(max_per_day=5), now=now)
    assert d.allowed is True


# ── 배선 확인 ───────────────────────────────────────────────────

def test_reconcile_이_cap_config_를_받는다():
    """시그니처가 있어야 호출부에서 사장님 설정을 넘길 수 있다."""
    import inspect

    from lemouton.uploader.reconcile import reconcile_after_crawl
    assert 'cap_config' in inspect.signature(reconcile_after_crawl).parameters


def test_reconcile_이_상한_서비스를_실제로_부른다():
    """모듈을 만들어 두고 안 부르던 게 이번 문제였다."""
    import inspect

    from lemouton.uploader import reconcile
    src = inspect.getsource(reconcile.reconcile_after_crawl)
    assert 'daily_cap_service' in src
    assert 'decide_for_plan' in src
