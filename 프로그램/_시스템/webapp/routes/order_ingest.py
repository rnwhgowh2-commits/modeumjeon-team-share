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


@bp.get("/api/orders-ingest/completeness")
def api_completeness():
    """마켓별 완성도 요약 — 사장님이 직접 확인하는 근거.

    각 마켓: 저장된 첫 주문일·마지막 주문일·건수 + 「그 이전은 실제로 0건인가」.
    적재분(order_store)만 읽고 마켓 API 는 안 부른다(빠르고 부하 없음). 경계 실측은
    무거우니 여기선 저장분 기준으로만 요약하고, 정밀 경계확인은 별도 프로브가 한다.
    """
    from lemouton.markets.order_export import market_label
    from lemouton.markets.order_store import coverage
    out = []
    for c in coverage():
        out.append({
            "market": c["market"],
            "label": market_label(c["market"]),
            "rows": c["rows"],
            "oldest": c["oldest"][:10],
            "newest": c["newest"][:10],
        })
    out.sort(key=lambda x: x["market"])
    return jsonify({"ok": True, "markets": out,
                    "note": "저장된 범위. '그 이전 0건'은 각 마켓 백필 로그·경계프로브로 확인됨."})


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


@bp.post("/api/orders-ingest/esm-claims-window")
def api_esm_claims_window():
    """옥션·G마켓 과거 클레임 백필 — 한 요청에 (마켓, 계정 1, 창 1)만 처리.

    1년 백필이 orders_only 라 ESM 과거 클레임이 0건이던 구멍을 창 단위로 메운다.
    body: {market, back=0, days=21, account_index=0}. 업서트라 멱등 — 겹쳐 돌아도 안전.
    호출자가 (계정 × 창) 조합을 반복 호출한다(gunicorn 60초 보호 = 한 번에 하나).
    """
    import datetime as _dt

    from lemouton.markets.order_export import KST, _active_accounts
    from lemouton.markets.order_ingest import ingest_esm_claims_window

    body = request.get_json(silent=True) or {}
    market = str(body.get("market") or "").strip()
    if market not in ("auction", "gmarket"):
        return jsonify({"ok": False, "error": "market 은 auction|gmarket"}), 400
    try:
        days = max(1, min(int(body.get("days") or 21), 31))
        back = max(0, min(int(body.get("back") or 0), 1200))
        ai = max(0, int(body.get("account_index") or 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "days·back·account_index 는 숫자"}), 400
    accounts = _active_accounts(market)
    if ai >= len(accounts):
        return jsonify({"ok": True, "done_accounts": True, "accounts": len(accounts)})
    prefix, name = accounts[ai]
    until = _dt.datetime.now(KST) - _dt.timedelta(days=back)
    since = until - _dt.timedelta(days=days)
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        st = ex.submit(ingest_esm_claims_window, market, since, until,
                       prefix=prefix, alias=name).result(timeout=50)
    except _TO:
        return jsonify({"ok": False, "account": name,
                        "error": "50초 초과 — days 를 줄여 재시도"}), 504
    except Exception as e:                              # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("esm-claims-window failed")
        return jsonify({"ok": False, "account": name,
                        "error": f"{type(e).__name__}: {e}"}), 500
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, "market": market, "account": name,
                    "accounts": len(accounts),
                    "window": f"{since:%Y-%m-%d}~{until:%Y-%m-%d}", **st})


