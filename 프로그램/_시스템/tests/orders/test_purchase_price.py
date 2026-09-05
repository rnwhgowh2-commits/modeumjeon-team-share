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
    "lemouton.markets.models_purchase_history",
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
# ② 우선순위 — 실매입가 > (사입가·소싱가 중 **싼 쪽**). 없으면 None(0 채움 금지)
#    2026-08-06 사장님 재확정. 판정은 pricing.cost_basis.resolve_cost_basis 하나.
# ══════════════════════════════════════════════════════════════════════

def _with_purchase(db, monkeypatch, avg, stock=5):
    """그 옵션에 사입 재고가 있고 실측 이동평균이 `avg` 인 상태로 만든다."""
    import shared.inventory_stock as IS
    monkeypatch.setattr(IS, "get_stock_batch",
                        lambda s, skus, loc=None, **kw: {SKU: stock})
    db.query(M.Option).filter_by(canonical_sku=SKU).one().boxhero_avg_purchase_price = avg
    db.commit()


def test_tier1_real_wins_over_everything(db, monkeypatch, fake_breakdown):
    """실매입가(사람이 적은 값)는 싸든 비싸든 무조건 최우선."""
    _with_purchase(db, monkeypatch, 60000)
    PP.upsert(db, line_uid=UID, price=88000)

    got = PP.resolve_purchase_price(db, [UID], rows=[_row()],
                                    matrix_loader=_matrix(50000))[UID]
    assert got == {"price": 88000, "tier": "real", "label": "실매입가"}


def test_cheaper_side_wins_sourcing(db, monkeypatch, fake_breakdown):
    """사입 5,000 · 소싱 4,000 → 4,000(예상). 어느 쪽인지 tier 가 밝힌다."""
    _with_purchase(db, monkeypatch, 5000)
    got = PP.resolve_purchase_price(db, [UID], rows=[_row()],
                                    matrix_loader=_matrix(4000))[UID]
    assert got == {"price": 4000, "tier": "estimate", "label": "최종매입가"}


def test_cheaper_side_wins_stock(db, monkeypatch, fake_breakdown):
    """사입 3,000 · 소싱 4,000 → 3,000(사입가)."""
    _with_purchase(db, monkeypatch, 3000)
    got = PP.resolve_purchase_price(db, [UID], rows=[_row()],
                                    matrix_loader=_matrix(4000))[UID]
    assert got == {"price": 3000, "tier": "stock", "label": "사입가"}


def test_same_rule_as_cost_basis(db, monkeypatch, fake_breakdown):
    """🔴 판정을 두 번 구현하지 않았는지 — 판매가 쪽 단일 원천과 답이 같아야 한다.

    여기가 갈리면 같은 상품 원가가 주문내역과 판매가 화면에서 달라진다(이번 커밋의 사유).
    """
    from lemouton.pricing.cost_basis import resolve_cost_basis
    for avg, sourcing in ((5000, 4000), (3000, 4000), (4000, 4000), (0, 4000)):
        _with_purchase(db, monkeypatch, avg)
        got = PP.resolve_purchase_price(db, [UID], rows=[_row()],
                                        matrix_loader=_matrix(sourcing))[UID]
        want = resolve_cost_basis(sourcing, avg, 5)
        assert got["price"] == want.cost, f"사입 {avg} vs 소싱 {sourcing}"
        assert got["tier"] == ("stock" if want.side == "purchase" else "estimate")


def test_stock_only_when_no_sourcing_price(db, monkeypatch, fake_breakdown):
    """소싱 크롤값이 없으면 사입가로 — 비교 대상이 없는 것이지 「없음」이 아니다."""
    _with_purchase(db, monkeypatch, 60000)
    empty = lambda model_code: {"ok": True, "options": [{"sku": SKU, "sources": []}]}
    got = PP.resolve_purchase_price(db, [UID], rows=[_row()], matrix_loader=empty)[UID]
    assert got == {"price": 60000, "tier": "stock", "label": "사입가"}


def test_tier3_estimate_when_no_real_no_stock(db, monkeypatch, fake_breakdown):
    _no_stock(monkeypatch)
    got = PP.resolve_purchase_price(db, [UID], rows=[_row()],
                                    matrix_loader=_matrix(50000))[UID]
    assert got["tier"] == "estimate" and got["price"] == 50000
    assert got["label"] == "최종매입가"


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


# ══════════════════════════════════════════════════════════════════════
# ⑥ 속도 회귀 감시 — 행이 늘어도 쿼리·매트릭스 조회가 비례해 늘면 안 된다
#    (라이브 실측 3줄 24초의 정체가 「행·모델코드마다 다시 조회」였다)
# ══════════════════════════════════════════════════════════════════════

