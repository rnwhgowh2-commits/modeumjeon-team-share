"""크롤 변동 주기 등급 — 상품이 얼마나 자주 바뀌는지로 계수를 **제안**한다.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md

━━ 잣대 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  강도(%) = (기간 내 변동 횟수 ÷ 기간 일수) × 100      ← 하루 1회 = 100%
  평균 주기(일) = 기간 일수 ÷ 변동 횟수

  30일에 5회  → 평균 6.0일 · 16.7%     (사장님 예시)
  30일에 30회 → 평균 1.0일 · 100%
  30일에 90회 → 하루 3회   · 300%

━━ 기준축 = 「하나라도 변동」(합집합) ━━━━━━━━━━━━━━━━━━━━━━━━━━━
  크롤은 URL 하나를 **한 번 도는 행위**다. 표면가가 바뀌든 재고가 바뀌든
  어차피 다시 가져와야 하고, 한 번 가져오면 4축을 모두 얻는다.
  → 계수 기준은 축별이 아니라 합집합. 축별 강도는 화면·업로드 게이트용으로 따로 보관.
  → 불변식: max(축별) ≤ 합집합 ≤ Σ(축별)   (union_is_consistent)

━━ ⚠️ 이 모듈은 「제안만」 한다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  사장님 결정 5-B: 통계가 갱신돼도 **자동 적용하지 않는다.** 제안 목록 → 확인 → 적용.
  그래서 여기서는 스케줄러(crawl_schedule.py)를 건드리지 않는다. 순수 계산만.

  ⚠️ 단위가 다르다 — 기존 스케줄러의 crawl_weight 는 **랩 quota(1~5 정수)** 이고,
  이 모듈의 제안은 **하루 N회(실수, 1/3 같은 값 포함)** 이다.
  「3일에 1회」는 현재 crawl_weight 로 표현할 수 없다(최소가 1). 둘을 잇는 변환은
  적용 단계에서 별도로 정해야 하며, 그 전까지 이 모듈의 출력은 **화면 표시·제안 전용**이다.

━━ 모든 수치는 기본값일 뿐 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  사장님 결정 §4: 경계값·계수·하한·상한 전부 화면에서 바꿀 수 있어야 한다.
  → GradeConfig 로 주입. 여기 상수는 **기본 제안값**이다.
"""
from __future__ import annotations

from dataclasses import dataclass

# 등급 이름 (강도 높은 순)
GRADE_NAMES = (
    "하루 2회 이상",
    "하루 1회",
    "2~3일에 1회",
    "주간급",
    "월간급",
    "변동 없음",
)

_DEFAULT_BOUNDARIES = (200.0, 100.0, 33.0, 14.0, 3.0)   # 내림차순, 5개 → 6등급
_DEFAULT_COEFFICIENTS = (3.0, 2.0, 1.0, 0.5, 1 / 3, 1 / 3)   # 등급별 제안 (하루 N회)
_DEFAULT_CEILING = 2.0      # 사장님 결정 4-A: 상한 하루 2회
_DEFAULT_FLOOR = 1 / 3      # 사장님 결정 3-A: 하한 3일 1회


@dataclass(frozen=True)
class GradeConfig:
    """등급 설정. 전부 사장님이 화면에서 바꿀 수 있는 값이다(설계서 §4)."""

    boundaries: tuple = _DEFAULT_BOUNDARIES
    coefficients: tuple = _DEFAULT_COEFFICIENTS
    ceiling_per_day: float = _DEFAULT_CEILING
    floor_per_day: float = _DEFAULT_FLOOR

    def __post_init__(self):
        b = self.boundaries
        if len(b) != len(GRADE_NAMES) - 1:
            raise ValueError(
                f"경계값은 {len(GRADE_NAMES) - 1}개여야 합니다 (등급 {len(GRADE_NAMES)}칸). 받은 값: {len(b)}개")
        if any(b[i] <= b[i + 1] for i in range(len(b) - 1)):
            raise ValueError(f"경계값은 내림차순이어야 합니다: {b}")
        if len(self.coefficients) != len(GRADE_NAMES):
            raise ValueError(f"계수는 {len(GRADE_NAMES)}개여야 합니다. 받은 값: {len(self.coefficients)}개")
        if self.floor_per_day > self.ceiling_per_day:
            raise ValueError(
                f"하한({self.floor_per_day})이 상한({self.ceiling_per_day})보다 클 수 없습니다")


_DEFAULT_CONFIG = GradeConfig()


# ── 강도 · 평균주기 ──────────────────────────────────────────────

def _check(count, window_days):
    if window_days <= 0:
        raise ValueError(f"기간(일)은 0보다 커야 합니다: {window_days}")
    if count < 0:
        raise ValueError(f"변동 횟수는 음수일 수 없습니다: {count}")


def intensity_pct(count, window_days) -> float:
    """강도(%). 하루 1회 = 100. 100 을 넘으면 하루에 여러 번 바뀐다는 뜻."""
    _check(count, window_days)
    return count / window_days * 100.0


