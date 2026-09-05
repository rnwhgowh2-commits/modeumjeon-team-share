# -*- coding: utf-8 -*-
"""마진계산기 행에 「정산여부」 + 「주문상태 이력」을 붙인다.

2026-09-05 사장님 지시 — 클레임(취소요청·반품요청·교환요청 등)으로 들어온 주문상태가
그 뒤 실제로 어떻게 결론났는지(철회·정산완료 등)를 화면이 안 보여줘서 이미 끝난
정상거래가 「손실 진행중」으로 잘못 보였다. 이 모듈은:
  ① `_정산여부` — O(마켓이 실제로 「입금했다」고 알려준 것만) / 확인불가(그 채널이
     없거나 아직 안 옴) / 진행중(반품·교환·취소가 마켓에서도 아직 안 끝남).
     ★ 폴백 금지 — 예정일이 지났다고 O 로 단정하지 않는다(재고·가격 정합성과 같은 원칙).
  ② `_주문상태이력` — 클레임 이벤트(시간순) + 주문 라인 자체 상태 전환(status_prev→상태,
     status_at) 을 합쳐 하나의 타임라인으로. 예: [{"status":"취소요청","at":"2026-08-30"},
     {"status":"배송완료","at":"2026-09-03"}].

「정산 O」 판정은 `_settle_paid_date`(마켓이 실제로 송금했다고 알려준 날짜) 유무 하나로
정한다 — 이 필드는 쿠팡(지급내역조회 DONE)·스마트스토어(settleCompleteDate)·롯데온
(lotteon_paid 지급내역 크롤, `refresh_settlement_lotteon`이 매 틱 조인) 셋 다 이미
채워 넣는 **같은 필드**다(단일 원천 — `lemouton.margin.settle_plan.classify`의 "paid"
부류와 동일 근거). 그 채널이 없는 마켓(11번가·옥션·G마켓)은 이 필드가 절대 안 채워지므로
자연히 「확인불가」로 떨어진다 — 마켓별로 따로 분기하지 않아도 정직하다.
"""
from __future__ import annotations

import datetime as _dt
import logging

logger = logging.getLogger(__name__)

# 두 소비자(마진계산기 matched 행 · 주문내역 order_store 원행)가 마켓을 서로 다른
#  표기로 부른다 — 마진계산기는 '마켓'(config.MARKET_REVERSE 결과: 쿠팡·G마켓2.0·롯데ON…),
#  주문내역은 '판매처'(order_store._MARKET_KEY 기준: 쿠팡·G마켓·롯데온…). 둘 다 여기
#  한 표로 합쳐 받는다 — 어느 화면에서 불러도 같은 판정을 쓰게(단일 원천).
_DISPLAY_TO_INTERNAL = {
    "스마트스토어": "smartstore", "쿠팡": "coupang", "11번가": "eleven11",
    "롯데온": "lotteon", "롯데ON": "lotteon", "옥션": "auction", "옥션2.0": "auction",
    "G마켓": "gmarket", "G마켓2.0": "gmarket",
}


def _row_market_disp(r: dict) -> str:
    """행의 마켓 표시값 — 마진계산기(마켓)·주문내역(판매처) 둘 다 받는다."""
    return str(r.get("마켓") or r.get("판매처") or "").strip()


def _row_order_no(r: dict) -> str:
    """행의 주문번호 — 마진계산기(마켓주문번호)·주문내역(오픈마켓주문번호) 둘 다 받는다."""
    return str(r.get("마켓주문번호") or r.get("오픈마켓주문번호") or "").strip()

# 반품·교환·취소가 **마켓 쪽에서도** 아직 안 끝났다는 뜻(settle_plan._RISK_MARKERS 와
#  같은 신호를 여기서도 화면 문구로 노출).
_RISK_LABEL = "진행중"


def _norm_date10(v) -> str:
    t = str(v or "").strip().replace("/", "-")[:10]
    if len(t) == 8 and t.isdigit():
        t = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    try:
        _dt.date.fromisoformat(t)
    except ValueError:
        return ""
    return t if t[:4] >= "2000" else ""


