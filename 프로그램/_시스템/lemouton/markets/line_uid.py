"""주문 한 줄(상품라인)의 안정적인 고유키 — 계정 간 중복제거 + DB 적재 공용.

## 왜 필요한가

계정 간 중복제거가 `(오픈마켓주문번호, 상품명, 옵션)` 을 키로 쓴다. 상품명은 **바뀐다**
(마켓에서 상품명 수정, 롯데온 HTML 언이스케이프, 11번가 클레임행은 상품명이 아예 공란).
바뀌면 중복이 안 걸려 **같은 주문이 두 번 계상**된다 — 발송·정산이 2배가 되는 금전 사고다.

반대로 `오픈마켓주문번호` 단독은 더 위험하다. 쿠팡·롯데온·11번가는 주문번호가 **주문 단위**라
다품목 주문의 라인들이 서로를 덮어쓴다(주문 소실).

그래서 마켓이 주는 **불변 식별자**로만 키를 만든다. 2026-07-20 라이브 구조 실측으로 확정:

| 마켓 | 키 | 표본 |
|---|---|---|
| smartstore | `productOrderId` | 32행, 공란 0, 전부 고유 |
| coupang | `shipmentBoxId` + `vendorItemId` | 60행, 공란 0 |
| eleven11 | `ordNo` + `ordPrdSeq` (클레임은 + `clmReqSeq`) | raw 확인 |
| auction·gmarket | `OrderNo` | 지도 fields: PayNo=대표 장바구니번호(상위) |
| lotteon | `odNo` + `odSeq`(+`sitmNo`·`clmNo`) | 지도 fields: odSeq=주문순번(단품별) |

## 호출 시점 (중요)

`_finalize_rows` 가 `_odseq`·`_shipkey`·`_oid`·`_vid` 를 **반환 직전에 pop** 한다.
따라서 반드시 **빌더 반환 직후·finalize 이전**에 심어야 한다. 그 뒤엔 조각이 이미 없다.

## 못 만들면 빈 문자열

조각이 없으면 지어내지 않고 `""` 를 돌려준다. 호출부는 빈 값을 「알 수 없음」으로 다루고
기존 방식으로 폴백해야 한다. 추측한 키로 행을 합치면 주문이 조용히 사라진다.
"""
from __future__ import annotations

import hashlib

FIELD = "_line_uid"          # 행에 심는 키 이름


def _sid(row: dict, name: str) -> str:
    return str((row.get("_send_ids") or {}).get(name) or "")


def _join(market: str, parts: list[str]) -> str:
    """조각이 하나라도 비면 키를 만들지 않는다(부분키는 서로 다른 라인을 합쳐버린다)."""
    if not parts or any(not p for p in parts):
        return ""
    return f"{market}|" + "|".join(parts)


def _smartstore(row: dict) -> str:
    # productOrderId. 빌더가 productOrderId 없으면 orderId 로 폴백하는 경로가 있으나
    # 실측(32행)에서 공란 0 · 전부 고유라 폴백은 발동하지 않았다.
    return _join("smartstore", [str(row.get("오픈마켓주문번호") or "")])


def _coupang(row: dict) -> str:
    # (shipmentBoxId, vendorItemId). orderId 는 주문 단위라 라인을 못 가른다.
    # _pd_market_option_id 는 vendorItemId 가 truthy 일 때만 설정된다.
    return _join("coupang", [_sid(row, "shipment_box_id"),
                             str(row.get("_pd_market_option_id") or "")])


def _lotteon(row: dict) -> str:
    """(odNo, odSeq[, sitmNo]) — 클레임행은 + clmNo.

    데이터 코드 지도 fields 로 확정(2026-07-20): `odSeq` = **주문순번(단품별)** 이다.
    즉 배송 seq 가 아니라 상품라인 seq → (odNo, odSeq) 만으로 라인이 갈린다.
    `sitmNo`(판매자단품번호)는 있으면 더 좁히고, 없어도 키를 포기하지 않는다.
    `clmNo`(클레임번호)는 같은 라인의 클레임을 서로 구분한다.
    """
    parts = [_sid(row, "od_no"), _sid(row, "od_seq")]
    if not all(parts):
        return ""
    for extra in ("sitm_no", "clm_no"):
        v = _sid(row, extra)
        if v:
            parts.append(v)
    return _join("lotteon", parts)