@bp.post("/api/orders-ingest/lotteon-orders-window")
def api_lotteon_orders_window():
    """롯데온 과거 209(출고/회수지시) 백필 — 한 요청에 (계정 1, 창 1)만 처리.

    정산 API 백필엔 수령자·주소·전화·송장이 없다 — 209 가 정본(2026-07-22 샵마인
    전열 대조: 구매자 정보 공란 792). body: {back=0, days=5(≤7), account_index=0}.
    창 안(지시생성일)만 걷는다(now 확장 없음 — 스캔범위 폭발 방지). 업서트 멱등.
    """
    import datetime as _dt

    from lemouton.markets.order_export import KST, _active_accounts
    from lemouton.markets.order_ingest import ingest_lotteon_orders_window

    body = request.get_json(silent=True) or {}
    try:
        days = max(1, min(int(body.get("days") or 5), 7))
        back = max(0, min(int(body.get("back") or 0), 1200))
        ai = max(0, int(body.get("account_index") or 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "days·back·account_index 는 숫자"}), 400
    accounts = _active_accounts("lotteon")
    if ai >= len(accounts):
        return jsonify({"ok": True, "done_accounts": True, "accounts": len(accounts)})
    prefix, name = accounts[ai]
    until = _dt.datetime.now(KST) - _dt.timedelta(days=back)
    since = until - _dt.timedelta(days=days)
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        st = ex.submit(ingest_lotteon_orders_window, since, until,
                       prefix=prefix, alias=name).result(timeout=50)
    except _TO:
        return jsonify({"ok": False, "account": name,
                        "error": "50초 초과 — days 를 줄여 재시도"}), 504
    except Exception as e:                              # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("lotteon-orders-window failed")
        return jsonify({"ok": False, "account": name,
                        "error": f"{type(e).__name__}: {e}"}), 500
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, "account": name, "account_index": ai,
                    "accounts": len(accounts), "back": back, "days": days, **st})


@bp.post("/api/orders-ingest/lotteon-claims-window")
def api_lotteon_claims_window():
    """롯데온 과거 클레임 백필 — 한 요청에 (계정 1, 창 1)만 처리.

    확정 전 취소는 정산API(구매확정건만)에 안 나와 과거 취소가 통째 빠졌다
    (2026-07-22 샵마인 대사: 취소완료 계열 233건). body: {back=0, days=30, account_index=0}.
    업서트라 멱등 — 호출자가 (계정 × 창)을 반복 호출한다.
    """
    import datetime as _dt

    from lemouton.markets.order_export import KST, _active_accounts
    from lemouton.markets.order_ingest import ingest_lotteon_claims_window

    body = request.get_json(silent=True) or {}
    try:
        days = max(1, min(int(body.get("days") or 30), 30))
        back = max(0, min(int(body.get("back") or 0), 1200))
        ai = max(0, int(body.get("account_index") or 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "days·back·account_index 는 숫자"}), 400
    accounts = _active_accounts("lotteon")
    if ai >= len(accounts):
        return jsonify({"ok": True, "done_accounts": True, "accounts": len(accounts)})
    prefix, name = accounts[ai]
    until = _dt.datetime.now(KST) - _dt.timedelta(days=back)
    since = until - _dt.timedelta(days=days)
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        st = ex.submit(ingest_lotteon_claims_window, since, until,
                       prefix=prefix, alias=name).result(timeout=50)
    except _TO:
        return jsonify({"ok": False, "account": name,
                        "error": "50초 초과 — days 를 줄여 재시도"}), 504
    except Exception as e:                              # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("lotteon-claims-window failed")
        return jsonify({"ok": False, "account": name,
                        "error": f"{type(e).__name__}: {e}"}), 500
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, "account": name, "accounts": len(accounts),
                    "window": f"{since:%Y-%m-%d}~{until:%Y-%m-%d}", **st})


@bp.post("/api/orders-ingest/eleven11-orders-by-no")
def api_eleven11_orders_by_no():
    """11번가 주문번호 단건 복구 — 한 요청에 최대 8개(gunicorn 60초 보호).

    body: {ord_nos: ["...", ...]}. 계정 순회 조회라 주문당 최대 (계정수×2)회 호출.
    찾은 계정·못 찾은 번호를 그대로 돌려준다.
    """
    from lemouton.markets.order_ingest import ingest_eleven11_orders_by_no

    body = request.get_json(silent=True) or {}
    nos = [str(n).strip() for n in (body.get("ord_nos") or []) if str(n).strip()]
    if not nos:
        return jsonify({"ok": False, "error": "ord_nos 필요"}), 400
    if len(nos) > 8:
        return jsonify({"ok": False, "error": "한 번에 8개까지(반복 호출)"}), 400
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        st = ex.submit(ingest_eleven11_orders_by_no, nos).result(timeout=50)
    except _TO:
        return jsonify({"ok": False, "error": "50초 초과 — 개수를 줄여 재시도"}), 504
    except Exception as e:                              # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("eleven11-orders-by-no failed")
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, **st})


