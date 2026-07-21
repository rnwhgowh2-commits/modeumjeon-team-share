# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) 클레임·입금확인중 주문 조회.

주문조회(RequestOrders)는 **클레임 주문을 반환하지 않는다**.
  공식문서 원문(etapi.gmarket.com/67): "클레임(취소, 반품, 교환, 미수령신고) 주문은
  조회되지 않습니다"
그래서 이걸 붙이기 전까지 옥션·G마켓만 취소·반품 주문이 통째로 빠진 채 집계됐다
(실증 2026-07-20: 마켓 화면 환불완료 1건 ↔ 우리 조회 0건).

★ API 마다 규약이 제각각이다. 하나만 틀려도 **에러 없이 0건**이 와서 눈치채기 어렵다.
  · 취소조회만 G마켓 = 3   (주문조회·반품·교환·입금확인중은 2)
  · 파라미터 대소문자: 취소/반품/교환 = SiteType · 입금확인중 = siteType
  · 조회기간: 클레임 7일 이하 · 입금확인중 31일 이하 (주문조회 31/180일과 또 다름)
  · ResultCode 가 0(int) 과 "success"(str) 로 섞여 내려온다
  · 취소만 '0=전체'가 있고, 반품·교환은 상태별로 순회해야 한다
"""
from __future__ import annotations

import datetime as _dt

PATHS = {
    "cancels":     "/claim/v1/sa/Cancels",
    "returns":     "/claim/v1/sa/Returns",
    "exchanges":   "/claim/v1/sa/Exchanges",
    "uncollected": "/shipping/v1/Delivery/ClaimList",
    "pre_orders":  "/shipping/v1/Order/PreRequestOrders",
}

# ★ 사이트 코드 — 취소조회만 G마켓이 3이다(공식문서 취소조회 SiteType: "1:옥션 3:G마켓").
#   2로 보내면 거부도 안 되고 조용히 0건이 온다.
_SITE = {
    "cancels":     {"auction": 1, "gmarket": 3},
    "returns":     {"auction": 1, "gmarket": 2},
    "exchanges":   {"auction": 1, "gmarket": 2},
    "uncollected": {"auction": 1, "gmarket": 2},
    "pre_orders":  {"auction": 1, "gmarket": 2},
}

# "7일 이하"인데 **정확히 7일도 거부**당한다(라이브 실측 2026-07-20:
# ResultCode 2000 "시작일과 종료일을 정확하게 입력 바랍니다"). 경계를 피해 6일로 쪼갠다.
_CLAIM_WINDOW_DAYS = 6
_UNCOLLECTED_WINDOW_DAYS = 30   # 미수령: "30일 이내" (초과 시 에러 3000)
_PRE_WINDOW_DAYS = 31       # 입금확인중: "31일 이내 조회 가능"

# 반품·교환은 '전체' 값이 없어 상태를 하나씩 돌아야 한다.
_RETURN_STATUSES = (1, 2, 3, 4, 5, 6)     # 요청/수거완료/환불보류/환불완료/철회/직권환불
_EXCHANGE_STATUSES = (1, 2, 3, 4, 5)      # 요청/수거완료/보류/완료(G마켓만)/철회

# '데이터 없음'은 오류가 아니다(미수령 조회는 건이 없으면 1100 을 준다).
_EMPTY_CODES = {1100, "1100"}


def site_code(market: str, api: str) -> int:
    """그 API 가 요구하는 사이트 코드. 모르는 조합은 ValueError(추측 금지)."""
    table = _SITE.get(api)
    if not table or market not in table:
        raise ValueError(f"ESM 클레임 대상 아님: market={market} api={api}")
    return table[market]


def _windows(since: _dt.datetime, until: _dt.datetime, days: int):
    """[since, until] 을 days 이하 구간으로 분할(빈틈·겹침 없음)."""
    step = _dt.timedelta(days=days)
    cur = since
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def _ok(resp: dict) -> bool:
    """ResultCode 성공 판정. 0 / "0" / "success" 가 섞여 내려온다."""
    rc = resp.get("ResultCode")
    if rc is None:
        return True
    return str(rc).strip().lower() in ("0", "success")


def _rows(resp: dict, path: str) -> list:
    """응답에서 행 목록 추출. 실패는 사유와 함께 예외(조용한 0건 금지)."""
    resp = resp or {}
    if resp.get("ResultCode") in _EMPTY_CODES:
        return []
    if not _ok(resp):
        raise RuntimeError(
            f"ESM {path} 실패 ResultCode={resp.get('ResultCode')} "
            f"{resp.get('Message') or ''}".strip())
    data = resp.get("Data")
    if isinstance(data, dict):                 # 입금확인중은 Data.RequestOrders
        return data.get("RequestOrders") or []
    return data or []


def _emit(rows, seen, kind):
    """OrderNo 중복 제거 + 어떤 클레임인지 표시해 넘긴다."""
    for od in rows:
        key = od.get("OrderNo")
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        od = dict(od)
        od["_claim_kind"] = kind
        yield od


# ★ 클레임은 **신청일과 완료일이 다르다**. 최근에 완료된 오래된 클레임을 신청일(Type=2)로만
#   조회하면 신청일이 기간 밖이라 통째로 빠진다(2026-07-21 실증: G마켓 취소 4471072276 은
#   완료일 07-21인데 신청일 기준 7일 조회로는 0건, 주문번호 조회로는 잡힘).
#   → 신청일(2)과 완료일(3) 두 기준으로 조회해 OrderNo 로 합친다. 완료일 기준이 있어야
#     "이번 주에 취소 처리된 오래된 주문"을 놓치지 않는다.
_CLAIM_TYPES = (2, 3)     # 2=신청일, 3=완료(철회)일


def _iter_by_status(market, since, until, *, client, api, status_field,
                    statuses, kind, type_values=_CLAIM_TYPES, date_fmt="%Y-%m-%d"):
    """클레임 3종 공통 — 기간 7일 분할 × 상태 순회 × (신청일·완료일) 기준."""
    site = site_code(market, api)
    path = PATHS[api]
    seen = set()
    for w_from, w_to in _windows(since, until, _CLAIM_WINDOW_DAYS):
        for st in statuses:
            for tp in type_values:
                body = {
                    "SiteType": site,
                    "Type": tp,                          # 2=신청일 / 3=완료(철회)일
                    "StartDate": w_from.strftime(date_fmt),
                    # ★ 그날 끝까지 포함하려면 EndDate 를 하루 올린다(마켓은 EndDate 를
                    #   그날 00:00 로 해석 → 오늘 낮 처리 건이 빠진다).
                    "EndDate": (w_to + _dt.timedelta(days=1)).strftime(date_fmt),
                }
                if status_field:
                    body[status_field] = st
                yield from _emit(_fetch_window(client, path, body, w_from, w_to,
                                               status_field, st, date_fmt),
                                 seen, kind)


# ★ 클레임 조회에는 **페이징 파라미터가 없고 응답에 TotalCount 도 없다**
#   (2026-07-20 라이브 프로브: wrapper 는 ResultCode·Message·BizRuleCode 뿐).
#   즉 마켓이 상한을 걸어 잘라도 **알 방법이 없다** — 취소가 많은 달에 일부가 통째로
#   빠져도 우리는 모른다(11번가 조용한 유실과 같은 유형).
#   → 한 구간이 이 건수 이상 오면 '잘렸을 수 있다'고 보고 기간을 반으로 쪼개 다시 받는다.
#     쪼갠 합이 더 크면 실제로 잘린 것이고, 같으면 손해 볼 것 없다(중복은 OrderNo 로 제거).
_SPLIT_SUSPECT = 50
_MIN_SPLIT_HOURS = 12       # 이보다 짧은 구간은 더 쪼개지 않는다(무한 분할 방지)


def _fetch_window(client, path, body, w_from, w_to, status_field, st, date_fmt):
    """한 구간 조회. 잘린 것으로 의심되면 기간을 반으로 쪼개 합쳐서 돌려준다."""
    rows = _rows(client.post(path, dict(body)), path)
    if len(rows) < _SPLIT_SUSPECT:
        return rows
    span = w_to - w_from
    if span.total_seconds() / 3600.0 <= _MIN_SPLIT_HOURS:
        return rows                      # 더 쪼갤 수 없다 — 받은 만큼만
    mid = w_from + span / 2
    out, seen_no = [], set()
    for a, b in ((w_from, mid), (mid, w_to)):
        sub = dict(body, StartDate=a.strftime(date_fmt),
                   EndDate=(b + _dt.timedelta(days=1)).strftime(date_fmt))
        for r in _fetch_window(client, path, sub, a, b, status_field, st, date_fmt):
            no = r.get("OrderNo")
            if no is not None and no in seen_no:
                continue
            if no is not None:
                seen_no.add(no)
            out.append(r)
    return out if len(out) > len(rows) else rows


def iter_cancels(market, since, until, *, client):
    """취소조회 — CancelStatus 0(전체) 한 번으로 끝난다(5초/1회라 호출을 아낀다)."""
    return _iter_by_status(market, since, until, client=client, api="cancels",
                           status_field="CancelStatus", statuses=(0,), kind="cancel")


def iter_returns(market, since, until, *, client):
    """반품조회 — 전체값이 없어 상태 6종을 순회."""
    return _iter_by_status(market, since, until, client=client, api="returns",
                           status_field="ReturnStatus", statuses=_RETURN_STATUSES,
                           kind="return")


def iter_exchanges(market, since, until, *, client):
    """교환조회 — 전체값이 없어 상태 5종을 순회."""
    return _iter_by_status(market, since, until, client=client, api="exchanges",
                           status_field="ExchangeStatus", statuses=_EXCHANGE_STATUSES,
                           kind="exchange")


def iter_uncollected(market, since, until, *, client):
    """미수령신고 조회 — SearchType 1(신고일 기준). 건이 없으면 1100(정상 빈결과)."""
    site_code(market, "uncollected")            # 마켓 검증(코드 자체는 본문에 안 쓴다)
    path = PATHS["uncollected"]
    seen = set()
    for w_from, w_to in _windows(since, until, _UNCOLLECTED_WINDOW_DAYS):
        body = {
            "SearchType": 1,                    # 1 = 미수령신고일 기준
            # OrderNo 는 문서상 필수(Y). 신고일 기준 조회에서도 자리를 채워야 해서
            # 공식 예시대로 0 을 보낸다(주문번호 검색이 아니라는 뜻).
            "OrderNo": 0,
            "StartDate": w_from.strftime("%Y-%m-%d"),
            "EndDate": (w_to + _dt.timedelta(days=1)).strftime("%Y-%m-%d"),
        }
        yield from _emit(_rows(client.post(path, body), path), seen, "uncollected")


def iter_pre_orders(market, since, until, *, client, page_size: int = 100):
    """입금확인중(무통장 입금대기) 주문조회 — 소문자 siteType, 31일 분할, 분단위."""
    site = site_code(market, "pre_orders")
    path = PATHS["pre_orders"]
    seen = set()
    for w_from, w_to in _windows(since, until, _PRE_WINDOW_DAYS):
        page = 1
        while True:
            body = {
                "siteType": site,               # ★ 소문자 s (클레임 3종과 다름)
                "requestDateFrom": w_from.strftime("%Y-%m-%d %H:%M"),
                "requestDateTo": w_to.strftime("%Y-%m-%d %H:%M"),
                "pageIndex": page,
                "pageSize": page_size,
            }
            # ★ 입금확인중도 '주문 조회' 계열이라 5초/1회 제한을 주문조회와 **공유**한다
            #   (라이브 실측: 주문조회 직후 호출하면 ResultCode 3000). is_order=True 로
            #   클라이언트 스로틀을 태운다.
            resp = client.post(path, body, is_order=True) or {}
            rows = _rows(resp, path)
            if not rows:
                break
            yield from _emit(rows, seen, "pre_order")
            data = resp.get("Data") or {}
            total = (data.get("TotalCount") or 0) if isinstance(data, dict) else 0
            if len(rows) < page_size or page * page_size >= total:
                break
            page += 1


def iter_all(market, since, until, *, client):
    """주문조회가 놓치는 것 전부 — 입금확인중 + 취소 + 반품 + 교환 + 미수령."""
    yield from iter_pre_orders(market, since, until, client=client)
    yield from iter_cancels(market, since, until, client=client)
    yield from iter_returns(market, since, until, client=client)
    yield from iter_exchanges(market, since, until, client=client)
    yield from iter_uncollected(market, since, until, client=client)
