# -*- coding: utf-8 -*-
"""[임시] flaky/누락 정밀 진단 — 스마트스토어 계정별 조회 변동성 + 11번가 특정주문 상태 위치. 확인 후 제거."""
import datetime as _dt

from flask import Blueprint, jsonify, request

bp = Blueprint("api_margin_probe", __name__, url_prefix="/api/margin")
KST = _dt.timezone(_dt.timedelta(hours=9))


@bp.post("/_probe")
def probe():
    import traceback
    try:
        from lemouton.markets import order_export as oe
        body = request.get_json(silent=True) or {}
        market = body.get("market")
        since = _dt.datetime(2026, 7, 5, tzinfo=KST)
        until = _dt.datetime(2026, 7, 12, tzinfo=KST)
        now = _dt.datetime.now(KST)
        out = {"market": market}

        if market == "smartstore":
            from shared.platforms.smartstore.orders import (
                iter_changed_product_order_ids, fetch_order_detail)
            accs = oe._active_accounts("smartstore") or [(None, "대표")]
            out["accounts"] = []
            for prefix, name in accs:
                cli = oe._account_client("smartstore", prefix) if prefix else oe._account_client("smartstore")
                runs = []
                for _ in range(2):   # 2회 반복 → 변동성(flaky) 확인
                    try:
                        ids = iter_changed_product_order_ids(since, min(until + _dt.timedelta(days=3), now), client=cli)
                        runs.append(len(ids))
                    except Exception as e:
                        runs.append(f"ERR {type(e).__name__}: {e}"[:100])
                out["accounts"].append({"acc": name, "id_counts_2run": runs})

        elif market == "eleven11":
            want = str((body.get("order_numbers") or [""])[0])
            from shared.platforms.eleven11 import orders as e11
            fns = [("orders", e11.iter_orders), ("delivered", e11.iter_delivered),
                   ("completed", e11.iter_completed), ("preparing", e11.iter_preparing),
                   ("shipping", e11.iter_shipping), ("canceled", e11.iter_canceled),
                   ("return", e11.iter_return), ("exchange", e11.iter_exchange)]
            accs = oe._active_accounts("eleven11") or [(None, "대표")]
            out["found"] = []
            for prefix, name in accs:
                cli = oe._account_client("eleven11", prefix) if prefix else oe._account_client("eleven11")
                for label, fn in fns:
                    got, hit, err = 0, False, None
                    try:
                        for od in fn(since, max(until, now), client=cli):
                            got += 1
                            if str(od.get("ordNo") or "") == want:
                                hit = True
                    except Exception as e:
                        err = f"{type(e).__name__}: {e}"[:100]
                    if hit or err or got:
                        out["found"].append({"acc": name, "status": label, "got": got, "HIT": hit, "err": err})
        return jsonify(out)
    except Exception as e:   # noqa: BLE001
        return jsonify({"fatal": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()[-1200:]}), 200