@bp.post("/api/orders-ingest/eleven11-qty-restore")
def api_eleven11_qty_restore():
    """11번가 주문행 수량 0(잔여수량 오염) → 클레임 원수량 복원 — 멱등 보수 1회 실행."""
    from lemouton.markets.order_store import restore_eleven11_qty_from_claims
    try:
        st = restore_eleven11_qty_from_claims()
        return jsonify({"ok": True, **st})
    except Exception as e:                              # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("eleven11-qty-restore failed")
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


@bp.post("/api/orders-ingest/claim-status-sync")
def api_claim_status_sync():
    """클레임 이력 → 주문행 상태 보정을 즉시 1회 실행(멱등·읽기+상태갱신만).

    증분 수집 끝에도 자동으로 돌지만(6시간 주기), 배포 직후·진단 시 바로 돌려
    결과(checked·fixed)를 확인하는 통로. 2026-07-21 이전 적재분(취소됐는데
    '배송준비중'으로 남은 74쌍)의 일회성 보정이 첫 용도다.
    """
    from lemouton.markets.order_store import (backfill_claim_dates_from_lines,
                                              dedupe_undated_claim_ghosts,
                                              sync_status_from_claims)
    try:
        st = sync_status_from_claims()
        ghosts = dedupe_undated_claim_ghosts()      # 재수집으로 날짜 생긴 쌍둥이 정리
        dates = backfill_claim_dates_from_lines()   # 날짜불명 클레임 실주문일 보정도 함께
        return jsonify({"ok": True, **st, "dates": dates, "ghosts": ghosts})
    except Exception as e:                              # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("claim-status-sync failed")
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


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
    # allow_unverified: ESM 등 아직 UI 미노출 마켓의 조회를 진단·백필용으로 허용(읽기만).
    _KNOWN = {"smartstore", "coupang", "lotteon", "eleven11", "auction", "gmarket"}
    ok_market = market in supported_markets() or (
        bool(body.get("allow_unverified")) and market in _KNOWN)
    if not ok_market:
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


