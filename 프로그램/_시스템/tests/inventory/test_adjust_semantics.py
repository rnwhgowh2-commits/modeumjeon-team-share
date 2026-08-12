# -*- coding: utf-8 -*-
"""조정(adjust)의 뜻 — **증감분(델타) 하나** (2026-08-13 통일).

왜 이 시험이 있나
  같은 표(`inventory_txs`)의 `adjust` 행을 **읽는 쪽 두 곳이 정반대**로 봤다:
    · lemouton/inventory/cogs.py      → 절대값(set)
    · shared/inventory_stock.py       → 델타 합
  「입고 100 → 실사 5개」에서 한쪽은 5, 다른쪽은 105 를 냈다(100개 과대).
  **쓰는 쪽도 갈려 있었다** — 모바일·재고연동은 델타, `create_adjustment` 만 절대값.
  그래서 한 표의 같은 종류 행이 두 가지 뜻을 가졌다.

왜 절대값이 아니라 델타로 통일했나
  ① 합(SUM)으로 셀 수 있다 — 절대값은 「그 값으로 정한다」라 합으로 표현이 안 된다
  ② **위치별 재고와 합이 맞는다** — 절대값이면 A창고 실사가 B창고 재고까지 덮는다
  ③ 쓰는 곳 3곳 중 2곳(모바일·재고연동)이 이미 델타였다
  ④ 라이브에 실재하는 단 하나의 조정 행(qty=0, 메모 「배포 검증(무변경)」)도
     델타로 읽어야 메모와 뜻이 맞는다
  창구는 여전히 「결과 수량」을 받는다 — 뺄셈은 프로그램이 한다.

  이 시험이 깨지면 재고 숫자가 화면마다 달라진다 = 돈이 틀어진다.
"""
from datetime import datetime, timedelta, timezone

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


def _tx(db, sku, tx_type, qty, seq, loc=1):
    from lemouton.inventory.models import InventoryTx
    db.add(InventoryTx(tx_type=tx_type, option_canonical_sku=sku, qty=qty,
                       status='completed', location_id=loc,
                       created_at=datetime(2026, 8, 13, tzinfo=timezone.utc)
                       + timedelta(minutes=seq)))
    db.flush()


def test_두_읽는_쪽이_같은_숫자를_낸다(db):
    """🔴 예전엔 「입고 100 + 조정」에서 5 와 105 가 동시에 나왔다."""
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.cogs import recalc_stock_total
    sku = _opt(db)
    _tx(db, sku, 'in', 100, 1)
    _tx(db, sku, 'adjust', -95, 2)          # 실사 5개 → 차이 -95
    batch = get_stock_batch(db, [sku])[sku]
    exact = recalc_stock_total(sku, db)
    assert batch == exact == 5, f'get_stock_batch={batch} recalc={exact} — 갈렸다'


def test_조정_뒤_입출고는_그_위에_쌓인다(db):
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.cogs import recalc_stock_total
    sku = _opt(db)
    _tx(db, sku, 'in', 100, 1)
    _tx(db, sku, 'adjust', -95, 2)
    _tx(db, sku, 'in', 3, 3)
    _tx(db, sku, 'out', 2, 4)
    assert get_stock_batch(db, [sku])[sku] == 6
    assert recalc_stock_total(sku, db) == 6


def test_조정이_없으면_예전과_똑같다(db):
    """빠른 길(합)을 그대로 쓴다 — 회귀 방지."""
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.cogs import recalc_stock_total
    sku = _opt(db)
    _tx(db, sku, 'in', 10, 1)
    _tx(db, sku, 'out', 4, 2)
    assert get_stock_batch(db, [sku])[sku] == 6
    assert recalc_stock_total(sku, db) == 6


def test_조정_0은_아무것도_안_바꾼다(db):
    """라이브에 실재하는 단 하나의 조정 행이 이 모양이다 — qty=0, 메모 「무변경」."""
    from shared.inventory_stock import get_stock_batch
    sku = _opt(db)
    _tx(db, sku, 'in', 7, 1)
    _tx(db, sku, 'adjust', 0, 2)
    assert get_stock_batch(db, [sku])[sku] == 7


def test_창구는_결과수량을_받고_원장엔_차이를_남긴다(db):
    """작업자는 「실사 5개」만 적는다(뺄셈 안 함). 원장엔 차이(-95)가 남는다."""
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.inbound import create_adjustment
    from lemouton.inventory.models import InventoryLocation, InventoryTx
    sku = _opt(db)
    db.add(InventoryLocation(id=1, name='기본 위치', is_default=True))
    db.flush()
    _tx(db, sku, 'in', 100, 1)
    create_adjustment(db, location_id=1, option_canonical_sku=sku, new_qty=5)
    tx = (db.query(InventoryTx).filter_by(option_canonical_sku=sku,
                                          tx_type='adjust').one())
    assert tx.qty == -95, f'원장엔 차이가 남아야 한다: {tx.qty}'
    assert get_stock_batch(db, [sku])[sku] == 5, '결과는 실사한 5개'


def test_한_위치_실사가_다른_위치_재고를_안_덮는다(db):
    """🔴 절대값으로 남기면 A창고 실사가 B창고 재고까지 지운다 — 델타여야 하는 이유."""
    from shared.inventory_stock import get_stock_batch
    sku = _opt(db)
    _tx(db, sku, 'in', 10, 1, loc=1)        # A창고 10
    _tx(db, sku, 'in', 7, 2, loc=2)         # B창고 7
    _tx(db, sku, 'adjust', -2, 3, loc=1)    # A창고 실사 8 → 차이 -2
    assert get_stock_batch(db, [sku])[sku] == 15, 'A 8 + B 7 = 15'
    assert get_stock_batch(db, [sku], location_id=2)[sku] == 7, 'B창고는 그대로'
