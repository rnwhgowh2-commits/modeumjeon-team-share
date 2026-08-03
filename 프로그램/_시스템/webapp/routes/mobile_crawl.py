# -*- coding: utf-8 -*-
"""폰 크롤 리모컨 — 폰이 시키고 로컬 PC 크롬 확장이 실행한다.

크롤 = 로컬 PC 원칙은 그대로다. 서버는 '할 일' 표시만 바꾸고,
실제 크롤은 확장이 /api/crawl/due-bundles 를 1분마다 폴링해 가져간다.

라우트:
  GET  /mobile/crawl/            → 리모컨 화면
  GET  /mobile/crawl/api/status  → PC 생존 · 자동 on/off · 대기 건수 · 오늘 바퀴
  POST /mobile/crawl/api/auto    → {"enabled": bool}
  POST /mobile/crawl/api/run-lap → 지금 한 바퀴 (자동 켜기 + 랩 카운터 리셋)

전 라우트 admin 전용 — 아래 _admin_only 참고.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request

from shared.db import SessionLocal

logger = logging.getLogger(__name__)

bp = Blueprint("mobile_crawl", __name__, url_prefix="/mobile/crawl")


@bp.before_request
def _admin_only():
    """리모컨 전체를 admin 에게만 연다 — PC 경로와 **같은 정책**.

    근거: 같은 설정(crawl_auto_enabled)을 바꾸는 PC 경로 POST /api/automation/save 가
    webapp/routes/settings.py 의 blueprint 게이트(_admin_only → enforce_admin) 뒤에 있다.
    폰만 열어 두면 member 가 전 팀의 자동 크롤을 끄거나 '지금 한 바퀴'로 전 소싱처를
    즉시 크롤 대상으로 되돌릴 수 있다. 크롤은 가격·재고를 움직이니 돈 문제다.

    읽기(api/status)와 화면까지 **통째로** 막는 이유: member 에게 리모컨을 보여 주면
    누를 수 없는 버튼이 달린 화면이 된다 — 이 설계가 가장 나쁘게 치는 결과가
    '눌러도 아무 일 없는 버튼'이다(tests/mobile/test_crawl_presence.py 서두).
    settings.py 가 blueprint 를 통째로 막는 관행과도 같다.

    나중에 팀원에게도 열려면 이 함수만 지우면 된다.
    """
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


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
        # 꺼져 있으면 0 — 원천(due_bundle_codes)도 같은 판정을 한다. 여긴 쿼리 절약용.
        waiting = len(due_bundle_codes(s, now=now)) if auto else 0
        stats_ok = True
        try:
            stats = lap_stats(s, now=now) or {}
        except Exception:       # noqa: BLE001 — 통계가 죽어도 리모컨은 떠야 한다
            logger.warning("[mobile] lap_stats 실패", exc_info=True)
            stats, stats_ok = {}, False
    finally:
        s.close()

    # lap_stats 반환(실측): laps_today=int, today_laps=[{"no":1,"at":"ISO"}...],
    #   current_lap_no, avg_lap_minutes, recent_lap_minutes
    #   ⚠️ today_laps 는 '개수'가 아니라 '목록'이다 — 개수는 laps_today 다.
    today = stats.get("today_laps") or []
    last_at = today[-1].get("at") if today else None
    # at 은 오프셋 없는 naive UTC 라 폰의 JS new Date() 가 로컬 시각으로 잘못 읽는다
    # (KST 에서 9시간 이르게 표시). 화면은 '몇 초 전'만 쓰게 초 단위를 같이 준다.
    last_ago = None
    if last_at:
        try:
            last_ago = max(0, int((now - datetime.fromisoformat(last_at)).total_seconds()))
        except (TypeError, ValueError):
            logger.warning("[mobile] 마지막 바퀴 시각을 못 읽음: %r", last_at)

    return {
        "ok": True,
        "pc": worker_presence(),
        "auto_enabled": auto,
        # 퍼센트는 주지 않는다 — 대기목록(모음전 코드)과 바퀴대상(소싱처 URL)의
        # 단위가 달라 정확한 진행률을 낼 수 없다. 지어내지 않는다(설계서 §4.4).
        "waiting": waiting,
        # 통계를 못 읽었으면 0 이 아니라 None — 0 을 주면 '진짜 0바퀴'와
        # '조회 실패'가 화면에서 구분이 안 된다(그것도 지어낸 숫자다). 화면은 '-'.
        "stats_ok": stats_ok,
        "laps_today": int(stats.get("laps_today") or 0) if stats_ok else None,
        # ★ '오늘(KST 자정 이후)' 마지막 바퀴다. 자정 직후엔 10분 전 바퀴가 있어도 None.
        "last_lap_today_at": last_at,
        "last_lap_seconds_ago": last_ago,
    }


@bp.get("/api/status")
def api_status():
    resp = jsonify(_status_payload())
    # 돈(가격·재고)을 움직이는 화면의 상태값 — 중간 캐시가 옛 답을 재사용하면
    # 꺼진 PC 가 켜진 것으로 보인다. 절대 캐시 금지.
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.post("/api/auto")
def api_auto():
    from lemouton.pricing.settings import save_automation

    body = request.get_json(silent=True) or {}
    if "enabled" not in body:
        return jsonify(ok=False, error="enabled 없음"), 400
    enabled = body["enabled"]
    # bool 만 받는다 — bool("false") 는 True 라, 문자열을 통과시키면 '끈다'가
    # 조용히 '켠다'가 된다(자동 크롤은 돈이 움직이는 스위치다).
    if not isinstance(enabled, bool):
        return jsonify(ok=False, error="enabled 는 true/false 만"), 400
    s = SessionLocal()
    try:
        save_automation(s, {"crawl_auto_enabled": enabled})
        s.commit()      # save_automation 은 flush 만 한다 — 여기서 안 하면 롤백된다
    finally:
        s.close()
    return jsonify(ok=True, auto_enabled=enabled)


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
    # ⚠️ reset 이름은 집안 관례(webapp/routes/api.py 의 /crawl/pass-done)와 맞춘 것.
    #   다만 start_new_lap 의 n 은 '리셋된 개수'가 아니라 **랩 대상 전체 개수**다.
    #   화면에 "N건 리셋됨"으로 쓰면 틀린 숫자다 — 응답에만 남기고 표시하지 말 것.
    return jsonify(ok=True, auto_enabled=True, reset=n)
