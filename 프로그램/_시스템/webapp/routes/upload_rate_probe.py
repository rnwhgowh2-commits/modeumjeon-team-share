# -*- coding: utf-8 -*-
"""업로드 속도 한도 실측 라우트 — **쓰기 프로브**(조사용, 상시 기능 아님).

마켓 API 는 서버 IP 허용목록(54.116.196.90)에 묶여 있어 로컬 PC 에서는 인증 이전에
거부된다. 그래서 실측은 서버에서 돌 수밖에 없고, 이 라우트가 그 통로다.

  GET /api/upload-rate-probe/targets?market=coupang
      → 이 마켓에 등록된 상품·옵션 후보 (읽기 전용)

  GET /api/upload-rate-probe/baseline?market=&product_id=&option_id=
      → 현재 재고 확인 (읽기 전용). 여기서 200 이 안 나오면 측정 불가.

  GET /api/upload-rate-probe/noop-check?market=&product_id=&option_id=&n=3
      → 무변화 갱신 n 회. 마켓이 무변화를 받아주는지·응답시간이 어떤지 확인.

  GET /api/upload-rate-probe/burst?market=&product_id=&option_id=&max_calls=40
      → 간격 없이 연속 → 첫 429 직전까지 = 버스트 용량

  GET /api/upload-rate-probe/ramp?market=&product_id=&option_id=&hold=20
      → 계단식 증속(0.2→20 req/s). 처음 429 난 계단과 그 직전.

★ 안전
  - **무변화 갱신**이라 재고가 바뀌지 않는다. 상태를 남기지 않으므로 원복도 불필요.
  - 매 요청이 시작 전 baseline 을 잡고, 끝나고 **다시 읽어** 값이 그대로인지 확인한다.
    달라졌으면 응답에 `restored=false` 로 표면화한다(조용한 오염 금지).
  - 가격은 어떤 경로로도 건드리지 않는다.
  - `UPLOAD_RATE_PROBE=1` 일 때만 열린다. 끄면 즉시 닫힌다(재배포 대기 불필요).
"""
from __future__ import annotations

import os
import time

from flask import Blueprint, jsonify, request

bp = Blueprint("upload_rate_probe", __name__)

_MARKETS = ("coupang", "smartstore", "lotteon", "eleven11", "auction", "gmarket")
_MAX_CALLS_CAP = 200          # 한 요청이 때릴 수 있는 최대 호출 수
_RAMP_STEPS = (0.2, 0.5, 1, 2, 3, 5, 8, 12, 20)


@bp.before_request
def _gate():
    """조사 기간에만 연다. 라이브에서 무인증으로 쓰기 API 를 두드릴 수 있으면 안 된다."""
    if (os.getenv("UPLOAD_RATE_PROBE") or "").strip() not in ("1", "true", "TRUE"):
        return jsonify({"ok": False,
                        "error": "프로브 비활성 — 서버 env UPLOAD_RATE_PROBE=1 필요"}), 404
    return None


def _args():
    market = (request.args.get("market") or "").strip()
    if market not in _MARKETS:
        return None, (jsonify({"ok": False, "error": f"market 이 잘못됨: {market!r}"}), 400)
    return {
        "market": market,
        "product_id": (request.args.get("product_id") or "").strip(),
        "option_id": (request.args.get("option_id") or "").strip(),
        "env_prefix": (request.args.get("env_prefix") or "").strip() or None,
    }, None


def _client(market: str, env_prefix):
    from lemouton.markets import order_export as _oe
    return _oe._account_client(market, env_prefix)


