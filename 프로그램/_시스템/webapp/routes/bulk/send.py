# -*- coding: utf-8 -*-
"""③ 데이터전송 — 업로드 게이트 결과 + 마켓별 속도 정책 (B안: 마켓별 열).

설계서: 2026-07-19-크롤주기-변동주기-등급-design.md §5 · 시안 12 ③-B안
사장님 확정: "B. 마켓별 열 · 업로드수 X초 X개 마켓별 수기 설정"

★ 읽기 전용이다. 여기서 전송을 실행하지 않는다.

■ 속도 제한은 **이미 있는 설정을 그대로 읽는다** (새로 만들지 않음)
  AccountUploadPolicy.seconds_per_item(계정별 1개당 초) → 마켓 합계로 파생.
  계정 5개면 처리량 5배 = 간격 1/5. (uploader/throttle.py 가 정본)
"""
from flask import jsonify

from shared.db import SessionLocal

from . import bp

# 화면에 보일 마켓 순서 (사장님 우선순위: 스스 → 쿠팡 → 롯데온 → 11번가)
MARKET_ORDER = ("smartstore", "coupang", "lotteon", "eleven11")
MARKET_LABELS = {
    "smartstore": "스마트스토어", "coupang": "쿠팡",
    "lotteon": "롯데온", "eleven11": "11번가",
}


def _rate(session, market: str) -> dict:
    """마켓의 속도 제한 — 「X초에 Y개」 형태로 환산해 돌려준다."""
    from lemouton.uploader.throttle import (
        market_hourly_total, market_min_interval_seconds,
    )
    per_hour = market_hourly_total(session, market)
    interval = market_min_interval_seconds(session, market)
    if per_hour <= 0:
        return {"per_hour": 0, "interval_seconds": 0.0, "text": "제한 없음 (계정 미설정)",
                "unlimited": True}
    per_sec = 1.0 / interval if interval > 0 else 0.0
    if per_sec >= 1:
        text = f"1초에 {per_sec:.0f}개"
    else:
        text = f"{interval:.0f}초에 1개"
    return {"per_hour": per_hour, "interval_seconds": round(interval, 2),
            "text": text, "unlimited": False}


@bp.get('/api/send/summary')
def send_summary():
    """게이트 요약 + 마켓별 현황·속도. ③ 데이터전송 탭이 읽는다."""
    from sqlalchemy import func

    from lemouton.pricing.settings import get_account_policies
    from lemouton.uploader.models import PriceSnapshot

    s = SessionLocal()
    try:
        # 게이트 — 무엇을 올렸고 무엇을 걸렀나 (사유별)
        gate_rows = (s.query(PriceSnapshot.action, PriceSnapshot.reason_code,
                             func.count(PriceSnapshot.id))
                     .group_by(PriceSnapshot.action, PriceSnapshot.reason_code).all())
        uploaded, skipped = [], []
        for action, code, cnt in gate_rows:
            item = {"reason_code": code or "(없음)", "count": int(cnt)}
            (uploaded if action == "upload" else skipped).append(item)
        uploaded.sort(key=lambda x: -x["count"])
        skipped.sort(key=lambda x: -x["count"])

        # 마켓별 — 올린 것 / 거른 것 / 실패
        per_market = (s.query(PriceSnapshot.market, PriceSnapshot.action,
                              func.count(PriceSnapshot.id))
                      .group_by(PriceSnapshot.market, PriceSnapshot.action).all())
        agg: dict = {}
        for market, action, cnt in per_market:
            b = agg.setdefault(market, {"uploaded": 0, "skipped": 0})
            b["uploaded" if action == "upload" else "skipped"] += int(cnt)

        policies = get_account_policies(s)
        s.commit()   # get_account_policies 가 기본 정책을 시드할 수 있다

        markets = []
        seen = set()
        for m in list(MARKET_ORDER) + sorted(agg.keys()):
            if m in seen:
                continue
            seen.add(m)
            b = agg.get(m, {"uploaded": 0, "skipped": 0})
            accs = [p for p in policies if p["market"] == m]
            markets.append({
                "market": m,
                "label": MARKET_LABELS.get(m, m),
                "uploaded": b["uploaded"],
                "skipped": b["skipped"],
                "accounts": len(accs),
                "accounts_on": sum(1 for p in accs if p["enabled"]),
                "rate": _rate(s, m),
            })

        return jsonify({
            "gate": {
                "uploaded": uploaded, "skipped": skipped,
                "uploaded_total": sum(x["count"] for x in uploaded),
                "skipped_total": sum(x["count"] for x in skipped),
            },
            "markets": markets,
            # ★ 지금 구조로는 초당 1개가 계정당 상한이다 — 화면이 이 사실을 알아야
            #   「1초에 10개」 같은 설정이 왜 안 되는지 설명할 수 있다.
            "limits": {
                "per_account_max_per_second": 1,
                "note": ("속도는 계정별 「1개당 초」로 저장됩니다(최소 1초). "
                         "그래서 한 계정은 초당 1개가 최대이고, 마켓 처리량은 "
                         "켜진 계정 수만큼 배가됩니다."),
            },
        })
    except Exception as e:      # noqa: BLE001
        s.rollback()
        return jsonify({"error": "send_summary_failed", "detail": str(e)[:300]}), 500
    finally:
        s.close()
