"""드라이런 — 변동 diff 계산 + 자동 보류 임계값 검사."""
from dataclasses import dataclass


@dataclass
class DryrunSummary:
    total_changes: int
    ss_changes: int
    coupang_changes: int
    warnings: int
    avg_price_change_pct: float
    should_hold: bool
    hold_reason: str


def compute_dryrun_summary(
    changes: list[dict],
    alerts: list[dict],
    warnings_threshold: int,
    avg_price_change_pct: float,
) -> DryrunSummary:
    ss = sum(1 for c in changes if c.get("market") == "smartstore")
    cp = sum(1 for c in changes if c.get("market") == "coupang")

    # 평균 가격 변동률 (이전 대비)
    pct_changes = []
    for c in changes:
        old = c.get("old_price")
        new = c.get("new_price")
        if old and new and old > 0:
            pct_changes.append(abs(new - old) / old * 100)
    avg_pct = sum(pct_changes) / len(pct_changes) if pct_changes else 0.0

    warnings = len([a for a in alerts if a.get("level") != "info"]) + len(alerts)
    # alerts 자체를 warning으로 간주

    should_hold = False
    reasons = []
    if warnings > warnings_threshold:
        should_hold = True
        reasons.append(f"warning {warnings}건 > 임계 {warnings_threshold}")
    if avg_pct > avg_price_change_pct:
        should_hold = True
        reasons.append(f"평균 변동률 {avg_pct:.1f}% > 임계 {avg_price_change_pct}%")

    return DryrunSummary(
        total_changes=len(changes),
        ss_changes=ss,
        coupang_changes=cp,
        warnings=len(alerts),
        avg_price_change_pct=avg_pct,
        should_hold=should_hold,
        hold_reason="; ".join(reasons) if reasons else "",
    )
