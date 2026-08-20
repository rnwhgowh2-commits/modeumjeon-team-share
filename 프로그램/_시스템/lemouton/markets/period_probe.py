"""마켓별 조회기간 상한 실측 프로브 — **읽기 전용**.

목적: 두 가지 상한을 마켓에 직접 물어 확정한다.
  ① 1회 조회 창(window) — 한 번 호출에 며칠치까지 받아주나
  ② 과거 상한(lookback)  — 얼마나 옛날 구간까지 받아주나

배경: `webapp/data/marketplace_api_map.json`(378 API) 전체를 훑어도 ② 를 규정한
문구가 **한 건도 없다**. 코드에도 하한 가드가 없다. 즉 ② 는 실측 외에 확인 방법이
없어서 이 모듈을 만들었다.

설계 원칙:
  - 각 프로브는 **단발 호출 1회**. 기존 iter_* 들은 윈도우를 하드코딩해 쪼개므로
    경계 측정에 쓸 수 없다(쪼개진 창은 항상 상한 이내라 절대 거부되지 않는다).
  - 조회(GET/검색 POST)만. 등록·수정·전송 경로는 건드리지 않는다.
  - 응답을 성공/거부/오류 3분류로만 판정하고 **데이터는 건수만** 반환한다
    (주문 상세가 로그·응답에 새지 않도록).

판정(verdict):
  accepted — 마켓이 그 구간을 받아줌(0건이어도 accepted. 데이터 없음 ≠ 거부)
  rejected — 마켓이 기간 제약으로 거부(에러코드/문구 확인)
  error    — 그 외 실패(인증·IP·네트워크). 상한 근거로 쓰면 안 된다.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Optional

KST = _dt.timezone(_dt.timedelta(hours=9))

# 기간 초과 거부를 나타내는 문구/코드 — 마켓별 실측 문서에서 수집
_RANGE_HINTS = (
    "range should less",          # 쿠팡 endTime-startTime range should less than31.
    "검색기간", "조회기간", "조회 기간", "조회범위", "조회 범위",
    "최대 조회", "일주일", "한달", "한 달", "기간을 확인",
    "이하의 기간", "이하의 범위",   # ESM 3000 "180일 이하의 기간만 조회 할 수 있습니다"
    "조회 날짜가 유효",             # 스마트스토어 104140(2026-07-20 실측)
    "date range", "period",
)
_RANGE_CODES = {
    "-3902", "-3903", "-3904", "-3205",     # 11번가 주문
    "-28008", "-29008", "-30008",           # 11번가 클레임
    "2003",                                  # 롯데온 주문 1일 초과
    "104139", "104140",                      # 스마트스토어 조회범위·조회날짜(실측)
    "3000",                                  # ESM 기간 초과(옥션 181일·G마켓 32일 실측)
}


def _looks_like_range_error(text: str) -> bool:
    """에러 문구/코드가 '기간 제약' 때문인지 판정. 인증·IP 오류와 섞이면 안 된다."""
    low = (text or "").lower()
    if any(c in text for c in _RANGE_CODES):
        return True
    return any(h.lower() in low for h in _RANGE_HINTS)


def _verdict_from_error(exc: BaseException) -> tuple[str, str]:
    msg = f"{type(exc).__name__}: {exc}"
    payload = getattr(exc, "payload", None)
    if payload:
        msg = f"{msg} | {str(payload)[:400]}"
    return ("rejected" if _looks_like_range_error(msg) else "error"), msg[:600]


# ────────────────────────────────────────────────────────────────────
# 마켓별 단발 프로브
# ────────────────────────────────────────────────────────────────────

def _probe_coupang_orders(start, end, client) -> dict:
    from shared.platforms.coupang.orders import fetch_orders
    r = fetch_orders(start, end, client=client, status="FINAL_DELIVERY", max_per_page=1)
    return {"verdict": "accepted", "code": str(r.get("code") or ""),
            "message": str(r.get("message") or "")[:200],
            "count": len(r.get("data") or [])}


def _probe_coupang_claims(start, end, client, *, path_ver="v4", kind="returnRequests") -> dict:
    """반품(v4/v6)·교환 단발 조회. iter_* 는 7일 하드코딩이라 경계 측정 불가."""
    from shared.platforms.coupang.claims import _vendor
    vid = _vendor(client)
    fmt = "%Y-%m-%dT%H:%M" if kind == "returnRequests" else "%Y-%m-%dT%H:%M:%S"
    q = (f"createdAtFrom={start.strftime(fmt)}&createdAtTo={end.strftime(fmt)}"
         f"&maxPerPage=1&searchType=timeFrame")
    if kind == "returnRequests":
        q += "&status=UC"
    path = f"/v2/providers/openapi/apis/api/{path_ver}/vendors/{vid}/{kind}"
    r = client.request("GET", path, query=q)
    return {"verdict": "accepted", "code": str(r.get("code") or ""),
            "message": str(r.get("message") or "")[:200],
            "count": len(r.get("data") or [])}


def _probe_smartstore_orders(start, end, client) -> dict:
    from shared.platforms.smartstore.orders import fetch_orders
    r = fetch_orders(start, end, client=client, limit_count=1)
    data = (r or {}).get("data") or {}
    return {"verdict": "accepted", "code": "200", "message": "",
            "count": len(data.get("lastChangeStatuses") or [])}


_ELEVEN_PATHS = {
    "orders":         "/rest/ordservices/complete/{s}/{e}",
    "orders_done":    "/rest/ordservices/completed/{s}/{e}",
    "claims_cancel":  "/rest/claimservice/cancelorders/{s}/{e}",
    "claims_return":  "/rest/claimservice/returnorders/{s}/{e}",
    "claims_exchange": "/rest/claimservice/exchangeorders/{s}/{e}",
}


def _probe_eleven11(start, end, client, *, kind="orders") -> dict:
    """11번가는 XML. resultCode 0 = 정상(0건 포함), 음수 = 거부."""
    from shared.platforms.eleven11.orders import _fmt, _parse, _localname
    path = _ELEVEN_PATHS[kind].format(s=_fmt(start), e=_fmt(end))
    xml_text = client.request("GET", path)
    code, msg = "", ""
    try:
        root = _parse(xml_text)
    except Exception:      # noqa: BLE001
        # 에러 응답이 본문 XML 규격을 벗어나는 경우가 있다(네임스페이스 미선언 등).
        # 파싱 실패로 판정을 포기하면 기간 거부를 error 로 오분류하므로 정규식으로 폴백.
        root = None
    if root is not None:
        for el in root.iter():
            tag = _localname(el.tag)
            if tag in ("resultCode", "returnCode") and not code:
                code = (el.text or "").strip()
            elif tag in ("resultMessage", "returnMessage") and not msg:
                msg = (el.text or "").strip()
    if not code:      # 코드 태그가 없거나 파싱 실패 → 본문에서 직접 긁는다(접두사 허용)
        m = re.search(r"<[\w.:-]*(?:resultCode|returnCode)>\s*(-?\d+)", xml_text or "")
        code = m.group(1) if m else ""
    if not msg:
        m = re.search(r"<[\w.:-]*(?:resultMessage|returnMessage)>([^<]*)", xml_text or "")
        msg = (m.group(1) or "").strip() if m else ""
    n = len(re.findall(r"<[\w.:-]*order>", xml_text or ""))
    negative = code.startswith("-")
    verdict = "accepted"
    if negative:
        verdict = "rejected" if _looks_like_range_error(f"{code} {msg}") else "error"
    return {"verdict": verdict, "code": code, "message": msg[:200], "count": n}


_LOTTEON_CLAIM_PATHS = {
    "claims_cancel":  "/v1/openapi/claim/v1/cancellationOpenApi/getCancellationRequestAndComplateList",
    "claims_return":  "/v1/openapi/claim/v1/returningOpenApi/returnRequestSearch",
    "claims_exchange": "/v1/openapi/claim/v1/exchangeOpenApi/exchangeSearch",
}
_LOTTEON_FMT = "%Y%m%d%H%M%S"


def _lotteon_verdict(r: dict) -> dict:
    code = str((r or {}).get("returnCode") or (r or {}).get("resultCode") or "")
    msg = str((r or {}).get("returnMessage") or (r or {}).get("resultMessage") or "")
    data = (r or {}).get("data")
    n = len(data) if isinstance(data, list) else (1 if data else 0)
    ok = code in ("", "0", "0000", "00", "200")
    verdict = "accepted"
    if not ok:
        verdict = "rejected" if _looks_like_range_error(f"{code} {msg}") else "error"
    return {"verdict": verdict, "code": code, "message": msg[:200], "count": n}


def _probe_lotteon_orders(start, end, client) -> dict:
    from shared.platforms.lotteon.orders import fetch_delivery_orders
    r = fetch_delivery_orders(start.strftime(_LOTTEON_FMT), end.strftime(_LOTTEON_FMT),
                              client=client)
    return _lotteon_verdict(r)


def _probe_lotteon_claims(start, end, client, *, kind="claims_cancel") -> dict:
    from shared.platforms.lotteon.claims import _fetch
    r = _fetch(_LOTTEON_CLAIM_PATHS[kind], start.strftime(_LOTTEON_FMT),
               end.strftime(_LOTTEON_FMT), client=client)
    return _lotteon_verdict(r)


def _esm_verdict(r: dict, rows_key: str = "") -> dict:
    code = str((r or {}).get("ResultCode"))
    msg = str((r or {}).get("Message") or "")
    data = (r or {}).get("Data") or {}
    n = 0
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                n = max(n, len(v))
        n = data.get("TotalCount") if isinstance(data.get("TotalCount"), int) else n
    ok = code in ("0", "None", "1100")     # 1100 = ESM '데이터 없음'(정상)
    verdict = "accepted"
    if not ok:
        verdict = "rejected" if _looks_like_range_error(f"{code} {msg}") else "error"
    return {"verdict": verdict, "code": code, "message": msg[:200], "count": n or 0}


def _probe_esm_orders(market, start, end, client) -> dict:
    from shared.platforms.esm.orders import _SITE_TYPE, _fmt
    body = {"siteType": _SITE_TYPE[market], "orderStatus": 5, "requestDateType": 1,
            "requestDateFrom": _fmt(start), "requestDateTo": _fmt(end),
            "pageIndex": 1, "pageSize": 1}
    return _esm_verdict(client.request_orders(body))


def _probe_esm_claims(market, start, end, client, *, kind="claims_cancel") -> dict:
    from shared.platforms.esm.claims import PATHS, site_code
    api = {"claims_cancel": "cancels", "claims_return": "returns",
           "claims_exchange": "exchanges"}[kind]
    body = {"SiteType": site_code(market, api), "Type": 2,
            "StartDate": start.strftime("%Y-%m-%d"), "EndDate": end.strftime("%Y-%m-%d")}
    return _esm_verdict(client.post(PATHS[api], body))


# market → {kind: callable(start, end, client)}
PROBES: dict[str, dict[str, Any]] = {
    "coupang": {
        "orders": _probe_coupang_orders,
        "claims_return": lambda s, e, c: _probe_coupang_claims(s, e, c, path_ver="v4", kind="returnRequests"),
        "claims_return_v6": lambda s, e, c: _probe_coupang_claims(s, e, c, path_ver="v6", kind="returnRequests"),
        "claims_exchange": lambda s, e, c: _probe_coupang_claims(s, e, c, path_ver="v4", kind="exchangeRequests"),
    },
    "smartstore": {"orders": _probe_smartstore_orders},
    "eleven11": {k: (lambda kk: (lambda s, e, c: _probe_eleven11(s, e, c, kind=kk)))(k)
                 for k in _ELEVEN_PATHS},
    "lotteon": {
        "orders": _probe_lotteon_orders,
        **{k: (lambda kk: (lambda s, e, c: _probe_lotteon_claims(s, e, c, kind=kk)))(k)
           for k in _LOTTEON_CLAIM_PATHS},
    },
    "auction": {
        "orders": lambda s, e, c: _probe_esm_orders("auction", s, e, c),
        **{k: (lambda kk: (lambda s, e, c: _probe_esm_claims("auction", s, e, c, kind=kk)))(k)
           for k in ("claims_cancel", "claims_return", "claims_exchange")},
    },
    "gmarket": {
        "orders": lambda s, e, c: _probe_esm_orders("gmarket", s, e, c),
        **{k: (lambda kk: (lambda s, e, c: _probe_esm_claims("gmarket", s, e, c, kind=kk)))(k)
           for k in ("claims_cancel", "claims_return", "claims_exchange")},
    },
}


def probe(market: str, kind: str, *, window_days: float, back_days: float,
          client=None, now: Optional[_dt.datetime] = None) -> dict:
    """단발 프로브 1회.

    구간 = [now - back_days - window_days, now - back_days].
    back_days=0 이면 '지금 기준 window_days 창'(=1회 조회 창 측정),
    window_days 고정 + back_days 증가면 '과거 상한 측정'.
    """
    fns = PROBES.get(market)
    if not fns:
        raise ValueError(f"지원하지 않는 마켓: {market} ({'|'.join(PROBES)})")
    fn = fns.get(kind)
    if not fn:
        raise ValueError(f"{market} 은 kind={kind} 미지원 ({'|'.join(fns)})")

    now = now or _dt.datetime.now(KST)
    end = now - _dt.timedelta(days=back_days)
    start = end - _dt.timedelta(days=window_days)
    base = {"market": market, "kind": kind, "window_days": window_days,
            "back_days": back_days,
            "start": start.strftime("%Y-%m-%d %H:%M"), "end": end.strftime("%Y-%m-%d %H:%M")}
    if client is None:
        return {**base, "verdict": "error", "code": "", "count": 0,
                "message": "클라이언트 없음 — 판매처관리에 키 미등록이거나 계정 비활성"}
    try:
        return {**base, **fn(start, end, client)}
    except Exception as exc:                    # noqa: BLE001
        verdict, msg = _verdict_from_error(exc)
        return {**base, "verdict": verdict, "code": "", "count": 0, "message": msg}