@bp.get("/api/upload-rate-probe/targets")
def targets():
    """이 마켓에 등록된 상품·옵션 후보 (읽기 전용, 마켓 API 미접촉)."""
    market = (request.args.get("market") or "").strip()
    if market not in _MARKETS:
        return jsonify({"ok": False, "error": f"market 이 잘못됨: {market!r}"}), 400
    limit = min(int(request.args.get("limit") or 20), 100)

    from shared.db import SessionLocal
    from lemouton.uploader.models import MarketRegistration
    with SessionLocal() as s:
        rows = (s.query(MarketRegistration)
                .filter(MarketRegistration.market == market)
                .filter(MarketRegistration.market_product_id.isnot(None))
                .filter(MarketRegistration.market_option_id.isnot(None))
                .limit(limit).all())
        out = [{"canonical_sku": r.canonical_sku,
                "product_id": r.market_product_id,
                "option_id": r.market_option_id,
                "status": getattr(r, "status", None)} for r in rows]
    return jsonify({"ok": True, "market": market, "count": len(out), "targets": out})


@bp.get("/api/upload-rate-probe/baseline")
def baseline():
    """현재 재고만 읽는다. 쓰기 없음."""
    a, err = _args()
    if err:
        return err
    from lemouton.markets.upload_rate_probe import read_stock

    cli = _client(a["market"], a["env_prefix"])
    if cli is None:
        return jsonify({"ok": False, "error": "클라이언트 생성 실패(키 미등록 의심)"}), 400
    t0 = time.monotonic()
    stock = read_stock(a["market"], client=cli,
                       product_id=a["product_id"], option_id=a["option_id"])
    return jsonify({"ok": stock is not None, "market": a["market"],
                    "product_id": a["product_id"], "option_id": a["option_id"],
                    "current_stock": stock,
                    "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
                    "note": None if stock is not None
                            else "재고를 못 읽음 — 측정 불가(상품·옵션ID 확인)"})


def _prepare(a):
    """클라이언트 + baseline. 실패하면 (None, None, 오류응답)."""
    from lemouton.markets.upload_rate_probe import Baseline, ProbeUnsafe

    cli = _client(a["market"], a["env_prefix"])
    if cli is None:
        return None, None, (jsonify({"ok": False,
                                     "error": "클라이언트 생성 실패(키 미등록 의심)"}), 400)
    try:
        base = Baseline.capture(a["market"], client=cli,
                                product_id=a["product_id"], option_id=a["option_id"])
    except ProbeUnsafe as e:
        return None, None, (jsonify({"ok": False, "error": str(e)}), 400)
    return cli, base, None


def _finish(a, cli, base, payload: dict):
    """끝나고 재고가 원래대로인지 **다시 읽어** 확인한다."""
    from lemouton.markets.upload_rate_probe import read_stock

    cur = read_stock(a["market"], client=cli,
                     product_id=a["product_id"], option_id=a["option_id"])
    payload["original_stock"] = base.original_stock
    payload["final_stock"] = cur
    payload["restored"] = (cur is not None and int(cur) == int(base.original_stock))
    if not payload["restored"]:
        payload["warning"] = ("재고가 원래 값과 다르다 — 수기 확인 필요 "
                              f"(원래 {base.original_stock} → 지금 {cur})")
    return jsonify(payload)


@bp.get("/api/upload-rate-probe/noop-check")
def noop_check():
    """무변화 갱신 n 회. 마켓이 받아주는지·응답시간이 조회보다 긴지 본다."""
    a, err = _args()
    if err:
        return err
    n = min(int(request.args.get("n") or 3), 10)
    from lemouton.markets.upload_rate_probe import noop_write

    cli, base, err = _prepare(a)
    if err:
        return err

    calls = []
    for _ in range(n):
        r = noop_write(a["market"], client=cli, product_id=a["product_id"],
                       option_id=a["option_id"], known_stock=base.original_stock)
        calls.append({"status": r.status, "elapsed_ms": round(r.elapsed_ms, 1),
                      "rate_limited": r.is_rate_limited, "error": r.error,
                      "headers": _rate_headers(r.headers)})
    return _finish(a, cli, base, {"ok": True, "market": a["market"],
                                  "mode": "noop", "calls": calls})


