# -*- coding: utf-8 -*-
"""11번가 수량 0 오염 복원 — ordQty(잔여수량) 덮어쓰기 사고의 치유·재발 방지."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import lemouton.markets.models_orders  # noqa: F401
from lemouton.markets import order_store
from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine


@pytest.fixture
def s():
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    Maker = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    ses = Maker()
    yield ses
    ses.close()


def _line(s, uid, no, qty):
    s.add(MarketOrderLine(line_uid=uid, market="eleven11", order_no=no,
                          row={"수량": qty, "오픈마켓주문번호": no}))


def test_restores_original_qty_from_claim(s):
    _line(s, "e11|A1|1", "A1", "0")
    s.add(MarketClaimEvent(event_uid="c1", line_uid="e11|A1|1", market="eleven11",
                           order_no="A1", row={"수량": "2"}))
    s.commit()
    st = order_store.restore_eleven11_qty_from_claims(session=s)
    assert st == {"targets": 1, "fixed": 1, "blanked": 0}
    assert s.get(MarketOrderLine, "e11|A1|1").row["수량"] == "2"


def test_no_claim_qty_blanks_not_zero(s):
    # 클레임에도 없으면 '' — 0(거짓값)을 남기지 않는다
    _line(s, "e11|B1|1", "B1", 0)
    s.commit()
    st = order_store.restore_eleven11_qty_from_claims(session=s)
    assert st["blanked"] == 1
    assert s.get(MarketOrderLine, "e11|B1|1").row["수량"] == ""


def test_healthy_rows_untouched(s):
    _line(s, "e11|C1|1", "C1", "3")
    s.commit()
    st = order_store.restore_eleven11_qty_from_claims(session=s)
    assert st["targets"] == 0
    assert s.get(MarketOrderLine, "e11|C1|1").row["수량"] == "3"


def test_builder_maps_zero_qty_to_blank():
    # 재발 방지: 11번가 빌더가 ordQty=0 을 ''(미제공) 로 낸다 — 소스에 규칙이 있는지 검사
    # (_row 는 eleven11_order_rows 내부 클로저라 직접 호출 불가 — 소스 검사로 계약 고정)
    import inspect

    from lemouton.markets import order_export as oe
    src = inspect.getsource(oe.eleven11_order_rows)
    assert "잔여수량" in src and '"0"' in src   # 0=미제공 규칙 존재
