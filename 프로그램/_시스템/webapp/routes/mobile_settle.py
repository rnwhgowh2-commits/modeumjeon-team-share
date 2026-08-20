# -*- coding: utf-8 -*-
"""폰 전용 정산 요약 화면 — `/mobile/settle` (E-1 · 사장님 확정 「기간 요약」 fE1).

mobile_orders.py 처럼 따로 둔 이유: 껍데기(mobile_shell)·주문(mobile_orders)·
매트릭스(mobile_matrix)와 관심사가 다르다. 정산 합계는 정산 세계의 일이라,
여기 붙이면 그쪽을 고칠 때 다른 폰 화면 시험이 같이 흔들린다.

데이터는 새 집계를 만들지 않는다 — 재사용 사슬 세 개가 전부다:
  ① 행 = `order_store.load`(주문일 기준 저장분, 마켓 호출 0 — orders.py 의
     `_rows_from_store` 가 90일 초과 주문내역에 쓰는 같은 길, orders.py:168)
  ② 보강 = `order_export.enrich_stored_rows`(라이브 화면과 같은 수준·읽기 전용)
  ③ 정산액·근거 = `sell_source._settlement_for`(**마진계산기 정산=주문내역
     단일원천** 그 함수 — 여기서 산식을 다시 만들면 두 화면이 다른 돈을 말한다)
분류(확정/추정/취소/미확인)는 `pipeline._TAG_RANK` 서열에서 유도한다(사본 금지).

[중요] 정직성 규약(프로젝트 1원칙의 정산판):
  · 미확인(none) 행의 금액은 모른다 — 합에 0 으로 넣지 않고 **건수로만** 센다.
  · KPI 이름은 「정산 확정」이다(시안 fE1 의 「정산 완료」에서 정정) — 저장분엔
    입금(지급) 사실이 없고, 마켓 정산 API 가 **금액을 확정**한 것까지만 안다
    (PC 정산 색칩 margin_settle_cell.js 의 「실정산 확정」과 같은 어휘).
  · 저장분이 아예 없으면 store_empty — 폰은 0 이 아니라 '-' + 이유를 그린다.
    저장분 없는 지원 마켓은 missing 으로 밝힌다(부분합을 전체인 척 금지).
  · 기간(이번 주/지난 주/이번 달)은 **주문일 기준**이다 — `order_store.load` 의
    since/until 계약(order_store.py:256 「주문일 기준」) 그대로. 정산일 축은
    저장분에 없다(지어내지 않는다). 이번 달이 가능한 이유: C-4 가 월을 뺀 건
    마켓 **라이브** 조회가 월 단위로 수 분이라서였는데(스펙 §6 C), 여기는 세
    기간 전부 저장분 DB 읽기라 그 제약이 없고 원천이 갈라지지도 않는다.
"""
from __future__ import annotations

import datetime as _dt
import logging

from flask import Blueprint, jsonify, render_template, request

_log = logging.getLogger(__name__)

bp = Blueprint("mobile_settle", __name__, url_prefix="/mobile")

#: 기간 칩과 서버가 같이 아는 값 — 템플릿 data-period 는 이 밖을 못 쓴다(시험이 대조).
PERIODS = ("this_week", "last_week", "this_month")

# ── 분류 = pipeline._TAG_RANK 서열에서 유도(같은 서열 두 곳 금지) ──
#   3=real·store(실정산 확정) / 2=estimated(추정) / 1=zero_cancel(취소 정산0) /
#   0=none(미확인 — 금액을 모른다).
from lemouton.margin.pipeline import _TAG_RANK

_CONFIRMED_TAGS = {t for t, r in _TAG_RANK.items() if r == 3}
_PENDING_TAGS = {t for t, r in _TAG_RANK.items() if r == 2}
_CANCEL_TAGS = {t for t, r in _TAG_RANK.items() if r == 1}


def _period_range(period: str, today: _dt.date) -> tuple[_dt.date, _dt.date]:
    """기간 칩 → (시작일, 끝일). 주 = 월요일 시작(ISO), 끝은 오늘을 넘지 않는다."""
    monday = today - _dt.timedelta(days=today.weekday())
    if period == "this_week":
        return monday, today
    if period == "last_week":
        return monday - _dt.timedelta(days=7), monday - _dt.timedelta(days=1)
    return today.replace(day=1), today          # this_month


@bp.route("/settle")
def settle():
    """정산 요약 폰 화면 — 데이터는 아래 summary.json 이 준다."""
    return render_template("mobile/settle.html")


