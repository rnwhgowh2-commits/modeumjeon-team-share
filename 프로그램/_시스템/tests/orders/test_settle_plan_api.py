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


# 🔴 「미확정」 줄의 지급예정일은 **관측 시각(status_at)에서 규칙으로 추정**한다.
#   그래서 기준점을 과거로 고정해 두면 오늘이 그 날짜를 지나가는 순간 「앞으로 받을 돈」에서
#   빠져 시험이 저절로 깨진다 — 2026-08-13 에 실제로 그렇게 깨졌고, 아무도 코드를
#   안 고쳤는데 **모두의 배포가 막혔다**. 「미래」를 봐야 하는 줄은 기준점도 미래로 둔다
#   (확정 줄이 이미 2099-08-20 을 쓰는 것과 같은 이유).
FUTURE_AT = _dt.datetime(2099, 8, 1, 12, 0)
PAST_AT = _dt.datetime(2026, 8, 1, 12, 0)


def _line(status="구매확정", market="gmarket", incl=10000, src="real",
          date=None, account="계정A", status_at=PAST_AT, **row_extra):
    row = {"주문상태": status, "정산예정금(배송비포함)": incl, "정산예정금액": incl,
           "_settle_source": src, "주문일": "2026-08-01 10:00",
           "오픈마켓주문번호": "ONO1", "상품명": "코트", "옵션": "블랙/95",
           "수량": 1, "배송비": 0}
    if date:
        row["정산예정일"] = date
    row.update(row_extra)
    return {"row": row, "market": market, "account": account,
            "status_at": status_at}


def _patch_lines(monkeypatch, lines):
    monkeypatch.setattr(om, "_settle_plan_lines", lambda markets=None: [
        ln for ln in lines if not markets or ln["market"] in markets])


def test_집계_지급예정일축(monkeypatch):
    _patch_lines(monkeypatch, [
        _line(date="2099-08-20", incl=100),
        _line(status="배송중", src="estimated", incl=200, status_at=FUTURE_AT),
    ])
    c = _make_client()
    r = c.get("/orders/api/settle-plan?axis=payout&unit=week")
    assert r.status_code == 200
    data = r.get_json()
    assert data["kpi"]["confirmed_future"] == 100
    assert data["kpi"]["unconfirmed_future"] == 200
    assert data["buckets"]


def test_집계_주문일축(monkeypatch):
    _patch_lines(monkeypatch, [_line(_매출기준액=12000)])
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


# ══ [2026-08-06 2차] 수령확인 부류 노출 ═══════════════════════════════════════

def test_수령확인_금액도_드릴다운으로_볼_수_있다(monkeypatch):
    """paid(이미 받은 것으로 확인) 가 KPI 에만 있고 목록이 없으면 근거를 못 본다."""
    ln = _line(status="구매확정", date="2026-07-20", incl=5000)
    ln["row"]["_settle_paid_date"] = "2026-07-20"
    _patch_lines(monkeypatch, [ln])
    c = _make_client()
    agg = c.get("/orders/api/settle-plan").get_json()
    assert agg["kpi"]["paid"] == 5000
    rows = c.get("/orders/api/settle-plan/detail?category=paid").get_json()["rows"]
    assert len(rows) == 1 and rows[0]["총정산예정"] == 5000
    assert rows[0]["category"] == "paid"


def test_규칙_API가_마켓별_계정_목록을_준다(monkeypatch, tmp_path):
    """빠른정산 계정을 손으로 타이핑하면 오타로 조용히 안 걸린다 — 목록에서 고르게."""
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    _patch_lines(monkeypatch, [])
    monkeypatch.setattr(om._oe, "_active_accounts",
                        lambda mk: [("A_", "브랜드마켓(" + mk + ")"), ("B_", "세소")])
    c = _make_client()
    data = c.get("/orders/api/settle-plan/rules").get_json()
    assert data["accounts"]["coupang"] == ["브랜드마켓(coupang)", "세소"]
    assert "smartstore" in data["accounts"]


def test_계정_목록_조회가_실패해도_규칙은_나온다(monkeypatch, tmp_path):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    _patch_lines(monkeypatch, [])

    def _boom(mk):
        raise RuntimeError("키 미등록")
    monkeypatch.setattr(om._oe, "_active_accounts", _boom)
    c = _make_client()
    data = c.get("/orders/api/settle-plan/rules").get_json()
    assert data["accounts"] == {} or all(v == [] for v in data["accounts"].values())
    assert data["rules"]["markets"]["coupang"]["cycle_days"] >= 0


