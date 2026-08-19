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

    # 🔴 [2026-08-13 사장님 확정] 예전 식:
    #       warnings = len(level != 'info') + len(alerts)
    #   이라 **`info` 알림도 1씩 세어졌다.** 임계가 5 이므로
    #   `naver_product_not_registered`·`coupang_product_not_registered`
    #   (= 「이 모델은 마켓 상품번호가 없어 보낼 게 없다」는 **안내**) 가
    #   모델 3개분(6건)만 쌓여도 6 > 5 → **전 마켓·전 상품 uploaded=0** 이 됐다.
    #   보낼 게 없는 모델 때문에 멀쩡한 상품 전송까지 멈추는 건 잘못이다.
    #
    #   ★ `info` 만 셈에서 뺀다. **warning 가중치(×2)는 그대로 둔다** —
    #     임계 5 가 그 가중치에 맞춰 정해진 값이라, 같이 건드리면 진짜 막이가
    #     소리 없이 두 배로 느슨해진다. warning 3건 → 6 > 5 → 보류(예전과 동일).
    _경고 = [a for a in alerts if a.get("level") != "info"]
    warnings = len(_경고) * 2

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
