# -*- coding: utf-8 -*-
"""실매입가 1단계 — 저장소 · 우선순위 3단계 · 수기 저장 · 더망고 엑셀 매칭.

설계서 `docs/superpowers/specs/2026-08-06-실매입가-주문통합-design.md` §3~§5.

in-memory SQLite(StaticPool) 하나를 라우트와 테스트가 함께 본다.
소싱 매트릭스·breakdown 은 주입/패치라 네트워크·라이브 소싱처 접속이 없다.
"""
import io
import json
import pathlib

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from shared.db import Base

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.sets.models", "lemouton.multitenancy.models",
    "lemouton.audit.models", "lemouton.mapping.models",
    "lemouton.markets.models_orders", "lemouton.markets.models_purchase",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M
import webapp.routes.orders as om
from lemouton.markets import order_store as OS
from lemouton.markets import purchase_mango as PM
from lemouton.markets import purchase_price as PP
from lemouton.markets.models_purchase import OrderLinePurchase
from lemouton.sets.models import ProductSet, SetChannel, SetChannelOption

SKU = "SKU-PP-0001"
UID = "coupang|BOX1|V777"
UID2 = "coupang|BOX2|V777"


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    s = Session(engine)
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    s.add(M.Option(canonical_sku=SKU, model_code="AF",
                   color_code="블랙", color_display="블랙",
                   size_code="260", size_display="260"))
    ps = ProductSet(model_code="AF", name="테스트 모음전")
    s.add(ps)
    s.flush()
    ch = SetChannel(set_id=ps.id, market="coupang", account_key="본계",
                    market_product_id="P100")
    s.add(ch)
    s.flush()
    s.add(SetChannelOption(channel_id=ch.id, canonical_sku=SKU,
                           market_option_id="V777", status="matched"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(engine, monkeypatch):
    """라우트가 같은 in-memory DB 를 보게 한다."""
    from flask import Flask
    monkeypatch.setattr(om, "SessionLocal", sessionmaker(bind=engine))
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


def _row(uid=UID, *, order_no="O1", name="운동화 12345", opt="블랙 / 260"):
    """주문 행 — 쿠팡 vendorItemId 로 우리 옵션(SKU)에 붙는다."""
    return {"_line_uid": uid, "판매처": "쿠팡", "오픈마켓주문번호": order_no,
            "상품명": name, "옵션": opt, "단가": 139000, "배송비": 0,
            "수량": 1, "_pd_market_option_id": "V777",
            "주문일": "2026-08-01 10:00:00"}


def _matrix(price):
    def loader(model_code):
        return {"ok": True, "options": [
            {"sku": SKU, "sources": [{"source_id": 1, "crawled_price": price,
                                      "source_product_id": 11}]}]}
    return loader


@pytest.fixture
def fake_breakdown(monkeypatch):
    """compute_breakdown = 크롤가 그대로 최종매입가(3순위 값)."""
    import webapp.routes.api_benefits as AB
    monkeypatch.setattr(AB, "_build_breakdown_cache", lambda s, items, sp_rows=None: {"_f": 1})
    monkeypatch.setattr(AB, "compute_breakdown",
                        lambda s, *, sku, source_id, sale_price, _cache=None, **kw:
                        {"final_price": int(sale_price)})


def _no_stock(monkeypatch):
    """2순위(사입) 없음 — 사입 재고 0."""
    import shared.inventory_stock as IS
    monkeypatch.setattr(IS, "get_stock_batch", lambda s, skus, loc=None, **kw: {})


# ══════════════════════════════════════════════════════════════════════
# ① upsert / delete — 0 이면 지운다(= 「입력 안 함」)
# ══════════════════════════════════════════════════════════════════════

def test_upsert_saves_and_updates(db):
    PP.upsert(db, line_uid=UID, price=88000, memo="첫 입력")
    got = PP.get_many(db, [UID])[UID]
    assert got.purchase_price == 88000
    assert got.source == PP.SOURCE_MANUAL and got.memo == "첫 입력"

    PP.upsert(db, line_uid=UID, price="91,000")      # 쉼표 문자열도 받는다
    assert PP.get_many(db, [UID])[UID].purchase_price == 91000
    # 메모를 안 주면 기존 메모를 지우지 않는다
    assert PP.get_many(db, [UID])[UID].memo == "첫 입력"


@pytest.mark.parametrize("price", [0, "0", None, "", "abc"])
def test_zero_or_blank_deletes_the_row(db, price):
    PP.upsert(db, line_uid=UID, price=70000)
    assert PP.upsert(db, line_uid=UID, price=price) is None
    assert PP.get_many(db, [UID]) == {}
    # 0 으로 채운 행이 남으면 「0원에 샀다」는 거짓이 된다
    assert db.query(OrderLinePurchase).count() == 0


def test_delete_returns_false_when_absent(db):
    assert PP.delete(db, UID) is False
    assert PP.upsert(db, line_uid=UID, price=1000) is not None
    assert PP.delete(db, UID) is True


def test_upsert_rejects_blank_uid_and_unknown_source(db):
    with pytest.raises(ValueError):
        PP.upsert(db, line_uid="", price=1000)
    with pytest.raises(ValueError):
        PP.upsert(db, line_uid=UID, price=1000, source="excel")


# ══════════════════════════════════════════════════════════════════════
# ② 우선순위 3단계 — 실 > 사입 > 예상. 없으면 None(0 채움 금지)
# ══════════════════════════════════════════════════════════════════════

def test_tier1_real_wins_over_everything(db, monkeypatch, fake_breakdown):
    import shared.inventory_stock as IS
    monkeypatch.setattr(IS, "get_stock_batch", lambda s, skus, loc=None, **kw: {SKU: 5})
    db.query(M.Option).filter_by(canonical_sku=SKU).one().boxhero_avg_purchase_price = 60000
    db.commit()
    PP.upsert(db, line_uid=UID, price=88000)

    got = PP.resolve_purchase_price(db, [UID], rows=[_row()],
                                    matrix_loader=_matrix(50000))[UID]
    assert got == {"price": 88000, "tier": "real", "label": "실매입가"}


def test_tier2_stock_when_no_real(db, monkeypatch, fake_breakdown):
    import shared.inventory_stock as IS
    monkeypatch.setattr(IS, "get_stock_batch", lambda s, skus, loc=None, **kw: {SKU: 5})
    db.query(M.Option).filter_by(canonical_sku=SKU).one().boxhero_avg_purchase_price = 60000
    db.commit()

    got = PP.resolve_purchase_price(db, [UID], rows=[_row()],
                                    matrix_loader=_matrix(50000))[UID]
    assert got["tier"] == "stock" and got["price"] == 60000
    assert got["label"] == "사입가"


def test_tier3_estimate_when_no_real_no_stock(db, monkeypatch, fake_breakdown):
    _no_stock(monkeypatch)
    got = PP.resolve_purchase_price(db, [UID], rows=[_row()],
                                    matrix_loader=_matrix(50000))[UID]
    assert got["tier"] == "estimate" and got["price"] == 50000
    assert got["label"] == "순마진 예상가"


def test_no_value_stays_none_not_zero(db, monkeypatch, fake_breakdown):
    """소싱 크롤값이 없으면 「확인 불가」 — 0 으로 채우지 않는다."""
    _no_stock(monkeypatch)
    empty = lambda model_code: {"ok": True, "options": [{"sku": SKU, "sources": []}]}
    got = PP.resolve_purchase_price(db, [UID], rows=[_row()], matrix_loader=empty)[UID]
    assert got == {"price": None, "tier": None, "label": "확인 불가"}


def test_unlinked_row_is_unknown(db, monkeypatch, fake_breakdown):
    """우리 옵션에 못 붙는 주문(남의 상품)은 2·3순위가 없다 — 지어내지 않는다."""
    _no_stock(monkeypatch)
    row = dict(_row(), _pd_market_option_id="NOPE")
    got = PP.resolve_purchase_price(db, [UID], rows=[row],
                                    matrix_loader=_matrix(50000))[UID]
    assert got["price"] is None and got["tier"] is None


def test_resolve_reads_rows_from_store_when_not_given(db, monkeypatch, fake_breakdown):
    """rows 를 안 주면 적재분에서 읽는다(화면 없이도 같은 답)."""
    _no_stock(monkeypatch)
    OS.save([_row()], session=db)
    got = PP.resolve_purchase_price(db, [UID], matrix_loader=_matrix(50000))[UID]
    assert got["tier"] == "estimate" and got["price"] == 50000


# ══════════════════════════════════════════════════════════════════════
# ③ 수기 저장 엔드포인트 — 200 / 400
# ══════════════════════════════════════════════════════════════════════

def test_manual_save_endpoint_200(client, db):
    r = client.post("/orders/api/purchase-price",
                    json={"line_uid": UID, "price": 88000, "memo": "손입력"})
    assert r.status_code == 200
    j = json.loads(r.data)
    assert j["ok"] is True and j["saved"] is True
    assert j["price"] == 88000 and j["tier"] == "real"
    assert PP.get_many(db, [UID])[UID].purchase_price == 88000


def test_manual_save_blank_deletes(client, db):
    PP.upsert(db, line_uid=UID, price=88000)
    r = client.post("/orders/api/purchase-price", json={"line_uid": UID, "price": ""})
    assert r.status_code == 200
    j = json.loads(r.data)
    assert j["ok"] is True and j["deleted"] is True and j["price"] is None
    db.expire_all()
    assert PP.get_many(db, [UID]) == {}


@pytest.mark.parametrize("payload", [
    {"price": 1000},                       # line_uid 없음
    {"line_uid": "", "price": 1000},
    {"line_uid": UID, "price": "여덟만원"},   # 숫자가 아니다 → 조용히 삭제되면 안 된다
])
def test_manual_save_endpoint_400(client, payload):
    r = client.post("/orders/api/purchase-price", json=payload)
    assert r.status_code == 400
    assert json.loads(r.data)["ok"] is False


def test_resolve_endpoint(client, db, monkeypatch, fake_breakdown):
    _no_stock(monkeypatch)
    PP.upsert(db, line_uid=UID, price=77000)
    r = client.post("/orders/api/purchase-price/resolve", json={"rows": [_row()]})
    assert r.status_code == 200
    j = json.loads(r.data)
    assert j["prices"][UID] == {"price": 77000, "tier": "real", "label": "실매입가"}


# ══════════════════════════════════════════════════════════════════════
# ④ 더망고 엑셀 업로드 — 매칭 저장 + 못 찾음 목록
# ══════════════════════════════════════════════════════════════════════

_MANGO_COLS = ["마켓주문일자", "마켓명", "마켓주문번호", "수령인명",
               "마켓상품명", "옵션1", "구매가격"]


def _buy_df(recs):
    return pd.DataFrame(recs, columns=_MANGO_COLS)


def _buy_xlsx(recs) -> bytes:
    bio = io.BytesIO()
    _buy_df(recs).to_excel(bio, index=False)
    return bio.getvalue()


def _mango(order_no="O1", *, name="운동화 12345", opt="블랙 / 260", price=88000,
           market="쿠팡", who="홍길동"):
    return {"마켓주문일자": "2026-08-01", "마켓명": market, "마켓주문번호": order_no,
            "수령인명": who, "마켓상품명": name, "옵션1": opt, "구매가격": price}


def test_mango_match_saves_and_reports_unmatched(db):
    OS.save([_row()], session=db)
    rows = OS.load(order_nos=["O1", "없는주문"], include_claims=False, session=db)
    res = PM.apply(db, _buy_df([_mango(), _mango(order_no="없는주문")]), rows,
                   filename="mango.xlsx")

    assert res["matched"] == 1 and res["saved"] == 1
    assert PP.get_many(db, [UID])[UID].purchase_price == 88000
    assert PP.get_many(db, [UID])[UID].source == PP.SOURCE_MANGO
    assert PP.get_many(db, [UID])[UID].mango_ref.startswith("mango.xlsx#")
    # 🔴 못 붙은 줄을 버리지 않는다
    assert len(res["unmatched"]) == 1
    assert res["unmatched"][0]["마켓주문번호"] == "없는주문"
    assert res["unmatched"][0]["사유"]


def test_mango_zero_price_is_not_saved(db):
    """센티널(999999999.99)은 파서가 0 으로 바꾼다 — 0 은 「입력 안 함」이라 저장 금지."""
    OS.save([_row()], session=db)
    rows = OS.load(order_nos=["O1"], include_claims=False, session=db)
    res = PM.apply(db, _buy_df([_mango(price=0)]), rows)
    assert res["matched"] == 1 and res["saved"] == 0
    assert len(res["skipped_zero"]) == 1
    assert PP.get_many(db, [UID]) == {}


def test_mango_ambiguous_is_not_saved(db):
    """한 주문번호에 라인이 둘인데 상품코드로도 못 좁히면 아무 데도 안 적는다."""
    OS.save([_row(UID, name="운동화"), _row(UID2, name="운동화", opt="블루 / 270")],
            session=db)
    rows = OS.load(order_nos=["O1"], include_claims=False, session=db)
    res = PM.apply(db, _buy_df([_mango(name="운동화", opt="빨강 / 280")]), rows)
    assert res["saved"] == 0 and res["matched"] == 0
    assert len(res["ambiguous"]) == 1
    assert res["ambiguous"][0]["후보"] and len(res["ambiguous"][0]["후보"]) == 2
    assert db.query(OrderLinePurchase).count() == 0


def test_mango_smartstore_bracket_order_no(db):
    """스마트스토어 'A(B)' 는 A·B 둘 다 후보 — matcher.order_match_keys 규칙 그대로."""
    row = dict(_row("smartstore|PO9"), 판매처="스마트스토어", 오픈마켓주문번호="222")
    OS.save([row], session=db)
    assert PM.order_keys_from_buy(
        _buy_df([_mango(order_no="111(222)", market="스마트스토어")])) == ["111", "222"]
    rows = OS.load(order_nos=["111", "222"], include_claims=False, session=db)
    res = PM.apply(db, _buy_df([_mango(order_no="111(222)", market="스마트스토어")]), rows)
    assert res["saved"] == 1
    assert PP.get_many(db, ["smartstore|PO9"])["smartstore|PO9"].purchase_price == 88000


def test_mango_upload_endpoint(client, db):
    OS.save([_row()], session=db)
    data = {"file": (io.BytesIO(_buy_xlsx([_mango(), _mango(order_no="없는주문")])),
                     "mango.xlsx")}
    r = client.post("/orders/api/purchase-price/upload-mango", data=data,
                    content_type="multipart/form-data")
    assert r.status_code == 200
    j = json.loads(r.data)
    assert j["ok"] is True and j["parsed"] == 2
    assert j["matched"] == 1 and j["saved"] == 1
    assert len(j["unmatched"]) == 1


def test_mango_upload_endpoint_rejects_bad_file(client):
    data = {"file": (io.BytesIO(b"not an excel"), "x.xlsx")}
    r = client.post("/orders/api/purchase-price/upload-mango", data=data,
                    content_type="multipart/form-data")
    assert r.status_code in (400, 422)
    assert json.loads(r.data)["ok"] is False


# ══════════════════════════════════════════════════════════════════════
# ⑤ 🔴 핵심 안전장치 — 주문을 다시 수집해도 매입가가 안 지워진다
# ══════════════════════════════════════════════════════════════════════

def test_reingest_does_not_wipe_purchase_price(db):
    """`order_store.save` 는 `market_order_lines` 만 건드린다 — 이 표는 안 본다.

    설계서 §3.2 가 B안(주문 줄 JSON 안에 끼워넣기)을 기각한 이유가 바로 이것이다:
    재수집이 `row` JSON 을 통째 교체하므로 사람이 적은 값이 조용히 증발한다.
    """
    OS.save([_row()], session=db)
    PP.upsert(db, line_uid=UID, price=88000, memo="사장님 입력")

    # 같은 라인을 다시 수집 — 상품명·단가·상태가 전부 바뀐 채로 들어온다
    OS.save([dict(_row(), 상품명="운동화(이름 바뀜) 12345", 단가=149000,
                  주문상태="배송완료")], session=db)
    db.expire_all()

    got = PP.get_many(db, [UID])[UID]
    assert got.purchase_price == 88000 and got.memo == "사장님 입력"
    # 주문 쪽은 실제로 갱신됐는지도 확인(테스트가 헛돌지 않게)
    stored = OS.load(order_nos=["O1"], include_claims=False, session=db)
    assert stored and stored[0]["상품명"] == "운동화(이름 바뀜) 12345"
