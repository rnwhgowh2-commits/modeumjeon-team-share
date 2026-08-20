"""계수 제안을 실제 규칙으로 적용 — 어느 스코프에 걸지 판정한다.

사장님 결정 5-B (확인 후 적용) · 4번 = 나 (버튼만 만들어 놓기).

━━ 🔴 구조적 틈 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  등급 제안은 **(소싱처 × 브랜드)** 단위다. 그런데 계수 규칙(CrawlWeightRule)의
  스코프는 `url · model · brand · source` 넷뿐이라 **그 조합을 담을 자리가 없다.**

      brand 로 걸면  → 그 브랜드가 **다른 소싱처에도** 걸린다
      source 로 걸면 → 그 소싱처의 **다른 브랜드까지** 걸린다

  스코프를 새로 만들면 resolve_crawl_weight 의 상속 순서를 건드려야 하고,
  그건 **라이브 크롤 스케줄러**를 또 고치는 일이다.
  그래서 지금은 **brand 로 걸되, 겹치면 경고를 달아** 사람이 알고 누르게 한다.
  (막지는 않는다 — 확인 후 적용이 원칙이므로 판단은 사람이 한다.)
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 통계가 브랜드 없는 구성에 쓰는 표시 문자열. 이걸 브랜드 이름으로 저장하면 안 된다.
_NO_BRAND = ("", "(브랜드 미지정)", "(미지정)", "-")

_WEIGHT_MIN, _WEIGHT_MAX = 0, 5     # 스케줄러와 같은 범위 (0 = 크롤 제외)


@dataclass(frozen=True)
class ApplyPlan:
    """「이 버튼을 누르면 무엇이 어떻게 바뀌나」."""

    scope_type: str                 # 'brand' | 'source'
    scope_key: str
    weight: int
    safe: bool                      # 경고 없이 눌러도 되나
    # 느리게 배수 (1.0 = 기본). 「3일에 1회」처럼 기준주기보다 뜸하게 긁는 건
    # 정수 계수로 표현할 수 없어 이 값이 맡는다. (2026-07-20 배선)
    slowdown: float = 1.0
    warning: str | None = None
    affected_sources: list = field(default_factory=list)

    @property
    def label(self) -> str:
        return (f"브랜드 「{self.scope_key}」" if self.scope_type == "brand"
                else f"소싱처 「{self.scope_key}」 전체")

    def to_dict(self) -> dict:
        return {
            "scope_type": self.scope_type,
            "scope_key": self.scope_key,
            "weight": self.weight,
            "slowdown": self.slowdown,
            "safe": self.safe,
            "warning": self.warning,
            "affected_sources": list(self.affected_sources),
            "label": self.label,
        }


def _is_no_brand(brand) -> bool:
    return (brand or "").strip() in _NO_BRAND


def plan_apply(*, source_key: str, brand: str, proposed_weight,
               brands_by_source: dict, proposed_slowdown=None) -> ApplyPlan:
    """적용 계획을 만든다. **저장하지 않는다** — 화면에 보여주고 확인받기 위한 것.

    Args:
        brands_by_source: {소싱처키: {브랜드,...}} — 겹침 판정에 쓴다.
    """
    sk = (source_key or "").strip()
    if not sk:
        raise ValueError("소싱처 키가 비었습니다.")

    w = max(_WEIGHT_MIN, min(_WEIGHT_MAX, int(proposed_weight)))
    sd = 1.0 if proposed_slowdown is None else float(proposed_slowdown)
    if sd < 1.0:
        raise ValueError(f"느리게 배수는 1.0 이상이어야 합니다: {sd}")
    warns = []

    if w == 0:
        # 0 = 크롤 제외. 실수로 누르면 그 URL 이 영영 안 긁힌다.
        warns.append("계수 0 은 **크롤 제외**입니다 — 이 대상은 더 이상 긁지 않습니다.")

    if _is_no_brand(brand):
        return ApplyPlan(scope_type="source", scope_key=sk, weight=w,
                         slowdown=sd, safe=not warns,
                         warning=(" ".join(warns) or None),
                         affected_sources=[sk])

    br = brand.strip()
    others = sorted(s for s, bs in (brands_by_source or {}).items()
                    if s != sk and br in (bs or set()))
    if others:
        warns.append(
            f"브랜드 규칙은 소싱처를 가리지 않습니다 — "
            f"「{br}」 는 {', '.join(others)} 에도 있어 **같이 바뀝니다**.")

    return ApplyPlan(scope_type="brand", scope_key=br, weight=w,
                     slowdown=sd, safe=not warns,
                     warning=(" ".join(warns) or None),
                     affected_sources=sorted({sk, *others}))


def apply_plan(session, plan: ApplyPlan) -> int:
    """계획을 실제로 저장한다. 호출자가 commit.

    ★ 여기서 다시 판단하지 않는다 — plan_apply 가 정한 대로만 쓴다.
      화면이 보여준 것과 저장되는 것이 달라지면 안 된다.
    """
    from lemouton.sources.crawl_schedule import set_crawl_weight_rule
    return set_crawl_weight_rule(session, plan.scope_type, plan.scope_key,
                                 plan.weight, slowdown=plan.slowdown)


def brands_by_source(session) -> dict:
    """{소싱처키: {브랜드,...}} — 겹침 판정용. 통계 표에서 그대로 읽는다."""
    from lemouton.sources.models import CrawlChangeStat
    out: dict = {}
    for sk, br in session.query(CrawlChangeStat.source_key,
                                CrawlChangeStat.brand).distinct().all():
        if not sk:
            continue
        if not _is_no_brand(br):
            out.setdefault(sk, set()).add((br or "").strip())
        else:
            out.setdefault(sk, set())
    return out
