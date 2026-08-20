"""등급 제안을 기존 스케줄러 단위로 옮긴다 — 「하루 N회」 ↔ crawl_weight.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §4-1

━━ 두 단위를 잇는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  crawl_grade.py 는 **하루 N회**(실수, 1/3 같은 값 포함)로 제안한다.
  crawl_schedule.py 는 **crawl_weight**로 돈다:  유효간격 = 기준주기 ÷ weight × 완화배수

  기준주기가 하루라면        하루 2회 → weight 2      · 3일 1회 → weight 1/3

━━ 🔴 함정 — int() 절삭이 '크롤 제외'로 둔갑시킨다 ━━━━━━━━━━━━━━
  effective_interval_seconds 는 `int(crawl_weight)` 후 `min(5, ...)` 로 접는다.
  그리고 **weight 0 은 '크롤 제외'(간격 무한대)** 다.

      weight 1/3  →  int(0.33) == 0  →  간격 ∞  →  그 상품은 영영 안 긁힌다

  「3일에 1회로 뜸하게 돌자」는 제안이 「아예 돌지 말자」로 뒤집힌다.
  그래서 이 모듈은 표현 가능 여부를 **먼저 판정하고**, 안 되면 applicable=False 로
  막는다. 조용히 넣지 않는다.

━━ 이 모듈은 적용하지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  사장님 결정 5-B: 자동 적용 금지. 제안 목록을 만들 뿐이고, 실제 반영은
  사장님이 화면에서 확인한 뒤에 한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from lemouton.sources.crawl_grade import (
    GradeConfig,
    classify,
    grade_name,
    intensity_pct,
    per_day_text,
    proposed_per_day,
    raw_per_day,
)

DAY_SECONDS = 86400.0

# 기존 스케줄러가 표현할 수 있는 계수 범위 (crawl_schedule.effective_interval_seconds)
_WEIGHT_MIN = 1
_WEIGHT_MAX = 5


def per_day_to_interval_seconds(per_day: float) -> float:
    """하루 N회 → 크롤 간격(초)."""
    if per_day <= 0:
        raise ValueError(f"하루 횟수는 0보다 커야 합니다: {per_day}")
    return DAY_SECONDS / per_day


def weight_for(per_day: float, *, base_interval_seconds: float) -> float:
    """하루 N회 → crawl_weight (실수). 유효간격 = 기준주기 ÷ weight 를 뒤집은 것."""
    if base_interval_seconds <= 0:
        raise ValueError(
            f"기준주기가 0 이하입니다({base_interval_seconds}) — "
            f"'항상 마감(연속)' 설정이라 계수로 환산할 수 없습니다")
    return base_interval_seconds / per_day_to_interval_seconds(per_day)


def to_weight_and_slowdown(per_day: float, *, base_interval_seconds: float):
    """하루 N회 → (계수, 느리게배수). 두 손잡이로 쪼갠다.

    계수는 **자주 긁는 쪽**(1~5 정수), 느리게배수는 **뜸하게 긁는 쪽**(1.0 이상).
    이렇게 나누면 Integer 컬럼을 그대로 두고도 「3일에 1회」를 표현할 수 있다.

        기준주기 1일 · 하루 2회  →  (2, 1.0)
        기준주기 1일 · 3일 1회   →  (1, 3.0)

    Returns:
        (weight, slowdown, capped) — capped=True 면 계수 상한 5에 걸려
        원하는 만큼 자주 못 긁는다는 뜻(느리게배수로는 해결 못 함).
    """
    target = per_day_to_interval_seconds(per_day)
    if base_interval_seconds <= 0:
        raise ValueError(
            f"기준주기가 0 이하입니다({base_interval_seconds}) — "
            f"'항상 마감(연속)' 설정이라 계수로 환산할 수 없습니다")

    ideal = base_interval_seconds / target          # 필요한 '자주' 배수
    weight = max(_WEIGHT_MIN, min(_WEIGHT_MAX, round(ideal)))
    slowdown = target * weight / base_interval_seconds

    if slowdown < 1.0:
        # 계수 상한 5로도 모자란다 — 더 자주 긁을 방법이 없다.
        # 1 미만 느리게배수는 거부되므로(방향이 반대) 1.0 으로 두고 사실을 알린다.
        return int(weight), 1.0, True
    return int(weight), slowdown, False


def weight_is_expressible(weight: float) -> bool:
    """지금 스케줄러가 이 계수를 그대로 쓸 수 있나.

    effective_interval_seconds 가 int() · min(5, ...) 로 접으므로
    **1~5 사이 정수**만 온전히 표현된다. 그 밖은 값이 조용히 바뀐다.
    """
    if weight < _WEIGHT_MIN or weight > _WEIGHT_MAX:
        return False
    return float(weight).is_integer()


@dataclass(frozen=True)
class CoefficientProposal:
    """계수 제안 1건. 적용 못 하는 것도 이유를 달아 **보여준다**(조용히 버리지 않음)."""

    target_id: str
    label: str

    window_days: int
    union_count: int
    intensity_pct: float
    grade: int
    grade_name: str

    current_per_day: float
    proposed_per_day: float
    proposed_weight: float        # 이상적인 실수 계수 (참고용)
    proposed_weight_int: int      # 실제로 저장할 crawl_weight (1~5 정수)
    proposed_slowdown: float      # 실제로 저장할 crawl_slowdown (1.0 이상)
    proposed_text: str

    direction: str              # 'up' | 'down' | 'same'
    capped: bool                # 상한에 깎였나
    applicable: bool            # 지금 스케줄러로 적용 가능한가
    blocked_reason: str | None  # 적용 못 하는 이유 (있으면 화면에 표시)
    reason: str                 # 왜 이렇게 제안하는지 (사람이 읽는 문장)

    @property
    def is_noop(self) -> bool:
        return self.direction == "same"

    def to_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "label": self.label,
            "window_days": self.window_days,
            "union_count": self.union_count,
            "intensity_pct": round(self.intensity_pct, 1),
            "grade": self.grade,
            "grade_name": self.grade_name,
            "current_per_day": self.current_per_day,
            "proposed_per_day": self.proposed_per_day,
            "proposed_weight": self.proposed_weight,
            "proposed_weight_int": self.proposed_weight_int,
            "proposed_slowdown": self.proposed_slowdown,
            "proposed_text": self.proposed_text,
            "direction": self.direction,
            "capped": self.capped,
            "applicable": self.applicable,
            "blocked_reason": self.blocked_reason,
            "reason": self.reason,
        }


def _reason(*, window_days, union_count, pct, gname, proposed, capped, raw) -> str:
    if union_count == 0:
        return (f"{window_days}일간 한 번도 안 바뀌었습니다 — 하한만 적용해 "
                f"{per_day_text(proposed)}.")
    if pct >= 100:
        head = f"{window_days}일 {union_count}회 · 하루 {pct / 100:.1f}회꼴"
    else:
        head = f"{window_days}일 {union_count}회 · 평균 {window_days / union_count:.1f}일에 1회"
    tail = f" → {gname}, {per_day_text(proposed)}."
    if capped:
        tail += f" (제안 {per_day_text(raw)} 이지만 상한에 걸려 {per_day_text(proposed)} 로 조정)"
    return head + tail


def build_proposal(*, target_id: str, label: str, union_count: int, window_days: int,
                   current_weight: float, base_interval_seconds: float,
                   config: GradeConfig | None = None) -> CoefficientProposal:
    """한 대상의 계수 제안을 만든다.

    Args:
        current_weight: 지금 걸려 있는 crawl_weight.
        base_interval_seconds: 자동화 설정의 기준 주기(초).
    """
    pct = intensity_pct(union_count, window_days)
    grade = classify(pct, config)
    raw = raw_per_day(grade, config)
    proposed = proposed_per_day(grade, config)

    # 현재 계수를 '하루 N회' 로 환산해 견준다 (같은 잣대로 비교해야 방향이 맞는다).
    current_per_day = (current_weight * DAY_SECONDS / base_interval_seconds
                       if base_interval_seconds > 0 else 0.0)

    if abs(proposed - current_per_day) < 1e-9:
        direction = "same"
    elif proposed > current_per_day:
        direction = "up"
    else:
        direction = "down"

    # 2026-07-19: 두 손잡이(계수 + 느리게배수)로 쪼개면 「3일에 1회」도 표현된다.
    #   예전에는 계수 하나로만 담으려다 1 미만이 int() 에 잘려 '크롤 제외'가 됐다.
    weight_int, slowdown, too_fast = to_weight_and_slowdown(
        proposed, base_interval_seconds=base_interval_seconds)
    weight = weight_for(proposed, base_interval_seconds=base_interval_seconds)
    ok = not too_fast
    blocked = None
    if too_fast:
        blocked = (f"기준 주기({base_interval_seconds / 3600:.1f}시간)로는 "
                   f"{per_day_text(proposed)} 만큼 자주 긁을 수 없습니다 — "
                   f"계수 상한 {_WEIGHT_MAX} 에 걸립니다. 기준 주기를 줄여야 합니다.")

    return CoefficientProposal(
        target_id=target_id, label=label,
        window_days=window_days, union_count=union_count,
        intensity_pct=pct, grade=grade, grade_name=grade_name(grade),
        current_per_day=current_per_day,
        proposed_per_day=proposed,
        proposed_weight=weight,
        proposed_weight_int=weight_int,
        proposed_slowdown=slowdown,
        proposed_text=per_day_text(proposed),
        direction=direction,
        capped=proposed < raw,
        applicable=ok,
        blocked_reason=blocked,
        reason=_reason(window_days=window_days, union_count=union_count, pct=pct,
                       gname=grade_name(grade), proposed=proposed,
                       capped=proposed < raw, raw=raw),
    )


def should_resurface(*, current_grade: int, dismissed_at_grade) -> bool:
    """무시했던 제안을 다시 올릴 때가 됐나.

    설계서 §4-1 — 같은 제안을 매일 다시 띄우면 피로해진다.
    **등급이 움직이기 전까지는 다시 올리지 않는다.**
    (강도가 조금 흔들리는 건 무시하고, 등급이 바뀔 만큼 움직였을 때만 다시 묻는다.)
    """
    if dismissed_at_grade is None:
        return True
    return current_grade != dismissed_at_grade