def test_이미_받은_주문은_받은_날을_보여준다(monkeypatch):
    """[2026-08-06 라이브] 입금 확인된 주문인데 「미정·근거없음」으로 떠 있었다 —
    받은 날(_settle_paid_date)이 있는데 지급'예정'만 보던 탓."""
    ln = _line(status="구매확정", incl=27360)
    ln["row"]["_settle_paid_date"] = "2026-07-27"
    _patch_lines(monkeypatch, [ln])
    c = _make_client()
    row = c.get("/orders/api/settle-plan/detail?category=paid").get_json()["rows"][0]
    assert row["지급예정일"] == "2026-07-27"
    assert row["date_source"] == "real"        # 마켓이 알려준 날이라 실측


def test_정산시작전_목록에_사유와_확인방법이_실린다(monkeypatch):
    """숫자만 보면 뭘 해야 할지 알 수 없다 — 원인과 확인법을 같이 준다.

    🔴 [2026-08-12] 이 건은 「입금일 지남」이 아니라 「정산 시작 전」이다 —
       구매확정 전인데 **우리 추정** 날짜만 지난 것이라 돈이 밀린 게 아니다.
    🔴 [2026-09-05] 리터럴 날짜(2026-07-20)를 쓰면 시간이 지날수록 추정예정일이
       assume_paid_after_days(30일)를 넘어 assumed_paid 로 옮겨가 「달력썩음」으로
       깨진다(다섯 번째 사례 — tests/QUARANTINE.txt 의 11번가 스냅샷 건과 동일 클래스).
       status_at 을 「오늘 기준 상대 날짜」로 잡아 다시는 안 썩게 한다."""
    ln = _line(status="배송완료", market="lotteon", src="estimated", incl=5000)
    ln["status_at"] = _dt.datetime.now() - _dt.timedelta(days=24)
    _patch_lines(monkeypatch, [ln])
    c = _make_client()
    assert c.get("/orders/api/settle-plan/detail?category=overdue"
                 ).get_json()["rows"] == []
    rows = c.get("/orders/api/settle-plan/detail?category=not_started"
                 ).get_json()["rows"]
    assert len(rows) == 1
    r = rows[0]
    assert r["사유코드"] == "not_confirmed_yet"
    assert "구매확정" in r["사유"]
    assert r["확인방법"]
    assert r["지난일수"] >= 1


def test_사유_요약도_집계에_들어간다(monkeypatch):
    """카드 옆에 「무엇 때문에 이만큼인지」를 한눈에.

    ★ 「지남」 사유 요약은 **진짜 지난 것만** 센다 — 마켓이 준 날짜(real)가 지난 건들.
      추정일만 지난 건 not_started 로 빠져 이 요약에 안 들어간다.

    🔴 [2026-09-05] 날짜는 「오늘−10일」로 상대적으로 잡는다 — assumed_paid 30일
      한도 안에 들면서(overdue 유지) 지나긴 지난(지난일수>=1) 상태를 계속 재현하려면
      리터럴 날짜는 못 쓴다(달력썩음 다섯 번째 사례)."""
    RECENT = (_dt.date.today() - _dt.timedelta(days=10)).isoformat()
    # 마켓이 준 날짜가 지났는데 아직 구매확정 전 = 진짜 지남(사유: 확정 전)
    a = _line(status="배송완료", market="lotteon", date=RECENT, incl=5000)
    b = _line(status="구매확정", market="eleven11", date=RECENT, incl=3000)
    _patch_lines(monkeypatch, [a, b])
    c = _make_client()
    agg = c.get("/orders/api/settle-plan").get_json()
    rs = agg["overdue_reasons"]
    assert rs["not_confirmed_yet"]["금액"] == 5000
    assert rs["no_confirm_channel"]["금액"] == 3000
    assert rs["not_confirmed_yet"]["건수"] == 1


def test_롯데온_수취완료는_확정예정으로_집계된다(monkeypatch):
    """사장님 신고 — 롯데온은 구매확정인데 「아직 구매확정 전」이라 떴다.
    롯데온의 확정 상태값은 「수취완료」(odPrgsStepCd=15)다."""
    ln = _line(status="수취완료", market="lotteon", date="2099-08-20", incl=8000)
    _patch_lines(monkeypatch, [ln])
    c = _make_client()
    agg = c.get("/orders/api/settle-plan").get_json()
    assert agg["kpi"]["confirmed_future"] == 8000
    assert agg["kpi"]["unconfirmed_future"] == 0