@bp.get("/settle/api/summary")
def summary():
    """기간 정산 요약 — {KPI 2칸 + 마켓별 막대}. 마켓 호출 0(저장분만).

    query: ?period=this_week|last_week|this_month
    응답: {ok, period, label, kpi:{pending:{sum,rows}, confirmed:{sum,rows}},
           unknown_rows, cancel_rows,
           markets:[{key,label,total,pending,confirmed,unknown_rows,rows}] (큰 순),
           missing:[저장분 없는 지원 마켓 라벨], store_empty}
    label 은 서버가 포맷한 문자열 — 폰은 ISO 파싱 없이 그대로 그린다.
    """
    period = (request.args.get("period") or "").strip()
    if period not in PERIODS:
        return jsonify({"ok": False,
                        "error": "period 는 %s 중 하나예요." % "·".join(PERIODS)}), 400

    # 함수 안 import — 시험이 원천 함수를 갈아끼워 배선을 검증한다(mobile_shell.menu 관례).
    from lemouton.margin.sell_source import _settlement_for
    from lemouton.markets import order_export as _oe
    from lemouton.markets import order_store as _os

    today = _dt.datetime.now(_oe.KST).date()
    since, until = _period_range(period, today)
    s, u = since.strftime("%Y-%m-%d"), until.strftime("%Y-%m-%d")

    markets = sorted(_oe.supported_markets())
    try:
        # 클레임 이벤트 행은 뺀다 — 정산 돈은 활성 라인이 들고 있고(취소완료도 그
        # 라인의 현재 상태다), 이벤트까지 합치면 같은 돈이 두 번 잡힌다
        # (order_export.py:2244 「정상 행(_kind≠change)만」 과 같은 결).
        rows = _os.load(markets, since=s, until=u, include_claims=False)
        cov = {c["market"]: c for c in _os.coverage()}
    except Exception as e:      # noqa: BLE001 — 0 으로 둔갑 금지: 실패는 실패로 말한다
        _log.exception("[mobile-settle] 저장분 읽기 실패 period=%s", period)
        return jsonify({"ok": False, "error": f"저장분을 읽지 못했어요: {e}"}), 500

    try:
        _oe.enrich_stored_rows(rows)    # 라이브 주문내역과 같은 수준 보강(읽기 전용)
    except Exception:                   # noqa: BLE001 — 보강 실패해도 행은 살린다
        _log.exception("[mobile-settle] 저장분 보강 실패 period=%s", period)

    kpi = {"pending": {"sum": 0, "rows": 0}, "confirmed": {"sum": 0, "rows": 0}}
    unknown_rows = cancel_rows = 0
    per: dict[str, dict] = {}
    for r in rows:
        if str(r.get("_kind") or "") == "change":
            continue                    # 방어 한 겹 — 이벤트 행이 섞여 들어와도 돈은 한 번만
        amount, tag = _settlement_for(r)    # 🔴 정산액·근거의 단일 원천(재계산 금지)
        key = _os._market_key(r) or str(r.get("판매처") or "?")
        m = per.setdefault(key, {"key": key, "label": _oe.market_label(key),
                                 "total": 0, "pending": 0, "confirmed": 0,
                                 "unknown_rows": 0, "rows": 0})
        m["rows"] += 1
        if tag in _CONFIRMED_TAGS:
            kpi["confirmed"]["sum"] += amount
            kpi["confirmed"]["rows"] += 1
            m["confirmed"] += amount
            m["total"] += amount
        elif tag in _PENDING_TAGS:
            kpi["pending"]["sum"] += amount
            kpi["pending"]["rows"] += 1
            m["pending"] += amount
            m["total"] += amount
        elif tag in _CANCEL_TAGS:
            cancel_rows += 1            # 정산 0 확정 — 합에 더할 것이 없다
        else:
            unknown_rows += 1           # 금액을 모른다 — 0 으로 합에 넣지 않는다
            m["unknown_rows"] += 1

    # 저장분 현황 — 부분 데이터를 전체인 척하지 않는다.
    covered = set(cov)
    missing = sorted(_oe.market_label(m) for m in markets if m not in covered)
    store_empty = not any(m in covered for m in markets)

    # 「주문분 기준 (입금일 아님)」 — 「이번 달 정산 확정」을 입금-달로 읽는 오독 방지
    #   (최종 검토 반영. 정산일·입금일 축은 저장분에 없다 — 위 docstring 규약 그대로).
    label = "%d/%d~%d/%d 주문분 기준 (입금일 아님)" % (since.month, since.day,
                                              until.month, until.day)
    return jsonify({
        "ok": True, "period": period, "label": label,
        "kpi": kpi, "unknown_rows": unknown_rows, "cancel_rows": cancel_rows,
        "markets": sorted(per.values(), key=lambda m: m["total"], reverse=True),
        "missing": missing, "store_empty": store_empty,
    })
