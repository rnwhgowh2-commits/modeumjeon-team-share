# -*- coding: utf-8 -*-
"""폰 크롤 리모컨 — 폰이 시키고 로컬 PC 크롬 확장이 실행한다.

크롤 = 로컬 PC 원칙은 그대로다. 서버는 '할 일' 표시만 바꾸고,
실제 크롤은 확장이 /api/crawl/due-bundles 를 1분마다 폴링해 가져간다.

라우트:
  GET  /mobile/crawl/            → 리모컨 화면
  GET  /mobile/crawl/api/status  → PC 생존 · 자동 on/off · 대기 건수 · 오늘 바퀴
  POST /mobile/crawl/api/auto    → {"enabled": bool}
  POST /mobile/crawl/api/run-lap → 지금 한 바퀴 (자동 켜기 + 랩 카운터 리셋)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request

from shared.db import SessionLocal

logger = logging.getLogger(__name__)

bp = Blueprint("mobile_crawl", __name__, url_prefix="/mobile/crawl")


@bp.route("/")
def page():
    return render_template("mobile/crawl.html")


def _status_payload() -> dict:
    from lemouton.sourcing.crawl_queue import worker_presence
    from lemouton.pricing.settings import get_automation
    from lemouton.sources.crawl_schedule import due_bundle_codes, lap_stats

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    s = SessionLocal()
    try:
        auto = bool(get_automation(s).get("crawl_auto_enabled"))
        waiting = len(due_bundle_codes(s, now=now)) if auto else 0
        try:
            stats = lap_stats(s, now=now) or {}
        except Exception:       # noqa: BLE001 — 통계가 죽어도 리모컨은 떠야 한다
            logger.warning("[mobile] lap_stats 실패", exc_info=True)
            stats = {}
    finally:
        s.close()

    # lap_stats 반환(실측): laps_today=int, today_laps=[{"no":1,"at":"ISO"}...],
    #   current_lap_no, avg_lap_minutes, recent_lap_minutes
    #   ⚠️ today_laps 는 '개수'가 아니라 '목록'이다 — 개수는 laps_today 다.
    today = stats.get("today_laps") or []
    return {
        "ok": True,
        "pc": worker_presence(),
        "auto_enabled": auto,
        # 퍼센트는 주지 않는다 — 대기목록(모음전 코드)과 바퀴대상(소싱처 URL)의
        # 단위가 달라 정확한 진행률을 낼 수 없다. 지어내지 않는다(설계서 §4.4).
        "waiting": waiting,
        "laps_today": int(stats.get("laps_today") or 0),
        "last_lap_at": (today[-1].get("at") if today else None),
    }


@bp.route("/api/status")
def api_status():
    return jsonify(_status_payload())


@bp.post("/api/auto")
def api_auto():
    from lemouton.pricing.settings import save_automation

    body = request.get_json(silent=True) or {}
    if "enabled" not in body:
        return jsonify(ok=False, error="enabled 없음"), 400
    s = SessionLocal()
    try:
        save_automation(s, {"crawl_auto_enabled": bool(body["enabled"])})
        s.commit()
    finally:
        s.close()
    return jsonify(ok=True, auto_enabled=bool(body["enabled"]))


@bp.post("/api/run-lap")
def api_run_lap():
    """지금 한 바퀴 — 랩 카운터를 0으로 되돌려 전 대상을 '지금 긁을 것'으로 만든다.

    record=False: 실제로 돈 바퀴가 아니므로 완료 기록을 남기지 않는다
    (남기면 '오늘 몇 바퀴' 가 가짜로 부풀어 오른다).
    자동 크롤이 꺼져 있으면 서버가 할 일 목록을 비우므로 같이 켠다.
    """
    from lemouton.pricing.settings import save_automation
    from lemouton.sources.crawl_schedule import start_new_lap

    s = SessionLocal()
    try:
        save_automation(s, {"crawl_auto_enabled": True})
        n = start_new_lap(s, record=False)
        s.commit()
    finally:
        s.close()
    return jsonify(ok=True, auto_enabled=True, reset=n)