@bp.post("/api/orders-ingest/lotteon-odno-probe")
def api_lotteon_odno_probe():
    """롯데온 209 를 **주문번호 단건**으로 조회 — 취소건도 나오는지 실측.

    근거: 공식문서 body "기간 또는 odNo"(우리는 기간만 써 왔음). 샵마인이 옛 계정
    연동 후에도 취소건 상세를 읽는다는 사장님 관찰(2026-07-22) — 이 경로가 맞으면
    취소 공란의 근본 해법이 된다. body: {"od_no": "...", "date": "yyyymmdd"(선택)}.
    값은 마스킹(키·존재 여부만) — 개인정보 비노출.
    """
    from lemouton.markets.order_export import _account_client, _active_accounts
    from shared.platforms.lotteon.orders import fetch_delivery_orders, _orders_of

    body = request.get_json(silent=True) or {}
    od_no = str(body.get("od_no") or "").strip()
    date = str(body.get("date") or "").strip()
    if not od_no:
        return jsonify({"ok": False, "error": "od_no 필수"}), 400

    def _try(client, acct, label, **kw):
        try:
            resp = fetch_delivery_orders(client=client, od_no=od_no, **kw)
            rc = (resp or {}).get("returnCode")
            rows = _orders_of(resp or {})
            hit = [r for r in rows if str(r.get("odNo")) == od_no]
            out = {"acct": acct, "label": label, "returnCode": rc,
                   "rows": len(rows), "hit": len(hit)}
            if hit:
                r0 = hit[0]
                out["filled"] = {k: bool(str(r0.get(k) or "").strip())
                                 for k in ("odrNm", "dvpCustNm", "dvpMphnNo", "mphnNo",
                                           "dvpStnmZipAddr", "actualAmt", "spdNm")}
                out["step"] = r0.get("odPrgsStepCd")
                out["typ"] = r0.get("odTypCd")
            return out
        except Exception as e:                        # noqa: BLE001
            return {"acct": acct, "label": label,
                    "error": f"{type(e).__name__}: {e}"[:120]}

    def _try_benefit(client, acct):
        """주문혜택 조회(getSROrderList) — 취소건에도 혜택 기록이 남아있나.

        남아있다면 실결제 = 단가×수량 − 혜택합(fvrAmt) 정확 계산 가능(클레임 API 가
        단가·수량은 준다). 요청 스펙 미접수라 표준 body(trNo류+odNo)로 시도.
        """
        cfg = getattr(client, "_cfg", {}) or {}
        base = {"trGrpCd": cfg.get("tr_grp_cd", "SR"), "trNo": cfg.get("tr_no", ""),
                "lrtrNo": cfg.get("lrtr_no", ""), "odNo": od_no}
        d8 = date if len(date) == 8 else od_no[:8]     # 롯데온 주문번호 앞 8자리 = 주문일
        variants = [("dttm", {"srchStrtDttm": d8 + "000000", "srchEndDttm": d8 + "235959"}),
                    ("dt", {"srchStrtDt": d8 + "000000", "srchEndDt": d8 + "235959"})]
        outs = []
        for vlabel, extra in variants:
            try:
                resp = client.request(method="POST",
                                      path="/v1/openapi/order/v1/getSROrderList",
                                      body=dict(base, **extra))
                rc = (resp or {}).get("returnCode")
                data = (resp or {}).get("data") or []
                if isinstance(data, dict):
                    # 실측: data = {"orderItems": [...]} 래퍼(2026-07-22 프로브)
                    data = (data.get("orderItems") or data.get("fvrList")
                            or data.get("list") or [])
                out = {"acct": acct, "label": f"주문혜택-{vlabel}", "returnCode": rc,
                       "rows": len(data)}
                if data:
                    d0 = data[0]
                    out["keys"] = (sorted(d0.keys())[:20]
                                   if isinstance(d0, dict) else str(type(d0)))
                    out["rows_detail"] = str(d0)[:300]
                    outs.append(out)
                    break
                out["message"] = str((resp or {}).get("message") or "")[:100]
                outs.append(out)
            except Exception as e:                    # noqa: BLE001
                outs.append({"acct": acct, "label": f"주문혜택-{vlabel}",
                             "error": f"{type(e).__name__}: {e}"[:120]})
        for o in outs:
            if o.get("rows"):
                return o
        return outs[-1]

    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO

    def _probe():
        # ★ifCplYN 빈값 = '미연동 신규주문'만 — 연동완료(Y)까지 훑어야 기존 주문이 보인다.
        #   또 롯데온은 계정별 trNo — 주문 소유 계정을 모르면 전 계정을 돈다.
        tries = []
        for prefix, name in _active_accounts("lotteon"):
            client = _account_client("lotteon", prefix)
            if client is None:
                continue
            for cpl in ("Y", ""):
                t = _try(client, name, f"odNo만 ifCpl={cpl or '빈값'}",
                         srch_start="", srch_end="", if_cpl_yn=cpl)
                tries.append(t)
                if t.get("hit"):
                    return tries
            if len(date) == 8:
                t = _try(client, name, "odNo+주문일 ifCpl=Y",
                         srch_start=date + "000000", srch_end=date + "235959",
                         if_cpl_yn="Y")
                tries.append(t)
                if t.get("hit"):
                    return tries
            tb = _try_benefit(client, name)
            tries.append(tb)
            if tb.get("rows"):
                return tries
        return tries

    ex = ThreadPoolExecutor(max_workers=1)
    try:
        tries = ex.submit(_probe).result(timeout=SYNC_TIMEOUT_SEC)
    except _TO:
        ex.shutdown(wait=False)
        return jsonify({"ok": False, "error": "50초 초과"}), 504
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, "od_no": od_no, "tries": tries})


