"""마켓 주문/클레임 응답의 **구조**만 재는 프로브 — 읽기 전용.

왜 필요한가: 주문을 DB 에 적재하려면 「한 행을 유일하게 식별하는 키」가 마켓마다
확정돼야 한다. 키가 틀리면 같은 주문이 중복 적재되거나(금액 이중계상) 서로 다른
라인이 덮어씌워진다(주문 소실). 둘 다 금전 사고다.

그런데 코드만으로는 5가지가 판정되지 않는다:
  ① ESM 의 OrderNo 가 주문 단위인가 상품라인 단위인가
     → 주문 단위인데 OrderNo 로 dedupe 하면 다품목 주문의 2번째 라인이 사라진다
  ② 롯데온 odSeq 가 상품라인 seq 인가 배송 seq 인가
  ③ 쿠팡 한 orderId 가 여러 shipmentBox 로 갈리는가(부분출고)
  ④ 11번가 클레임 raw 에 ordPrdSeq 가 실려 오는가(오면 클레임 키 문제가 즉시 해결)
  ⑤ 스마트스토어 productOrderId 가 비어 orderId 로 폴백하는 일이 실제로 있는가

**개인정보 금지**: 이 모듈은 건수·비율·필드명만 돌려준다. 수령자·전화번호·주소 등
값은 어떤 경로로도 반환하지 않는다. 주문번호조차 값 자체는 내보내지 않고
'몇 개인가'로만 집계한다.
"""
from __future__ import annotations

import datetime as _dt
import re
from collections import Counter
from typing import Any, Optional

KST = _dt.timezone(_dt.timedelta(hours=9))

# 값이 절대 밖으로 나가면 안 되는 필드(필드명 목록에는 남기되 값은 안 씀 — 애초에 값을 안 쓴다)
_PII_HINT = ("name", "tel", "phone", "addr", "zip", "receiver", "buyer", "memo", "message")


def _field_names(sample: dict) -> list[str]:
    """샘플 1건의 최상위 필드명만. 값은 절대 포함하지 않는다."""
    return sorted(str(k) for k in (sample or {}).keys())


def _dist(counter: Counter) -> dict:
    """{그룹당 개수: 그런 그룹이 몇 개}. 예 {1: 40, 2: 3} = 2줄짜리 주문이 3건."""
    out = Counter(counter.values())
    return {str(k): out[k] for k in sorted(out)}


def _summary(per_group: Counter, label: str) -> dict:
    return {
        "그룹수": len(per_group),
        "총행수": sum(per_group.values()),
        f"{label}당_행수_분포": _dist(per_group),
        f"최대_{label}당_행수": max(per_group.values(), default=0),
        "다행_그룹수": sum(1 for v in per_group.values() if v > 1),
    }


# ────────────────────────────────────────────────────────────────
def _shape_esm(market: str, client, days: int) -> dict:
    """① OrderNo 가 주문 단위인가 라인 단위인가."""
    from shared.platforms.esm.orders import _SITE_TYPE, _fmt
    now = _dt.datetime.now(KST)
    since, until = now - _dt.timedelta(days=days), now
    per_order, rows_seen, sample = Counter(), 0, None
    nested_lists: Counter = Counter()
    for status in (1, 2, 3, 4, 5):
        body = {"siteType": _SITE_TYPE[market], "orderStatus": status,
                "requestDateType": 1, "requestDateFrom": _fmt(since),
                "requestDateTo": _fmt(until), "pageIndex": 1, "pageSize": 100}
        resp = client.request_orders(body) or {}
        for od in ((resp.get("Data") or {}).get("RequestOrders") or []):
            rows_seen += 1
            per_order[str(od.get("OrderNo"))] += 1
            sample = sample or od
            for k, v in od.items():
                if isinstance(v, list):
                    nested_lists[k] = max(nested_lists[k], len(v))
    return {
        "질문": "OrderNo 가 주문 단위인가 상품라인 단위인가",
        **_summary(per_order, "OrderNo"),
        "판정": ("라인단위(안전) — OrderNo 가 겹치지 않음"
                 if per_order and max(per_order.values()) == 1
                 else "🔴 주문단위 — 같은 OrderNo 로 여러 행. 현행 OrderNo dedupe 는 라인을 버린다"
                 if per_order else "표본 0건 — 판정 불가(기간을 늘려 재측정)"),
        "리스트필드_최대길이": dict(nested_lists),
        "필드명": _field_names(sample or {}),
    }


