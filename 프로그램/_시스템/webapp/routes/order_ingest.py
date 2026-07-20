"""주문 적재 운영 라우트 — 현황 확인 + 1년치 백필 실행.

  GET  /api/orders-ingest/coverage   — 마켓별로 어디까지 쌓였나
  GET  /api/orders-ingest/estimate?days=365 — 백필이 몇 번 호출될지(돌리기 전 규모 확인)
  POST /api/orders-ingest/run-sync   — 한 구간을 **동기로** 돌려 결과를 바로 돌려준다(진단용)
  POST /api/orders-ingest/backfill   — 백필 시작(배경 스레드). {"days":365,"markets":[...]}
  GET  /api/orders-ingest/status     — 진행 중인 백필 상태

백필은 마켓 API 를 많이 두드린다(1년치 전 마켓 ≈ 800회 · 수십 분). 그래서 배경 스레드로
돌리고 진행률을 따로 조회한다.

★ 상태는 **DB** 에 둔다. 앱이 멀티워커라 모듈 전역에 두면 시작한 워커와 상태를 묻는
워커가 달라 진행률이 0/0 으로 보인다(2026-07-20 라이브에서 실제로 겪음).
"""
from __future__ import annotations

import threading
import traceback
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

bp = Blueprint("order_ingest", __name__)

_ROW_ID = "current"


def _session():
    from shared.db import SessionLocal
    return SessionLocal()


def _get_run(s):
    from lemouton.markets.models_orders import OrderIngestRun
    row = s.get(OrderIngestRun, _ROW_ID)
    if row is None:
        row = OrderIngestRun(id=_ROW_ID, running="0")
        s.add(row)
        s.commit()
    return row


def _as_dict(row) -> dict:
    return {"running": row.running == "1", "markets": row.markets, "days": row.days,
            "done": int(row.done or 0), "total": int(row.total or 0),
            "market": row.market or "", "error": row.error or "",
            "results": row.result or [],
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None}


def _update(**kw):
    """상태 갱신. 실패해도 백필 자체를 죽이지 않는다(진행률은 부가정보)."""
    try:
        s = _session()
        try:
            row = _get_run(s)
            for k, v in kw.items():
                setattr(row, k, v)
            s.commit()
        finally:
            s.close()
    except Exception:                                # noqa: BLE001
        pass


@bp.get("/api/orders-ingest/coverage")
def api_coverage():
    """마켓별 적재 현황 — 몇 건이 언제부터 언제까지 쌓였나."""
    from lemouton.markets.order_store import coverage
    return jsonify({"ok": True, "coverage": coverage()})


@bp.get("/api/orders-ingest/estimate")
def api_estimate():
    from lemouton.markets.order_export import supported_markets
    from lemouton.markets.order_ingest import estimate
    try:
        days = max(1, min(int(request.args.get("days") or 365), 1095))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "days 는 숫자"}), 400
    markets = [m for m in (request.args.get("markets") or "").split(",") if m]
    return jsonify({"ok": True, **estimate(markets or list(supported_markets()), days)})


@bp.get("/api/orders-ingest/status")
def api_status():
    from lemouton.markets import backfill_runner
    return jsonify({"ok": True, **backfill_runner.status()})


@bp.post("/api/orders-ingest/run-sync")
def api_run_sync():
    """한 구간을 동기로 수집해 **결과를 바로** 돌려준다.

    배경 스레드는 실패해도 왜 실패했는지 보기 어렵다(멀티워커·로그 접근). 진단과
    소규모 수집용으로 동기 경로를 둔다. 기본 1개 창만 돈다.
    """
    import datetime as _dt

    from lemouton.markets.order_export import supported_markets
    from lemouton.markets.order_ingest import KST, chunk_days, ingest_window

    body = request.get_json(silent=True) or {}
    market = str(body.get("market") or "").strip()
    if market not in supported_markets():
        return jsonify({"ok": False,
                        "error": f"지원하지 않는 마켓: {market or '(없음)'}"}), 400
    try:
        days = max(1, min(int(body.get("days") or chunk_days(market)), 365))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "days 는 숫자"}), 400

    until = _dt.datetime.now(KST)
    since = until - _dt.timedelta(days=days)
    try:
        stat = ingest_window(market, since, until)
    except Exception as e:                           # noqa: BLE001
        # 진단이 목적이므로 사유를 숨기지 않는다(스택 마지막 줄까지).
        return jsonify({"ok": False, "market": market, "days": days,
                        "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-1500:]}), 500
    return jsonify({"ok": True, "market": market, "days": days,
                    "since": since.strftime("%Y-%m-%d"),
                    "until": until.strftime("%Y-%m-%d"), **stat})


@bp.post("/api/orders-ingest/backfill")
def api_backfill():
    """백필 **요청**만 남긴다 — 실행은 스케줄러 프로세스가 가져간다.

    긴 작업을 gunicorn 워커에서 돌렸다가 라이브를 두 번 망가뜨렸다(2026-07-20):
    워커가 점유돼 앱이 502 가 됐고, 워커가 `--max-requests`/`--timeout 60` 으로
    재활용될 때 작업 스레드가 통째로 죽어 백필이 75/796 창에서 조용히 멈췄다.
    → 여기서는 DB 에 요청 플래그만 적고 즉시 돌아온다(202). 실행은 마스터의
    스케줄러 스레드가 1분 안에 가져가고, 중단돼도 cursor 부터 이어서 한다.
    """
    from lemouton.markets import backfill_runner
    from lemouton.markets.order_export import supported_markets

    body = request.get_json(silent=True) or {}
    try:
        days = max(1, min(int(body.get("days") or 365), 1095))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "days 는 숫자"}), 400
    markets = [m for m in (body.get("markets") or []) if m] or list(supported_markets())
    unknown = [m for m in markets if m not in supported_markets()]
    if unknown:
        return jsonify({"ok": False, "error": f"지원하지 않는 마켓: {', '.join(unknown)}"}), 400

    st = backfill_runner.status()
    if st["requested"] and not body.get("force"):
        return jsonify({"ok": False, "error": "이미 백필이 예약·진행 중이에요",
                        "status": st}), 409

    est = backfill_runner.request_backfill(markets, days)
    return jsonify({"ok": True, "requested": True, "days": days, "markets": markets,
                    "note": "스케줄러가 1분 안에 시작해요. 진행은 /status 로 보세요.",
                    **est}), 202


@bp.post("/api/orders-ingest/cancel")
def api_cancel():
    """진행 중인 백필 중단(다음 틱부터 멈춘다)."""
    from lemouton.markets import backfill_runner
    backfill_runner.cancel()
    return jsonify({"ok": True, "status": backfill_runner.status()})