@bp.post("/api/orders-ingest/eleven11-settle-shape-probe")
def api_eleven11_settle_shape_probe():
    """11번가 settlementList 원시 라인 구조 실측 — 배송비 라인 구분자 찾기.

    샵마인 대조(2026-07-23): 우리 정산예정금액이 샵마인보다 정확히 +배송비만큼 큼
    = 배송비 정산 라인이 상품 라인과 같은 (ordNo,ordPrdSeq)로 합산되는 중.
    분리하려면 라인 유형 필드를 알아야 한다. 값은 키·타입만(마스킹).
    body: {"days": 3}
    """
    import datetime as _dt2

    from lemouton.markets.order_export import _account_client

    body = request.get_json(silent=True) or {}
    try:
        days = max(1, min(int(body.get("days") or 3), 31))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "days 는 숫자"}), 400
    client = _account_client("eleven11")
    if client is None:
        return jsonify({"ok": False, "error": "11번가 계정 키 없음"}), 400

    def _probe():
        from xml.etree.ElementTree import Element  # noqa: F401
        from shared.platforms.eleven11.orders import _localname, _parse
        until = _dt2.datetime.now()
        since = until - _dt2.timedelta(days=days)
        path = "/rest/settlement/settlementList/{s}/{e}".format(
            s=since.strftime("%Y%m%d"), e=until.strftime("%Y%m%d"))
        xml_text = client.request("GET", path)
        root = _parse(xml_text) if isinstance(xml_text, str) else xml_text
        if root is None:
            return {"error": "빈 응답"}
        keysets = {}
        samples = []
        n = 0
        for el in root.iter():
            entry = {}
            for child in el:
                entry[_localname(child.tag)] = (child.text or "").strip()
            if not entry.get("ordNo"):
                continue
            n += 1
            ks = ",".join(sorted(entry.keys()))
            if ks not in keysets:
                keysets[ks] = 0
                # 값 마스킹: 금액류는 자릿수만, 코드류는 그대로(개인정보 아님)
                samp = {}
                for k, v in entry.items():
                    if any(t in k.lower() for t in ("amt", "prc", "fee", "cst")):
                        samp[k] = f"num({len(v)})"
                    elif any(t in k.lower() for t in ("nm", "name", "addr")):
                        samp[k] = f"str({len(v)})"
                    else:
                        samp[k] = v[:20]
                samples.append(samp)
            keysets[ks] += 1
        return {"lines": n, "keyset_count": len(keysets),
                "keysets": [{"keys": k.split(","), "count": c}
                            for k, c in keysets.items()][:4],
                "samples": samples[:4]}

    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        out = ex.submit(_probe).result(timeout=SYNC_TIMEOUT_SEC)
    except _TO:
        ex.shutdown(wait=False)
        return jsonify({"ok": False, "error": "50초 초과"}), 504
    except Exception as e:                            # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-600:]}), 500
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, "days": days, **out})