def _order_status_event(line: dict) -> list[dict]:
    """한 line(row+status_at/status_prev) → 이력 이벤트 0~2개.

    클레임 행(_kind=change)은 `status_at`이 항상 None이다(order_store.lines_for_markets
    가 주문 라인에만 그 값을 준다) — 클레임 자체의 발생일(`_change_date`, 마켓 원본
    날짜)을 대신 쓴다. 못 찾으면 날짜 없이(정렬에서 뒤로 밀림·날조 금지)."""
    row = line.get("row") or {}
    status = str(row.get("주문상태") or "").strip()
    if not status:
        return []
    is_claim = str(row.get("_kind") or "") == "change"
    if is_claim:
        at = _norm_date10(row.get("_change_date")) or _norm_date10(row.get("주문일"))
        return [{"status": status, "at": at}]
    status_at = line.get("status_at")
    at = status_at.date().isoformat() if isinstance(status_at, _dt.datetime) else ""
    events = []
    prev = str(line.get("status_prev") or "").strip()
    # status_prev 는 order_store.lines_for_markets 가 실어 주는 필드(있으면 전환 증거)
    #  — 없으면 「과거에 뭐였는지」를 지어내지 않는다.
    if prev and prev != status:
        events.append({"status": prev, "at": ""})   # 시작 시각은 모른다(날조 금지)
    events.append({"status": status, "at": at})
    return events


def build_status_history(lines_for_order: list) -> list[dict]:
    """한 주문번호에 속한 모든 line(클레임 포함) → 시간순 이력(중복 연속 제거)."""
    events: list[dict] = []
    for ln in lines_for_order:
        events.extend(_order_status_event(ln))
    # 날짜가 있는 것부터, 없는 것은 뒤로 — 그다음 안정 정렬(원 순서 보존).
    events.sort(key=lambda e: (e["at"] == "", e["at"]))
    out: list[dict] = []
    for e in events:
        if out and out[-1]["status"] == e["status"]:
            continue
        out.append(e)
    return out


def build_verdict_map(matched: list, *, today=None) -> dict:
    """행들(마진계산기 matched 또는 주문내역 order_store 원행)이 걸친 마켓만 골라 조회
    → {오픈마켓주문번호: {"정산여부", "이력"}}.

    한 번만 order_store.lines_for_markets 를 불러 전부 처리한다(주문 건마다 DB 왕복
    금지 — 라이브에서 수백~수천 건이 된다).
    """
    today = today or _dt.date.today()
    markets_disp = {_row_market_disp(r) for r in matched}
    markets = sorted({_DISPLAY_TO_INTERNAL[m] for m in markets_disp if m in _DISPLAY_TO_INTERNAL})
    if not markets:
        return {}
    order_nos = sorted({_row_order_no(r) for r in matched if _row_order_no(r)})
    if not order_nos:
        return {}

    from lemouton.margin import settle_plan as _sp
    from lemouton.markets import order_store as _store

    try:
        # ★ order_nos 로 반드시 좁힌다 — 안 좁히면 마켓 전체 180일+클레임 무제한을
        #   analyze() 마다 통째로 읽는다(2026-09-05 라이브 실측: 매칭 3,499건에 analyze
        #   50초 — Cloudflare 100초 상한에 근접해 「서버 오류」로 이어질 위험이 있었다).
        lines = _store.lines_for_markets(markets, order_nos=order_nos)
    except Exception:   # noqa: BLE001 — 정산여부는 부가 정보, 실패해도 본 분석은 살아야 한다
        logger.exception("settle_status: lines_for_markets 실패 markets=%s", markets)
        return {}

    by_order: dict[str, list] = {}
    for ln in lines:
        onno = str((ln.get("row") or {}).get("오픈마켓주문번호") or "").strip()
        if onno:
            by_order.setdefault(onno, []).append(ln)

    out: dict = {}
    for onno, lns in by_order.items():
        history = build_status_history(lns)
        # classify()/resolve() 는 '주문 라인'(클레임 아닌 것) 기준으로 판정한다 —
        #  annotate_claims 가 이미 그 라인에 `_claim` 표식을 남겨 뒀다.
        order_lines = [l for l in lns if str((l.get("row") or {}).get("_kind") or "") != "change"]
        verdict = "확인불가"
        if order_lines:
            paid_date = _norm_date10((order_lines[0].get("row") or {}).get("_settle_paid_date"))
            if paid_date:
                verdict = "O"
            else:
                cat = _sp.classify(order_lines[0], today=today)
                if cat in ("risk", "returned"):
                    verdict = _RISK_LABEL
        out[onno] = {"정산여부": verdict, "_주문상태이력": history}
    return out


def attach_settlement_status(matched: list, *, today=None) -> None:
    """행 리스트(마진계산기 matched 또는 주문내역 order_store 원행)를 제자리에서
    보강 — 실패해도 본 화면(매출·마진·주문 목록)은 그대로 살린다."""
    try:
        verdict_map = build_verdict_map(matched, today=today)
    except Exception:   # noqa: BLE001
        logger.exception("settle_status: 정산여부 계산 실패 — 매출/마진은 영향 없음")
        verdict_map = {}
    for r in matched:
        onno = _row_order_no(r)
        v = verdict_map.get(onno) or {"정산여부": "확인불가", "_주문상태이력": []}
        r["정산여부"] = v["정산여부"]
        r["_주문상태이력"] = v["_주문상태이력"]
