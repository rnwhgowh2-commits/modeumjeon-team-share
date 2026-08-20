# -*- coding: utf-8 -*-
"""[TEST] 2차 T8 — 실구매 피드백으로 경유 쿠폰 추정 보정 (사장님 확정 2026-07-23).

■ 왜 필요한가
  아이몰 네이버 플러스쿠폰은 "이 상품에 어느 쿠폰이 붙는지"가 **주문서에서만** 100%
  확정된다(스펙 §11-5). 그래서 평소엔 카테고리 매핑으로 **확실할 때만** 차감하고
  (애매하면 안 깎음 = 매입가 과대 = 안전), 실구매 때 주문서에서 **실제 적용된 요율**을
  기록해 다음부터 그 (소싱처, 카테고리) 조합은 추정 대신 **실적용값**을 쓴다.

■ 무엇을 잠그나
  1) 기록한 (소싱처, 카테고리) 조합은 `resolve_via_rate` 가 실적용 요율을 돌려준다.
  2) 기록 없는 조합은 None — 추정 로직(카테고리 매핑)으로 넘어가고, 그것도 없으면 안 깎음.
  3) 같은 조합을 다시 기록하면 **최신 값이 이긴다**(요율이 바뀌는 달이 있다).
  4) 카테고리는 부분 일치로 찾는다(상품 breadcrumb 이 더 길기 때문).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.sourcing.purchase_feedback import record_feedback, resolve_via_rate


def _sess():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_recorded_rate_wins_for_same_source_and_category():
    s = _sess()
    try:
        record_feedback(s, source_key="lotteimall", category="패션잡화",
                        applied_rate=7.0, note="주문서 실적용 2026-07-23")
        assert resolve_via_rate(s, "lotteimall", "패션잡화 > 여성신발 > 스니커즈") == 7.0
    finally:
        s.close()


def test_unrecorded_returns_none():
    s = _sess()
    try:
        record_feedback(s, source_key="lotteimall", category="패션잡화", applied_rate=7.0)
        assert resolve_via_rate(s, "lotteimall", "식품 > 건강식품") is None
        assert resolve_via_rate(s, "ssg", "패션잡화 > 여성신발") is None   # 다른 소싱처
        assert resolve_via_rate(s, "lotteimall", "") is None
    finally:
        s.close()


def test_latest_record_wins():
    s = _sess()
    try:
        record_feedback(s, source_key="lotteimall", category="패션잡화", applied_rate=7.0)
        record_feedback(s, source_key="lotteimall", category="패션잡화", applied_rate=9.0,
                        note="8월 요율 상향")
        assert resolve_via_rate(s, "lotteimall", "패션잡화 > 여성신발") == 9.0
    finally:
        s.close()


def test_invalid_rate_is_rejected():
    """0 이하·100 초과는 저장 거부 — 잘못된 값이 매입가를 오염시키지 않게."""
    s = _sess()
    try:
        for bad in (0, -1, 101):
            try:
                record_feedback(s, source_key="lotteimall", category="패션잡화",
                                applied_rate=bad)
                assert False, f"거부 안 됨: {bad}"
            except ValueError:
                pass
    finally:
        s.close()
