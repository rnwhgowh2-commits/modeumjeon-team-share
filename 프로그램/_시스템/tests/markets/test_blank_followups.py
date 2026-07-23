# -*- coding: utf-8 -*-
"""공란·상태 후속 3종 (2026-07-24 실측 기반).

① 롯데온 정산 백필로만 들어온 라인 — 상품명·단가·주문상태가 통째로 빈 187건.
   키 목록이 209 경로 행과 아예 달랐다(파생열 부재) = `_finalize_rows` 미통과.
② 마켓 공통 공란 자가치유 — 「비어 있음」 기준으로 골라 주문번호 단건 조회로 채움.
③ 클레임이 주문상태를 **매 틱 되덮던** 것 — 취소가 철회돼 마켓이 다시 정상으로
   보고해도 다음 틱이 또 '취소완료'로 되돌렸다(11번가 20260707082636494: 주문행
   원본코드 901=수취완료인데 상태만 취소완료, 라이브는 구매확정).
   취소완료 = 정산 0 규칙이라 마진계산기에서 매입 전액이 손실로 잡힌다.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from lemouton.markets import line_uid as L
from lemouton.markets import order_ingest as OI
from lemouton.markets import order_store as OS

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


def _recent():
    return (_dt.datetime.now(KST) - _dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")


def _blank_line(market, order_no, **row_over):
    from lemouton.markets.models_orders import MarketOrderLine
    row = {"오픈마켓주문번호": order_no, "상품명": "", "단가": "", "수량": ""}
    row.update(row_over)
    return MarketOrderLine(line_uid=f"{market}|{order_no}|1", market=market,
                           order_no=order_no, order_date=_recent(),
                           status=row.get("주문상태", ""), row=row)


# ── ② 마켓 공통 공란 자가치유 ────────────────────────────────────────────

def test_롯데온_공란도_단건조회로_채운다(monkeypatch):
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    s.add(_blank_line("lotteon", "LO1"))
    s.add(_blank_line("eleven11", "E1"))          # 다른 마켓은 안 건드린다
    s.commit()
    called = {}

    def _fake(nos, session=None):
        called["nos"] = list(nos)
        for no in nos:
            line = session.get(MarketOrderLine, f"lotteon|{no}|1")
            line.row = {**line.row, "상품명": "롯데 상품", "단가": 30000}
        session.commit()
        return {"not_found": []}

    monkeypatch.setattr(OI, "ingest_lotteon_orders_by_no", _fake)
    st = OI.restore_blank_orders("lotteon", session=s)
    assert called["nos"] == ["LO1"]
    assert st["targets"] == 1 and st["filled_lines"] == 1
    s.close()


def test_지원안하는_마켓은_크게_실패한다():
    """조용히 0건으로 넘어가면 '채웠다'로 오해한다."""
    s = _sess()
    with pytest.raises(ValueError, match="쿠팡|coupang"):
        OI.restore_blank_orders("coupang", session=s)
    s.close()


def test_11번가_기존_이름도_같은_동작(monkeypatch):
    """호출부·스케줄러 호환용 얇은 껍질이 공통 함수로 위임되는지."""
    seen = {}
    monkeypatch.setattr(OI, "restore_blank_orders",
                        lambda market, **kw: seen.setdefault("m", market) or {"targets": 0})
    OI.restore_eleven11_blank_orders()
    assert seen["m"] == "eleven11"


# ── ③ 클레임이 주문상태를 되덮지 않게 ────────────────────────────────────

def _mk_pair(s, *, line_status, claim_status, line_seen, claim_seen):
    from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine
    uid = "eleven11|X1|1"
    s.add(MarketOrderLine(line_uid=uid, market="eleven11", order_no="X1",
                          order_date="2026-07-07 10:00:00", status=line_status,
                          row={"주문상태": line_status, "주문상태원본": "901"},
                          last_seen_at=line_seen))
    s.add(MarketClaimEvent(event_uid="eleven11|X1|c", line_uid=uid, market="eleven11",
                           order_no="X1", changed_at="2026-07-08",
                           status=claim_status, row={}, last_seen_at=claim_seen))
    s.commit()
    return uid


def test_마켓이_계속_주는_주문은_옛_클레임이_못_덮는다():
    """취소가 철회돼 마켓이 다시 정상으로 보고하면, 옛 취소완료 이벤트가 이겨선 안 된다."""
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    now = _dt.datetime.utcnow()
    uid = _mk_pair(s, line_status="구매확정", claim_status="취소완료",
                   line_seen=now, claim_seen=now - _dt.timedelta(hours=6))
    st = OS.sync_status_from_claims(session=s)
    assert st["skipped_stale"] == 1 and st["fixed"] == 0
    assert s.get(MarketOrderLine, uid).status == "구매확정"
    s.close()


def test_같은_틱에_둘_다_보이면_예전대로_클레임이_이긴다():
    """진짜 취소건 — 여기서 안 덮으면 취소 주문이 매출로 계상된다(원래 이 함수의 목적)."""
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    now = _dt.datetime.utcnow()
    uid = _mk_pair(s, line_status="배송준비중", claim_status="취소완료",
                   line_seen=now, claim_seen=now - _dt.timedelta(seconds=3))
    st = OS.sync_status_from_claims(session=s)
    assert st["fixed"] == 1 and st.get("skipped_stale", 0) == 0
    assert s.get(MarketOrderLine, uid).status == "취소완료"
    s.close()


def test_확인시각을_모르면_예전대로_적용한다():
    """옛 적재분엔 시각이 없을 수 있다 — 모른다고 보정을 포기하면 취소가 매출로 남는다."""
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    uid = _mk_pair(s, line_status="배송준비중", claim_status="반품완료",
                   line_seen=_dt.datetime.utcnow(), claim_seen=None)
    st = OS.sync_status_from_claims(session=s)
    assert st["fixed"] == 1
    assert s.get(MarketOrderLine, uid).status == "반품완료"
    s.close()


# ── ① 롯데온 정산 백필도 파생값을 계산한다 ───────────────────────────────

def test_롯데온_정산백필도_파생열을_만든다(monkeypatch):
    """이 경로만 _finalize_rows 를 안 태워서 상품금액·정산예정금(배송비포함)·수수료율이
    통째로 없었다 — 저장분 빈 행 187건의 키 목록이 209 경로와 달랐던 이유."""
    from shared.platforms.lotteon import settle_orders as _so
    monkeypatch.setattr(OI, "_acct_client", lambda *a, **k: object())
    monkeypatch.setattr(_so, "order_rows", lambda *a, **k: [{
        "판매처": "롯데온", "오픈마켓주문번호": "L9", "주문일": "2026-07-01 10:00:00",
        "상품명": "롯데 상품", "단가": 20000, "수량": 2, "배송비": 2500,
        "정산예정금액": 35000, "주문상태": "구매확정",
        "_send_ids": {"od_no": "L9", "od_seq": "1", "sitm_no": ""},
    }])
    rows = OI._fetch_inner("lotteon", _dt.datetime(2026, 7, 1, tzinfo=KST),
                           _dt.datetime(2026, 7, 2, tzinfo=KST), backfill=True)
    assert rows[0]["상품금액"] == 40000                  # 단가×수량
    assert rows[0]["정산예정금(배송비포함)"] == 37500     # 정산 + 배송비
    assert rows[0][L.FIELD] == "lotteon|L9|1"           # uid 도 그대로 찍힌다
