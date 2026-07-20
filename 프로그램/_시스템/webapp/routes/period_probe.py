"""조회기간 상한 실측 라우트 — **읽기 전용 프로브**(조사용, 상시 기능 아님).

마켓 API 는 서버 IP 허용목록(54.116.196.90)에 묶여 있어 로컬 PC 에서는 인증 이전에
거부된다. 그래서 상한 실측은 서버에서 돌 수밖에 없고, 이 라우트가 그 통로다.

  GET /api/period-probe?market=coupang&kind=orders&window_days=32&back_days=0
      → 단발 1회. verdict = accepted|rejected|error

  GET /api/period-probe/sweep?market=coupang&kind=orders&axis=window
      → 사다리 순회(창 크기를 키우며 거부 지점 탐색). axis=lookback 이면 창은 고정하고
        과거로 밀며 탐색.

주의: 실제 라이브 마켓 API 를 때린다. sweep 은 호출 사이 delay(기본 2초, ESM 은 5초)를
두고 **순차** 실행하며, 상한 초과가 확인되면 그 축은 즉시 중단한다(무의미한 추가 호출 방지).
"""
from __future__ import annotations

import os
import time

from flask import Blueprint, jsonify, request

bp = Blueprint("period_probe", __name__)


@bp.before_request
def _gate():
    """조사 기간에만 연다. 라이브에서 무인증으로 마켓 API 를 두드릴 수 있으면 안 된다.

    서버에 `PERIOD_PROBE=1` 을 켜는 동안만 동작하고, 조사 끝나면 끄면 즉시 닫힌다
    (라우트 제거 배포를 기다릴 필요 없음).
    """
    if (os.getenv("PERIOD_PROBE") or "").strip() not in ("1", "true", "TRUE"):
        return jsonify({"ok": False,
                        "error": "프로브 비활성 — 서버 env PERIOD_PROBE=1 필요"}), 404
    return None

# 축별 기본 사다리 — 문서상 상한(1·7·30·31·180) 바로 앞뒤를 노려 경계를 집는다
_WINDOW_LADDER = [1, 2, 7, 8, 15, 31, 32, 60, 90, 180, 181, 365]
_LOOKBACK_LADDER = [0, 30, 90, 180, 365, 545, 730, 1095]

# 마켓별 호출 간격(초) — ESM 은 주문조회 5초/1회 제한이 있다
_DELAY = {"auction": 6, "gmarket": 6, "smartstore": 3}
_DEFAULT_DELAY = 2


def _client(market: str, env_prefix: str | None):
    from lemouton.markets import order_export as _oe
    return _oe._account_client(market, env_prefix)


def _args():
    market = (request.args.get("market") or "").strip()
    kind = (request.args.get("kind") or "orders").strip()
    env_prefix = (request.args.get("env_prefix") or "").strip() or None
    return market, kind, env_prefix


@bp.get("/api/period-probe")
def api_probe():
    from lemouton.markets.period_probe import probe
    market, kind, env_prefix = _args()
    try:
        window_days = float(request.args.get("window_days") or 1)
        back_days = float(request.args.get("back_days") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "window_days·back_days 는 숫자"}), 400
    try:
        res = probe(market, kind, window_days=window_days, back_days=back_days,
                    client=_client(market, env_prefix))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "result": res})


@bp.get("/api/period-probe/sweep")
def api_sweep():
    """사다리 순회. axis=window(1회 조회 창) | lookback(과거 상한)."""
    from lemouton.markets.period_probe import probe
    market, kind, env_prefix = _args()
    axis = (request.args.get("axis") or "window").strip()
    if axis not in ("window", "lookback"):
        return jsonify({"ok": False, "error": "axis 는 window|lookback"}), 400
    try:
        delay = float(request.args.get("delay") or _DELAY.get(market, _DEFAULT_DELAY))
        base_window = float(request.args.get("base_window") or 1)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "delay·base_window 는 숫자"}), 400

    raw = (request.args.get("ladder") or "").strip()
    if raw:
        try:
            ladder = [float(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            return jsonify({"ok": False, "error": "ladder 는 쉼표구분 숫자"}), 400
    else:
        ladder = list(_WINDOW_LADDER if axis == "window" else _LOOKBACK_LADDER)

    client = _client(market, env_prefix)
    steps, stopped = [], None
    for i, step in enumerate(ladder):
        if i:
            time.sleep(delay)
        window = step if axis == "window" else base_window
        back = 0.0 if axis == "window" else step
        try:
            res = probe(market, kind, window_days=window, back_days=back, client=client)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        steps.append(res)
        if res["verdict"] == "rejected":
            stopped = f"{axis}={step} 에서 마켓이 거부 → 중단"
            break
        if res["verdict"] == "error" and i == 0:
            stopped = "첫 호출부터 오류 — 인증·IP 문제일 수 있어 중단(상한 근거 아님)"
            break

    accepted = [s for s in steps if s["verdict"] == "accepted"]
    return jsonify({
        "ok": True, "market": market, "kind": kind, "axis": axis,
        "max_accepted": (max(s["window_days"] if axis == "window" else s["back_days"]
                             for s in accepted) if accepted else None),
        "first_rejected": next((s["window_days"] if axis == "window" else s["back_days"]
                                for s in steps if s["verdict"] == "rejected"), None),
        "stopped": stopped, "steps": steps,
    })
