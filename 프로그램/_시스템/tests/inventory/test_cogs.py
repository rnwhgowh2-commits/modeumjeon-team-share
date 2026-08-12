"""[TEST] cogs.py — 이동평균·snapshot·마진·재고총합 단위 테스트.

ai-workflow STEP 7 Sprint 1A Task 1.1
"""
import pytest
from types import SimpleNamespace

from lemouton.inventory.cogs import (
    update_moving_avg,
    snapshot_at_outbound,
    compute_margin,
    recalc_stock_total,
)


# ============ 이동평균 ============

def make_option(qty=0, avg=0):
    """가벼운 Option mock — DB 없이 attribute 검증."""
    return SimpleNamespace(
        boxhero_stock_total=qty,
        boxhero_avg_purchase_price=avg,
        boxhero_avg_updated_at=None,
    )


def test_first_inbound_sets_avg():
    """초기 재고 0 + 첫 입고 → 그 매입가가 곧바로 평균."""
    o = make_option(qty=0, avg=0)
    new_avg = update_moving_avg(o, qty_in=10, price_in=5000)
    assert new_avg == 5000
    assert o.boxhero_stock_total == 10
    assert o.boxhero_avg_purchase_price == 5000
    assert o.boxhero_avg_updated_at is not None


def test_subsequent_inbound_weighted_avg():
    """기존 10@5000 + 추가 5@7000 → (50000+35000)/15 = 5667."""
    o = make_option(qty=10, avg=5000)
    new_avg = update_moving_avg(o, qty_in=5, price_in=7000)
    assert new_avg == 5667
    assert o.boxhero_stock_total == 15


def test_inbound_after_zero_stock():
    """재고 0 (출고로 소진 후) + 새 가격 입고 → 새 매입가가 곧바로 평균."""
    o = make_option(qty=0, avg=5000)  # 이전 평균 있지만 재고 0
    new_avg = update_moving_avg(o, qty_in=10, price_in=8000)
    # (5000*0 + 8000*10) / (0+10) = 8000
    assert new_avg == 8000
    assert o.boxhero_stock_total == 10


def test_negative_qty_raises():
    """음수 입고 수량은 ValueError."""
    o = make_option(qty=10, avg=5000)
    with pytest.raises(ValueError):
        update_moving_avg(o, qty_in=-5, price_in=7000)


# ============ snapshot ============

def test_snapshot_returns_current_avg():
    """출고 시점 평균 매입가를 그대로 반환."""
    o = make_option(qty=10, avg=5500)
    snap = snapshot_at_outbound(o)
    assert snap == 5500


def test_snapshot_zero_when_no_avg():
    """평균이 None이면 0 반환 (안전)."""
    o = make_option(qty=0, avg=0)
    o.boxhero_avg_purchase_price = None
    assert snapshot_at_outbound(o) == 0


def test_snapshot_immutable_after_inbound():
    """snapshot 후 입고로 평균 변해도 snapshot 값은 별개."""
    o = make_option(qty=10, avg=5000)
    snap = snapshot_at_outbound(o)  # 5000
    # 입고로 평균 변경
    update_moving_avg(o, qty_in=10, price_in=10000)
    assert o.boxhero_avg_purchase_price == 7500  # 평균 변함
    assert snap == 5000  # snapshot은 그대로


# ============ 마진 계산 ============

def test_margin_basic():
    """매입가 5000, 판매가 10000, 수량 2 → 매출 20000, 원가 10000, 이익 10000, 마진율 50%."""
    m = compute_margin(unit_purchase_at_tx=5000, unit_sale=10000, qty=2)
    assert m['revenue'] == 20000
    assert m['cogs'] == 10000
    assert m['profit'] == 10000
    assert m['rate'] == 0.5
    assert m['has_data'] is True


def test_margin_no_purchase_data():
    """매입가 없음 (snapshot 박제 안 됨) → has_data=False."""
    m = compute_margin(unit_purchase_at_tx=None, unit_sale=10000, qty=2)
    assert m['has_data'] is False
    assert m['revenue'] == 20000
    assert m['cogs'] == 0


def test_margin_zero_revenue():
    """판매가 0 → 마진율 0."""
    m = compute_margin(unit_purchase_at_tx=5000, unit_sale=0, qty=2)
    assert m['revenue'] == 0
    assert m['rate'] == 0.0


def test_margin_loss():
    """매입가 > 판매가 → 음수 이익, 음수 마진율."""
    m = compute_margin(unit_purchase_at_tx=8000, unit_sale=5000, qty=1)
    assert m['profit'] == -3000
    assert m['rate'] == -0.6


# ============ 재고총합 재계산 (DB 필요) ============

def test_recalc_stock_total_simple(tmp_path):
    """입고·출고·조정·이동 통합 — 재고총합 재계산."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from shared.db import Base
    import lemouton.inventory.models  # 등록

    # sorted_tables 대신 metadata.tables에서 직접 필터 (외부 모델 의존 ❌)
    INV_TABLE_PREFIXES = ('inventory_', 'item_attributes', 'item_attribute_values',
                           'purchase_orders', 'sales_orders', 'return_orders')
    inv_tables = [t for name, t in Base.metadata.tables.items()
                   if name.startswith(INV_TABLE_PREFIXES)]

    engine = create_engine(f'sqlite:///{tmp_path}/test.db')
    Base.metadata.create_all(engine, tables=inv_tables)
    Session = sessionmaker(bind=engine)
    s = Session()

    from lemouton.inventory.models import InventoryTx
    sku = 'TEST-SKU-001'

    # 입고 10
    s.add(InventoryTx(tx_type='in', option_canonical_sku=sku, qty=10, status='completed'))
    # 출고 3
    s.add(InventoryTx(tx_type='out', option_canonical_sku=sku, qty=3, status='completed'))
    # 입고 5
    s.add(InventoryTx(tx_type='in', option_canonical_sku=sku, qty=5, status='completed'))
    # 이동 2 (총합 영향 ❌)
    s.add(InventoryTx(tx_type='move', option_canonical_sku=sku, qty=2, status='completed'))
    s.commit()

    total = recalc_stock_total(sku, s)
    # 10 - 3 + 5 + 0(move) = 12
    assert total == 12

    # 조정 (절대값 set)
    s.add(InventoryTx(tx_type='adjust', option_canonical_sku=sku, qty=20, status='completed'))
    s.commit()
    total2 = recalc_stock_total(sku, s)
    assert total2 == 20  # 조정 후 절대값
