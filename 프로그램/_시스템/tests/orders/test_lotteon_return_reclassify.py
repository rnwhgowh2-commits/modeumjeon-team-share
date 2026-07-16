# -*- coding: utf-8 -*-
"""롯데온 회수/반품(209 경로) 재분류 — 옛 주문이 회수지시일로 '오늘 신규주문'에 새는 버그 방지.

라이브 실측(2026-07-16): 209(SellerDeliveryOrdersSearch)는 회수지시 건도 돌려주는데
그 행 odCmptDttm='회수지시 생성일시'라, 07-14 주문이 주문일=07-16(오늘)으로 오염돼
new_order_rows(오늘 신규주문)에 잘못 섞였다. 주문번호 앞 8자리(실주문일)로 복원 + change 재분류.
"""
import datetime as dt
from lemouton.markets import order_export as oe

KST = dt.timezone(dt.timedelta(hours=9))


def test_odno_date_parses_lotteon_prefix():
    assert oe._lotteon_odno_date("2026071416337230") == "2026-07-14"
    assert oe._lotteon_odno_date("2026070313164904") == "2026-07-03"
    assert oe._lotteon_odno_date("") is None
    assert oe._lotteon_odno_date("abc") is None
    assert oe._lotteon_odno_date("2026139999999999") is None   # 13월 → 무효


def test_reclassify_restores_orderdate_dedups_and_retags():
    """원출고행(07-14)+회수지시행(07-16) 중복 → 실주문일 복원·change·1건 병합."""
    rows = [
        {"오픈마켓주문번호": "2026071416337230", "주문일": "2026-07-14 07:31:41",
         "상품명": "백팩", "옵션": "BLACK", "주문상태원본": "23",
         "_shipkey": ("lotteon", "x1"), "_kind": "order", "수령자": "홍길동"},
        {"오픈마켓주문번호": "2026071416337230", "주문일": "2026-07-16 09:33:32",
         "상품명": "백팩", "옵션": "BLACK", "주문상태원본": "23",
         "_shipkey": ("lotteon", "x2"), "_kind": "order", "수령자": "홍길동"},
        # 정상 주문행(건드리면 안 됨)
        {"오픈마켓주문번호": "2026071617059997", "주문일": "2026-07-16 20:59:55",
         "상품명": "운동화", "옵션": "260", "주문상태원본": "12",
         "_shipkey": ("lotteon", "y"), "_kind": "order"},
    ]
    out = oe._reclassify_lotteon_returns(rows)

    normal = [r for r in out if r["오픈마켓주문번호"] == "2026071617059997"]
    assert len(normal) == 1 and normal[0]["_kind"] == "order"
    assert normal[0]["주문일"] == "2026-07-16 20:59:55"      # 정상행 주문일 불변

    ret = [r for r in out if r["오픈마켓주문번호"] == "2026071416337230"]
    assert len(ret) == 1                                     # 원행+회수행 → 1건 병합
    assert ret[0]["주문일"] == "2026-07-14"                  # 실주문일 복원
    assert ret[0]["_kind"] == "change"                       # 반품 이벤트로 재분류
    assert str(ret[0]["_change_date"]).startswith("2026-07-16")   # 변경일=회수 시각(최신)
    assert ret[0]["수령자"] == "홍길동"                       # 구매자정보 보존


def test_reclassify_leaves_claimrows_and_blank_shipkey_untouched():
    """이미 change(클레임행)·비209행은 건드리지 않는다."""
    rows = [
        {"오픈마켓주문번호": "Z", "주문일": "2026-07-15", "주문상태원본": "21",
         "_kind": "change", "_change_date": "2026-07-15"},   # _shipkey 없음
    ]
    out = oe._reclassify_lotteon_returns(rows)
    assert len(out) == 1 and out[0]["_kind"] == "change"


def test_return_excluded_from_today_new_order_rows(monkeypatch):
    """복원된 회수건(실주문일 07-14)이 오늘(07-16) 신규주문에서 빠지는지 (end-to-end)."""
    combined = [
        {"오픈마켓주문번호": "2026071416337230", "주문일": "2026-07-14",
         "주문상태": "회수지시", "_kind": "change", "_change_date": "2026-07-16 09:33"},
        {"오픈마켓주문번호": "2026071617059997", "주문일": "2026-07-16 20:59",
         "주문상태": "상품준비", "_kind": "order"},
    ]
    monkeypatch.setattr(oe, "combined_order_rows",
                        lambda markets, **kw: list(combined))
    since = dt.datetime(2026, 7, 16, tzinfo=KST)
    until = dt.datetime(2026, 7, 16, 23, 59, tzinfo=KST)
    out = oe.new_order_rows(["lotteon"], since=since, until=until)
    assert {r["오픈마켓주문번호"] for r in out} == {"2026071617059997"}