def test_정산시작전도_KPI와_목록이_일치한다(monkeypatch):
    """새 부류를 만들 때마다 KPI 와 드릴다운이 갈리는 사고가 났다 — 같이 잠근다.

    🔴 [2026-09-05] status_at 을 「오늘 기준 상대 날짜」로 — 리터럴 날짜는 달력썩음."""
    ln = _line(status="배송완료", market="lotteon", src="estimated", incl=5000)
    ln["status_at"] = _dt.datetime.now() - _dt.timedelta(days=24)
    _patch_lines(monkeypatch, [ln])
    c = _make_client()
    agg = c.get("/orders/api/settle-plan").get_json()
    rows = c.get("/orders/api/settle-plan/detail?category=not_started"
                 ).get_json()["rows"]
    assert agg["kpi"]["not_started"] == sum(r["총정산예정"] for r in rows) == 5000
    assert agg["kpi"]["total_uncollected"] == 5000     # 사라지는 돈 0원


# ══ [2026-08-06 개선] 정산율 감시 · 엑셀 내보내기 ════════════════════════════

def test_주문일축에_정산율_감시가_실린다(monkeypatch):
    """라이브 정산율 90~92%(수수료 6~18% 감안 시 과대)를 아무도 못 알아채던 것."""
    a = _line(status="구매확정", market="coupang", incl=950000)
    a["row"]["_매출기준액"] = 1000000
    a["row"]["주문일"] = "2026-08-01 10:00"
    _patch_lines(monkeypatch, [a])
    c = _make_client()
    d = c.get("/orders/api/settle-plan?axis=order&unit=month"
              "&from=2026-08-01&to=2026-08-31").get_json()
    w = d["rate_watch"]["coupang"]
    assert w["정산율"] == 95.0
    assert w["기대수수료"] == 11.55
    assert w["경고"] is True


def test_엑셀_내보내기는_상한없이_전건(monkeypatch):
    """목록은 2,000건에서 잘린다 — 통장 대조하려면 전건이 필요하다."""
    rows = []
    for i in range(30):
        ln = _line(status="구매확정", date="2099-08-20", incl=100)
        ln["row"]["오픈마켓주문번호"] = f"ONO{i}"
        rows.append(ln)
    _patch_lines(monkeypatch, rows)
    c = _make_client()
    r = c.get("/orders/api/settle-plan/export.xlsx?category=confirmed")
    assert r.status_code == 200
    assert "spreadsheet" in r.headers["Content-Type"]
    assert len(r.data) > 2000          # 실제 파일이 나온다


def test_엑셀_모르는_부류는_거부(monkeypatch):
    _patch_lines(monkeypatch, [])
    c = _make_client()
    assert c.get("/orders/api/settle-plan/export.xlsx?category=몰라").status_code == 400


# ══ [2026-08-12] 노션 c-1·c-2·c-3 ════════════════════════════════════════════

def test_상세내역에_수령자가_실린다(monkeypatch):
    """c-1 — 마켓 정산 화면과 한 건씩 맞대 보려면 「누구에게 간 주문인가」가 있어야 한다.
    마켓·계정·주문상태·주문일은 이미 실려 있었고 수령자만 빠져 있었다."""
    _patch_lines(monkeypatch, [_line(date="2099-08-20", 수령자="홍길동")])
    c = _make_client()
    r = c.get("/orders/api/settle-plan/detail?category=confirmed").get_json()["rows"][0]
    for k in ("market", "account", "주문상태", "주문일", "수령자"):
        assert r.get(k), f"{k} 가 상세내역에 없다"
    assert r["수령자"] == "홍길동"


def test_받은_이력이_받은_날_칸으로_나온다(monkeypatch):
    """c-2 — 「받는 날 기준」인데 미래만 보였다. 과거 칸을 따로 준다."""
    _patch_lines(monkeypatch, [
        _line(date="2026-07-01", incl=900, _settle_paid_date="2026-07-28"),
        _line(date="2099-08-20", incl=100),
    ])
    c = _make_client()
    agg = c.get("/orders/api/settle-plan?axis=payout&unit=week").get_json()
    pb = agg["past_buckets"]
    assert [b["key"] for b in pb] == ["2026-07-27"]
    assert pb[0]["paid"] == 900
    # 미래 본표·합계는 그대로 — 과거를 더해 부풀리지 않는다
    assert sum(b["total"] for b in agg["buckets"]) == 100


