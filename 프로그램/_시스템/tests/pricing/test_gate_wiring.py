# -*- coding: utf-8 -*-
"""gated_off_names 순수 헬퍼 단위 테스트 (Task 1b-3).

SAFETY INVARIANTS 검증:
  1. status='conditional' 혜택만 게이트 대상 — always/others 는 절대 반환 안 됨.
  2. 하드코딩 사이트 혜택(동적 _DynBenefit)은 본 헬퍼와 무관 — 테스트 범위 외.
  3. 폴백 금지: 헬퍼는 이름 집합만 반환(enabled 토글 전용), 값 대체 없음.
  4. benefit_lines 또는 guide_benefits 가 비면 빈 집합 → no-op (배포 안전).
  5. 현재 무신사(_site_for='musinsa')만 적용 — 헬퍼 자체는 사이트 무관 순수 함수.
"""
import pytest

from lemouton.pricing.benefit_gate import gated_off_names


# ── 픽스처 데이터 ─────────────────────────────────────────────────────────────

def _make_benefit(name: str, status: str, triggers: list[str],
                  match: str = "any", excludes: list[str] = None,
                  exclude_match: str = "any") -> dict:
    return {
        "name": name,
        "status": status,
        "triggers": triggers,
        "match": match,
        "excludes": excludes or [],
        "exclude_match": exclude_match,
    }


EXCL_NONE = []
EXCL_BUGA = [{"word": "불가", "with": [], "except": []}]


# ── 핵심 기능 테스트 ──────────────────────────────────────────────────────────

def test_conditional_trigger_match_not_in_off():
    """conditional 혜택이 트리거 키워드 매칭 → off 집합에 없음 (적용됨)."""
    benefits = [_make_benefit("후기적립", "conditional", ["후기"])]
    off = gated_off_names(benefits, ["후기 적립"], EXCL_NONE)
    assert "후기적립" not in off


def test_conditional_trigger_no_match_in_off():
    """conditional 혜택이 트리거 키워드 미매칭 → off 집합에 있음 (비활성화 대상)."""
    benefits = [_make_benefit("후기적립", "conditional", ["후기"])]
    off = gated_off_names(benefits, ["없음"], EXCL_NONE)
    assert "후기적립" in off


def test_conditional_trigger_match_but_exclude_in_off():
    """conditional 혜택이 트리거 매칭했으나 제외 키워드로 veto → off."""
    benefits = [_make_benefit("후기적립", "conditional", ["후기"])]
    off = gated_off_names(benefits, ["후기 적립 불가"], EXCL_BUGA)
    assert "후기적립" in off


def test_conditional_per_benefit_exclude_in_off():
    """혜택 자체 excludes 키워드로 veto → off."""
    benefits = [_make_benefit("후기적립", "conditional", ["후기"],
                              excludes=["불가"], exclude_match="any")]
    off = gated_off_names(benefits, ["후기 적립 불가"], EXCL_NONE)
    assert "후기적립" in off


# ── 불변 조건 #1: always 혜택은 절대 off 에 없음 ─────────────────────────────

def test_always_benefit_never_in_off_even_if_triggers_absent():
    """INVARIANT #1: always 혜택은 트리거 미매칭·benefit_lines 비어도 절대 off 안 됨."""
    benefits = [
        _make_benefit("상품쿠폰", "always", ["쿠폰"]),     # always — lines 에 '쿠폰' 없음
        _make_benefit("후기적립", "conditional", ["후기"]), # conditional — lines 에 '후기' 없음
    ]
    off = gated_off_names(benefits, ["없음"], EXCL_NONE)
    assert "상품쿠폰" not in off   # always → 절대 불변
    assert "후기적립" in off       # conditional 트리거 미매칭 → off


def test_always_benefit_never_in_off_even_with_empty_lines():
    """INVARIANT #4: benefit_lines 가 빈 리스트면 빈 집합 (no-op)."""
    benefits = [
        _make_benefit("상품쿠폰", "always", ["쿠폰"]),
        _make_benefit("후기적립", "conditional", ["후기"]),
    ]
    off = gated_off_names(benefits, [], EXCL_NONE)
    assert off == set()            # lines 비면 항상 빈 집합