def _eleven11(row: dict) -> str:
    # (ordNo, ordPrdSeq). 지도 fields 확정(2026-07-20): ordPrdSeq=주문순번,
    #  clmReqSeq=**외부몰 클레임 번호**. 같은 라인이 여러 번 접수돼도 갈린다.
    parts = [_sid(row, "ord_no"), _sid(row, "ord_prd_seq")]
    clm = _sid(row, "clm_req_seq")
    if clm:
        parts.append(clm)
    return _join("eleven11", parts)


def _esm(market: str):
    # OrderNo = 라인 단위. 데이터 코드 지도 fields 로 확정(2026-07-20):
    #   `PayNo` = **대표 장바구니번호**(상위 묶음) / `OrderNo` = 주문번호(라인).
    #   즉 한 결제에 OrderNo 가 여러 개고, OrderNo 로 dedupe 해도 라인이 안 사라진다.
    return lambda row: _join(market, [str(row.get("오픈마켓주문번호") or "")])


_EXTRACTORS = {
    "smartstore": _smartstore,
    "coupang": _coupang,
    "lotteon": _lotteon,
    "eleven11": _eleven11,
    "auction": _esm("auction"),
    "gmarket": _esm("gmarket"),
}


def line_uid(market: str, row: dict) -> str:
    """행의 고유키. 만들 수 없으면 "" (지어내지 않는다)."""
    fn = _EXTRACTORS.get(market)
    if not fn:
        return ""
    try:
        return fn(row or {})
    except Exception:                    # noqa: BLE001 — 키 생성 실패가 조회를 깨면 안 된다
        return ""


def stamp(market: str, rows: list) -> list:
    """행들에 `_line_uid` 를 심는다. **빌더 반환 직후·_finalize_rows 이전**에 호출할 것."""
    for r in rows or []:
        uid = line_uid(market, r)
        if uid:
            r[FIELD] = uid
    return rows


def dedupe_key(row: dict) -> tuple:
    """계정 간 중복제거 키. line_uid 가 있으면 그것만, 없으면 기존 방식으로 폴백.

    폴백은 `(주문번호, 상품명, 옵션)` — 상품명이 바뀌면 못 잡는 한계가 있지만, 키를
    못 만든 행을 통과시켜 **2배 계상**을 내는 것보다 낫다(과잉제거보다 과소제거가
    덜 위험한 게 아니라, 폴백이라도 있어야 최소한의 방어선이 남는다).
    """
    uid = str(row.get(FIELD) or "")
    if uid:
        return ("uid", uid)
    return ("legacy", str(row.get("오픈마켓주문번호", "")),
            str(row.get("상품명", "")), str(row.get("옵션", "")))


def claim_event_uid(row: dict) -> str:
    """클레임 이벤트 고유키 — 같은 라인이 반품요청→반품완료로 갈 때를 구분한다.

    라인키(line_uid) 만으로 적재하면 나중 이벤트가 앞 이벤트를 덮어써 이력이 사라진다.
    클레임 고유번호를 주는 마켓은 line_uid 에 이미 들어가 있고(11번가 clmReqSeq),
    안 주는 마켓은 변경일 + 마켓 상태코드로 이벤트를 가른다.
    """
    base = str(row.get(FIELD) or "") or str(row.get("오픈마켓주문번호") or "")
    if not base:
        return ""
    sig = f"{row.get('_change_date') or ''}|{row.get('주문상태원본') or ''}"
    return f"{base}|CLM|{hashlib.sha1(sig.encode('utf-8')).hexdigest()[:12]}"