def test_받은_이력_칸을_누르면_그_칸_주문만_나온다(monkeypatch):
    """예전엔 칸 거르기를 확정/미확정에만 걸어, 지난 칸을 눌러도 전건이 나왔다."""
    _patch_lines(monkeypatch, [
        _line(date="2026-07-01", incl=900, _settle_paid_date="2026-07-28",
              오픈마켓주문번호="OLD"),
        _line(date="2026-06-01", incl=500, _settle_paid_date="2026-06-02",
              오픈마켓주문번호="OLDER"),
    ])
    c = _make_client()
    rows = c.get("/orders/api/settle-plan/detail"
                 "?category=paid&bucket=2026-07-27&unit=week").get_json()["rows"]
    assert [r["주문번호"] for r in rows] == ["OLD"]


def test_주문일축에도_상세내역이_있다(monkeypatch):
    """c-3 — 주문일 축은 드릴다운이 아예 없었다."""
    _patch_lines(monkeypatch, [
        _line(date="2099-08-20", incl=100, _매출기준액=12000, 수령자="홍길동"),
        _line(date="2099-08-20", incl=100, 주문일="2026-07-01 10:00",
              오픈마켓주문번호="OTHER", _매출기준액=5000),
    ])
    c = _make_client()
    agg = c.get("/orders/api/settle-plan?axis=order&unit=day").get_json()
    keys = [b["key"] for b in agg["buckets"]]
    assert "2026-08-01" in keys
    d = c.get("/orders/api/settle-plan/detail"
              "?axis=order&bucket=2026-08-01&unit=day").get_json()
    assert d["axis"] == "order"
    assert [r["주문번호"] for r in d["rows"]] == ["ONO1"]
    r = d["rows"][0]
    assert r["매출액"] == 12000 and r["수령자"] == "홍길동"
    # 집계와 목록이 같은 판정을 쓴다 — 그 칸의 매출 합이 목록 합과 같아야 한다
    b = [x for x in agg["buckets"] if x["key"] == "2026-08-01"][0]
    assert b["revenue"] == sum(x["매출액"] for x in d["rows"])


def test_주문일축_목록은_매출_대체를_숨기지_않는다(monkeypatch):
    """집계 meta 엔 건수만 있었다 — 어느 주문이 대체됐는지 줄마다 적는다."""
    _patch_lines(monkeypatch, [_line(date="2099-08-20", incl=100,
                                     상품금액=9000, 배송비=3000)])
    c = _make_client()
    d = c.get("/orders/api/settle-plan/detail"
              "?axis=order&bucket=2026-08-01&unit=day").get_json()
    assert d["rows"][0]["매출액"] == 12000
    assert d["rows"][0]["매출액대체"] is True


# ══ [2026-08-12] 노션 c-4 — 마켓 정산 대조 라우트 ════════════════════════════

def _xlsx(rows):
    import io as _io
    import pandas as pd
    buf = _io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()


def test_대조항목이_기준일_규칙과_함께_나온다(monkeypatch):
    """기준일을 잘못 뽑으면 대조 자체가 거짓 — 화면이 규칙을 그대로 보여줘야 한다."""
    _patch_lines(monkeypatch, [])
    c = _make_client()
    j = c.get("/orders/settle-recon/items").get_json()
    keys = {x["key"] for x in j["items"]}
    assert keys == {"coupang_rg", "coupang_confirmed",
                    "coupang_unconfirmed", "smartstore"}
    rg = [x for x in j["items"] if x["key"] == "coupang_rg"][0]
    assert "매출인식일 2달" in rg["기준일"]


def test_모르는_항목은_거부한다(monkeypatch):
    _patch_lines(monkeypatch, [])
    c = _make_client()
    r = c.post("/orders/settle-recon/run",
               data={"item": "없는항목", "file": (__import__("io").BytesIO(b"x"), "a.xlsx")},
               content_type="multipart/form-data")
    assert r.status_code == 400


def test_금액열을_못_찾으면_422로_본_열이름을_말한다(monkeypatch):
    """🔴 조용히 0원으로 넘어가 「대조했는데 일치」라고 하면 안 된다."""
    import io as _io
    _patch_lines(monkeypatch, [])
    c = _make_client()
    r = c.post("/orders/settle-recon/run",
               data={"item": "coupang_confirmed",
                     "file": (_io.BytesIO(_xlsx([{"엉뚱한열": 1}])), "a.xlsx")},
               content_type="multipart/form-data")
    assert r.status_code == 422
    assert "엉뚱한열" in r.get_json()["error"]
