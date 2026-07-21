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

#  gunicorn 워커 타임아웃(60초)보다 먼저 우리가 끊는다 — 넘기면 워커가 죽어 앱이 502.
SYNC_TIMEOUT_SEC = 50

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
        # back = 창을 '지금'이 아니라 며칠 전에서 끝낸다. 과거 창을 하나씩 정확히
        #   지정해 돌리려는 용도(호출자가 재시도·속도조절을 직접 제어할 수 있게).
        back = max(0, min(int(body.get("back") or 0), 1200))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "days·back 은 숫자"}), 400

    until = _dt.datetime.now(KST) - _dt.timedelta(days=back)
    since = until - _dt.timedelta(days=days)
    # backfill=true 면 백필 전용 경로(롯데온=정산 API 29일 창)를 그대로 시험한다.
    #  배경 스레드에서만 도는 경로라 진단 통로가 없으면 조용한 유실을 못 잡는다.
    use_backfill = bool(body.get("backfill"))
    # 🔴 이 라우트는 gunicorn **워커**에서 돈다(--timeout 60). 오래 걸리는 창을 그냥
    #    돌리면 워커가 죽고 앱이 502 가 된다(2026-07-20 실제로 냈다). 워커 타임아웃보다
    #    먼저 우리가 끊고, 어디서 봐야 하는지 알려준다.
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(ingest_window, market, since, until, backfill=use_backfill)
        stat = fut.result(timeout=SYNC_TIMEOUT_SEC)
    except _TO:
        ex.shutdown(wait=False)          # 기다리면 워커가 같이 죽는다
        return jsonify({
            "ok": False, "market": market, "days": days, "backfill": use_backfill,
            "error": f"{SYNC_TIMEOUT_SEC}초 안에 못 끝냈어요 — 이 창은 웹에서 재기엔 큽니다. "
                     "기간을 줄이거나, 백필(스케줄러)로 돌리고 /status·/coverage 로 보세요.",
        }), 504
    except Exception as e:                           # noqa: BLE001
        # 진단이 목적이므로 사유를 숨기지 않는다(스택 마지막 줄까지).
        return jsonify({"ok": False, "market": market, "days": days,
                        "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-1500:]}), 500
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, "market": market, "days": days, "back": back,
                    "backfill": use_backfill,
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


@bp.post("/api/orders-ingest/ss-bydate-probe")
def api_ss_bydate_probe():
    """스마트스토어 **주문일(결제일) 기준** 목록 조회로 과거 주문 존재를 확정한다.
    변경일 조회의 보관기간과 독립. body: {"date":"2025-10-15","searchType":"PAYED"}.
    엔드포인트 GET /external/v1/pay-order/seller/product-orders (지도: 조건형 상세조회)."""
    import datetime as _dt

    from lemouton.markets.order_export import _account_client
    body = request.get_json(silent=True) or {}
    date = str(body.get("date") or "").strip()
    stype = str(body.get("searchType") or "PAYED").strip()
    try:
        d0 = _dt.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"ok": False, "error": "date=YYYY-MM-DD"}), 400
    d1 = d0 + _dt.timedelta(days=1)
    client = _account_client("smartstore")

    def _q(p):
        import urllib.parse
        return "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in p.items() if v is not None)

    def _probe():
        query = _q({
            "from": d0.strftime("%Y-%m-%dT00:00:00.000+09:00"),
            "to":   d1.strftime("%Y-%m-%dT00:00:00.000+09:00"),
            "rangeType": "PAYED_DATETIME",
            "productOrderStatuses": stype if stype != "PAYED" else None,
            "pageSize": 100, "page": 1,
        })
        resp = client.request(method="GET",
                              path="/external/v1/pay-order/seller/product-orders",
                              query=query)
        data = resp.get("data") if isinstance(resp, dict) else None
        contents = (data or {}).get("contents") if isinstance(data, dict) else None
        n = len(contents) if isinstance(contents, list) else (
            len(data) if isinstance(data, list) else 0)
        keys = sorted(resp.keys())[:15] if isinstance(resp, dict) else []
        return {"count": n, "resp_keys": keys, "raw": str(resp)[:400]}

    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        out = ex.submit(_probe).result(timeout=SYNC_TIMEOUT_SEC)
    except _TO:
        ex.shutdown(wait=False)
        return jsonify({"ok": False, "date": date, "error": "50초 초과"}), 504
    except Exception as e:                            # noqa: BLE001
        return jsonify({"ok": False, "date": date, "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-800:]}), 500
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, "date": date, **out})


@bp.post("/api/orders-ingest/ss-settle-probe")
def api_ss_settle_probe():
    """스마트스토어 정산(결제일 기준) 교차 검증 — 변경일 조회로 안 나오는 과거 주문이
    실제로 없는지(vs API 보관기간에 가려진 건지) 확인. body: {"date":"2025-10-15"}.
    정산 레코드가 있으면 그 시점에 주문이 있었다는 뜻(변경일 조회가 놓친 것)."""
    from lemouton.markets.order_export import _account_client
    from shared.platforms.smartstore import settlements as _st
    body = request.get_json(silent=True) or {}
    date = str(body.get("date") or "").strip()
    period = str(body.get("period") or "").strip() or None
    client = _account_client("smartstore")
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO

    def _count():
        n, sample = 0, None
        kw = {"search_date": date, "client": client}
        if period:
            kw["period_type"] = period
        for el in _st.iter_settle_by_case(**kw):
            n += 1
            if sample is None and isinstance(el, dict):
                sample = sorted(el.keys())[:20]
            if n >= 500:
                break
        return n, sample

    ex = ThreadPoolExecutor(max_workers=1)
    try:
        n, sample = ex.submit(_count).result(timeout=SYNC_TIMEOUT_SEC)
    except _TO:
        ex.shutdown(wait=False)
        return jsonify({"ok": False, "date": date, "error": "50초 초과"}), 504
    except Exception as e:                            # noqa: BLE001
        return jsonify({"ok": False, "date": date, "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-800:]}), 500
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, "date": date, "period": period,
                    "settle_count": n, "fields": sample})


@bp.post("/api/orders-ingest/step")
def api_step():
    """백필 한 배치를 **워커에서** 처리한다(짧은 시간예산). 호출자가 반복해 끝까지 민다.

    마스터 스케줄러 경로는 gunicorn --preload fork 환경에서 Supabase 연결이 굳는 일이
    있다(2026-07-20: 몇 창 돌고 hang). 워커의 DB 연결은 안정적이라 이 경로로 민다.
    body: {"seconds": 40}  — 이 배치를 최대 몇 초 돌릴지(gunicorn 60초 타임아웃 아래로).
    """
    from lemouton.markets import backfill_runner as BR
    body = request.get_json(silent=True) or {}
    try:
        seconds = max(3.0, min(float(body.get("seconds") or 5), 15))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "seconds 는 숫자"}), 400
    # 창 타임아웃 45초 → 예산 + 한 창 ≤ ~60초(gunicorn 타임아웃) 아래로 확실히.
    res = BR.run_if_requested(budget=seconds, in_worker=True, window_timeout=45)
    return jsonify({"ok": True, "status": res or BR.status()})


@bp.post("/api/orders-ingest/cancel")
def api_cancel():
    """진행 중인 백필 중단(다음 틱부터 멈춘다)."""
    from lemouton.markets import backfill_runner
    backfill_runner.cancel()
    return jsonify({"ok": True, "status": backfill_runner.status()})
