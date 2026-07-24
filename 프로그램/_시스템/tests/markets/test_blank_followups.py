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


def test_롯데온_단건조회는_기간을_쪼개지_않는다(monkeypatch):
    """🔴 라이브 504 실측 — odNo 조회인데 하루 윈도우 루프를 타면 1년치가 365회 호출이
    되어 요청 상한을 넘긴다. 단건은 1회(마켓이 기간을 요구하면 최대 2회)여야 한다."""
    from shared.platforms.lotteon import orders as LO
    calls = []

    def _fake_fetch(srch_start, srch_end, **kw):
        calls.append((srch_start, srch_end, kw.get("od_no")))
        return {"data": {"deliveryOrderList": [{"odNo": kw.get("od_no"), "odSeq": "1"}]}}

    monkeypatch.setattr(LO, "fetch_delivery_orders", _fake_fetch)
    got = list(LO.iter_delivery_orders_by_no(
        "L9", client=object(),
        since=_dt.datetime(2025, 7, 1, tzinfo=KST), until=_dt.datetime(2026, 7, 1, tzinfo=KST)))
    assert len(got) == 1
    assert len(calls) == 1 and calls[0][0] == "" and calls[0][2] == "L9"


def test_기간없이_빈손이면_기간을_한번만_더_묻는다(monkeypatch):
    from shared.platforms.lotteon import orders as LO
    calls = []

    def _fake_fetch(srch_start, srch_end, **kw):
        calls.append(srch_start)
        if not srch_start:
            return {"data": {"deliveryOrderList": []}}
        return {"data": {"deliveryOrderList": [{"odNo": "L9", "odSeq": "1"}]}}

    monkeypatch.setattr(LO, "fetch_delivery_orders", _fake_fetch)
    got = list(LO.iter_delivery_orders_by_no(
        "L9", client=object(),
        since=_dt.datetime(2025, 7, 1, tzinfo=KST), until=_dt.datetime(2026, 7, 1, tzinfo=KST)))
    assert len(got) == 1 and len(calls) == 2     # 창을 쪼개지 않는다


def test_롯데온_단건복구는_클레임을_훑지_않는다(monkeypatch):
    """🔴 라이브 504 2차 원인 — 단건 조회인데 취소·반품·교환 3종을 기간만큼 하루씩
    훑어(1년이면 1,000회+) 또 상한을 넘겼다. 단건 복구의 목적은 그 주문행의 상품·금액을
    채우는 것이고, 클레임은 창 조회가 이미 적재한다."""
    from lemouton.markets import order_export as OE
    from shared.platforms.lotteon import claims as CLM
    from shared.platforms.lotteon import orders as LO

    monkeypatch.setattr(LO, "fetch_delivery_orders",
                        lambda srch_start, srch_end, **kw: {"data": {"deliveryOrderList": [
                            {"odNo": "L9", "odSeq": "1", "spdNm": "롯데 상품",
                             "slUprc": 30000, "odQty": 1}]}})
    for name in ("iter_cancel", "iter_return", "iter_exchange"):
        monkeypatch.setattr(CLM, name,
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("클레임 조회 금지")))
    rows = OE.lotteon_order_rows(_dt.datetime(2025, 7, 1, tzinfo=KST),
                                 _dt.datetime(2026, 7, 1, tzinfo=KST),
                                 client=object(), include_settlement=False,
                                 orders_to_now=False, od_no="L9")
    assert len(rows) == 1 and rows[0]["오픈마켓주문번호"] == "L9"


# ── 중복 껍데기 정리 — 같은 라인이 짧은 키로 한 번 더 저장된 것 ────────────

