# -*- coding: utf-8 -*-
"""옵션별 원가 기준 선택 — 사장님 확정 규칙(2026-07-20) 고정.

  (1) 사입한 상품 있으면 → 사입 기준
  (2) 없으면 → 100% 소싱 크롤 기준
  (3) 소싱이 더 싸면 → 소싱 기준
  마진 설정(side)은 고른 원가를 따라간다.
"""
from lemouton.pricing.cost_basis import resolve_cost_basis, has_purchased_stock


# ── (2) 사입 없음 → 소싱 ────────────────────────────────────────────────
def test_no_purchase_uses_sourcing():
    r = resolve_cost_basis(sourcing_cost=107_700, purchase_avg=0, purchase_stock=0)
    assert r.cost == 107_700 and r.side == 'sourcing'


def test_stock_but_no_avg_is_not_purchased():
    # 재고 숫자만 있고 실측 매입가가 없으면 '사입한 상품'으로 안 본다
    r = resolve_cost_basis(107_700, purchase_avg=0, purchase_stock=6)
    assert r.side == 'sourcing'


def test_avg_but_no_stock_is_not_purchased():
    # 과거에 사서 매입가는 남았지만 재고가 0이면 지금 팔 물건이 없다
    r = resolve_cost_basis(107_700, purchase_avg=95_000, purchase_stock=0)
    assert r.side == 'sourcing' and r.cost == 107_700


# ── (1) 사입 있음 → 사입 ────────────────────────────────────────────────
def test_purchased_and_cheaper_uses_purchase():
    r = resolve_cost_basis(107_700, purchase_avg=95_000, purchase_stock=6)
    assert r.cost == 95_000 and r.side == 'purchase'


def test_purchase_only_when_no_crawl_price():
    r = resolve_cost_basis(None, purchase_avg=95_000, purchase_stock=6)
    assert r.cost == 95_000 and r.side == 'purchase'


# ── (3) 소싱이 더 싸면 → 소싱 ───────────────────────────────────────────
def test_sourcing_cheaper_wins():
    r = resolve_cost_basis(89_000, purchase_avg=95_000, purchase_stock=6)
    assert r.cost == 89_000 and r.side == 'sourcing'
    assert '더 싸' in r.reason


def test_tie_goes_to_purchase():
    # 같으면 사입 — 이미 산 물건을 먼저 턴다
    r = resolve_cost_basis(95_000, purchase_avg=95_000, purchase_stock=6)
    assert r.side == 'purchase'


# ── 원가 불명 ──────────────────────────────────────────────────────────
def test_neither_known_blocks():
    r = resolve_cost_basis(None, purchase_avg=0, purchase_stock=0)
    assert r.cost is None and r.side is None


# ── ★ 사고 방지: 템플릿 손입력값은 후보가 아니다 ────────────────────────
def test_template_hand_typed_value_is_not_a_candidate():
    """호출자가 템플릿 폴백값(전 옵션 공통 95,000)을 넣지 않는 한,
    사입 이력 없는 옵션은 절대 그 값으로 원가가 깎이지 않는다."""
    # 라이브 실측 상황: 사입 이력 0, 소싱 107,700, 템플릿엔 95,000 이 적혀 있음
    r = resolve_cost_basis(107_700, purchase_avg=0, purchase_stock=0)
    assert r.cost == 107_700, '사입한 적 없는 옵션이 템플릿값으로 깎이면 안 된다'


def test_has_purchased_stock_guards():
    assert has_purchased_stock(6, 95_000) is True
    assert has_purchased_stock(0, 95_000) is False
    assert has_purchased_stock(6, 0) is False
    assert has_purchased_stock(None, None) is False
    assert has_purchased_stock('x', 'y') is False       # 잘못된 타입도 안 죽는다


def test_string_numbers_are_tolerated():
    r = resolve_cost_basis('107700', purchase_avg='95000', purchase_stock='6')
    assert r.cost == 95_000 and r.side == 'purchase'