def average_period_days(count, window_days):
    """평균 몇 일에 1회 바뀌나. 변동이 없으면 None(= '변동 없음', 0 이 아님)."""
    _check(count, window_days)
    if count == 0:
        return None
    return window_days / count


# ── 등급 ────────────────────────────────────────────────────────

def classify(pct: float, config: GradeConfig | None = None) -> int:
    """강도(%) → 등급 index (0=가장 자주 ~ 5=변동 없음).

    강도 0 은 마지막 등급('변동 없음'). 0 초과면 아무리 작아도 '월간급'이다 —
    '한 번도 안 바뀜'과 '아주 가끔 바뀜'은 다르게 다뤄야 하기 때문.
    """
    cfg = config or _DEFAULT_CONFIG
    if pct <= 0:
        return len(GRADE_NAMES) - 1
    for i, edge in enumerate(cfg.boundaries):
        if pct >= edge:
            return i
    return len(GRADE_NAMES) - 2   # 0 초과 ~ 최저 경계 미만 = 월간급


def grade_name(grade: int) -> str:
    return GRADE_NAMES[grade]


# ── 제안 계수 ───────────────────────────────────────────────────

def raw_per_day(grade: int, config: GradeConfig | None = None) -> float:
    """상한·하한 적용 **전** 제안 계수. 화면에 '제안 3회 → 상한 2회' 를 보이려면 필요.

    ★ 마지막 등급('변동 없음')은 계수표가 아니라 **하한 그 자체**를 쓴다.
      변동이 0 이면 얼마나 자주 돌지 정할 **신호가 없다**. 그때 도는 빈도가 곧 하한의 정의다.
      (계수표에도 값을 두면 하한을 바꿔도 안 따라오는 조용한 버그가 된다 — 실제로 그랬다.)
    """
    cfg = config or _DEFAULT_CONFIG
    if grade == len(GRADE_NAMES) - 1:
        return cfg.floor_per_day
    return cfg.coefficients[grade]


def proposed_per_day(grade: int, config: GradeConfig | None = None) -> float:
    """상한·하한을 적용한 최종 제안 계수 (하루 N회)."""
    cfg = config or _DEFAULT_CONFIG
    return max(cfg.floor_per_day, min(cfg.ceiling_per_day, raw_per_day(grade, cfg)))


def per_day_text(per_day: float) -> str:
    """사람이 읽는 표기. 1 이상은 'N회/일', 1 미만은 'N일 1회'."""
    if per_day >= 1:
        n = round(per_day, 2)
        return f"{int(n) if float(n).is_integer() else n}회/일"
    days = round(1 / per_day)
    return f"{days}일 1회"


# ── 합집합 불변식 ───────────────────────────────────────────────

def union_is_consistent(counts_by_axis: dict, union_count: int) -> bool:
    """max(축별) ≤ 합집합 ≤ Σ(축별) 인지.

    - 어느 축이든 바뀐 날은 합집합에도 잡히므로 **최댓값 이상**.
    - 같은 크롤 회차에 둘이 같이 바뀌면 합집합은 1회로 세므로 **합계 이하**.
    """
    vals = list(counts_by_axis.values())
    if not vals:
        return union_count == 0
    return max(vals) <= union_count <= sum(vals)


# ── 요약 ────────────────────────────────────────────────────────

def summarize(*, counts_by_axis: dict, union_count: int, window_days: int,
              config: GradeConfig | None = None) -> dict:
    """한 상품(또는 한 구성)의 한 기간 요약.

    등급은 **합집합**으로 매긴다(크롤 계수의 기준축). 축별 강도는 화면·업로드 게이트용.
    합집합이 불변식을 어기면 조용히 계산하지 않고 **터뜨린다** — 데이터 모순을 숨기면
    계수가 조용히 틀어진다.
    """
    cfg = config or _DEFAULT_CONFIG
    if not union_is_consistent(counts_by_axis, union_count):
        vals = list(counts_by_axis.values()) or [0]
        raise ValueError(
            f"합집합({union_count})이 불변식을 어깁니다 — "
            f"max({max(vals)}) ≤ 합집합 ≤ sum({sum(vals)}) 이어야 합니다")

    pct = intensity_pct(union_count, window_days)
    grade = classify(pct, cfg)
    raw = raw_per_day(grade, cfg)
    proposed = proposed_per_day(grade, cfg)

    return {
        "window_days": window_days,
        "union_count": union_count,
        "intensity_pct": pct,
        "average_period_days": average_period_days(union_count, window_days),
        "grade": grade,
        "grade_name": grade_name(grade),
        "raw_per_day": raw,
        "proposed_per_day": proposed,
        "proposed_text": per_day_text(proposed),
        # 상한에 깎였나 / 하한이 속도를 정하고 있나 (화면에 '제안 3회 → 상한 2회' 표시용)
        "capped": proposed < raw,
        "floored": raw <= cfg.floor_per_day,
        "axes": {
            axis: {
                "count": c,
                "intensity_pct": intensity_pct(c, window_days),
                "average_period_days": average_period_days(c, window_days),
            }
            for axis, c in counts_by_axis.items()
        },
    }