@bp.get("/api/upload-rate-probe/burst")
def burst():
    """간격 없이 연속 호출 → 첫 429 직전까지 = 버스트 용량."""
    a, err = _args()
    if err:
        return err
    max_calls = min(int(request.args.get("max_calls") or 40), _MAX_CALLS_CAP)
    from lemouton.markets.upload_rate_probe import noop_write, measure_burst

    cli, base, err = _prepare(a)
    if err:
        return err

    seen = []

    def probe():
        r = noop_write(a["market"], client=cli, product_id=a["product_id"],
                       option_id=a["option_id"], known_stock=base.original_stock)
        seen.append({"status": r.status, "ms": round(r.elapsed_ms, 1),
                     "error": r.error, "headers": _rate_headers(r.headers)})
        return r

    t0 = time.monotonic()
    res = measure_burst(probe, max_calls=max_calls)
    res.update(ok=True, market=a["market"], mode="burst",
               wall_sec=round(time.monotonic() - t0, 2),
               observed_per_sec=(round(len(seen) / max(0.001, time.monotonic() - t0), 2)),
               calls=seen[-10:], total_calls=len(seen),
               rate_headers_seen=[c["headers"] for c in seen if c.get("headers")][-3:])
    return _finish(a, cli, base, res)


@bp.get("/api/upload-rate-probe/ramp")
def ramp():
    """계단식 증속. 각 계단을 hold 초 유지하며 429 가 나면 그 계단이 상한."""
    a, err = _args()
    if err:
        return err
    hold = min(float(request.args.get("hold") or 20), 60.0)
    cooldown = min(float(request.args.get("cooldown") or 10), 60.0)
    from lemouton.markets.upload_rate_probe import noop_write, ramp_up

    cli, base, err = _prepare(a)
    if err:
        return err

    log = []
    budget = {"used": 0}

    def holds_at(rate: float) -> bool:
        interval = 1.0 / rate
        deadline = time.monotonic() + hold
        n = fails = 0
        while time.monotonic() < deadline:
            if budget["used"] >= _MAX_CALLS_CAP:
                break
            r = noop_write(a["market"], client=cli, product_id=a["product_id"],
                           option_id=a["option_id"], known_stock=base.original_stock)
            budget["used"] += 1
            n += 1
            if r.is_rate_limited:
                fails += 1
                log.append({"rate": rate, "calls": n, "verdict": "429",
                            "note": "한도 도달"})
                time.sleep(cooldown)
                return False
            if r.status is None or r.status >= 400:
                log.append({"rate": rate, "calls": n, "verdict": f"error {r.status}",
                            "note": r.error})
                time.sleep(cooldown)
                return False
            time.sleep(interval)
        log.append({"rate": rate, "calls": n, "verdict": "ok"})
        time.sleep(cooldown)
        return True

    t0 = time.monotonic()
    res = ramp_up(holds_at, steps=_RAMP_STEPS)
    res.update(ok=True, market=a["market"], mode="ramp", steps=log,
               total_calls=budget["used"],
               wall_sec=round(time.monotonic() - t0, 2))
    if res.get("last_ok"):
        from lemouton.markets.upload_rate_probe import recommended_rate, calls_per_upload
        res["calls_per_upload"] = calls_per_upload(a["market"])
        res["recommended_calls_per_sec"] = recommended_rate(res["last_ok"])
        res["recommended_uploads_per_sec"] = round(
            res["recommended_calls_per_sec"] / calls_per_upload(a["market"]), 3)
    return _finish(a, cli, base, res)


def _rate_headers(headers) -> dict:
    """한도 관련 헤더만 추린다(어떤 마켓이 뭘 주는지 모르니 후보를 넓게)."""
    if not headers:
        return {}
    want = ("ratelimit", "rate-limit", "retry-after", "quota", "x-rate",
            "gncp-gw", "throttle", "remaining")
    return {k: v for k, v in dict(headers).items()
            if any(w in str(k).lower() for w in want)}
