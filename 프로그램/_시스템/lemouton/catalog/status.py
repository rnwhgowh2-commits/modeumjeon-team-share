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
        # ★ [2026-07-24 라이브 실측] 목록 응답 statusName 은 **한글**로 온다
        #   ("승인완료"). 영문 코드만 넣었더니 19건이 전부 unknown 으로 저장됐다.
        #   영문도 살려둔다 — 다른 API 가 영문을 줄 수 있다.
        'approved': 'sale', '승인완료': 'sale',
        'partial_approved': 'stopped', '부분승인완료': 'stopped',
        'denied': 'stopped', '승인반려': 'stopped',
        'deleted': 'stopped', '상품삭제': 'stopped',
        'saved': 'waiting', '임시저장': 'waiting',
        'in_review': 'waiting', '심사중': 'waiting',
        'approving': 'waiting', '승인대기중': 'waiting',
    },
}
_MAP['gmarket'] = _MAP['auction']   # 옥션·G마켓은 같은 ESM 코드계


def unify_status(market: str, raw: Optional[str]) -> str:
    """마켓 원본 상태코드를 통일 상태로. 모르면 'unknown'."""
    table = _MAP.get((market or '').strip().lower())
    if not table or raw is None:
        return 'unknown'
    return table.get(str(raw).strip().lower(), 'unknown')
