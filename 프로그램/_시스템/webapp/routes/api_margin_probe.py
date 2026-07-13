# -*- coding: utf-8 -*-
"""[임시] 11번가 특정 취소완료 주문이 전체 조회경로 어디서 사라지는지 추적. 확인 후 제거."""
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
        want = str((body.get("order_numbers") or [""])[0])
        since = _dt.datetime(2026, 7, 5, tzinfo=KST)
        until = _dt.datetime(2026, 7, 12, tzinfo=KST)
        now = _dt.datetime.now(KST)
        out = {"want": want}

        # 1) 전체 조회경로(order_rows) 결과에 있나 + 필드
        rows = oe.order_rows("eleven11", since=since, until=until)
        hit = [r for r in rows if str(r.get("오픈마켓주문번호") or "") == want]
        out["in_order_rows"] = len(hit)
        if hit:
            r = hit[0]
            out["fields"] = {k: r.get(k) for k in ("주문일", "주문상태", "오픈마켓주문번호", "단가", "정산예정금액")}

        # 2) 계정별 iter_canceled 원천에서 그 주문의 raw 필드(ordDt 등)
        from shared.platforms.eleven11 import orders as e11
        out["raw_from_canceled"] = []
        for prefix, name in (oe._active_accounts("eleven11") or []):
            cli = oe._account_client("eleven11", prefix)
            try:
                for od in e11.iter_canceled(since, min(until + _dt.timedelta(days=14), now), client=cli):
                    if str(od.get("ordNo") or "") == want:
                        out["raw_from_canceled"].append({
                            "acc": name,
                            "ordDt": od.get("ordDt"), "ordNo": od.get("ordNo"),
                            "ordPrdSeq": od.get("ordPrdSeq"),
                            "keys": list(od.keys())[:25]})
            except Exception as e:
                out["raw_from_canceled"].append({"acc": name, "err": str(e)[:100]})

        # 3) combined_order_rows(주문일 필터 포함) 결과에 있나
        cr = oe.combined_order_rows(["eleven11"], since=since, until=until, warnings=[])
        out["in_combined"] = sum(1 for r in cr if str(r.get("오픈마켓주문번호") or "") == want)
        return jsonify(out)
    except Exception as e:   # noqa: BLE001
        return jsonify({"fatal": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()[-1500:]}), 200
