# -*- coding: utf-8 -*-
"""쿠팡 즉시할인쿠폰 — 만들기 · 옵션에 붙이기 · 처리됐나 확인 · 내리기.

지도 전수정독(2026-08-06 · consult-market-map)으로 확보한 스펙 그대로:
  ① 만들기   POST /v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupon
             {contractId, name, maxDiscountPrice, discount, startAt, endAt,
              type: RATE|PRICE|FIXED_WITH_QUANTITY, wowExclusive}
  ② 붙이기   POST .../api/v1/vendors/{vendorId}/coupons/{couponId}/items
             {vendorItems: [옵션ID…]}  — 한 번에 10,000개까지
  ③ 확인     GET  .../api/v1/vendors/{vendorId}/requested/{requestedId}
             → data.content {couponId, status, total, succeeded, failed, failedVendorItems}
  ④ 내리기   PUT  .../api/v1/vendors/{vendorId}/coupons/{couponId}

🔴 ⏰ **유효시작일은 다음날 0시부터만 설정 가능**(문서 명시). 오늘 켤 수 없다.
   → :func:`tomorrow_midnight` 로 기본값을 만들고, 화면도 그렇게 안내한다.
🔴 ①②는 **접수만** 하고 requestedId 를 돌려준다(비동기). 성공했다고 단정하지 말고
   ③으로 확인한다 — 접수 성공 ≠ 적용 완료.
🔴 이 저장소의 쿠팡 클라이언트는 params dict 가 아니라 **query 문자열**을 받는다
   (HMAC 서명에 query 가 들어간다). vendor_id 는 속성이 아니라 `client._cfg` 안.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_V2 = '/v2/providers/fms/apis/api/v2/vendors/{vid}'
_BASE_V1 = '/v2/providers/fms/apis/api/v1/vendors/{vid}'

#: 한 번에 붙일 수 있는 옵션 수 상한(문서). 넘으면 나눠 부른다.
MAX_ITEMS_PER_CALL = 10_000

#: 우리가 쓰는 할인 방식만 허용한다. 실측·문서에 있는 것 외엔 안 만든다(날조 금지).
_UNIT_TO_TYPE = {'WON': 'PRICE', 'PERCENT': 'RATE'}


class CoupangCouponError(Exception):
    """사용자에게 그대로 보여줄 수 있는 실패 사유."""


def vendor_id_of(client) -> Optional[str]:
    """⚠️ vendor_id 는 속성이 아니라 설정 주머니(_cfg) 안에 있다.

    getattr(client, 'vendor_id') 로 읽으면 전 계정이 「없음」이 된다(2026-08-05 실사고).
    """
    return (getattr(client, '_cfg', {}) or {}).get('vendor_id')


def tomorrow_midnight(now: Optional[datetime] = None) -> str:
    """쿠팡이 받아 주는 가장 이른 시작 시각 = **다음날 00:00:00**."""
    base = (now or datetime.now()) + timedelta(days=1)
    return base.strftime('%Y-%m-%d 00:00:00')


def _content(resp) -> dict:
    """실측 응답 꼴: {code, message, data:{success, content:{…}}}."""
    if not isinstance(resp, dict):
        return {}
    data = resp.get('data')
    if isinstance(data, dict) and isinstance(data.get('content'), dict):
        return data['content']
    return {}


def _content_list(resp) -> list:
    """목록형 응답의 content. 단건형(`_content`)과 자리를 나눠 둔다."""
    if not isinstance(resp, dict):
        return []
    data = resp.get('data')
    if isinstance(data, dict) and isinstance(data.get('content'), list):
        return data['content']
    return []


# ── 계약서 — **쿠폰 기간의 최대는 우리가 정하는 게 아니다** ──────────────────
#  🔴 쿠팡 생성 API 가 실제로 뱉는 에러(지도 [180]):
#       「계약의 유효기간 안에 쿠폰이 존재해야 한다
#         (계약서의 유효기간:2017-03-01 00:00:00~2017-12-31 23:59:59)
#         (쿠폰의 유효기간:2016-12-05 00:00:00~2017-09-05 00:00:00)」
#     → 쿠폰 `endAt` 의 **상한 = 그 계약서의 종료일**. 「N년」 같은 고정 한도는 없다.
#  🔴 계약 유형이 둘이다 — `CONTRACT_BASED`(기간 있는 계약)와
#     `NON_CONTRACT_BASED`(자유계약). 자유계약은 종료일이 2999-12-31 인 경우가 있어
#     사실상 무제한이다. 그래서 **가장 늦게 끝나는 것**을 고르면 그게 곧 「최대」다.
#  🔴 못 읽으면 **쿠폰을 만들지 않는다** — 계약ID를 지어내면 엉뚱한 계약에 걸린다.
def list_contracts(client, vendor_id: str) -> list[dict]:
    """계약서 목록. [{contract_id, start, end, type}] — 못 읽으면 빈 목록."""
    resp = client.request(
        'GET', _BASE_V2.format(vid=vendor_id) + '/contract/list')
    out = []
    for c in _content_list(resp):
        if not isinstance(c, dict) or not c.get('contractId'):
            continue
        out.append({
            'contract_id': c.get('contractId'),
            'start': str(c.get('start') or ''),
            'end': str(c.get('end') or ''),
            'type': str(c.get('type') or ''),
        })
    return out


def pick_contract(contracts: list, *, now: Optional[datetime] = None) -> Optional[dict]:
    """지금 유효한 계약 중 **가장 늦게 끝나는** 것 = 쿠폰을 가장 길게 걸 수 있는 계약.

    🔴 종료일이 이미 지난 계약은 고르지 않는다 — 쿠팡이 「계약의 유효기간 안에」로
      거부하고, 그 거부는 금액 문제가 아니라서 10원씩 올려 봐야 영영 안 낫는다.
    🔴 날짜를 못 알아보는 계약도 고르지 않는다(추측 금지).
    """
    stamp = (now or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
    live = [c for c in (contracts or [])
            if c.get('end') and c['end'] >= stamp
            and (not c.get('start') or c['start'] <= stamp)]
    if not live:
        return None
    return max(live, key=lambda c: c['end'])


def create_coupon(client, vendor_id: str, *, contract_id, name: str,
                  unit: str, value: int, max_discount: Optional[int] = None,
                  start_at: Optional[str] = None, end_at: str,
                  wow_exclusive: bool = False) -> str:
    """즉시할인쿠폰 **접수**. 돌려주는 것은 requestedId(쿠폰ID 아님).

    Args:
        unit: 'WON'(정액) | 'PERCENT'(정률) — 그 외는 거부한다.
        max_discount: 최대 할인 금액. 정액이면 그 값 자체가 상한이라 값과 같게 둔다.
        start_at: 안 주면 **내일 0시**(쿠팡이 오늘을 안 받는다).
    """
    ctype = _UNIT_TO_TYPE.get((unit or '').upper())
    if ctype is None:
        raise CoupangCouponError(f'모르는 할인 방식이라 만들지 않습니다: {unit!r}')
    if not value or int(value) <= 0:
        raise CoupangCouponError('깎을 값이 없어 쿠폰을 만들지 않습니다')
    if not contract_id:
        raise CoupangCouponError('계약ID(contractId)가 없어 쿠폰을 만들 수 없습니다')

    body = {
        'contractId': contract_id,
        'name': (name or '모음전 즉시할인')[:45],   # 문서: 최대 45자
        'maxDiscountPrice': int(max_discount if max_discount else value),
        'discount': int(value),
        'startAt': start_at or tomorrow_midnight(),
        'endAt': end_at,
        'type': ctype,
        'wowExclusive': bool(wow_exclusive),
    }
    resp = client.request('POST', _BASE_V2.format(vid=vendor_id) + '/coupon',
                          body=body)
    content = _content(resp)
    rid = content.get('requestedId')
    if not content.get('success') or not rid:
        raise CoupangCouponError(
            f"쿠폰 접수 실패: {resp.get('message') or resp.get('errorMessage') or resp}")
    logger.info('[쿠팡쿠폰] 접수 %s (%s %s) requestedId=%s',
                body['name'], ctype, value, rid)
    return str(rid)


def add_items(client, vendor_id: str, coupon_id, vendor_item_ids: list) -> list[str]:
    """쿠폰에 옵션을 붙인다. 1만 개를 넘으면 나눠 부르고 requestedId 를 모아 준다."""
    ids = [int(v) for v in (vendor_item_ids or []) if v]
    if not ids:
        raise CoupangCouponError('붙일 옵션이 없습니다')
    out = []
    path = _BASE_V1.format(vid=vendor_id) + f'/coupons/{coupon_id}/items'
    for i in range(0, len(ids), MAX_ITEMS_PER_CALL):
        chunk = ids[i:i + MAX_ITEMS_PER_CALL]
        resp = client.request('POST', path, body={'vendorItems': chunk})
        content = _content(resp)
        rid = content.get('requestedId')
        if not content.get('success') or not rid:
            raise CoupangCouponError(
                f"옵션 붙이기 실패({len(chunk)}개): "
                f"{resp.get('message') or resp.get('errorMessage') or resp}")
        out.append(str(rid))
    return out


def check_request(client, vendor_id: str, requested_id) -> dict:
    """접수한 것이 실제로 처리됐는지. status DONE 이어도 failed 를 봐야 한다."""
    resp = client.request(
        'GET', _BASE_V1.format(vid=vendor_id) + f'/requested/{requested_id}')
    c = _content(resp)
    return {
        'coupon_id': c.get('couponId'),
        'status': c.get('status'),                  # DONE 등
        'total': c.get('total'),
        'succeeded': c.get('succeeded'),
        'failed': c.get('failed'),
        'failed_items': c.get('failedVendorItems') or [],
        'done': (c.get('status') == 'DONE'),
    }


def expire_coupon(client, vendor_id: str, coupon_id) -> bool:
    """쿠폰 내리기(만료·비활성).

    🔴 `action=expire` 를 **반드시** 붙여야 한다 — 없으면 쿠팡이 500 을 주며
      「Parameter conditions "action=expire" not met」이라고 답한다(2026-08-06 실측).
      500 이라 재시도까지 돌다 실패해서, 원인이 우리 쪽 파라미터 누락임을 놓치기 쉽다.
    """
    resp = client.request(
        'PUT', _BASE_V1.format(vid=vendor_id) + f'/coupons/{coupon_id}',
        query='action=expire')
    return bool(_content(resp).get('success') or resp.get('code') in (200, '200'))