def _shape_lotteon(client, days: int) -> dict:
    """② odSeq 가 무엇의 seq 인가 (odNo 당 몇 개인지, sitmNo 와 어떻게 다른지)."""
    from shared.platforms.lotteon.orders import fetch_delivery_orders
    now = _dt.datetime.now(KST)
    fmt = "%Y%m%d%H%M%S"
    per_od, per_od_seq, sample = Counter(), Counter(), None
    empty_seq = 0
    for d in range(days):                       # 1일 창 제약 → 하루씩
        end = now - _dt.timedelta(days=d)
        r = fetch_delivery_orders((end - _dt.timedelta(days=1)).strftime(fmt),
                                  end.strftime(fmt), client=client) or {}
        data = r.get("data")
        for od in (data if isinstance(data, list) else []):
            odno, odseq = str(od.get("odNo") or ""), str(od.get("odSeq") or "")
            per_od[odno] += 1
            per_od_seq[f"{odno}|{odseq}"] += 1
            if not odseq:
                empty_seq += 1
            sample = sample or od
    return {
        "질문": "odSeq 가 상품라인 seq 인가 배송 seq 인가",
        **_summary(per_od, "odNo"),
        "odNo+odSeq_조합수": len(per_od_seq),
        "odSeq_공란_행수": empty_seq,
        "판정": ("(odNo,odSeq) 가 행을 유일하게 가른다 — 키로 적합"
                 if per_od_seq and max(per_od_seq.values()) == 1
                 else "🔴 (odNo,odSeq) 로도 행이 겹친다 — sitmNo 등 추가 조각 필요"
                 if per_od_seq else "표본 0건 — 판정 불가"),
        "필드명": _field_names(sample or {}),
    }


def _shape_coupang(client, days: int) -> dict:
    """③ 한 orderId 가 여러 shipmentBox 로 갈리는가 + vendorItemId 공란 비율."""
    from shared.platforms.coupang.orders import fetch_orders
    now = _dt.datetime.now(KST)
    since = now - _dt.timedelta(days=min(days, 30))
    per_order_box, per_box_item, sample_box, sample_item = Counter(), Counter(), None, None
    empty_vid = total_items = 0
    for status in ("ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY"):
        r = fetch_orders(since, now, client=client, status=status, max_per_page=50) or {}
        for box in (r.get("data") or []):
            oid, bid = str(box.get("orderId") or ""), str(box.get("shipmentBoxId") or "")
            per_order_box[oid] += 1
            sample_box = sample_box or box
            for it in (box.get("orderItems") or []):
                total_items += 1
                per_box_item[f"{bid}|{it.get('vendorItemId')}"] += 1
                if not it.get("vendorItemId"):
                    empty_vid += 1
                sample_item = sample_item or it
    return {
        "질문": "한 orderId 가 여러 shipmentBox 로 갈리는가 / vendorItemId 가 비는가",
        **_summary(per_order_box, "orderId"),
        "총_상품라인수": total_items,
        "vendorItemId_공란수": empty_vid,
        "shipmentBoxId+vendorItemId_조합수": len(per_box_item),
        "판정": ("(shipmentBoxId,vendorItemId) 가 라인을 유일하게 가른다 — 키로 적합"
                 if per_box_item and max(per_box_item.values()) == 1
                 else "🔴 조합이 겹친다 — 조각 추가 필요" if per_box_item else "표본 0건"),
        "orderId_다중박스_여부": ("있음 — orderId 단독 키는 위험"
                                  if any(v > 1 for v in per_order_box.values()) else "없음(표본 내)"),
        "박스_필드명": _field_names(sample_box or {}),
        "상품라인_필드명": _field_names(sample_item or {}),
    }


