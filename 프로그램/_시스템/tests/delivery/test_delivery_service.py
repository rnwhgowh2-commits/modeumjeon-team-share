import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
import lemouton.delivery.models as M
from lemouton.delivery import service as svc


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _row(uid, **kw):
    base = dict(mango_uid=uid, market_name="롯데ON", market_order_no="C" + uid,
                ordered_at="2026-07-11", recipient="염수경", product_name="백팩",
                option1="ONESIZE", phone="010", invoice_no="", courier="",
                mango_status="해외현지배송중", market_status="특이사항없음", memo="")
    base.update(kw)
    return base


def test_models_create(db):
    o = M.MangoOrder(mango_uid="12039", recipient="이주연", market_name="쿠팡")
    db.add(o)
    db.commit()
    got = db.query(M.MangoOrder).filter_by(mango_uid="12039").one()
    assert got.recipient == "이주연"
    assert got.delivery_method == "미지정"
    assert got.delivery_method_source == "자동"

    sm = M.MangoStatusMap(status_value="해외현지배송중", meaning="해외배송중",
                          default_method="까대기", is_flow_check_target=False)
    db.add(sm)
    db.commit()
    assert db.query(M.MangoStatusMap).filter_by(status_value="해외현지배송중").one().default_method == "까대기"


def test_seed_default_status_map(db):
    svc.seed_default_status_map(db)
    rows = {r.status_value: r for r in db.query(M.MangoStatusMap).all()}
    assert rows["해외현지배송중"].default_method == "까대기"
    assert rows["국내배송중"].is_flow_check_target is True
    assert rows["배송완료"].is_flow_check_target is True
    assert rows["결제완료"].is_flow_check_target is False
    svc.seed_default_status_map(db)  # idempotent
    assert db.query(M.MangoStatusMap).filter_by(status_value="해외현지배송중").count() == 1


def test_upsert_auto_method_from_map(db):
    svc.seed_default_status_map(db)
    res = svc.upsert_orders(db, [_row("100")])
    assert res["inserted"] == 1
    o = db.query(M.MangoOrder).filter_by(mango_uid="100").one()
    assert o.delivery_method == "까대기"       # 해외현지배송중 -> 까대기
    assert o.delivery_method_source == "자동"


def test_upsert_preserves_manual(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("101")])
    o = db.query(M.MangoOrder).filter_by(mango_uid="101").one()
    o.delivery_method = "직배"
    o.delivery_method_source = "수기"
    first = o.first_uploaded_at
    db.commit()
    svc.upsert_orders(db, [_row("101", mango_status="국내배송중")])  # 재업로드
    o2 = db.query(M.MangoOrder).filter_by(mango_uid="101").one()
    assert o2.delivery_method == "직배"
    assert o2.delivery_method_source == "수기"
    assert o2.first_uploaded_at == first
    assert o2.mango_status == "국내배송중"


def test_upsert_invoice_history_and_duplicate(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("102", invoice_no="AAA")])
    svc.upsert_orders(db, [_row("102", invoice_no="BBB")])  # 다른 송장 재등장
    o = db.query(M.MangoOrder).filter_by(mango_uid="102").one()
    assert o.invoice_no == "BBB"
    assert len(o.invoice_history) == 2
    assert o.is_duplicate_invoice is True


def test_find_duplicate_invoices(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("200", invoice_no="AAA")])
    svc.upsert_orders(db, [_row("200", invoice_no="BBB")])  # 중복
    svc.upsert_orders(db, [_row("201", invoice_no="CCC")])  # 단일 → 정상
    dups = svc.find_duplicate_invoices(db)
    assert {o.mango_uid for o in dups} == {"200"}


def test_find_flow_missing(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("300", mango_status="배송완료",
                                 market_status="송장전송실패", invoice_no="X")])
    svc.upsert_orders(db, [_row("301", mango_status="배송완료",
                                 market_status="송장전송완료", invoice_no="Y")])
    svc.upsert_orders(db, [_row("302", mango_status="결제완료", market_status="특이사항없음")])
    missing = svc.find_flow_missing(db)
    assert {o.mango_uid for o in missing} == {"300"}


def test_apply_bulk_method_skips_manual(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("400"), _row("401")])
    o = db.query(M.MangoOrder).filter_by(mango_uid="401").one()
    o.delivery_method = "직배"
    o.delivery_method_source = "수기"
    db.commit()
    n = svc.apply_bulk_method(db, "까대기")
    assert n == 1
    assert db.query(M.MangoOrder).filter_by(mango_uid="400").one().delivery_method == "까대기"
    assert db.query(M.MangoOrder).filter_by(mango_uid="401").one().delivery_method == "직배"


def test_set_method_manual(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("500")])
    assert svc.set_method_manual(db, "500", "직배") is True
    o = db.query(M.MangoOrder).filter_by(mango_uid="500").one()
    assert o.delivery_method == "직배"
    assert o.delivery_method_source == "수기"
    assert svc.set_method_manual(db, "nonexist", "직배") is False
