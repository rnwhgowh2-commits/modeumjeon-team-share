# -*- coding: utf-8 -*-
"""`_settle_plan_lines()` 가 클레임(반품·교환·취소) 행을 **실제 DB 에서** 담아 오는가.

🔴 왜 이 시험이 필요한가 — 방금 라이브에 배포한 「반품·교환 제외 + 반품비」(PR#1041)가
   **배포된 채로 통째로 안 돌고 있었다.** 라이브 재확인:

     쿠팡 반품완료 234건이 있는데 kpi.returned = 0
     주문 26101843772429(반품완료 확인) → category 여전히 'unconfirmed'

   원인 — `annotate_claims(lines)` 자체는 옳게 짰다(단위시험 17건 통과). 그런데
   `_settle_plan_lines()` 는 **`MarketOrderLine` 한 테이블만** 읽는다. 클레임은
   `order_store.save()` 가 **별도 테이블**(`MarketClaimEvent`)에 넣는다
   (같은 라인이 반품요청→반품완료로 갈 때 주문 테이블에 덮어쓰면 이력이 사라지기
   때문). `annotate_claims` 에 넘기는 `lines` 안에 클레임 행이 **애초에 하나도
   없어서**, 「이어 줄」 대상 자체가 없었다.

🔴 이게 바로 그 사고 부류다 — **가짜 데이터로 만든 단위시험은 통과하는데, 실제
   DB 조회 경로는 그 재료를 아예 안 만든다.** `_line()` 헬퍼로 손수 지은 딕셔너리는
   `_settle_plan_lines()` 가 실제로 뭘 돌려주는지 증명하지 못한다 — 그래서 이
   시험은 **실제 SQLite 세션에 두 테이블을 채우고, `_settle_plan_lines()` 를
   직접 호출**해서 본다.
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import webapp.routes.orders as om
from lemouton.markets import line_uid as L


@pytest.fixture
def session(monkeypatch):
    from shared.db import Base
    import lemouton.markets.models_orders  # noqa: F401  — 테이블 등록

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    Session = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    s = Session()
    # `_settle_plan_lines()` 는 자기가 직접 `SessionLocal()` 을 연다 — 그 자리를
    # 이 인메모리 세션으로 바꿔치기해야, 실제 함수가 실제로 뭘 돌려주는지 본다.
    monkeypatch.setattr(om, "SessionLocal", lambda: s)
    yield s
    s.close()


def _seed(session, *, order_status="배송완료", claim_status="반품완료",
          order_no="O1", amount=100000, ship=None, days_ago=1):
    from lemouton.markets import order_store as OS

    order_date = (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()
    row = {L.FIELD: f"coupang|{order_no}", "판매처": "쿠팡",
           "오픈마켓주문번호": order_no, "주문일": f"{order_date} 10:00:00",
           "주문상태": order_status, "쇼핑몰별칭": "브랜드마켓(쿠팡)",
           "상품명": "테스트상품", "단가": amount, "수량": 1,
           "정산예정금(배송비포함)": amount, "정산예정금액": amount,
           "_settle_source": "real", "정산예정일": "2026-09-01"}
    if ship is not None:
        row["_ship_settle"] = ship
    rows = [row]
    if claim_status:
        rows.append({L.FIELD: f"coupang|{order_no}", "판매처": "쿠팡",
                     "오픈마켓주문번호": order_no, "_kind": "change",
                     "_change_date": dt.date.today().isoformat(),
                     "주문상태": claim_status, "주문상태원본": "X"})
    OS.save(rows, session=session)
    session.flush()


def test_클레임_행이_실제로_담긴다(session):
    """🔴 이게 뚫려 있던 구멍이다 — `MarketClaimEvent` 도 같이 읽어야 한다."""
    _seed(session, claim_status="반품완료")
    lines = om._settle_plan_lines(["coupang"])
    kinds = sorted(str(ln["row"].get("_kind") or "order") for ln in lines)
    assert "change" in kinds, "클레임 행이 lines 안에 없다 — annotate_claims 가 볼 재료가 없다"


def test_반품완료_주문이_실제로_returned로_떨어진다(session):
    """🔴 라이브에서 이게 깨져 있었다 — kpi.returned=0, 카테고리는 여전히 unconfirmed."""
    from lemouton.margin import settle_plan as SP
    from lemouton.margin.settle_plan_rules import load_rules

    _seed(session, order_status="배송완료", claim_status="반품완료", ship=7736)
    lines = om._settle_plan_lines(["coupang"])
    agg = SP.aggregate_payout(lines, load_rules(), unit="week", today=dt.date.today())
    assert agg["kpi"]["returned"] == 100000, "반품완료 주문이 여전히 받을 돈에 섞여 있다"
    assert agg["kpi"]["total_uncollected"] == 7736, "반품비만 남아야 하는데 안 남았다"


def test_반품_없는_주문은_그대로_잡힌다(session):
    """대조군 — 클레임 병합이 멀쩡한 주문까지 건드리면 안 된다."""
    from lemouton.margin import settle_plan as SP
    from lemouton.margin.settle_plan_rules import load_rules

    _seed(session, order_status="배송완료", claim_status=None, order_no="O2")
    lines = om._settle_plan_lines(["coupang"])
    agg = SP.aggregate_payout(lines, load_rules(), unit="week", today=dt.date.today())
    assert agg["kpi"]["returned"] == 0
    assert agg["kpi"]["total_uncollected"] == 100000


def test_마켓을_지정하면_그_마켓_클레임만_온다(session):
    """다른 마켓의 클레임을 섞으면 엉뚱한 주문에 표식이 붙을 수 있다."""
    _seed(session, order_no="O3")
    lines = om._settle_plan_lines(["smartstore"])
    assert lines == [], "쿠팡 데이터만 있는데 스마트스토어로 걸러도 안 나와야 정상"


def test_드릴다운도_실제_DB_에서_같은_답을_준다(session, monkeypatch):
    """🔴 이 저장소가 겪은 「KPI 는 맞는데 목록은 0건」과 같은 사고를 실제 라우트로 재현·차단."""
    from flask import Flask

    _seed(session, order_status="배송완료", claim_status="반품완료", ship=7736)
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=__import__("pathlib").Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    client = app.test_client()
    d = client.get("/orders/api/settle-plan/detail?category=returned&market=coupang").get_json()
    assert d["rows"], "카드는 반품비를 보여 주는데 눌러도 목록이 빈다"
    assert d["rows"][0]["주문번호"] == "O1"
