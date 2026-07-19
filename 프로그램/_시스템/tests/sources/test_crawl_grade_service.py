"""구성별 등급 서비스 — 「하루에 몇 번 긁나」 환산 + 등급 얹기.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §6

크롤 모드가 둘이라 환산도 둘이다:
  · 벽시계 모드 (기준주기 > 0) — 하루 크롤 = 계수 × 하루 ÷ 기준주기 ÷ 느리게배수
  · 연속(랩) 모드 (기준주기 0) — 하루 크롤 = 하루 랩 수 × 계수
"""
import pytest

from lemouton.sources.crawl_grade_service import DAY_MINUTES, crawls_per_day


# ── 벽시계 모드 ─────────────────────────────────────────────────

def test_기준주기_하루_계수2면_하루_2회():
    assert crawls_per_day(weight=2, base_interval_seconds=86400,
                          avg_lap_minutes=None) == pytest.approx(2.0)


def test_기준주기_12시간_계수1이면_하루_2회():
    assert crawls_per_day(weight=1, base_interval_seconds=43200,
                          avg_lap_minutes=None) == pytest.approx(2.0)


def test_느리게배수3이면_3분의1로_준다():
    assert crawls_per_day(weight=1, base_interval_seconds=86400,
                          avg_lap_minutes=None, slowdown=3.0) == pytest.approx(1 / 3)


def test_느리게배수_None은_1로_본다():
    assert crawls_per_day(weight=1, base_interval_seconds=86400,
                          avg_lap_minutes=None, slowdown=None) == pytest.approx(1.0)


def test_느리게배수가_1미만이면_거부():
    """1 미만은 '더 자주'라 계수가 할 일 — 스케줄러와 같은 규칙을 지킨다."""
    with pytest.raises(ValueError):
        crawls_per_day(weight=1, base_interval_seconds=86400,
                       avg_lap_minutes=None, slowdown=0.5)


# ── 연속(랩) 모드 ───────────────────────────────────────────────

def test_기준주기0이면_랩_회전속도로_환산한다():
    """1바퀴 30분이면 하루 48바퀴. 계수 2면 URL 하나를 하루 96번 긁는다."""
    assert crawls_per_day(weight=2, base_interval_seconds=0,
                          avg_lap_minutes=30) == pytest.approx(DAY_MINUTES / 30 * 2)


def test_기준주기_None도_연속모드로_본다():
    assert crawls_per_day(weight=1, base_interval_seconds=None,
                          avg_lap_minutes=60) == pytest.approx(24.0)


def test_연속모드인데_랩시간을_모르면_None():
    """아직 한 바퀴도 안 돌았으면 '모름'이다. 0 이나 1 로 지어내지 않는다."""
    assert crawls_per_day(weight=1, base_interval_seconds=0,
                          avg_lap_minutes=None) is None
    assert crawls_per_day(weight=1, base_interval_seconds=0,
                          avg_lap_minutes=0) is None


# ── 계수 0 = 크롤 제외 ──────────────────────────────────────────

def test_계수0이면_하루_0회():
    """스케줄러의 '계수 0 = 크롤 제외' 와 같은 뜻이어야 한다."""
    assert crawls_per_day(weight=0, base_interval_seconds=86400,
                          avg_lap_minutes=None) == 0.0
    assert crawls_per_day(weight=0, base_interval_seconds=0,
                          avg_lap_minutes=30) == 0.0


def test_음수_계수도_0():
    assert crawls_per_day(weight=-1, base_interval_seconds=86400,
                          avg_lap_minutes=None) == 0.0


# ── 계수 상한이 반영된다 ────────────────────────────────────────

def test_계수는_스케줄러와_같이_5에서_잘린다():
    """effective_interval_seconds 가 min(5, ...) 로 접으므로 여기도 같아야 한다.

    다르면 화면이 '하루 8회 긁는 중' 이라고 말하는데 실제로는 5회만 긁는다.
    """
    a = crawls_per_day(weight=8, base_interval_seconds=86400, avg_lap_minutes=None)
    b = crawls_per_day(weight=5, base_interval_seconds=86400, avg_lap_minutes=None)
    assert a == b == pytest.approx(5.0)
