# -*- coding: utf-8 -*-
"""포장 스캔 출고 시험 — 사입 줄만 깎고, 두 번 찍어도 두 번 안 깎는다.

사장님 확정(2026-08-06): 차감은 바코드 찍을 때 · 사입만 · 재고 부족은 경고 후 진행.
"""
import pytest


@pytest.fixture(autouse=True)
def clean():
    from shared.db import Base, SessionLocal, engine
    from lemouton.inventory.models import InventoryTx, InventoryLocation
    from lemouton.markets.models_supply import OrderLineSupply
    from lemouton.sourcing.models import Option
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.query(InventoryTx).filter(
            InventoryTx.option_canonical_sku.like("SKU-SCANTEST%")).delete(
            synchronize_session=False)
        s.query(OrderLineSupply).delete()
        s.query(Option).filter(Option.canonical_sku.like("SKU-SCANTEST%")).delete(
            synchronize_session=False)
        loc = s.query(InventoryLocation).filter_by(name="스캔시험위치").first()
        if not loc:
            loc = InventoryLocation(name="스캔시험위치")
            s.add(loc)
            s.flush()
        s.add(Option(canonical_sku="SKU-SCANTEST", model_code="SCANTEST",
                     color_code="BK", size_code="250"))
        s.commit()
        loc_id = loc.id
    yield loc_id


def _stock(sku="SKU-SCANTEST"):
    from shared.db import SessionLocal
    from shared.inventory_stock import get_stock_batch
    with SessionLocal() as s:
        return int(get_stock_batch(s, [sku]).get(sku, 0))


def _inbound(loc_id, qty):
    from shared.db import SessionLocal
    from lemouton.inventory.models import InventoryTx
    with SessionLocal() as s:
        s.add(InventoryTx(tx_type="in", location_id=loc_id, qty=qty,
                          option_canonical_sku="SKU-SCANTEST", status="completed"))
        s.commit()


def test_무재고_줄은_재고를_안_깎는다(clean):
    from shared.db import SessionLocal
    from lemouton.inventory import order_outbound as oo
    _inbound(clean, 5)
    with SessionLocal() as s:
        r = oo.ship_order_line(s, line_uid="L-드롭", canonical_sku="SKU-SCANTEST",
                               location_id=clean, qty=2)
    assert r["result"] == "no_deduct"
    assert r["deducted_qty"] == 0
    assert _stock() == 5          # 그대로


def test_사입_줄은_재고를_깎는다(clean):
    from shared.db import SessionLocal
    from lemouton.inventory import order_outbound as oo
    from lemouton.markets import supply_mode as sm
    _inbound(clean, 5)
    with SessionLocal() as s:
        sm.set_mode(s, line_uid="L-사입", mode="사입")
        r = oo.ship_order_line(s, line_uid="L-사입", canonical_sku="SKU-SCANTEST",
                               location_id=clean, qty=2)
    assert r["result"] == "deducted"
    assert r["deducted_qty"] == 2
    assert r["stock_after"] == 3
    assert _stock() == 3


def test_두_번_찍어도_두_번_안_깎는다(clean):
    """포장 현장에서 같은 상자를 두 번 찍는 일은 흔하다."""
    from shared.db import SessionLocal
    from lemouton.inventory import order_outbound as oo
    from lemouton.markets import supply_mode as sm
    _inbound(clean, 5)
    with SessionLocal() as s:
        sm.set_mode(s, line_uid="L-사입", mode="사입")
        oo.ship_order_line(s, line_uid="L-사입", canonical_sku="SKU-SCANTEST",
                           location_id=clean, qty=2)
        r2 = oo.ship_order_line(s, line_uid="L-사입", canonical_sku="SKU-SCANTEST",
                                location_id=clean, qty=2)
    assert r2["result"] == "already"
    assert r2["deducted_qty"] == 0
    assert _stock() == 3          # 5 - 2, 한 번만


def test_재고_모자라도_막지_않고_경고한다(clean):
    """사장님 확정 — 막으면 발송을 못 한다. 경고를 남기고 진행한다."""
    from shared.db import SessionLocal
    from lemouton.inventory import order_outbound as oo
    from lemouton.markets import supply_mode as sm
    _inbound(clean, 1)
    with SessionLocal() as s:
        sm.set_mode(s, line_uid="L-부족", mode="사입")
        r = oo.ship_order_line(s, line_uid="L-부족", canonical_sku="SKU-SCANTEST",
                               location_id=clean, qty=3)
    assert r["result"] == "deducted"
    assert r["warning"] and "모자랍니다" in r["warning"]
    assert _stock() == -2         # 장부가 실물과 다르다는 신호로 남는다


def test_같은_주문_여러_줄은_각자_처리된다(clean):
    from shared.db import SessionLocal
    from lemouton.inventory import order_outbound as oo
    from lemouton.markets import supply_mode as sm
    _inbound(clean, 10)
    with SessionLocal() as s:
        sm.set_mode(s, line_uid="ORD-1|1", mode="사입")   # 1번 줄만 사입
        r1 = oo.ship_order_line(s, line_uid="ORD-1|1", canonical_sku="SKU-SCANTEST",
                                location_id=clean, qty=1)
        r2 = oo.ship_order_line(s, line_uid="ORD-1|2", canonical_sku="SKU-SCANTEST",
                                location_id=clean, qty=1)
    assert r1["result"] == "deducted"
    assert r2["result"] == "no_deduct"     # 형제 줄은 기본 무재고 그대로
    assert _stock() == 9


def test_주문목록_조회는_없으면_빈_목록(clean):
    """주문이 없어도 화면이 안 깨진다 — 예외로 죽으면 폰에서 아무것도 못 한다."""
    from shared.db import SessionLocal
    from lemouton.inventory import order_outbound as oo
    with SessionLocal() as s:
        assert oo.pending_lines_for_sku(s, "SKU-SCANTEST") == []
        assert oo.pending_lines_for_sku(s, "") == []
        assert oo.pending_lines_for_sku(s, None) == []


def test_빈_값은_거부된다(clean):
    from shared.db import SessionLocal
    from lemouton.inventory import order_outbound as oo
    with SessionLocal() as s:
        with pytest.raises(ValueError):
            oo.ship_order_line(s, line_uid="", canonical_sku="SKU-SCANTEST",
                               location_id=clean, qty=1)
        with pytest.raises(ValueError):
            oo.ship_order_line(s, line_uid="L-1", canonical_sku="",
                               location_id=clean, qty=1)
        with pytest.raises(ValueError):
            oo.ship_order_line(s, line_uid="L-1", canonical_sku="SKU-SCANTEST",
                               location_id=clean, qty=0)
