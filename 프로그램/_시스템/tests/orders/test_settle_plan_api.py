# -*- coding: utf-8 -*-
"""정산예정금액 탭 API — 집계·상세·규칙표(+실측 보정 역산)."""
import datetime as _dt
import pathlib

import webapp.routes.orders as om

KST = _dt.timezone(_dt.timedelta(hours=9))


def _make_client():
    from flask import Flask
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


def _line(status="구매확정", market="gmarket", incl=10000, src="real",
          date=None, account="계정A", **row_extra):
    row = {"주문상태": status, "정산예정금(배송비포함)": incl, "정산예정금액": incl,
           "_settle_source": src, "주문일": "2026-08-01 10:00",
           "오픈마켓주문번호": "ONO1", "상품명": "코트", "옵션": "블랙/95",
           "수량": 1, "배송비": 0}
    if date:
        row["정산예정일"] = date
    row.update(row_extra)
    return {"row": row, "market": market, "account": account,
            "status_at": _dt.datetime(2026, 8, 1, 12, 0)}


def _patch_lines(monkeypatch, lines):
    monkeypatch.setattr(om, "_settle_plan_lines", lambda markets=None: [
        ln for ln in lines if not markets or ln["market"] in markets])


def test_집계_지급예정일축(monkeypatch):
    _patch_lines(monkeypatch, [
        _line(date="2099-08-20", incl=100),
        _line(status="배송중", src="estimated", incl=200),
    ])
    c = _make_client()
    r = c.get("/orders/api/settle-plan?axis=payout&unit=week")
    assert r.status_code == 200
    data = r.get_json()
    assert data["kpi"]["confirmed_future"] == 100
    assert data["kpi"]["unconfirmed_future"] == 200
    assert data["buckets"]


def test_집계_주문일축(monkeypatch):
    _patch_lines(monkeypatch, [_line(실결제금액=12000)])
    c = _make_client()
    r = c.get("/orders/api/settle-plan?axis=order&unit=day"
              "&from=2026-08-01&to=2026-08-31")
    assert r.status_code == 200
    data = r.get_json()
    assert data["buckets"][0]["revenue"] == 12000


def test_상세_카테고리와_마켓_필터(monkeypatch):
    _patch_lines(monkeypatch, [
        _line(date="2099-08-20", incl=100, market="gmarket"),
        _line(status="배송중", src="estimated", incl=200, market="coupang"),
    ])
    c = _make_client()
    r = c.get("/orders/api/settle-plan/detail?category=confirmed&market=gmarket")
    assert r.status_code == 200
    rows = r.get_json()["rows"]
    assert len(rows) == 1
    assert rows[0]["총정산예정"] == 100
    assert rows[0]["지급예정일"] == "2099-08-20"
    assert rows[0]["_settle_source"] == "real"


def test_상세_배송비_3칸_분리(monkeypatch):
    _patch_lines(monkeypatch, [
        _line(date="2099-08-20", incl=13000, 배송비=3000, market="smartstore")])
    c = _make_client()
    r = c.get("/orders/api/settle-plan/detail?category=confirmed")
    row = r.get_json()["rows"][0]
    assert row["총정산예정"] == 13000
    assert row["배송비정산예정"] == 3000
    assert row["상품정산예정"] == 10000


def test_규칙_조회와_저장_왕복(monkeypatch, tmp_path):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    _patch_lines(monkeypatch, [])
    c = _make_client()
    r = c.get("/orders/api/settle-plan/rules")
    assert r.status_code == 200
    data = r.get_json()
    assert data["rules"]["markets"]["coupang"]["split_ratio"] == 0.7
    assert "calibration" in data

    r2 = c.post("/orders/api/settle-plan/rules", json={
        "markets": {"lotteon": {"cycle_days": 9}},
        "fast_accounts": {"smartstore": ["본계정"]}})
    assert r2.status_code == 200
    r3 = c.get("/orders/api/settle-plan/rules")
    assert r3.get_json()["rules"]["markets"]["lotteon"]["cycle_days"] == 9
    assert r3.get_json()["rules"]["fast_accounts"]["smartstore"] == ["본계정"]


def test_규칙_저장_검증_모르는키_거부(monkeypatch, tmp_path):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    _patch_lines(monkeypatch, [])
    c = _make_client()
    r = c.post("/orders/api/settle-plan/rules", json={
        "markets": {"lotteon": {"cycle_days": 9999}}})     # 범위 밖
    assert r.status_code == 400


def test_보정_실측_구매확정_행에서_역산(monkeypatch, tmp_path):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    # 관측확정 8/1 → 실지급예정 8/3 = 간격 2일 (gmarket rule 1일과 1일 차)
    _patch_lines(monkeypatch, [_line(date="2026-08-03")])
    c = _make_client()
    data = c.get("/orders/api/settle-plan/rules").get_json()
    cal = data["calibration"]["gmarket"]
    assert cal["measured_days"] == 2
    assert cal["n"] == 1


def test_보정_재료없으면_측정불가(monkeypatch, tmp_path):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    _patch_lines(monkeypatch, [])
    c = _make_client()
    data = c.get("/orders/api/settle-plan/rules").get_json()
    assert data["calibration"]["gmarket"] == "측정불가"


# ══ [2026-08-06 라이브 교정] KPI ↔ 드릴다운 일치 ═══════════════════════════════

def test_KPI와_드릴다운이_같은_판정을_쓴다(monkeypatch):
    """라이브 사고 재발 방지 — KPI 는 5.5억인데 목록은 0건이던 어긋남."""
    _patch_lines(monkeypatch, [
        _line(status="구매확정", date="2099-08-20", incl=100),
        _line(status="구매확정", src="estimated"),          # 날짜 미정 후보
    ])
    c = _make_client()
    agg = c.get("/orders/api/settle-plan?axis=payout&unit=week").get_json()
    for cat in ("confirmed", "overdue", "undated", "assumed_paid"):
        kpi_key = "confirmed_future" if cat == "confirmed" else cat
        amt = agg["kpi"].get(kpi_key, 0)
        rows = c.get("/orders/api/settle-plan/detail?category=" + cat).get_json()["rows"]
        got = sum(r["총정산예정"] for r in rows)
        assert got == amt, f"{cat}: KPI {amt} vs 목록 {got}"


def test_날짜_미정은_별도_카테고리로_조회된다(monkeypatch):
    ln = _line(status="구매확정", src="estimated")
    ln["status_at"] = None
    ln["row"]["주문일"] = ""
    _patch_lines(monkeypatch, [ln])
    c = _make_client()
    agg = c.get("/orders/api/settle-plan").get_json()
    assert agg["kpi"]["undated"] == 10000
    assert agg["kpi"]["overdue"] == 0
    rows = c.get("/orders/api/settle-plan/detail?category=undated").get_json()["rows"]
    assert len(rows) == 1 and rows[0]["총정산예정"] == 10000


def test_이미_받았을_것_기준일_저장_왕복(monkeypatch, tmp_path):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    _patch_lines(monkeypatch, [])
    c = _make_client()
    assert c.post("/orders/api/settle-plan/rules",
                  json={"assume_paid_after_days": 45}).status_code == 200
    assert c.get("/orders/api/settle-plan/rules").get_json()[
        "rules"]["assume_paid_after_days"] == 45
    assert c.post("/orders/api/settle-plan/rules",
                  json={"assume_paid_after_days": 0}).status_code == 400
