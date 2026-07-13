# -*- coding: utf-8 -*-
"""[임시 진단] 마켓 API 실호출 프로브 — 누락 주문이 어떤 조회/상태값으로 잡히는지 서버(화이트리스트 IP)에서 확인.
쿠팡 취소/반품 상태값·롯데온 출고지시 창 문제 진단용. 확인 후 제거."""
import datetime as _dt

from flask import Blueprint, jsonify, request

bp = Blueprint("api_margin_probe", __name__, url_prefix="/api/margin")
KST = _dt.timezone(_dt.timedelta(hours=9))


def _pd(v, default):
    try:
        return _dt.datetime.strptime(str(v)[:10], "%Y-%m-%d").replace(tzinfo=KST)
    except Exception:
        return default


@bp.post("/_probe")
def probe():
    import traceback
    try:
        return _probe_impl()
    except Exception as e:   # noqa: BLE001 — 진단용: 실오류 그대로 반환
        return jsonify({"fatal": f"{type(e).__name__}: {e}",
                        "traceback": traceback.format_exc()[-1500:]}), 200


def _probe_impl():
    from lemouton.markets import order_export as oe
    body = request.get_json(silent=True) or {}
    market = body.get("market")
    want = set(str(x) for x in (body.get("order_numbers") or []))
    since = _pd(body.get("since"), _dt.datetime(2026, 7, 3, tzinfo=KST))
    until = _pd(body.get("until"), _dt.datetime(2026, 7, 12, tzinfo=KST))
    now = _dt.datetime.now(KST)
    out = {"market": market, "want_n": len(want), "found_by": {}}

    if market == "coupang":
        from shared.platforms.coupang import claims as cc
        cl = oe._account_client("coupang")     # 작동 경로와 동일한 실계정 클라이언트
        out["client_ok"] = cl is not None
        vid = cc._vendor(cl)
        out["vendor_id"] = str(vid)
        # 1) returnRequests: 각 상태값별 실호출 → 반환 orderId + 우리 want 중 몇 개
        cand = ["RU", "CC", "PR", "UC", "RETURNS_COMPLETED", "RETURNS_UNCHECKED",
                "VENDOR_WAREHOUSE_CONFIRM", "REQUEST_COUPANG_CHECK", "RELEASE_STOP_UNCHECKED"]
        rr = {}
        path = f"/v2/providers/openapi/apis/api/v4/vendors/{vid}/returnRequests"
        for st in cand:
            got, err, hit = 0, None, 0
            try:
                for wf, wt in cc._windows(since, max(until, now)):
                    tok = None
                    for _ in range(30):
                        q = (f"searchType=timeFrame&createdAtFrom={cc._iso(wf)}"
                             f"&createdAtTo={cc._iso(wt)}&status={st}&maxPerPage=50")
                        if tok:
                            q += f"&nextToken={tok}"
                        resp = cl.request("GET", path, query=q)
                        for r in (resp.get("data") or []):
                            got += 1
                            if str(r.get("orderId") or "") in want:
                                hit += 1
                        tok = resp.get("nextToken")
                        if not tok:
                            break
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:120]
            rr[st] = {"got": got, "want_hit": hit, "err": err}
        out["returnRequests_by_status"] = rr
        # 2) exchangeRequests
        exg, ehit, eerr = 0, 0, None
        try:
            for r in cc.iter_exchanges(since, max(until, now), client=cl):
                exg += 1
                if str(r.get("orderId") or "") in want:
                    ehit += 1
        except Exception as e:
            eerr = f"{type(e).__name__}: {e}"[:120]
        out["exchangeRequests"] = {"got": exg, "want_hit": ehit, "err": eerr}

    elif market == "lotteon":
        from shared.platforms.lotteon.orders import iter_delivery_orders
        from shared.platforms.lotteon import claims as lc
        cl = oe._account_client("lotteon")
        out["client_ok"] = cl is not None
        # 출고지시(209) — until vs now 확장 비교
        for label, u in (("until", until), ("now", now)):
            got, hit, err = 0, 0, None
            try:
                for od in iter_delivery_orders(since, u, client=cl):
                    got += 1
                    if str(od.get("odNo") or "") in want:
                        hit += 1
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:120]
            out["found_by"][f"delivery_{label}"] = {"got": got, "want_hit": hit, "err": err}
        # 클레임
        for nm, fn in (("cancel", lc.iter_cancel), ("return", lc.iter_return), ("exchange", lc.iter_exchange)):
            got, hit, err = 0, 0, None
            try:
                for it in fn(since, now, client=cl):
                    got += 1
                    if str(it.get("odNo") or "") in want:
                        hit += 1
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:120]
            out["found_by"][f"claim_{nm}"] = {"got": got, "want_hit": hit, "err": err}

    return jsonify(out)