@bp.post("/api/orders-ingest/amount-probe")
def api_amount_probe():
    """주문 1건의 **원시 금액 필드 전량** 덤프 — 샵마인 J~N열 잔차의 원천 판별용.

    2026-07-23 대조에서 공식으로 못 푼 3계열: ①롯데온 40건 = 우리 M이 정확히
    판매가×2% 큼(34건은 0차이 — 판별 필드가 API에 있어야 함) ②11번가 배송완료
    잔차(+1,247 등)·실결제 소액차(−324 등) ③쿠팡 배송비 5,000 미포착(762660613)·
    단가 39,900≠39,000(769047062). 개인정보(이름·주소·전화)는 키 자체를 제외.
    body: {"market": "eleven11"|"lotteon"|"coupang", "ono": "...", "date": "yyyymmdd"(선택)}
    """
    import datetime as _dt2
    import re as _re

    from lemouton.markets.order_export import _account_client, _active_accounts

    body = request.get_json(silent=True) or {}
    market = str(body.get("market") or "").strip()
    ono = str(body.get("ono") or "").strip()
    date = str(body.get("date") or "").strip()
    if market not in ("eleven11", "lotteon", "coupang") or not ono:
        return jsonify({"ok": False, "error": "market(eleven11|lotteon|coupang)·ono 필수"}), 400

    _BLACK = _re.compile(r"(?i)(nm$|name|addr|tel|prtbl|mphn|mail|zip|memo|cont$"
                         r"|rcvr|buyer|orderer|receiver|cust|email|memid)")
    _WHITE = _re.compile(r"(?i)(amt|cst|prc|price|fee|qty|cnt|yn$|seq|stl|dlv|dscnt"
                         r"|dc|discount|point|remote|no$|cd$|dt$|stat|typ|bndl)")

    def _amounts(d: dict) -> dict:
        out = {}
        for k, v in (d or {}).items():
            if _BLACK.search(k):
                continue
            sv = str(v)
            if _WHITE.search(k) or sv.replace(".", "").replace("-", "").isdigit():
                out[k] = sv[:40]
        return out

    def _probe():
        results = []
        if market == "eleven11":
            from shared.platforms.eleven11.orders import (
                iter_orders, iter_preparing, iter_shipping, iter_delivered,
                iter_completed)
            d8 = date if len(date) == 8 else (ono[:8] if ono[:2] == "20" else "")
            if not d8:
                return {"error": "date(yyyymmdd) 필요(ordNo 에 날짜 없음)"}
            base = _dt2.datetime.strptime(d8, "%Y%m%d").replace(
                tzinfo=_dt2.timezone(_dt2.timedelta(hours=9)))
            since = base - _dt2.timedelta(days=1)
            until = min(base + _dt2.timedelta(days=2),
                        _dt2.datetime.now(_dt2.timezone(_dt2.timedelta(hours=9))))
            lists = [("complete", iter_orders), ("packaging", iter_preparing),
                     ("shipping", iter_shipping), ("dlvcompleted", iter_delivered),
                     ("completed", iter_completed)]
            for prefix, name in _active_accounts("eleven11"):
                client = _account_client("eleven11", prefix)
                if client is None:
                    continue
                for lname, fn in lists:
                    try:
                        for od in fn(since, until, client=client):
                            if str(od.get("ordNo")) == ono:
                                results.append({"acct": name, "list": lname,
                                                "fields": _amounts(od)})
                    except Exception as e:              # noqa: BLE001
                        results.append({"acct": name, "list": lname,
                                        "error": f"{type(e).__name__}: {e}"[:100]})
                if any("fields" in r for r in results):
                    break                       # 소유 계정 발견 — 다른 계정은 안 훑음
        elif market == "lotteon":
            from shared.platforms.lotteon.orders import fetch_delivery_orders, _orders_of
            d8 = date if len(date) == 8 else ono[:8]
            for prefix, name in _active_accounts("lotteon"):
                client = _account_client("lotteon", prefix)
                if client is None:
                    continue
                for cpl in ("Y", ""):
                    try:
                        resp = fetch_delivery_orders(client=client, od_no=ono,
                                                     srch_start=d8 + "000000",
                                                     srch_end=d8 + "235959",
                                                     if_cpl_yn=cpl)
                        for od in _orders_of(resp or {}):
                            if str(od.get("odNo")) == ono:
                                results.append({"acct": name, "ifCpl": cpl or "빈값",
                                                "fields": _amounts(od)})
                    except Exception as e:              # noqa: BLE001
                        results.append({"acct": name, "ifCpl": cpl or "빈값",
                                        "error": f"{type(e).__name__}: {e}"[:100]})
                if any("fields" in r for r in results):
                    break
        else:                                           # coupang
            from shared.platforms.coupang.orders import fetch_orders
            d8 = date
            if len(d8) != 8:
                return {"error": "쿠팡은 date(yyyymmdd=주문일) 필수(주문번호에 날짜 없음)"}
            base = _dt2.datetime.strptime(d8, "%Y%m%d").replace(
                tzinfo=_dt2.timezone(_dt2.timedelta(hours=9)))
            since, until = base - _dt2.timedelta(days=1), base + _dt2.timedelta(days=2)
            statuses = ("ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING",
                        "FINAL_DELIVERY", "NONE_TRACKING")
            for prefix, name in _active_accounts("coupang"):
                client = _account_client("coupang", prefix)
                if client is None:
                    continue
                found = False
                for st in statuses:
                    token = None
                    try:
                        while True:
                            resp = fetch_orders(since, until, client=client,
                                                status=st, next_token=token)
                            for box in (resp or {}).get("data") or []:
                                if str(box.get("orderId")) != ono:
                                    continue
                                found = True
                                ent = {"acct": name, "status": st,
                                       "box": _amounts({k: v for k, v in box.items()
                                                        if not isinstance(v, (dict, list))}),
                                       "shippingPrice": box.get("shippingPrice"),
                                       "remotePrice": box.get("remotePrice"),
                                       "items": []}
                                for it in box.get("orderItems") or []:
                                    ent["items"].append(_amounts(
                                        {k: (v.get("units") if isinstance(v, dict)
                                             and "units" in v else v)
                                         for k, v in it.items()
                                         if not isinstance(v, list)}))
                                results.append(ent)
                            token = (resp or {}).get("nextToken") or None
                            if not token:
                                break
                    except Exception as e:              # noqa: BLE001
                        results.append({"acct": name, "status": st,
                                        "error": f"{type(e).__name__}: {e}"[:100]})
                    if found:
                        break
                if found:
                    break
        return {"results": results[:12]}

    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        out = ex.submit(_probe).result(timeout=SYNC_TIMEOUT_SEC)
    except _TO:
        ex.shutdown(wait=False)
        return jsonify({"ok": False, "error": "50초 초과"}), 504
    except Exception as e:                              # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-600:]}), 500
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, "market": market, "ono": ono, **out})


