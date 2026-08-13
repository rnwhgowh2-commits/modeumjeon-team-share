# -*- coding: utf-8 -*-
"""조정(adjust)의 뜻 — **차이값 하나** (2026-08-13 사장님 확정).

왜 이 시험이 있나
  같은 표(`inventory_txs`)의 `adjust` 행을 읽는 쪽·쓰는 쪽이 서로 다르게 봤다.
  하루에 규약이 **세 번** 뒤집혔고, 매번 한두 군데만 고쳐서 그랬다.
  세 번 다 **에러 없이 숫자만 틀렸다**(재고 4, 6, −2).

  🔴 차이값으로 정한 이유 — 절대값이면 **위치별 합이 전체와 안 맞는다.**
     절대값은 SUM 으로 표현이 안 돼 전체는 「접어서」, 위치별은 「더해서」 센다:
         창고A 입고 10 · 조정 5  →  전체 5 · 창고A 15   (합 15 ≠ 전체 5)
     창고별 합이 전체와 다르면 없는 재고를 팔게 된다.
     자세한 근거 = shared/inventory_stock.py 머리말
     위치 정합 시험 = tests/inventory/test_adjust_location_consistency.py

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
    """🔴 「입고 100 → 조정 −95」 = 5. 두 읽는 쪽이 같은 숫자를 내야 한다.

    창구는 「실사 5개」를 받고 뺄셈은 서버가 한다 → 원장엔 −95 가 남는다.
    """
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.cogs import recalc_stock_total
    sku = _opt(db)
    _tx(db, sku, 'in', 100, 1)
    _tx(db, sku, 'adjust', -95, 2)      # 실사 5 → 차이 −95
    batch = get_stock_batch(db, [sku])[sku]
    exact = recalc_stock_total(sku, db)
    assert batch == exact == 5, f'get_stock_batch={batch} recalc={exact} — 갈렸다'


def test_조정_뒤_입출고는_조정값_위에_쌓인다(db):
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.cogs import recalc_stock_total
    sku = _opt(db)
    _tx(db, sku, 'in', 100, 1)
    _tx(db, sku, 'adjust', -95, 2)      # 실사 5 → 차이 −95
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


def test_조정으로_재고를_0으로_만들_수_있다(db):
    """실사해 보니 0개 — 창구는 0 을 받고 원장엔 −7 이 남는다."""
    from shared.inventory_stock import get_stock_batch
    sku = _opt(db)
    _tx(db, sku, 'in', 7, 1)
    _tx(db, sku, 'adjust', -7, 2)       # 실사 0 → 차이 −7
    assert get_stock_batch(db, [sku])[sku] == 0


def test_쓰는_쪽은_차이값으로_남긴다(db):
    """`create_adjustment(new_qty=5)` 는 **차이**를 남긴다 — 받는 값은 결과 수량이다.

    작업자에게 뺄셈을 시키지 않는다. 뺄셈은 이 함수 안에서 한다.
    """
    from lemouton.inventory.inbound import create_adjustment
    from lemouton.inventory.models import InventoryLocation, InventoryTx
    sku = _opt(db)
    db.add(InventoryLocation(id=1, name='기본 위치', is_default=True))
    db.flush()
    _tx(db, sku, 'in', 100, 1)
    create_adjustment(db, location_id=1, option_canonical_sku=sku, new_qty=5)
    tx = (db.query(InventoryTx).filter_by(option_canonical_sku=sku,
                                          tx_type='adjust').one())
    assert tx.qty == -95, '조정은 차이값(5 − 100)으로 남아야 한다'