def test_짧은키_빈껍데기만_지운다():
    """🔴 롯데온 실측 187건 — 정산 백필은 sitmNo 를 안 줘서 같은 상품라인이
    `lotteon|odNo|1`(공란)과 `lotteon|odNo|1|sitmNo`(실데이터) 두 행으로 갈렸다."""
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    s.add(MarketOrderLine(line_uid="lotteon|A|1", market="lotteon", order_no="A",
                          order_date="2026-06-25", row={"상품명": "", "단가": 0}))
    s.add(MarketOrderLine(line_uid="lotteon|A|1|SITM", market="lotteon", order_no="A",
                          order_date="2026-06-25", row={"상품명": "롯데 상품", "단가": 46500}))
    s.commit()
    assert OS.dedupe_short_uid_ghosts(session=s)["removed"] == 1
    assert s.get(MarketOrderLine, "lotteon|A|1") is None
    assert s.get(MarketOrderLine, "lotteon|A|1|SITM") is not None
    s.close()


def test_형제가_없으면_안_지운다():
    """유일한 원본일 수 있다 — 비었다고 지우면 주문이 사라진다."""
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    s.add(MarketOrderLine(line_uid="lotteon|B|1", market="lotteon", order_no="B",
                          order_date="2026-06-25", row={"상품명": "", "단가": 0}))
    s.commit()
    assert OS.dedupe_short_uid_ghosts(session=s)["removed"] == 0
    assert s.get(MarketOrderLine, "lotteon|B|1") is not None
    s.close()


def test_값이_있으면_형제가_있어도_안_지운다():
    """껍데기가 아니면 남긴다 — 값이 있는 쪽을 지우면 정보 손실."""
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    s.add(MarketOrderLine(line_uid="lotteon|C|1", market="lotteon", order_no="C",
                          order_date="2026-06-25", row={"상품명": "값 있음", "단가": 100}))
    s.add(MarketOrderLine(line_uid="lotteon|C|1|SITM", market="lotteon", order_no="C",
                          order_date="2026-06-25", row={"상품명": "다른 값", "단가": 200}))
    s.commit()
    assert OS.dedupe_short_uid_ghosts(session=s)["removed"] == 0
    s.close()


def test_복구가_다른_키로_들어오면_채웠다고_보고하지_않는다(monkeypatch):
    """예전엔 주문번호로 아무 라인이나 세서, 껍데기가 그대로 남아도 '채웠다'고 했다."""
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    s.add(_blank_line("lotteon", "D1"))
    s.commit()

    def _fake(nos, session=None):                 # 복구분이 **더 긴 키**로 들어온다
        session.add(MarketOrderLine(line_uid="lotteon|D1|1|SITM", market="lotteon",
                                    order_no="D1", order_date=_recent(),
                                    row={"상품명": "롯데 상품", "단가": 30000}))
        session.commit()
        return {"not_found": []}

    monkeypatch.setattr(OI, "ingest_lotteon_orders_by_no", _fake)
    st = OI.restore_blank_orders("lotteon", session=s)
    assert st["filled_lines"] == 0 and st["superseded"] == 1   # 정직하게 구분
    s.close()


def test_롯데온_단건복구도_회수반품_재분류를_거친다(monkeypatch):
    """🔴 라이브 실측 3건 — 조기 반환이 `_reclassify_lotteon_returns` 까지 건너뛰어,
    209 가 회수지시(21~27)로 준 행이 order 로 남아 같은 line_uid 가 order·claim
    두 행이 됐다. 그 함수는 순수 변환(마켓 호출 없음)이라 504 와 무관하다."""
    from lemouton.markets import order_export as OE
    from shared.platforms.lotteon import orders as LO

    monkeypatch.setattr(LO, "fetch_delivery_orders",
                        lambda srch_start, srch_end, **kw: {"data": {"deliveryOrderList": [
                            {"odNo": "2026071917781423", "odSeq": "1",
                             "spdNm": "회수 상품", "slUprc": 45300, "odQty": 1,
                             "odPrgsStepCd": "21",          # 회수지시 = 클레임으로 재분류
                             "odCmptDttm": "2026-07-20 10:00:00"}]}})
    rows = OE.lotteon_order_rows(_dt.datetime(2026, 7, 1, tzinfo=KST),
                                 _dt.datetime(2026, 7, 22, tzinfo=KST),
                                 client=object(), include_settlement=False,
                                 orders_to_now=False, od_no="2026071917781423")
    assert [r.get("_kind") for r in rows] == ["change"]


