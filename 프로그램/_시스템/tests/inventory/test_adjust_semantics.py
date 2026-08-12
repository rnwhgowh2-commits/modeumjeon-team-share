# -*- coding: utf-8 -*-
"""조정(adjust)의 뜻 — **절대값 하나** (2026-08-13 감사에서 통일).

왜 이 시험이 있나
  같은 표(`inventory_txs`)의 `adjust` 행을 **읽는 쪽 두 곳이 정반대**로 봤다:
    · lemouton/inventory/cogs.py      → 절대값(set)
    · shared/inventory_stock.py       → delta 합
  「입고 100 → 실사 조정 5」에서 한쪽은 5, 다른쪽은 105 를 냈다(100개 과대).
  **쓰는 쪽도 두 곳이 정반대**였다(`create_adjustment` 절대값 / `api_inventory_link`
  차이값) — 그래서 한 표의 행이 두 가지 뜻을 가졌다.

  이 시험이 깨지면 재고 숫자가 화면마다 달라진다 = 돈이 틀어진다.
"""
import pytest


@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models   # noqa: F401
    import lemouton.inventory.models  # noqa: F401
    from shared.db import Base
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _opt(db, sku='SKU-ADJ001'):
    from lemouton.sourcing.models import Model, Option
    db.add(Model(model_code='MADJ', model_name_raw='조정검사', brand='르무통'))
    db.flush()
    db.add(Option(canonical_sku=sku, model_code='MADJ',
                  color_code='블랙', size_code='250'))
    db.flush()
    return sku


def _tx(db, sku, tx_type, qty, seq):
    from datetime import datetime, timedelta, timezone
    from lemouton.inventory.models import InventoryTx
    db.add(InventoryTx(tx_type=tx_type, option_canonical_sku=sku, qty=qty,
                       status='completed', location_id=1,
                       created_at=datetime(2026, 8, 13, tzinfo=timezone.utc)
                       + timedelta(minutes=seq)))
    db.flush()


def test_두_읽는_쪽이_같은_숫자를_낸다(db):
    """🔴 「입고 100 → 실사 조정 5」 = 5. 한쪽이 105 면 100개를 없는 재고로 판다."""
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.cogs import recalc_stock_total
    sku = _opt(db)
    _tx(db, sku, 'in', 100, 1)
    _tx(db, sku, 'adjust', 5, 2)
    batch = get_stock_batch(db, [sku])[sku]
    exact = recalc_stock_total(sku, db)
    assert batch == exact == 5, f'get_stock_batch={batch} recalc={exact} — 갈렸다'


def test_조정_뒤_입출고는_조정값_위에_쌓인다(db):
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.cogs import recalc_stock_total
    sku = _opt(db)
    _tx(db, sku, 'in', 100, 1)
    _tx(db, sku, 'adjust', 5, 2)
    _tx(db, sku, 'in', 3, 3)
    _tx(db, sku, 'out', 2, 4)
    assert get_stock_batch(db, [sku])[sku] == 6
    assert recalc_stock_total(sku, db) == 6


def test_조정이_없으면_예전과_똑같다(db):
    """빠른 길(SUM)을 그대로 쓴다 — 회귀 방지."""
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.cogs import recalc_stock_total
    sku = _opt(db)
    _tx(db, sku, 'in', 10, 1)
    _tx(db, sku, 'out', 4, 2)
    assert get_stock_batch(db, [sku])[sku] == 6
    assert recalc_stock_total(sku, db) == 6


def test_조정을_0으로_하면_재고가_0이_된다(db):
    """라이브에 실제로 있는 단 하나의 조정 행이 이 모양(= 0)이다."""
    from shared.inventory_stock import get_stock_batch
    sku = _opt(db)
    _tx(db, sku, 'in', 7, 1)
    _tx(db, sku, 'adjust', 0, 2)
    assert get_stock_batch(db, [sku])[sku] == 0


def test_쓰는_쪽도_절대값으로_남긴다(db):
    """`create_adjustment(new_qty=5)` 는 qty=5(결과 수량)를 남긴다 — 차이값이 아니다."""
    from lemouton.inventory.inbound import create_adjustment
    from lemouton.inventory.models import InventoryLocation, InventoryTx
    sku = _opt(db)
    db.add(InventoryLocation(id=1, name='기본 위치', is_default=True))
    db.flush()
    _tx(db, sku, 'in', 100, 1)
    create_adjustment(db, location_id=1, option_canonical_sku=sku, new_qty=5)
    tx = (db.query(InventoryTx).filter_by(option_canonical_sku=sku,
                                          tx_type='adjust').one())
    assert tx.qty == 5, '조정은 결과 수량(절대값)으로 남아야 한다'
