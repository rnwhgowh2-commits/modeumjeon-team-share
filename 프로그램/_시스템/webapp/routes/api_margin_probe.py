# -*- coding: utf-8 -*-
"""[임시] 롯데온 누락 주문 정밀 진단 — 6건이 어느 조회(ifCplYN·계정·진행단계)에 있는지 서버에서 실호출. 확인 후 제거."""
import datetime as _dt

from flask import Blueprint, jsonify, request

bp = Blueprint("api_margin_probe", __name__, url_prefix="/api/margin")
KST = _dt.timezone(_dt.timedelta(hours=9))


@bp.post("/_probe")
def probe():
    import traceback
    try:
        from lemouton.markets import order_export as oe
        from shared.platforms.lotteon.orders import iter_delivery_orders, fetch_progress_states
        body = request.get_json(silent=True) or {}
        want = set(str(x) for x in (body.get("order_numbers") or []))
        since = _dt.datetime(2026, 7, 3, tzinfo=KST)
        now = _dt.datetime.now(KST)
        out = {"want_n": len(want), "accounts": [], "progress": {}}

        # 활성 롯데온 계정 전부 × ifCplYN("" 신규 / "Y" 연동완료) 조회
        accs = oe._active_accounts("lotteon") or [(None, "대표")]
        for prefix, name in accs:
            cli = oe._account_client("lotteon", prefix) if prefix else oe._account_client("lotteon")
            for flag in ("", "Y"):
                got, hit, err, sample = 0, 0, None, []
                try:
                    for od in iter_delivery_orders(since, now, if_cpl_yn=flag, client=cli):
                        got += 1
                        on = str(od.get("odNo") or "")
                        if on in want:
                            hit += 1
                        if len(sample) < 3:
                            sample.append(on)
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"[:150]
                out["accounts"].append({"acc": name, "ifCplYN": flag or "(신규)",
                                        "got": got, "hit": hit, "sample": sample, "err": err})

        # 6건 각각 진행단계(140, odNo 단건) 조회 → 현재 어떤 단계인지
        cli0 = oe._account_client("lotteon")
        for on in sorted(want)[:8]:
            try:
                resp = fetch_progress_states(
                    srch_start=(since).strftime("%Y%m%d%H%M%S"),
                    srch_end=now.strftime("%Y%m%d%H%M%S"),
                    od_no=on, client=cli0)
                data = resp.get("data") or resp
                out["progress"][on] = str(data)[:200]
            except Exception as e:
                out["progress"][on] = f"ERR {type(e).__name__}: {e}"[:120]
        return jsonify(out)
    except Exception as e:   # noqa: BLE001
        return jsonify({"fatal": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()[-1200:]}), 200