def test_클레임_테이블에서_읽으면_무조건_이력_표시():
    """🔴 롯데온 실측 3건 — 이력 줄에 '이건 이력' 표시가 없어서 화면이 주문 줄로
    착각해 한 주문이 두 줄로 그려졌다(출고지시 + 배송완료). 어느 테이블에서 왔는지가
    유일한 진실이므로 읽을 때 다시 새긴다. 지우지 않는다 — 표시만 고친다."""
    from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine
    s = _sess()
    uid = "lotteon|Z1|1|SITM"
    s.add(MarketOrderLine(line_uid=uid, market="lotteon", order_no="Z1",
                          order_date="2026-07-19", status="배송완료",
                          row={"오픈마켓주문번호": "Z1", "주문상태": "배송완료",
                               "상품명": "수영복", "단가": 45300}))
    s.add(MarketClaimEvent(event_uid="lotteon|Z1|CLM|x", line_uid=uid, market="lotteon",
                           order_no="Z1", changed_at="2026-07-20", status="출고지시",
                           row={"오픈마켓주문번호": "Z1", "주문상태": "출고지시",
                                "상품명": "수영복", "단가": 45300,
                                "_kind": "order"}))     # ← 옛 경로가 남긴 잘못된 표시
    s.commit()
    rows = OS.load(["lotteon"], session=s)
    kinds = sorted(str(r.get("_kind")) for r in rows)
    assert kinds == ["change", "None"] or kinds == ["None", "change"]
    orders = [r for r in rows if r.get("_kind") != "change"]
    assert len(orders) == 1 and orders[0]["주문상태"] == "배송완료"   # 한 줄로 보인다
    s.close()


# ── 같은 라인은 「지금 상태」 한 줄만 ─────────────────────────────────────

def test_같은_라인은_최신_상태_한줄만_나온다():
    """사장님 확정 — "변경이력보다는 최신화 주문상태의 현재기준으로 1건만".
    저장 키 조합이 시절마다 달랐던 주문은 옛 키·새 키 두 행으로 남는다
    (롯데온 실측 3건: 출고지시 + 배송완료). 화면엔 최근에 본 쪽만."""
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    uid = "lotteon|2026071917781423|1|LO2726849808"
    old = _dt.datetime(2026, 7, 19, 0, 0)
    new = _dt.datetime(2026, 7, 24, 0, 0)
    s.add(MarketOrderLine(line_uid=uid + "|OLD", market="lotteon", order_no="A",
                          order_date="2026-07-19", status="출고지시",
                          row={"_line_uid": uid, "주문상태": "출고지시",
                               "정산예정금(배송비포함)": 37599},
                          last_seen_at=old))
    s.add(MarketOrderLine(line_uid=uid, market="lotteon", order_no="A",
                          order_date="2026-07-19", status="배송완료",
                          row={"_line_uid": uid, "주문상태": "배송완료",
                               "정산예정금(배송비포함)": 38505},
                          last_seen_at=new))
    s.commit()
    rows = OS.load(["lotteon"], session=s)
    assert len(rows) == 1
    assert rows[0]["주문상태"] == "배송완료"          # 지금 상태
    assert rows[0]["정산예정금(배송비포함)"] == 38505  # 정산도 최신 쪽
    s.close()


def test_식별자_없는_행은_합치지_않는다():
    """정체가 불확실한 행을 합치면 남의 주문과 섞인다 — 그건 더 위험하다."""
    from lemouton.markets.models_orders import MarketOrderLine
    s = _sess()
    for i in (1, 2):
        s.add(MarketOrderLine(line_uid=f"lotteon|N{i}", market="lotteon",
                              order_no=f"N{i}", order_date="2026-07-19",
                              status="배송완료", row={"주문상태": "배송완료"}))
    s.commit()
    assert len(OS.load(["lotteon"], session=s)) == 2
    s.close()
