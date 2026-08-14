# -*- coding: utf-8 -*-
"""11번가 판매자할인 회수 스윕 (2026-08-13 라이브 실측 기반).

매출 = 정가 + 배송비 − **판매자부담** 할인 인데, 11번가는 배송중·배송완료·구매확정
목록조회가 `sellerDscPrc` 를 아예 안 준다(실측 150/157행). 그 행들은 매출이 옛 기준
(실결제+배송비)에 머무는데, 실결제엔 11번가가 부담한 할인까지 빠져 있어 매출이 과소다.

회수는 단건조회(eleven11.110)로만 된다 — 라이브 4건 실증: 배송완료·구매확정 모두
`sellerDscPrc`·`tmallDscPrc` 가 왔고 63,100 − 3,150(마켓) = 59,950 으로 저장분과 맞았다.

🔴 이 시험이 지키는 것 — 「0원」과 「모름」을 가르는 것. 마켓이 값을 안 주는데 0 을 써 버리면
   그 차액이 전부 마켓 부담이라고 단정하는 셈이라, 반대 방향으로 틀린다.
"""
from __future__ import annotations

import datetime as _dt

from lemouton.markets import order_ingest as OI

KST = _dt.timezone(_dt.timedelta(hours=9))


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import lemouton.markets.models_orders  # noqa: F401
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"]])
    return sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()


def _line(order_no, seq="1", *, status="배송완료", 단가=63100, 수량=1,
           배송비=3000, 실결제=59950, **over):
    """라이브 실측 형태의 저장분 라인.

    ★저장분은 **반드시 `_finalize_rows` 를 통과한 상태**다(적재 경로가 그렇게 만든다).
      그 단계를 빼고 시험을 짜면 `_매출기준출처` 같은 파생 칸이 아예 없어, 「회수 실패 시
      옛 값이 유지되는가」를 물을 수가 없다 — 실제와 다른 자료로 묻는 시험이 된다.
    """
    from lemouton.markets.models_orders import MarketOrderLine
    from lemouton.markets.order_export import _finalize_rows
    row = {"오픈마켓주문번호": order_no, "판매처": "11번가", "주문상태": status,
           "상품명": "테스트 상품", "단가": 단가, "수량": 수량, "옵션추가금": 0,
           "배송비": 배송비, "실결제금액": 실결제,
           "_send_ids": {"ord_prd_seq": seq}}
    row.update(over)
    _finalize_rows([row])
    d = (_dt.datetime.now(KST) - _dt.timedelta(days=3)).strftime("%Y-%m-%d")
    return MarketOrderLine(line_uid=f"eleven11|{order_no}|{seq}", market="eleven11",
                           order_no=order_no, order_date=d, status=status, row=row)


def _fake_rows(mapping):
    """order_nos=[no] 로 불리면 그 주문의 라인들을 돌려주는 가짜 조회.

    mapping: {주문번호: [(seq, 셀러할인, 마켓할인), ...]}
    """
    def _f(since, until, *, client=None, include_settlement=True, order_nos=None, **kw):
        out = []
        for no in (order_nos or []):
            for seq, sdc, mdc in mapping.get(no, []):
                out.append({"오픈마켓주문번호": no, "_send_ids": {"ord_prd_seq": seq},
                            "_dc_seller": sdc, "_dc_market": mdc})
        return out
    return _f


def _patch(monkeypatch, mapping):
    from lemouton.markets import order_export as OE
    monkeypatch.setattr(OE, "eleven11_order_rows", _fake_rows(mapping))
    monkeypatch.setattr(OE, "_active_accounts", lambda m: [("E11_1", "브랜드위시")])
    monkeypatch.setattr(OE, "_account_client", lambda *a, **k: object())


def test_회수하면_매출이_정가_빼기_판매자할인이_된다(monkeypatch):
    """마켓이 실값을 주면 그대로 쓰고, 매출 기준이 즉시 다시 만들어진다."""
    s = _sess()
    s.add(_line("E1"))
    s.commit()
    # 라이브 실측 그 주문 — 판매자 0 · 11번가 3,150
    _patch(monkeypatch, {"E1": [("1", "0", "3150")]})
    st = OI.refresh_eleven11_seller_dc(session=s)
    assert st["targets"] == 1 and st["filled"] == 1, st
    from lemouton.markets.models_orders import MarketOrderLine
    row = s.get(MarketOrderLine, "eleven11|E1|1").row
    assert row["_dc_seller"] == "0"
    assert row["_매출기준출처"] == "gross_minus_seller_dc", row.get("_매출기준출처")
    # 정가 63,100 + 배송비 3,000 − 판매자 0 = 66,100 (예전엔 59,950+3,000=62,950)
    assert row["_매출기준액"] == 66100, row["_매출기준액"]