def _many_lines(db, n):
    """한 모델(AF)에 옵션 n개 + 쿠팡 채널 옵션 n개를 깔고, 주문 행 n줄을 만든다."""
    ps = db.query(ProductSet).filter_by(model_code="AF").one()
    ch = db.query(SetChannel).filter_by(set_id=ps.id, market="coupang").one()
    rows = []
    for i in range(n):
        sku, vid = f"SKU-N-{i:03d}", f"VN{i:03d}"
        db.add(M.Option(canonical_sku=sku, model_code="AF",
                        color_code="블랙", color_display="블랙",
                        size_code=str(200 + i), size_display=str(200 + i)))
        db.add(SetChannelOption(channel_id=ch.id, canonical_sku=sku,
                                market_option_id=vid, status="matched"))
        rows.append(_row(f"coupang|N{i}|{vid}", order_no=f"N{i}"))
        rows[-1]["_pd_market_option_id"] = vid
    db.commit()
    return rows


def test_query_count_does_not_grow_with_rows(db, engine, monkeypatch, fake_breakdown):
    """N+1 회귀 감시 — 3줄이든 40줄이든 쿼리 수·매트릭스 조회 수가 그대로여야 한다."""
    import threading

    from sqlalchemy import event

    _no_stock(monkeypatch)
    rows = _many_lines(db, 40)
    calls = {"matrix": 0}

    def loader(model_code):
        calls["matrix"] += 1
        return {"ok": True, "options": [
            {"sku": f"SKU-N-{i:03d}",
             "sources": [{"source_id": 1, "crawled_price": 50000 + i,
                          "source_product_id": 11}]} for i in range(40)]}

    tid = threading.get_ident()
    box = {"n": 0}

    def _count(*a, **k):
        if threading.get_ident() == tid:
            box["n"] += 1

    def measure(sub):
        db.expire_all()
        box["n"] = 0
        calls["matrix"] = 0
        got = PP.resolve_purchase_price(db, [r["_line_uid"] for r in sub],
                                        rows=sub, matrix_loader=loader)
        assert all(v["price"] is not None for v in got.values()), \
            "감시 시험이 헛돌면 안 된다 — 값이 실제로 나와야 쿼리 수도 뜻이 있다"
        return box["n"], calls["matrix"]

    event.listen(engine, "before_cursor_execute", _count)
    try:
        q3, m3 = measure(rows[:3])
        q40, m40 = measure(rows)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert m3 == m40 == 1, (
        f"옵션 매트릭스를 {m3} → {m40} 번 읽었다 — 모델코드당 1회여야 한다")
    assert q40 <= q3, (
        f"행을 3 → 40 으로 늘렸더니 쿼리가 {q3} → {q40} 로 늘었다 — N+1 이 살아 있다")
    # 절대 상한은 넉넉히 — 진짜 감시선은 위의 「늘지 않는다」다.
    assert q3 <= 25, f"3줄 조회가 쿼리 {q3}개 — IN 절 일괄로 묶여 있어야 한다"


# ══════════════════════════════════════════════════════════════════════
# ⑦ 대용량 더망고 업로드 회귀 감시 (issue #1139)
#    3,902행 업로드가 Cloudflare 524(타임아웃)로 죽었다 — 행마다 커밋·조회하던 것이
#    원격 DB(Supabase) 왕복을 수천 번 만든 것이 정체. 행 수가 늘어도 커밋·쿼리는
#    거의 그대로여야 한다(§⑥ 과 같은 감시 방식, PM.apply 대상).
# ══════════════════════════════════════════════════════════════════════

def _bulk_rows_and_mango(n):
    """서로 다른 주문 n개(각 1줄) + 그대로 매칭되는 더망고 매입 행 n개."""
    rows = [_row(f"coupang|BOX{i}|V{i}", order_no=f"B{i}",
                 name=f"상품{i} 12345", opt=f"옵션{i}") for i in range(n)]
    mangos = [_mango(order_no=f"B{i}", name=f"상품{i} 12345", opt=f"옵션{i}",
                     price=10000 + i) for i in range(n)]
    return rows, mangos


def test_bulk_apply_commits_once_not_per_row(db, engine):
    """N 개 행을 저장해도 커밋은 1번 — 예전엔 upsert+history 가 행마다 2번씩 커밋했다."""
    from sqlalchemy import event

    N = 50
    rows, mangos = _bulk_rows_and_mango(N)
    OS.save(rows, session=db)
    order_rows = OS.load(order_nos=[f"B{i}" for i in range(N)],
                         include_claims=False, session=db)

    commits = {"n": 0}

    def _count(conn):
        commits["n"] += 1

    event.listen(engine, "commit", _count)
    try:
        res = PM.apply(db, _buy_df(mangos), order_rows, filename="bulk.xlsx")
    finally:
        event.remove(engine, "commit", _count)

    assert res["saved"] == N
    assert commits["n"] <= 2, (
        f"{N}건을 저장하는데 커밋이 {commits['n']}번 — 행마다 커밋하면 원격 DB에선 "
        f"N번의 네트워크 왕복이 되어 대량 업로드가 타임아웃 난다(issue #1139)")


