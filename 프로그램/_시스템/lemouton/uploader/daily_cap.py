"""업로드 상한 — 상품당 하루 N회. 품절은 예외로 무조건 나간다.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §5-1 · §5-1-1

━━ 사장님 확정 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  "여유가 되면 가격/재고 변동되면 바로바로 업로드하면 됨.
   다만 업로드할 게 너무 많으면 상품별로 하루에 최대 2회까지만."
  "품절은 빠르게 무조건 빼야 함."

  → 기본은 **즉시 업로드**. 이 모듈은 정시 배치가 아니라 **안전장치**다.
  → 상한에 걸려도 **버리지 않는다**(held). 마지막 값만 들고 있다가 다음 슬롯에 최신 상태로.
  → 품절(재고 0)만 면제. 계속 팔면 주문 받고 취소 → 마켓 페널티·고객 이탈.

━━ 이 모듈이 다루지 않는 것 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - 올릴지 말지 판정      → upload_gate.decide_upload
  - 왕복 변동 흡수         → reconcile.last_confirmed_snapshot (목표값 대조)
  - 마켓 전체 속도 제한    → uploader/throttle.py
  이 모듈은 **한 상품이 하루에 마켓을 몇 번 건드리냐**만 본다.
"""
from __future__ import annotations

from dataclasses import dataclass

_DEFAULT_MAX_PER_DAY = 2      # 사장님 확정: 상품당 하루 2회


@dataclass(frozen=True)
class CapConfig:
    """상한 설정. 사장님이 화면에서 바꿀 수 있는 값이다."""

    max_per_day: int = _DEFAULT_MAX_PER_DAY
    exempt_on_sold_out: bool = True

    def __post_init__(self):
        if self.max_per_day < 0:
            raise ValueError(f"상한은 음수일 수 없습니다: {self.max_per_day}")


_DEFAULT_CONFIG = CapConfig()


@dataclass(frozen=True)
class CapDecision:
    """상한 판정 결과. **막힌 것도 이 객체로 말한다** (조용한 실패 금지)."""

    allowed: bool
    used: int                 # 오늘 이 상품이 이미 쓴 횟수 (이번 건 세기 전)
    limit: int
    reason_code: str          # 기계용 고정 코드
    reason: str               # 사람이 읽는 한 문장

    exempt: bool = False      # 품절 예외로 상한을 뚫고 통과했나
    over_limit: bool = False  # 상한을 이미 넘긴 상태인가 (품절 예외일 때만 True 가능)
    held: bool = False        # 막혔지만 **버리지 않고** 대기 중인가

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "used": self.used,
            "limit": self.limit,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "exempt": self.exempt,
            "over_limit": self.over_limit,
            "held": self.held,
        }


def decide_cap(*, used_today: int, is_sold_out, config: CapConfig | None = None) -> CapDecision:
    """이 상품을 지금 올려도 되나.

    Args:
        used_today: 오늘 이 상품이 이미 마켓에 나간 횟수.
        is_sold_out: 재고 0 인가.
            **True 만 품절로 친다.** None(확인 불가)·False 는 품절이 아니다 —
            크롤 실패로 재고를 못 읽은 걸 품절로 오인하면 멀쩡한 상품을 내린다.
            (이 프로젝트 확립 원칙: 파싱 실패는 0 이 아니라 '확인 불가')
        config: 상한 설정.
    """
    cfg = config or _DEFAULT_CONFIG
    if used_today < 0:
        raise ValueError(f"사용량은 음수일 수 없습니다: {used_today}")

    limit = cfg.max_per_day
    within = used_today < limit

    if within:
        return CapDecision(
            allowed=True, used=used_today, limit=limit,
            reason_code="within_daily_cap",
            reason=f"오늘 {used_today}/{limit}회 — 아직 여유가 있습니다.",
        )

    # 여기부터는 상한을 이미 다 썼다.
    if is_sold_out is True and cfg.exempt_on_sold_out:
        return CapDecision(
            allowed=True, used=used_today, limit=limit,
            exempt=True, over_limit=True,
            reason_code="sold_out_exempt",
            reason=(f"품절이라 상한({limit}회)을 넘겨 올립니다 — "
                    f"오늘 {used_today}회 사용. 계속 팔면 주문 취소가 납니다."),
        )

    why = "재고를 확인하지 못했습니다" if is_sold_out is None else "품절이 아닙니다"
    return CapDecision(
        allowed=False, used=used_today, limit=limit, held=True,
        reason_code="daily_cap_reached",
        reason=(f"오늘 상한 {limit}회를 다 썼습니다({used_today}회) · {why}. "
                f"버리지 않고 최신 값으로 대기시킵니다."),
    )


# ── 합치기 ──────────────────────────────────────────────────────

def _key(item):
    if isinstance(item, dict):
        return (item.get("canonical_sku"), item.get("market"), item.get("account_key"))
    return (getattr(item, "canonical_sku", None),
            getattr(item, "market", None),
            getattr(item, "account_key", None))


def coalesce_pending(items, *, key=_key) -> list:
    """대기 중인 업로드를 (상품, 마켓, 계정) 단위로 **마지막 것만** 남긴다.

    ⚠️ 2026-07-20 현재 **호출부가 없다.** 죽은 코드가 아니라 아직 필요가 없는 것이다:
      :func:`lemouton.uploader.reconcile.reconcile_after_crawl` 은 크롤이 끝날 때마다
      **지금 상태에서 계획을 다시 세운다**. 대기 큐에 중간 값이 쌓이는 구조가 아니라
      '다시 세우기'가 곧 합치기다. 대기분을 큐에 쌓아 배치로 내보내는 방식으로
      바꾸면 그때 이 함수가 필요해진다.


    상한에 걸려 쌓인 변동을 다음 슬롯에 한꺼번에 올릴 때, 중간 값들은 의미가 없다.
    마지막 값 하나면 그 사이 변화를 전부 담는다.

    순서는 **처음 나온 자리**를 지킨다 — 우선순위 정렬은 다른 단계에서 하므로
    여기서 순서를 흔들면 결과를 예측하기 어려워진다.
    """
    latest: dict = {}
    order: list = []
    for it in items:
        k = key(it)
        if k not in latest:
            order.append(k)
        latest[k] = it
    return [latest[k] for k in order]
