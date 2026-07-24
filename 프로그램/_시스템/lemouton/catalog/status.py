# -*- coding: utf-8 -*-
"""마켓 원본 상태코드 → 통일 4상태(+unknown).

★ 모르는 코드는 절대 'sale' 로 만들지 않는다. 품절인 상품이 판매중으로 보이면
  재고 없이 팔리는 오버셀이 난다. 모르면 'unknown' 으로 남기고 화면에 그대로 띄워
  사람이 알아채게 한다(조용한 실패 금지).

근거: 판매처 > 데이터 코드 지도 각 마켓 「상품 목록 조회」 요청/응답 코드표.
"""
from __future__ import annotations

from typing import Optional

#: 화면·집계가 쓰는 통일 상태. 순서 = 화면 표시 순서.
UNIFIED = ('sale', 'soldout', 'stopped', 'waiting', 'unknown')

#: 마켓별 원본코드 → 통일상태. 키는 **소문자**로 정규화해 담는다.
_MAP: dict[str, dict[str, str]] = {
    'smartstore': {
        'sale': 'sale', 'outofstock': 'soldout',
        'suspension': 'stopped', 'close': 'stopped', 'prohibition': 'stopped',
        'delete': 'stopped',
        'wait': 'waiting', 'unadmission': 'waiting', 'rejection': 'waiting',
    },
    'lotteon': {
        'sale': 'sale', 'sout': 'soldout', 'stp': 'stopped', 'end': 'stopped',
    },
    'eleven11': {
        '103': 'sale', '104': 'soldout',
        '105': 'stopped', '106': 'stopped', '108': 'stopped',
        '101': 'waiting', '102': 'waiting',
    },
    'auction': {'11': 'sale', '31': 'soldout', '21': 'stopped', '22': 'stopped'},
    'coupang': {
        'approved': 'sale',
        'partial_approved': 'stopped', 'denied': 'stopped', 'deleted': 'stopped',
        'saved': 'waiting', 'in_review': 'waiting', 'approving': 'waiting',
    },
}
_MAP['gmarket'] = _MAP['auction']   # 옥션·G마켓은 같은 ESM 코드계


def unify_status(market: str, raw: Optional[str]) -> str:
    """마켓 원본 상태코드를 통일 상태로. 모르면 'unknown'."""
    table = _MAP.get((market or '').strip().lower())
    if not table or raw is None:
        return 'unknown'
    return table.get(str(raw).strip().lower(), 'unknown')