def test_optional_status_never_in_off():
    """optional 상태 혜택도 conditional 이 아니므로 off 에 절대 없음."""
    benefits = [_make_benefit("등급할인", "optional", ["등급"])]
    off = gated_off_names(benefits, ["없음"], EXCL_NONE)
    assert "등급할인" not in off


def test_planned_status_never_in_off():
    """planned 상태 혜택도 conditional 이 아니므로 off 에 절대 없음."""
    benefits = [_make_benefit("신규쿠폰", "planned", ["쿠폰"])]
    off = gated_off_names(benefits, ["없음"], EXCL_NONE)
    assert "신규쿠폰" not in off


# ── 불변 조건 #4: no-op 경우들 ───────────────────────────────────────────────

def test_empty_guide_benefits_returns_empty_set():
    """INVARIANT #4: guide_benefits 비면 빈 집합."""
    assert gated_off_names([], ["후기 적립"], EXCL_NONE) == set()


def test_none_guide_benefits_returns_empty_set():
    """None guide_benefits → 빈 집합."""
    assert gated_off_names(None, ["후기 적립"], EXCL_NONE) == set()


def test_empty_lines_returns_empty_set():
    """INVARIANT #4: benefit_lines 비면 빈 집합 (conditional 있어도)."""
    benefits = [_make_benefit("후기적립", "conditional", ["후기"])]
    assert gated_off_names(benefits, [], EXCL_NONE) == set()


def test_none_lines_returns_empty_set():
    """None benefit_lines → 빈 집합."""
    benefits = [_make_benefit("후기적립", "conditional", ["후기"])]
    assert gated_off_names(benefits, None, EXCL_NONE) == set()


def test_no_conditional_benefits_returns_empty_set():
    """conditional 없으면 빈 집합 (always + optional 만 있음)."""
    benefits = [
        _make_benefit("상품쿠폰", "always", ["쿠폰"]),
        _make_benefit("등급할인", "optional", ["등급"]),
    ]
    assert gated_off_names(benefits, ["없음"], EXCL_NONE) == set()


# ── 복합 시나리오 ─────────────────────────────────────────────────────────────

def test_mixed_always_and_conditional_only_conditional_gated():
    """always + conditional 혼합: conditional 만 게이트, always 는 불변."""
    benefits = [
        _make_benefit("기본적립", "always", ["적립"]),       # always
        _make_benefit("후기적립", "conditional", ["후기"]),  # conditional, 미매칭
        _make_benefit("등급적립", "conditional", ["적립"]),  # conditional, 매칭
    ]
    off = gated_off_names(benefits, ["적립 100원"], EXCL_NONE)
    assert "기본적립" not in off   # always → 항상 보존
    assert "후기적립" in off       # conditional, 트리거 '후기' 미매칭
    assert "등급적립" not in off   # conditional, 트리거 '적립' 매칭 → 적용됨


def test_exclude_keyword_vetos_matched_conditional():
    """포함 매칭됐지만 공통 제외 키워드로 veto → off."""
    benefits = [_make_benefit("등급할인", "conditional", ["등급"])]
    excl = [{"word": "불가", "with": [], "except": []}]
    # "등급 할인 불가" — 포함 매칭 OK, 제외 '불가' veto
    off = gated_off_names(benefits, ["등급 할인 불가"], excl)
    assert "등급할인" in off


def test_exclude_keyword_except_cancels_veto():
    """제외 규칙의 except 예외 키워드가 있으면 veto 취소 → 적용됨 (off 아님)."""
    benefits = [_make_benefit("등급할인", "conditional", ["등급"])]
    excl = [{"word": "불가", "with": [], "except": ["예외적용"]}]
    # "등급 불가 예외적용" — 제외 '불가' 발동하려 했으나 '예외적용'이 있어 취소
    off = gated_off_names(benefits, ["등급 불가 예외적용"], excl)
    assert "등급할인" not in off


def test_return_type_is_set():
    """반환 타입은 set (이름 중복 없음)."""
    benefits = [
        _make_benefit("후기적립", "conditional", ["후기"]),
        _make_benefit("후기적립", "conditional", ["후기"]),  # 중복 이름
    ]
    off = gated_off_names(benefits, ["없음"], EXCL_NONE)
    assert isinstance(off, set)
    assert len(off) <= 1  # set 이므로 중복 없음