@bp.post("/api/orders-ingest/shopmine-upsert")
def api_shopmine_upsert():
    """샵마인 내보내기 행을 적재(sm_uid 업서트 — 멱등). body: {"rows": [{...} ≤500]}.

    공란 채움 소스 ⑥(order_export._shopmine_fill)의 재료. 같은 파일 재업로드 안전.
    """
    from lemouton.markets.models_shopmine import ShopmineOrder

    body = request.get_json(silent=True) or {}
    rows = body.get("rows") or []
    if not rows or len(rows) > 500:
        return jsonify({"ok": False, "error": "rows 는 1~500개"}), 400
    _FIELDS = ("market", "order_no", "account_alias", "ordered_at", "product_name",
               "option1", "qty", "unit_price", "paid_amount", "buyer", "recipient",
               "phone", "buyer_phone", "zipcode", "address", "invoice")
    s = _session()
    try:
        new = updated = skipped = 0
        pending: dict = {}    # 배치 내 중복 가드(autoflush=False 대응 — order_store.save 패턴)
        for r in rows:
            uid = str(r.get("sm_uid") or "").strip()
            if not uid:
                skipped += 1              # 고유코드 없는 행은 저장 안 함(키 날조 금지)
                continue
            obj = pending.get(uid) or s.get(ShopmineOrder, uid)
            vals = {k: str(r.get(k) or "").strip() for k in _FIELDS}
            if obj is None:
                obj = ShopmineOrder(sm_uid=uid, **vals)
                s.add(obj)
                new += 1
            else:
                for k, v in vals.items():
                    if v:                 # 새 값이 비었으면 기존 유지(덜 주는 재업로드 안전)
                        setattr(obj, k, v)
                updated += 1
            pending[uid] = obj
        s.commit()
        return jsonify({"ok": True, "new": new, "updated": updated, "skipped": skipped})
    finally:
        s.close()


@bp.post("/api/orders-ingest/order-no-membership")
def api_order_no_membership():
    """주문번호 목록이 우리 적재분(market_order_lines·claim_events)에 있는지 일괄 대조.

    용도(2026-07-22 사장님): 샵마인 3개월치 (마켓×계정)별 주문번호를 우리 1년 적재와
    교집합 내어 「어느 샵마인 계정 = 우리 어느 계정」 매핑을 **근거(교집합 N/M)**로 확정.
    body: {"market": "lotteon", "nos": ["...", ...]}  (nos ≤ 3000)
    응답: found/total + 우리 계정명 분포 + 미존재 샘플.
    """
    from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine

    body = request.get_json(silent=True) or {}
    market = str(body.get("market") or "").strip()
    nos = [str(x).strip() for x in (body.get("nos") or []) if str(x).strip()]
    if not market or not nos:
        return jsonify({"ok": False, "error": "market·nos 필수"}), 400
    if len(nos) > 3000:
        return jsonify({"ok": False, "error": "nos 는 3000개 이하"}), 400
    s = _session()
    try:
        found = {}
        for o in (s.query(MarketOrderLine.order_no, MarketOrderLine.account)
                  .filter(MarketOrderLine.market == market,
                          MarketOrderLine.order_no.in_(nos)).all()):
            found.setdefault(o.order_no, o.account or "(계정없음)")
        # 주문 라인엔 없고 클레임 이벤트로만 잡힌 번호도 '있음'으로 집계.
        rest = [n for n in nos if n not in found]
        if rest:
            for c in (s.query(MarketClaimEvent.order_no)
                      .filter(MarketClaimEvent.market == market,
                              MarketClaimEvent.order_no.in_(rest)).all()):
                found.setdefault(c.order_no, "(클레임만)")
        accounts = {}
        for acc in found.values():
            accounts[acc] = accounts.get(acc, 0) + 1
        missing = [n for n in nos if n not in found]
        return jsonify({"ok": True, "market": market, "total": len(nos),
                        "found": len(found), "accounts": accounts,
                        "missing_sample": missing[:5], "missing": len(missing)})
    finally:
        s.close()


