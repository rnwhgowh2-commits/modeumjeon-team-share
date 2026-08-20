# -*- coding: utf-8 -*-
"""가이드의 「수집 방식」을 코드가 읽는다 — 표면노출가·혜택의 크롤 여부.

배경(2026-07-19 사용자 확정):
  크롤이 혜택을 못 가져왔는데 소싱처 기본 혜택(템플릿)이 그대로 차감되면
  최종 매입가가 **실제보다 싸게** 나온다 → 원가를 싸게 알고 판매가를 낮게 잡는 금전 위험.

  규칙: 가이드에 혜택이 **크롤 대상**(API·HTML·DOM)으로 적혀 있는데 이번 크롤에서
        혜택을 못 가져왔으면 → 템플릿 혜택도 적용하지 않는다 → **최종 매입가 = 표면 노출가**.
        (모르면 안 빼기 = 비싼 쪽 = 안전)

  단 르무통 공홈처럼 혜택이 **원래 템플릿**(크롤 아님)인 소싱처는 그대로 템플릿을 적용한다.
  가이드가 아직 비어 있는 소싱처는 **지금 동작을 유지**(=크롤 대상 아님으로 간주)한다.

정합성 원칙 2 (CLAUDE.md): 크롤 실패 시 폴백 금지 — 단, 여기서는 '더 비싼 쪽'이 안전한
방향이라 크롤실패로 막지 않고 혜택 0 으로 두는 것이 사용자 확정 사항이다.
"""
import pytest

from lemouton.sourcing import crawl_guide as cg


def _guide(*, benefit_mechanism=None, benefit_method=None,
           price_mechanism=None, price_method=None):
    """빈 스켈레톤에 해당 항목의 수집 방식만 채운 가이드."""
    g = cg.empty_skeleton()
    if benefit_mechanism is not None:
        g["fields"]["benefit"]["mechanism"] = benefit_mechanism
    if benefit_method is not None:
        g["fields"]["benefit"]["method"] = benefit_method
    if price_mechanism is not None:
        g["fields"]["price"]["mechanism"] = price_mechanism
    if price_method is not None:
        g["fields"]["price"]["method"] = price_method
    return g


# ── 혜택 크롤 여부 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("mechanism", ["api", "html", "crawl"])
def test_benefit_crawled_when_mechanism_is_a_crawl_kind(mechanism):
    """API·HTML·크롤(미분류) = 크롤로 가져오는 혜택."""
    assert cg.benefit_is_crawled(_guide(benefit_mechanism=mechanism)) is True


@pytest.mark.parametrize("mechanism", ["manual", "none"])
def test_benefit_not_crawled_when_manual_or_none(mechanism):
    """수동·없음 = 크롤 대상 아님 (르무통 공홈처럼 템플릿으로 채우는 소싱처)."""
    assert cg.benefit_is_crawled(_guide(benefit_mechanism=mechanism)) is False


def test_benefit_not_crawled_on_empty_guide():
    """가이드 미작성 = 지금 동작 유지 → 크롤 대상 아님으로 간주(갑작스런 변화 방지)."""
    assert cg.benefit_is_crawled(cg.empty_skeleton()) is False


def test_benefit_not_crawled_when_method_is_uniform():
    """method=uniform(일괄) = 상품별 크롤이 아님 → 크롤 대상 아님."""
    g = _guide(benefit_mechanism="none", benefit_method="uniform")
    assert cg.benefit_is_crawled(g) is False


def test_benefit_crawled_reads_method_when_mechanism_missing():
    """구 카드(mechanism 없음)는 method 로 판단 — 하위호환."""
    g = cg.empty_skeleton()
    g["fields"]["benefit"]["method"] = "crawl_per_product"
    g["fields"]["benefit"].pop("mechanism", None)
    assert cg.benefit_is_crawled(g) is True


# ── 표면 노출가 크롤 여부 (같은 규칙 · 사장님이 이후 채울 항목) ──────────────

@pytest.mark.parametrize("mechanism", ["api", "html", "crawl"])
def test_price_crawled_when_mechanism_is_a_crawl_kind(mechanism):
    assert cg.price_is_crawled(_guide(price_mechanism=mechanism)) is True


@pytest.mark.parametrize("mechanism", ["manual", "none"])
def test_price_not_crawled_when_manual_or_none(mechanism):
    assert cg.price_is_crawled(_guide(price_mechanism=mechanism)) is False


def test_price_not_crawled_on_empty_guide():
    assert cg.price_is_crawled(cg.empty_skeleton()) is False


# ── 방어: 잘못된 입력에도 안전한 쪽(False)으로 ─────────────────────────────

@pytest.mark.parametrize("bad", [None, {}, [], "guide", 0])
def test_bad_input_defaults_to_not_crawled(bad):
    """None·빈 dict·엉뚱한 타입 → False(=지금 동작 유지). 절대 예외를 던지지 않는다."""
    assert cg.benefit_is_crawled(bad) is False
    assert cg.price_is_crawled(bad) is False


def test_missing_fields_key_is_safe():
    assert cg.benefit_is_crawled({"version": 3}) is False
    assert cg.price_is_crawled({"version": 3, "fields": {}}) is False
