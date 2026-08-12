# -*- coding: utf-8 -*-
"""조정(adjust)은 **차이값**이다 — 사장님 확정(2026-08-13).

🔴 왜 차이값인가 — **절대값이면 위치별 재고 합이 전체와 안 맞는다.**

절대값 방식에서는 전체를 셀 때 조정을 「그 시점 재고」로 덮는데,
위치별로 셀 때는 「그 위치의 실사」라는 뜻이 없어 조정을 그냥 더한다.
그래서 창고A 입고 10 · 조정 5 인 상품이
    전체 재고    = 5
    창고A 재고   = 15
로 갈린다. 창고별 합(15)과 전체(5)가 다르면 **없는 재고를 팔게 된다.**

차이값이면 조정도 그냥 더하는 값이라 전체·위치별이 같은 규칙으로 계산돼
자동으로 맞는다. 그리고 SUM 한 번으로 셀 수 있어 특수 처리도 필요 없다.

⚠️ 2026-08-13 하루에 규약이 세 번 뒤집혔고 매번 **한두 군데만** 고쳐서 그랬다.
   이 파일은 「전부 같은 뜻인가」를 한 자리에서 못 박는다.
"""
from __future__ import annotations

import pytest

from shared.inventory_stock import fold_tx_rows


# ── 규칙 자체 ────────────────────────────────────────────────────────────────
def test_조정은_차이값으로_더한다():
    """입고2·출고1(=1) 뒤 조정 +4 → 5. 실사한 수가 그대로 나온다."""
    assert fold_tx_rows([("in", 2), ("out", 1), ("adjust", 4)]) == 5


def test_조정이_여러_번이면_모두_더한다():
    """절대값이면 마지막 것만 남는다 — 그러면 중간 실사가 사라진다."""
    assert fold_tx_rows([("in", 10), ("adjust", -3), ("adjust", 2)]) == 9


def test_조정만_있으면_그_값이다():
    assert fold_tx_rows([("adjust", 7)]) == 7


# ── 위치별 합 = 전체 (이 규약을 택한 이유) ───────────────────────────────────
@pytest.fixture()
def db():
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _seed(s, sku, loc_a, loc_b):
    from lemouton.inventory.models import InventoryTx
    s.query(InventoryTx).filter_by(option_canonical_sku=sku).delete()
    for tx_type, qty, loc in (("in", 10, loc_a), ("adjust", -5, loc_a),
                              ("in", 3, loc_b)):
        s.add(InventoryTx(tx_type=tx_type, qty=qty, option_canonical_sku=sku,
                          location_id=loc, status="completed"))
    s.flush()


def test_위치별_합이_전체와_같다(db):
    """🔴 이게 절대값을 안 쓰는 이유다. 창고A 10 − 5 = 5, 창고B 3 → 전체 8."""
    from lemouton.inventory.models import InventoryLocation
    from shared.inventory_stock import get_stock_batch, get_stock_by_location_batch

    sku = "SKU-ADJLOC"
    locs = []
    for nm in ("시험창고A", "시험창고B"):
        lo = db.query(InventoryLocation).filter_by(name=nm).first()
        if not lo:
            lo = InventoryLocation(name=nm)
            db.add(lo)
            db.flush()
        locs.append(lo.id)
    _seed(db, sku, *locs)

    total = get_stock_batch(db, [sku]).get(sku, 0)
    by_loc = get_stock_by_location_batch(db, [sku]).get(sku, {})

    assert total == 8, f"전체 재고가 8 이 아니다: {total}"
    assert sum(by_loc.values()) == total, \
        f"창고별 합({sum(by_loc.values())}) 과 전체({total}) 가 다르다 — {by_loc}"


# ── 적는 쪽 두 창구가 같은 뜻인가 ────────────────────────────────────────────
def test_적는_쪽_두_창구가_같은_뜻이다():
    """한쪽만 고치면 같은 표의 행이 두 가지 뜻을 갖는다 — 오늘 세 번 그랬다."""
    import inspect
    from lemouton.inventory import inbound
    from webapp.routes import mobile

    desk = inspect.getsource(inbound.create_adjustment).replace(" ", "")
    assert "qty=delta" in desk, "데스크탑 조정이 차이값을 안 남긴다"

    mob = (inspect.getsource(mobile)
           .split("else:  # adjust")[1].split("tx = InventoryTx")[0].replace(" ", ""))
    assert "tx_qty=int(qty)-current" in mob or "tx_qty=delta" in mob, \
        "모바일 조정이 차이값을 안 남긴다"