def test_bulk_apply_select_count_does_not_grow_with_rows(db, engine):
    """매칭된 행마다 session.get() 이 매번 원격 SELECT 를 날리면 안 된다.

    INSERT/UPDATE 문 자체는 행 수만큼 나오는 게 정상(그건 N+1 이 아니라 그냥 N개
    저장이다) — 여기서 감시하는 건 **SELECT** 문 수다. `get_many` 로 대상 line_uid
    를 한 번에 읽어 `_existing` 맵을 넘기면, 그 뒤 `upsert` 내부의 개별
    `session.get()` 이 아예 안 불려서 SELECT 는 (행 수와 무관하게) 상수여야 한다.
    """
    from sqlalchemy import event

    N = 60
    rows, mangos = _bulk_rows_and_mango(N)
    OS.save(rows, session=db)
    order_rows = OS.load(order_nos=[f"B{i}" for i in range(N)],
                         include_claims=False, session=db)

    selects = {"n": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith("SELECT"):
            selects["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        res = PM.apply(db, _buy_df(mangos), order_rows, filename="bulk.xlsx")
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert res["saved"] == N
    # 상한을 넉넉히 둬도(10) "행마다 1개"였던 옛 동작(N=60)은 확실히 잡는다.
    assert selects["n"] <= 10, (
        f"{N}건 저장에 SELECT 가 {selects['n']}번 — 행마다 session.get() 이 원격 "
        f"조회를 하고 있다(N+1 회귀, issue #1139)")


def test_match_to_lines_scales_subquadratically_and_stays_correct():
    """매칭이 매입행마다 매출행 전체를 다시 훑으면 안 된다.

    O(n²) 이면 행을 10배 늘릴 때 시간은 대략 100배가 돼야 한다 — 20배 미만이면
    order_key 로 인덱싱된 것으로 본다. 절대 시간 상한도 둔다: 1,000행이 몇 초 안에
    끝나야 실사용 규모(3,900+행)도 Cloudflare 100초 벽 안에 든다(issue #1139).
    """
    import time

    def _timed(n):
        rows, mangos = _bulk_rows_and_mango(n)
        t0 = time.perf_counter()
        res = PM.match_to_lines(_buy_df(mangos), rows)
        elapsed = time.perf_counter() - t0
        assert len(res["matched"]) == n, (
            f"{n}행 중 {len(res['matched'])}건만 매칭 — 인덱싱하며 매칭 결과가 바뀌면 안 된다")
        assert not res["unmatched"] and not res["ambiguous"]
        return elapsed

    t_small = _timed(100)
    t_big = _timed(1000)
    ratio = t_big / max(t_small, 1e-6)
    assert t_big < max(t_small * 20, 2.0), (
        f"100행 {t_small:.3f}s → 1000행 {t_big:.3f}s ({ratio:.1f}배) — O(n²) 라면 "
        f"~100배 늘어야 하는데 이 비율이면 order_key 인덱싱이 빠졌을 수 있다")
    assert t_big < 5.0, f"1,000행 매칭에 {t_big:.1f}초 — 3,900+행에서 타임아웃 위험"


def test_target_index_reads_only_asked_ids(db, engine, monkeypatch, fake_breakdown):
    """연동 표를 통째로 읽지 않는다 — 연동이 늘어도 조회 행 수가 안 늘어야 한다.

    예전엔 요청마다 SetChannel⋈SetChannelOption 전수를 파이썬 dict 로 쌓았다.
    주문 표 한 판이 이 색인을 세 군데(가격전후·이행분류·매입가)에서 각각 만들었다.
    """
    from lemouton.orders import price_diff as PD

    _many_lines(db, 40)
    by_option, by_product = PD._target_index(db, option_ids=["VN000", "VN001"],
                                             product_ids=[])
    got = {k[1] for k in by_option}
    assert got == {"VN000", "VN001"}, f"물어본 번호 밖까지 읽었다: {sorted(got)}"
    # 전수 조회(옛 방식)와 답이 같은지 — 좁혔다고 다른 답이 나오면 안 된다
    full_option, _ = PD._target_index(db)
    for k in by_option:
        assert by_option[k] == full_option[k]