def test_마켓도_할인을_안_주면_0으로_안_친다(monkeypatch):
    """🔴 「0원」과 「모름」은 다르다 — 빈 값이 오면 아무것도 쓰지 않는다."""
    s = _sess()
    s.add(_line("E2"))
    s.commit()
    _patch(monkeypatch, {"E2": [("1", "", "")]})     # 단건조회도 할인을 안 줌
    st = OI.refresh_eleven11_seller_dc(session=s)
    assert st["filled"] == 0 and st["no_value"] == 1, st
    from lemouton.markets.models_orders import MarketOrderLine
    row = s.get(MarketOrderLine, "eleven11|E2|1").row
    assert "_dc_seller" not in row or not str(row["_dc_seller"]).strip()
    assert row["_매출기준출처"] == "paid_seller_dc_unknown", row.get("_매출기준출처")
    assert row[OI._DCFILL_STAMP], "시도 표식이 안 찍혔다 — 굶김 방지가 안 돈다"


def test_다품_주문에_할인이_브로드캐스트되지_않는다(monkeypatch):
    """🔴 조인은 (주문번호, 순번) 라인 단위. 주문번호만으로 맞추면 다른 벌에 남의 할인이 붙는다."""
    s = _sess()
    s.add(_line("E3", "1", 단가=50000, 실결제=45000))
    s.add(_line("E3", "2", 단가=20000, 실결제=20000))
    s.commit()
    _patch(monkeypatch, {"E3": [("1", "5000", "0"), ("2", "0", "0")]})
    OI.refresh_eleven11_seller_dc(session=s)
    from lemouton.markets.models_orders import MarketOrderLine
    r1 = s.get(MarketOrderLine, "eleven11|E3|1").row
    r2 = s.get(MarketOrderLine, "eleven11|E3|2").row
    assert r1["_dc_seller"] == "5000" and r2["_dc_seller"] == "0"
    assert r1["_매출기준액"] == 50000 + 3000 - 5000, r1["_매출기준액"]
    assert r2["_매출기준액"] == 20000 + 3000 - 0, r2["_매출기준액"]


def test_대상_고르기_제외_규칙(monkeypatch):
    """이미 받은 행·클레임 행·배송 전 상태·단가 빈 행은 부르지 않는다."""
    s = _sess()
    s.add(_line("HAVE", **{"_dc_seller": "0"}))          # 이미 받아 둠
    s.add(_line("CLAIM", **{"_kind": "change"}))          # 클레임 행
    s.add(_line("PREP", status="배송준비중"))              # 목록이 이미 할인을 준다
    s.add(_line("BLANK", 단가="", 수량=""))                # 단가 없음 → 회수해도 매출 안 바뀜
    s.add(_line("OK"))                                    # 이것만 대상
    s.commit()
    seen = {}

    def _f(since, until, *, client=None, include_settlement=True, order_nos=None, **kw):
        seen.setdefault("nos", []).extend(order_nos or [])
        return [{"오픈마켓주문번호": n, "_send_ids": {"ord_prd_seq": "1"},
                 "_dc_seller": "0", "_dc_market": "0"} for n in (order_nos or [])]

    from lemouton.markets import order_export as OE
    monkeypatch.setattr(OE, "eleven11_order_rows", _f)
    monkeypatch.setattr(OE, "_active_accounts", lambda m: [("E11_1", "브랜드위시")])
    monkeypatch.setattr(OE, "_account_client", lambda *a, **k: object())
    st = OI.refresh_eleven11_seller_dc(session=s)
    assert seen.get("nos") == ["OK"], seen
    assert st["orders"] == 1


def test_최근에_시도했으면_건너뛴다(monkeypatch):
    """굶김 방지 — 못 구하는 주문이 앞자리를 계속 차지하면 뒤 주문은 영영 안 본다."""
    s = _sess()
    just = _dt.datetime.utcnow().isoformat(timespec="seconds")
    s.add(_line("RECENT", **{OI._DCFILL_STAMP: just}))
    s.commit()
    _patch(monkeypatch, {})
    st = OI.refresh_eleven11_seller_dc(session=s, retry_hours=24)
    assert st["targets"] == 0, st
    # 표식이 오래됐으면 다시 잡는다
    from lemouton.markets.models_orders import MarketOrderLine
    o = s.get(MarketOrderLine, "eleven11|RECENT|1")
    old = (_dt.datetime.utcnow() - _dt.timedelta(hours=48)).isoformat(timespec="seconds")
    o.row = {**o.row, OI._DCFILL_STAMP: old}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(o, "row")
    s.commit()
    st2 = OI.refresh_eleven11_seller_dc(session=s, retry_hours=24)
    assert st2["targets"] == 1, st2


def test_못_찾은_주문과_값없음을_따로_센다(monkeypatch):
    """🔴 「마켓에 값이 없다」와 「키가 안 먹었다」는 다른 사실이다.

    합쳐 버리면 회수 0건일 때 원인이 주문인지 자격증명인지 못 가른다.
    """
    s = _sess()
    s.add(_line("GONE"))
    s.commit()
    _patch(monkeypatch, {})                      # 어느 계정에서도 안 나옴
    st = OI.refresh_eleven11_seller_dc(session=s)
    assert st["not_found"] == ["GONE"], st
    assert st["no_value"] == 0 and st["filled"] == 0, st
