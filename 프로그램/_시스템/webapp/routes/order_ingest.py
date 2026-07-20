"""주문 적재 운영 라우트 — 현황 확인 + 1년치 백필 실행.

  GET  /api/orders-ingest/coverage   — 마켓별로 어디까지 쌓였나
  GET  /api/orders-ingest/estimate?days=365 — 백필이 몇 번 호출될지(돌리기 전 규모 확인)
  POST /api/orders-ingest/backfill   — 백필 시작(배경 스레드). {"days":365,"markets":[...]}
  GET  /api/orders-ingest/status     — 진행 중인 백필 상태

백필은 마켓 API 를 많이 두드린다(1년치 전 마켓 ≈ 1,760회 · 수십 분). 그래서
**배경 스레드**로 돌리고 진행률을 따로 조회하게 했다. 동시에 두 번 돌지 않는다.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

bp = Blueprint("order_ingest", __name__)

_lock = threading.Lock()
_state: dict = {"running": False, "started_at": None, "finished_at": None,
                "market": "", "done": 0, "total": 0, "results": [], "error": ""}


def _snapshot() -> dict:
    return dict(_state)


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
    return jsonify({"ok": True, **_snapshot()})


@bp.post("/api/orders-ingest/backfill")
def api_backfill():
    """백필 시작. 이미 돌고 있으면 409 — 두 번 돌면 마켓 rate limit 에 걸린다."""
    from lemouton.markets.order_export import supported_markets
    from lemouton.markets.order_ingest import backfill, estimate

    body = request.get_json(silent=True) or {}
    try:
        days = max(1, min(int(body.get("days") or 365), 1095))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "days 는 숫자"}), 400
    markets = [m for m in (body.get("markets") or []) if m] or list(supported_markets())
    unknown = [m for m in markets if m not in supported_markets()]
    if unknown:
        return jsonify({"ok": False, "error": f"지원하지 않는 마켓: {', '.join(unknown)}"}), 400

    with _lock:
        if _state["running"]:
            return jsonify({"ok": False, "error": "이미 백필이 돌고 있어요",
                            "status": _snapshot()}), 409
        est = estimate(markets, days)
        _state.update({"running": True, "started_at": datetime.now(timezone.utc).isoformat(),
                       "finished_at": None, "market": "", "done": 0,
                       "total": est["total_windows"], "results": [], "error": ""})

    def _progress(i, n, market):
        _state["market"] = market

    def _work():
        try:
            results = backfill(markets, days=days,
                               on_progress=lambda i, n, m: (_progress(i, n, m),
                                                            _state.__setitem__("done",
                                                                               _state["done"] + 1)))
            _state["results"] = results
        except Exception as e:                       # noqa: BLE001
            _state["error"] = f"{type(e).__name__}: {e}"
        finally:
            _state["running"] = False
            _state["finished_at"] = datetime.now(timezone.utc).isoformat()

    threading.Thread(target=_work, name="order-backfill", daemon=True).start()
    return jsonify({"ok": True, "started": True, "days": days,
                    "markets": markets, **est})