@bp.post("/api/orders-ingest/lotteon-claim-shape-probe")
def api_lotteon_claim_shape_probe():
    """롯데온 취소 클레임 **원시 응답의 필드 구조**를 본다(값은 마스킹 — 키만).

    왜 — claims._iter_claim 이 부모 data[] 에서 odNo·clmNo 만 꺼내고 나머지를 버린다.
    부모/아이템에 주문자·주소·실결제 필드가 있는데 매핑만 안 한 것이면, 취소완료 행의
    공란 39건(2026-07-21 감사)을 재조회 없이 채울 수 있다. 문서 요약이 아닌 실응답이 정본.
    body: {"days": 7}
    """
    import datetime as _dt2

    from lemouton.markets.order_export import _account_client

    body = request.get_json(silent=True) or {}
    try:
        days = max(1, min(int(body.get("days") or 7), 29))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "days 는 숫자"}), 400
    client = _account_client("lotteon")
    if client is None:
        return jsonify({"ok": False, "error": "롯데온 계정 키 없음"}), 400

    def _shape(v, depth=0):
        """값은 버리고 구조(키·타입·문자열 길이)만 남긴다 — 개인정보 비노출."""
        if depth > 4:
            return "…"
        if isinstance(v, dict):
            return {k: _shape(x, depth + 1) for k, x in v.items()}
        if isinstance(v, list):
            return [_shape(v[0], depth + 1)] if v else []
        if isinstance(v, str):
            return f"str({len(v)})" if len(v) > 2 else (v if v.isdigit() else "str")
        return type(v).__name__

    def _probe():
        from shared.platforms.lotteon import claims as _clm
        until = _dt2.datetime.now()
        since = until - _dt2.timedelta(days=days)
        resp = _clm._fetch(_clm._PATH_CANCEL, since.strftime(_clm._FMT),
                           until.strftime(_clm._FMT), client)
        data = (resp.get("data") if isinstance(resp, dict) else None) or []
        out = {"count": len(data)}
        if data:
            out["parent_keys"] = sorted(data[0].keys())
            out["parent_shape"] = _shape({k: v for k, v in data[0].items()
                                          if k != "itemList"})
            items = data[0].get("itemList") or []
            if items:
                out["item_keys"] = sorted(items[0].keys())
                out["item_shape"] = _shape(items[0])
        return out

    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _TO
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        out = ex.submit(_probe).result(timeout=SYNC_TIMEOUT_SEC)
    except _TO:
        ex.shutdown(wait=False)
        return jsonify({"ok": False, "error": "50초 초과"}), 504
    except Exception as e:                            # noqa: BLE001
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-800:]}), 500
    finally:
        ex.shutdown(wait=False)
    return jsonify({"ok": True, "days": days, **out})


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
    span = max(1, min(int(body.get("days") or 1), 366))
    d1 = d0 + _dt.timedelta(days=span)
    client = _account_client("smartstore")

    def _q(p):
        import urllib.parse
        return "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in p.items() if v is not None)

    def _probe():
        n, page = 0, 1
        first_raw = None
        while page <= 50:
            query = _q({
                "from": d0.strftime("%Y-%m-%dT00:00:00.000+09:00"),
                "to":   d1.strftime("%Y-%m-%dT00:00:00.000+09:00"),
                "rangeType": "PAYED_DATETIME",
                "productOrderStatuses": stype if stype != "PAYED" else None,
                "pageSize": 300, "page": page,
            })
            resp = client.request(method="GET",
                                  path="/external/v1/pay-order/seller/product-orders",
                                  query=query)
            if first_raw is None:
                first_raw = str(resp)[:300]
            data = resp.get("data") if isinstance(resp, dict) else None
            contents = (data or {}).get("contents") if isinstance(data, dict) else None
            got = len(contents) if isinstance(contents, list) else 0
            n += got
            pg = (data or {}).get("pagination") if isinstance(data, dict) else None
            if not got or not (pg or {}).get("hasNext"):
                break
            page += 1
        return {"count": n, "pages": page, "raw": first_raw}

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
