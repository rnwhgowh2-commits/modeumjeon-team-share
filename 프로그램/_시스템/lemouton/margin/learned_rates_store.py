# -*- coding: utf-8 -*-
"""마켓이 한 번 알려준 값을 기억/재사용 — MarketLearnedRates(id=1) 읽기·병합.

`product_count_store` 와 같은 단일 행 JSON 패턴. 저장 실패는 **삼킨다** — 기억은
정확도를 올리는 보조 수단이지 조회의 전제가 아니다. DB 가 없거나(테스트·폴백 SQLite)
동시 삽입이 부딪혀도 주문 조회 자체는 그대로 돌아야 한다.

★병합만 하고 삭제는 안 한다. 한 번 확정 근거로 배운 값은 다음 조회에 그 근거가
  안 들어왔다고 해서 지우면 안 된다(그게 바로 고치려는 병이다).
★값이 갈리면(같은 채널이 제휴·직영 둘 다) 호출부가 학습 대상에서 빼고 넘긴다 —
  여기서는 넘어온 것만 덮어쓴다.
"""
from __future__ import annotations

import logging

from lemouton.margin.models import MarketLearnedRates

logger = logging.getLogger(__name__)

_CONFIG_ID = 1

# 쿠팡 요율 상식 범위. 역산이 이 밖으로 나오면 '정산이 아닌 무언가'(부분취소·조정·
# 쿠폰 정산 등)를 요율로 오해한 것 → 배우지 않는다. 틀린 요율을 기억하면 그 상품의
# 모든 미정산 주문이 조용히 틀린다.
CP_RATE_MIN = 0.05
CP_RATE_MAX = 0.30


def _row(session):
    return session.get(MarketLearnedRates, _CONFIG_ID)


def load(session) -> dict:
    """{'lotteon_channels': {...}, 'coupang_fee_rates': {...}}. 행 없으면 빈 dict 2개."""
    row = _row(session)
    if row is None:
        return {"lotteon_channels": {}, "coupang_fee_rates": {}}
    return {
        "lotteon_channels": dict(row.lotteon_channels or {}),
        "coupang_fee_rates": dict(row.coupang_fee_rates or {}),
    }


def merge(session, lotteon_channels=None, coupang_fee_rates=None) -> dict:
    """새로 배운 것만 얹는다(덮어쓰기·삭제 없음). 병합 후 전체를 돌려준다."""
    from sqlalchemy.exc import IntegrityError

    row = _row(session)
    if row is None:
        row = MarketLearnedRates(id=_CONFIG_ID, lotteon_channels={}, coupang_fee_rates={})
        session.add(row)
        try:
            session.flush()
        except IntegrityError:
            # 최초 사용 시 동시 요청 둘이 모두 '행 없음'을 보고 각자 INSERT → PK 충돌.
            session.rollback()
            row = _row(session)
            if row is None:
                raise

    if lotteon_channels:
        merged = dict(row.lotteon_channels or {})
        merged.update({str(k): bool(v) for k, v in lotteon_channels.items()})
        row.lotteon_channels = merged          # JSON 은 재대입해야 변경이 잡힌다
    if coupang_fee_rates:
        merged = dict(row.coupang_fee_rates or {})
        merged.update({str(k): float(v) for k, v in coupang_fee_rates.items()})
        row.coupang_fee_rates = merged
    session.commit()
    return load(session)


def load_safe() -> dict:
    """세션까지 알아서 여는 안전판. 실패하면 빈 기억(조회는 계속 돈다)."""
    try:
        from shared.db import SessionLocal
        with SessionLocal() as s:
            return load(s)
    except Exception:   # noqa: BLE001 — 기억은 보조 수단, 조회를 막지 않는다
        logger.debug("learned_rates 읽기 실패 — 빈 기억으로 진행", exc_info=True)
        return {"lotteon_channels": {}, "coupang_fee_rates": {}}


def merge_safe(lotteon_channels=None, coupang_fee_rates=None) -> None:
    """세션까지 알아서 여는 안전판. 실패는 삼킨다(다음 조회에 다시 배우면 된다)."""
    if not lotteon_channels and not coupang_fee_rates:
        return
    try:
        from shared.db import SessionLocal
        with SessionLocal() as s:
            merge(s, lotteon_channels, coupang_fee_rates)
    except Exception:   # noqa: BLE001
        logger.debug("learned_rates 저장 실패 — 이번 조회분만 사용", exc_info=True)