def _shape_eleven11_claim(client, days: int) -> dict:
    """④ 클레임 raw XML 에 ordPrdSeq 가 실려 오는가 (오면 클레임 키 문제 즉시 해결)."""
    from shared.platforms.eleven11.orders import _fmt, _localname, _parse
    now = _dt.datetime.now(KST)
    paths = {"취소요청": "/rest/claimservice/cancelorders/{s}/{e}",
             "반품요청": "/rest/claimservice/returnorders/{s}/{e}",
             "교환요청": "/rest/claimservice/exchangeorders/{s}/{e}"}
    out: dict[str, Any] = {"질문": "클레임 응답에 ordPrdSeq 가 있는가"}
    for label, tmpl in paths.items():
        tags: set[str] = set()
        n_orders = 0
        for w in range(0, days, 7):             # 7일 창 제약
            end = now - _dt.timedelta(days=w)
            start = end - _dt.timedelta(days=min(7, days - w))
            xml = client.request("GET", tmpl.format(s=_fmt(start), e=_fmt(end))) or ""
            n_orders += len(re.findall(r"<[\w.:-]*order>", xml))
            try:
                root = _parse(xml)
            except Exception:                    # noqa: BLE001
                root = None
            if root is not None:
                tags.update(_localname(el.tag) for el in root.iter())
        out[label] = {
            "행수": n_orders,
            "ordPrdSeq_존재": "ordPrdSeq" in tags,
            "태그명": sorted(tags) if n_orders else [],
            "판정": ("ordPrdSeq 있음 — _claim_row 에 담기만 하면 키 확정"
                     if "ordPrdSeq" in tags else
                     "표본 0건 — 판정 불가(클레임이 쌓인 기간으로 재측정)" if not n_orders else
                     "🔴 ordPrdSeq 없음 — 다른 조각을 찾아야 함"),
        }
    return out


def _shape_smartstore(client, days: int) -> dict:
    """⑤ productOrderId 가 비어 orderId 로 폴백하는 일이 실제로 있는가."""
    from shared.platforms.smartstore.orders import fetch_orders
    now = _dt.datetime.now(KST)
    per_poid, empty_poid, total, sample = Counter(), 0, 0, None
    for d in range(days):                       # 24시간 창 제약 → 하루씩
        end = now - _dt.timedelta(days=d)
        r = fetch_orders(end - _dt.timedelta(days=1), end,
                         client=client, limit_count=300) or {}
        for st in ((r.get("data") or {}).get("lastChangeStatuses") or []):
            total += 1
            poid = str(st.get("productOrderId") or "")
            if not poid:
                empty_poid += 1
            per_poid[poid] += 1
            sample = sample or st
    return {
        "질문": "productOrderId 가 비어 orderId 폴백이 발동하는가",
        "총행수": total,
        "productOrderId_공란수": empty_poid,
        "고유_productOrderId수": len(per_poid),
        "판정": ("productOrderId 가 행마다 고유 — 키로 적합"
                 if total and empty_poid == 0 and max(per_poid.values(), default=0) == 1
                 else "🔴 공란 또는 중복 있음 — 폴백이 다품목 주문을 덮어쓸 수 있다"
                 if total else "표본 0건 — 판정 불가"),
        "필드명": _field_names(sample or {}),
    }


SHAPES = {
    "auction": lambda c, d: _shape_esm("auction", c, d),
    "gmarket": lambda c, d: _shape_esm("gmarket", c, d),
    "lotteon": _shape_lotteon,
    "coupang": _shape_coupang,
    "eleven11": _shape_eleven11_claim,
    "smartstore": _shape_smartstore,
}


def shape(market: str, *, days: int = 7, client=None) -> dict:
    """마켓 응답 구조 측정 1회. 건수·비율·필드명만 반환(값·개인정보 없음)."""
    fn = SHAPES.get(market)
    if not fn:
        raise ValueError(f"지원하지 않는 마켓: {market} ({'|'.join(SHAPES)})")
    if client is None:
        return {"market": market, "days": days, "error": "클라이언트 없음 — 키 미등록/계정 비활성"}
    try:
        return {"market": market, "days": days, **fn(client, days)}
    except Exception as exc:                     # noqa: BLE001
        return {"market": market, "days": days,
                "error": f"{type(exc).__name__}: {exc}"[:500]}
