# -*- coding: utf-8 -*-
"""실구매 피드백 — 경유 쿠폰 추정 보정 (2026-07-23 · 2차 T8, 스펙 §11-5).

■ 배경
  아이몰 네이버 플러스쿠폰은 "이 상품에 어느 쿠폰이 붙는지"가 **주문서에서만** 확정된다.
  평소 계산은 카테고리 매핑으로 **확실할 때만** 차감하고(애매하면 안 깎음 = 매입가 과대
  = 안전), 실구매 때 주문서에서 본 **실제 적용 요율**을 여기 기록해 다음부터 그
  (소싱처, 카테고리) 조합은 추정 대신 실적용값을 쓴다.

■ 사용 순서 (계산 쪽)
    rate = resolve_via_rate(session, source_key, product_category)   # ① 실적용 기록
    if rate is None:
        info = pick_naver_coupon(coupons, product_category)          # ② 카테고리 추정
        rate = info['rate'] if info else None
    # ③ 그래도 없으면 안 깎는다(폴백 금지)

■ 무결성
  · 요율은 0 < rate <= 100 만 저장(클램프 금지 — 잘못된 입력은 거부해 매입가 오염 차단).
  · 같은 조합을 다시 기록하면 최신 값이 이긴다(월별로 요율이 바뀐다).
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from shared.db import Base


class SourcePurchaseFeedback(Base):
    """주문서에서 실제 적용된 경유 쿠폰 요율 기록 — 추정 보정용."""

    __tablename__ = 'source_purchase_feedback'

    id = Column(Integer, primary_key=True)
    source_key = Column(String(32), nullable=False, index=True)
    category = Column(String(64), nullable=False)      # 쿠폰이 걸린 카테고리(예: '패션잡화')
    applied_rate = Column(Float, nullable=False)       # 퍼센트 단위(7 = 7%)
    note = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)


def record_feedback(session, *, source_key, category, applied_rate, note=None):
    """실구매 주문서에서 확인한 요율을 기록한다. 잘못된 값은 ValueError."""
    try:
        rate = float(applied_rate)
    except (TypeError, ValueError):
        raise ValueError('applied_rate 는 숫자여야 합니다')
    if not (0 < rate <= 100):
        raise ValueError(f'applied_rate 범위 오류(0 초과 100 이하): {applied_rate}')
    key = (source_key or '').strip()
    cat = (category or '').strip()
    if not key or not cat:
        raise ValueError('source_key·category 는 필수입니다')
    row = SourcePurchaseFeedback(source_key=key, category=cat,
                                 applied_rate=rate, note=(note or None))
    session.add(row)
    session.commit()
    return row


def resolve_via_rate(session, source_key, product_category):
    """(소싱처, 상품 카테고리)에 해당하는 실적용 요율. 기록 없으면 None.

    상품 카테고리(breadcrumb)가 기록된 카테고리를 **포함**하면 매칭으로 본다
    ('패션잡화' 기록 ↔ '패션잡화 > 여성신발 > 스니커즈' 상품).
    같은 조합이 여럿이면 최신 기록이 이긴다.
    """
    key = (source_key or '').strip()
    pc = (product_category or '').replace(' ', '')
    if not key or not pc:
        return None
    rows = (session.query(SourcePurchaseFeedback)
            .filter(SourcePurchaseFeedback.source_key == key)
            .order_by(SourcePurchaseFeedback.id.desc())
            .all())
    for r in rows:
        cat = (r.category or '').replace(' ', '')
        if cat and cat in pc:
            return float(r.applied_rate)
    return None
