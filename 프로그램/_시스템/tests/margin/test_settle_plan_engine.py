"""정산예정금액 엔진 — 분류 상호배타·지급이벤트·버킷 집계 (자금계획 정확성의 핵심).

스펙: docs/superpowers/specs/2026-08-06-settle-plan-tab-design.md §2·§3·§5
"""
import datetime as dt

from lemouton.margin import settle_plan as SP
from lemouton.margin.settle_plan_rules import DEFAULT_RULES

TODAY = dt.date(2026, 8, 6)


def _line(status="구매확정", market="gmarket", incl=10000, src="real",
          date=None, paid=None, kind=None, account="계정A", status_at=None):
    row = {"주문상태": status, "정산예정금(배송비포함)": incl, "정산예정금액": incl,
           "_settle_source": src}
    if date:
        row["정산예정일"] = date
    if paid:
        row["_settle_paid_date"] = paid
    if kind:
        row["_kind"] = kind
    return {"row": row, "market": market, "account": account,
            "status_at": status_at or dt.datetime(2026, 8, 1, 12, 0)}


# ── 분류 ──────────────────────────────────────────────────────────────────────

def test_분류_상호배타_한_주문은_딱_한_부류():
    """[2026-08-06 교정] classify 는 5부류만 — 기한 판정은 이벤트 단위(resolve)로 갔다."""
    lines = [
        _line(status="구매확정", date="2026-08-20"),                    # confirmed
        _line(status="배송중"),                                          # unconfirmed
        _line(status="구매확정", date="2026-07-01"),                    # confirmed(날짜는 이벤트가)
        _line(status="반품요청"),                                        # risk
        _line(status="취소완료"),                                        # excluded
        _line(kind="change"),                                            # excluded
        _line(status="구매확정", date="2026-07-01", paid="2026-07-02"),  # paid
    ]
    cats = [SP.classify(ln, today=TODAY) for ln in lines]
    assert cats == ["confirmed", "unconfirmed", "confirmed", "risk",
                    "excluded", "excluded", "paid"]


def test_분류_송장_전_단계는_대상이_아니다():
    assert SP.classify(_line(status="신규주문"), today=TODAY) == "excluded"
    assert SP.classify(_line(status="발송대기"), today=TODAY) == "excluded"


def test_분류_쿠팡_잔여분이_미래에_남으면_아직_미래예정():
    ln = _line(status="구매확정", market="coupang", date="2026-08-01")
    ln["row"]["_settle_final_date"] = "2026-09-01"
    assert SP.classify(ln, today=TODAY) == "confirmed"


# ── 지급이벤트 ────────────────────────────────────────────────────────────────

def test_실값_지급예정일이_규칙추정보다_우선():
    ln = _line(status="구매확정", date="2026-08-20")
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    assert evs == [{"date": "2026-08-20", "amount": 10000, "date_source": "real"}]


def test_추정_미확정_배송중은_이동중일수와_자동확정과_주기를_더한다():
    ln = _line(status="배송중", market="lotteon", src="estimated",
               status_at=dt.datetime(2026, 8, 1, 12, 0))
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    # 8/1 관측 + transit2 + auto_confirm7 + cycle7 = 8/17
    assert evs[0]["date"] == "2026-08-17"
    assert evs[0]["date_source"] == "estimated"


def test_추정_구매확정이면_주기만_더한다():
    ln = _line(status="구매확정", market="lotteon", src="estimated",
               status_at=dt.datetime(2026, 8, 1, 12, 0))
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    assert evs[0]["date"] == "2026-08-08"                    # 8/1 + cycle7


def test_쿠팡_추정은_두_조각이고_합이_원금과_같다():
    ln = _line(status="구매확정", market="coupang", incl=10001, src="estimated",
               status_at=dt.datetime(2026, 8, 1, 12, 0))
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    assert len(evs) == 2
    assert sum(e["amount"] for e in evs) == 10001            # 반올림 유실 금지


def test_쿠팡_실값_두_날짜가_있으면_실값으로_분할():
    ln = _line(status="구매확정", market="coupang", incl=10000, date="2026-08-10")
    ln["row"]["_settle_final_date"] = "2026-09-01"
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    assert [e["date"] for e in evs] == ["2026-08-10", "2026-09-01"]
    assert sum(e["amount"] for e in evs) == 10000
    assert all(e["date_source"] == "real" for e in evs)


def test_빠른정산_계정은_발송기준_주기로_계산():
    rules = {**DEFAULT_RULES, "fast_accounts": {"smartstore": ["본계정"]}}
    ln = _line(status="배송중", market="smartstore", account="본계정",
               src="estimated", status_at=dt.datetime(2026, 8, 5, 9, 0))
    evs = SP.payout_events(ln, rules, today=TODAY)
    assert evs[0]["date"] == "2026-08-06"                    # 발송관측 8/5 + fast_cycle 1


def test_금액이_없으면_이벤트도_없다():
    ln = _line(incl="", src="none")
    ln["row"]["정산예정금액"] = ""
    assert SP.payout_events(ln, DEFAULT_RULES, today=TODAY) == []


def test_관측시각도_실값도_없으면_날짜없음으로_정직_표기():
    ln = _line(status="구매확정", src="estimated", status_at=None)
    ln["status_at"] = None
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    assert evs == [{"date": None, "amount": 10000, "date_source": None}]


# ── 날짜 정규화·버킷 ──────────────────────────────────────────────────────────

def test_날짜_정규화_형식_4종과_센티널():
    assert SP._norm_date("2026-08-06") == "2026-08-06"
    assert SP._norm_date("2026-08-06T00:00:00") == "2026-08-06"
    assert SP._norm_date("2026/08/06") == "2026-08-06"
    assert SP._norm_date("20260806") == "2026-08-06"
    assert SP._norm_date("1991-01-01T00:00:00") is None      # ESM 보류 센티널
    assert SP._norm_date("0001-01-01T00:00:00") is None
    assert SP._norm_date("") is None
    assert SP._norm_date("이상한값") is None


def test_버킷_주별은_월요일_시작():
    assert SP.bucket_key("2026-08-06", "week") == "2026-08-03"   # 목→그 주 월요일
    assert SP.bucket_key("2026-08-06", "month") == "2026-08"
    assert SP.bucket_key("2026-08-06", "day") == "2026-08-06"


# ── 집계(지급예정일 축) ───────────────────────────────────────────────────────

def test_집계_확정과_미확정이_섞이지_않고_기한경과는_본표_밖():
    lines = [
        _line(status="구매확정", date="2026-08-20", incl=100),
        _line(status="배송완료", src="estimated", incl=200,
              status_at=dt.datetime(2026, 8, 1)),
        _line(status="구매확정", date="2026-08-01", incl=400),   # overdue(5일 전)
    ]
    agg = SP.aggregate_payout(lines, DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["kpi"]["confirmed_future"] == 100
    assert agg["kpi"]["unconfirmed_future"] == 200
    assert agg["kpi"]["overdue"] == 400
    assert agg["kpi"]["total_uncollected"] == 700
    assert sum(b["total"] for b in agg["buckets"]) == 300    # overdue 는 버킷 밖


def test_집계_위험은_예정액에서_빠지고_별도로_잡힌다():
    lines = [_line(status="구매확정", date="2026-08-20", incl=100),
             _line(status="반품요청", incl=999)]
    agg = SP.aggregate_payout(lines, DEFAULT_RULES, unit="month", today=TODAY)
    assert agg["kpi"]["risk"] == 999
    assert agg["kpi"]["total_uncollected"] == 100            # 위험은 미수령 합에 안 넣음
    assert agg["extras"]["risk"]["gmarket"]["계정A"] == 999


def test_집계_계정별로_갈라진다():
    lines = [_line(date="2026-08-20", incl=100, account="A"),
             _line(date="2026-08-20", incl=50, account="B")]
    agg = SP.aggregate_payout(lines, DEFAULT_RULES, unit="week", today=TODAY)
    slot = agg["buckets"][0]["markets"]["gmarket"]
    assert slot["accounts"]["A"]["confirmed"] == 100
    assert slot["accounts"]["B"]["confirmed"] == 50


def test_집계_쿠팡_1차분만_지난_경우_그_조각만_기한경과():
    ln = _line(status="구매확정", market="coupang", incl=10000, date="2026-08-01")
    ln["row"]["_settle_final_date"] = "2026-09-01"
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="month", today=TODAY)
    assert agg["kpi"]["overdue"] == 7000                     # 70% 조각은 지남
    assert agg["kpi"]["confirmed_future"] == 3000            # 30% 조각은 미래


# ── 집계(주문일 축) ───────────────────────────────────────────────────────────

def test_주문일축_매출은_매출기준액_우선_없으면_대체시_카운트():
    """매출액 = order_export._매출기준액(판매가+배송비, 할인 무관) — 마진계산기와 같은 정의.
    옛 저장분이라 그 칸이 없는 줄만 상품금액+배송비로 대체한다(2026-08-27 통일)."""
    lines = [_line(status="구매확정", incl=100), _line(status="구매확정", incl=100)]
    lines[0]["row"]["_매출기준액"] = 12000
    lines[0]["row"]["주문일"] = "2026-08-01 10:00"
    lines[1]["row"]["상품금액"] = 9000
    lines[1]["row"]["배송비"] = 3000
    lines[1]["row"]["주문일"] = "2026-08-01 11:00"
    agg = SP.aggregate_by_order_date(lines, unit="day",
                                     d_from="2026-08-01", d_to="2026-08-31")
    b = agg["buckets"][0]
    assert b["revenue"] == 24000
    assert agg["meta"]["revenue_substituted"] == 1           # 조용한 대체 금지 — 개수 표기


def test_주문일축_클레임은_매출에서_빠진다():
    lines = [_line(status="취소완료"), _line(status="반품완료"),
             _line(status="반품요청"), _line(kind="change")]
    for ln in lines:
        ln["row"]["실결제금액"] = 10000
        ln["row"]["주문일"] = "2026-08-01 10:00"
    agg = SP.aggregate_by_order_date(lines, unit="day",
                                     d_from="2026-08-01", d_to="2026-08-31")
    assert agg["buckets"] == []


# ══ [2026-08-06 라이브 실측 후 교정] ══════════════════════════════════════════
# 🔴 ESM 은 정산조회에서 날짜(SettleExpectDate·RemitDate·BuyDecisonDate)를 **전부 null**
#   로 준다(D1·D4·D5·D6 전 기준일 실측). 쿠팡도 settlementDate 가 안 붙었다.
#   → 실값 날짜는 거의 없고 대부분 추정이다. 그런데 status_at(관측시각)이 없는 옛 행은
#   추정 근거조차 없어 「날짜 미정」이 되는데, 그것이 「입금일 지남」으로 계상돼
#   라이브에 5.5억이 잘못 찍혔다(드릴다운은 0건 — 화면 안에서 숫자가 어긋남).

def test_날짜_미정은_입금일_지남이_아니다():
    """근거 없는 것을 「기한 경과」로 단정하지 않는다 — 별도 부류."""
    ln = _line(status="구매확정", src="estimated")
    ln["status_at"] = None
    ln["row"]["주문일"] = ""                      # 주문일 폴백도 없음
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["kpi"]["undated"] == 10000
    assert agg["kpi"]["overdue"] == 0
    assert agg["kpi"]["total_uncollected"] == 10000   # 받을 돈은 맞다(시점만 모름)


def test_관측시각이_없으면_주문일로_추정한다():
    """status_at 은 옛 저장분에 없다 — 주문일은 거의 항상 있다(추정 배지 유지)."""
    ln = _line(status="배송중", src="estimated")
    ln["status_at"] = None
    ln["row"]["주문일"] = "2026-08-01 10:00"
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    # 주문일 8/1 + 배송소요5 + 자동확정8 + 주기1 = 8/15 (gmarket)
    assert evs[0]["date"] == "2026-08-15"
    assert evs[0]["date_source"] == "estimated"


def test_한참_지난_예정일은_이미_받았을_것으로_보고_총액에서_뺀다():
    """지급 완료를 알려주는 마켓이 없어 「안 받았다」고 단정할 수 없다 —
    30일(규칙표) 넘게 지난 건 별도 부류로 빼고, 그 사실을 화면에 적는다."""
    ln = _line(status="구매확정", date="2026-05-01", incl=500)   # 97일 전
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["kpi"]["assumed_paid"] == 500
    assert agg["kpi"]["overdue"] == 0
    assert agg["kpi"]["total_uncollected"] == 0      # 합계에서 뺌


def test_최근에_지난_예정일만_입금일_지남():
    ln = _line(status="구매확정", date="2026-08-01", incl=700)    # 5일 전
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["kpi"]["overdue"] == 700
    assert agg["kpi"]["assumed_paid"] == 0
    assert agg["kpi"]["total_uncollected"] == 700


def test_resolve_는_집계와_상세가_같은_판정을_쓴다():
    """KPI 5.5억인데 드릴다운 0건이던 불일치의 재발 방지 —
    aggregate 와 detail 이 같은 함수(resolve)를 쓴다."""
    lines = [
        _line(status="구매확정", date="2099-08-20", incl=100),
        _line(status="구매확정", date="2026-08-01", incl=700),      # overdue
        _line(status="구매확정", date="2026-05-01", incl=500),      # assumed_paid
    ]
    lines[2]["row"]["주문일"] = "2026-05-01 10:00"
    agg = SP.aggregate_payout(lines, DEFAULT_RULES, unit="week", today=TODAY)
    for cat, amt in (("confirmed", 100), ("overdue", 700), ("assumed_paid", 500)):
        got = sum(e["amount"] for ln in lines
                  for e in SP.resolve(ln, DEFAULT_RULES, today=TODAY)["events"]
                  if e["bucket"] == cat)
        assert got == amt, cat
    assert agg["kpi"]["confirmed_future"] == 100
    assert agg["kpi"]["overdue"] == 700
    assert agg["kpi"]["assumed_paid"] == 500


def test_분류는_다섯_부류만_반환한다():
    """overdue·undated·assumed_paid 는 **이벤트 단위** 판정이라 classify 밖으로 나갔다."""
    assert SP.classify(_line(status="구매확정", date="2026-07-01"),
                       today=TODAY) == "confirmed"
    assert SP.classify(_line(status="반품요청"), today=TODAY) == "risk"
    assert SP.classify(_line(status="취소완료"), today=TODAY) == "excluded"
    assert SP.classify(_line(status="구매확정", date="2026-07-01",
                             paid="2026-07-02"), today=TODAY) == "paid"


# ══ [2026-08-06] 「입금일 지남」 사유 — 사장님이 원인을 알 수 있게 ════════════
#  라이브 실측 393건 구성: 배송완료인데 구매확정 전 289건(롯데온 212·쿠팡 74·옥션 2·스스 1)
#  + 11번가 104건(마켓이 준 송금예정일 지남·입금 확인 창구 없음).
#  → 대부분은 「돈이 밀린 것」이 아니라 「아직 구매확정이 안 된 것」이다.

def test_구매확정_전이면_사유는_아직_확정_전():
    # 7/20 관측 + 자동확정7 + 주기7 = 8/3 → 3일 지남
    # 🔴 [2026-08-12 교정] 이건 「입금일 지남」이 아니라 「정산 시작 전」이다 —
    #   추정 날짜가 이른 것이지 돈이 밀린 게 아니다(사장님 신고: 쿠팡 배송완료가 왜 지남?).
    ln = _line(status="배송완료", market="lotteon", src="estimated",
               status_at=dt.datetime(2026, 7, 20))
    r = SP.resolve(ln, DEFAULT_RULES, today=TODAY)
    ev = [e for e in r["events"] if e["bucket"] == "not_started"][0]
    assert ev["reason"] == "not_confirmed_yet"
    assert ev["days_over"] == 3


def test_확정됐지만_입금_알려주는_창구가_없는_마켓():
    ln = _line(status="구매확정", market="eleven11", date="2026-08-01")
    r = SP.resolve(ln, DEFAULT_RULES, today=TODAY)
    ev = [e for e in r["events"] if e["bucket"] == "overdue"][0]
    assert ev["reason"] == "no_confirm_channel"


def test_확정됐고_창구도_있으면_아직_회차에_안_잡힘():
    ln = _line(status="구매확정", market="coupang", date="2026-08-01")
    r = SP.resolve(ln, DEFAULT_RULES, today=TODAY)
    ev = [e for e in r["events"] if e["bucket"] == "overdue"][0]
    assert ev["reason"] == "not_in_batch"


def test_기한_안_지난_이벤트엔_사유가_없다():
    ln = _line(status="구매확정", date="2099-08-20")
    r = SP.resolve(ln, DEFAULT_RULES, today=TODAY)
    assert r["events"][0].get("reason") is None


def test_사유_설명은_사람이_읽는_말로_나온다():
    txt = SP.reason_text("not_confirmed_yet", "lotteon")
    assert "구매확정" in txt["뜻"] and txt["확인"]
    assert "11번가" in SP.reason_text("no_confirm_channel", "eleven11")["뜻"]


# ══ [2026-08-06] 개선 — 정산율 감시 · 「구매결정」 확정 인정 ═══════════════════

def test_구매결정도_구매확정으로_본다():
    """옥션·G마켓은 확정을 「구매결정」이라 쓴다. 사유 판정은 이미 그렇게 보는데
    분류만 미확정으로 넣어 **같은 프로그램 안에서 기준이 어긋났다**(라이브 1건)."""
    assert SP.classify(_line(status="구매결정", market="gmarket"),
                       today=TODAY) == "confirmed"
    assert SP.classify(_line(status="구매확정"), today=TODAY) == "confirmed"


def test_정산율_감시_수수료와_어긋나면_경고():
    """매출 대비 정산율이 마켓 수수료율과 크게 다르면 돈이 틀어진 신호다.
    라이브 실측 90~92%(수수료 6~18% 감안 시 과대) — 아무도 못 알아채던 것."""
    rows = [{"market": "coupang", "revenue": 1000000, "settle": 950000},
            {"market": "smartstore", "revenue": 1000000, "settle": 940000}]
    w = SP.rate_watch(rows)
    cp = w["coupang"]
    assert cp["정산율"] == 95.0
    assert cp["기대수수료"] == 11.55          # 마켓 요율표
    assert cp["차이"] > 5                      # 95% 면 수수료 5% — 6.55%p 어긋남
    assert cp["경고"] is True
    assert w["smartstore"]["경고"] is False    # 스스 6% → 94% 는 정상


def test_정산율_감시_재료없으면_말하지_않는다():
    assert SP.rate_watch([{"market": "coupang", "revenue": 0, "settle": 0}]) == {}


# ══ [2026-08-12] 롯데온 확정 인식 · 「정산 시작 전」 부류 (노션 주문관리 d) ═════
#  사장님 신고 2건이 모두 「입금일 지남」 칸에 안 늦은 돈이 쌓이는 문제였다:
#    · 롯데온 — 구매확정인데 「아직 구매확정 전」이라 나온다
#    · 쿠팡  — 배송완료인데 왜 「입금일 지남」에 있나
#  원인도 둘이다: ①롯데온의 확정 상태값 「수취완료」를 확정으로 안 봤다
#                ②확정 전 주문의 **추정** 예정일이 지나면 「지남」으로 셌다

def test_롯데온_수취완료는_구매확정이다():
    """롯데온 odPrgsStepCd 에는 구매확정 코드가 아예 없고 「수취완료」(15)가 그 자리다.
    이걸 미확정으로 보는 바람에 롯데온은 confirmed 부류가 **구조적으로 0건**이었다."""
    assert SP.classify(_line(status="수취완료", market="lotteon"),
                       today=TODAY) == "confirmed"


def test_수취완료는_롯데온에서만_확정으로_본다():
    """다른 마켓까지 번지면 안 된다 — 마켓별로 좁힌 낱말이다."""
    assert SP.classify(_line(status="수취완료", market="coupang"),
                       today=TODAY) == "unconfirmed"


def test_정산조회에_잡힌_건은_상태와_무관하게_확정():
    """롯데온 SettleItmdSales 는 **정산기준일 = 구매확정일**이다 — 거기 잡혔으면
    확정된 것이다. 상태 문자열 추측보다 마켓이 준 증거가 우선.
    ★ 응답에 확정 **날짜**는 없어 날짜를 지어내지 않고 사실만 True 로 적는다."""
    ln = _line(status="배송완료", market="lotteon", src="estimated")
    ln["row"]["_settle_confirmed"] = True
    assert SP.classify(ln, today=TODAY) == "confirmed"


def test_롯데온_확정건에_자동확정일수를_덧붙이지_않는다():
    """확정을 못 알아보면 auto_confirm_days(7)가 덧붙어 예정일이 7일 밀렸다."""
    ln = SP and _line(status="수취완료", market="lotteon", src="estimated",
                      status_at=dt.datetime(2026, 8, 1, 12, 0))
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    assert evs[0]["date"] == "2026-08-08"          # 8/1 + cycle7 (자동확정 7 안 붙음)


def test_확정_전_추정일이_지난_것은_입금일_지남이_아니다():
    """쿠팡 배송완료가 「지남」에 쌓이던 것 — 늦은 게 아니라 **추정일이 이른** 것이다.
    돈은 총액에 그대로 두되(받을 돈은 맞다) 「지남·미확인」 경고에서는 뺀다."""
    # 7/1 관측 + 자동확정7 + 주기15 = 7/23 → 14일 지남. 쿠팡은 70/30 분할.
    ln = _line(status="배송완료", market="coupang", src="estimated", incl=1000,
               status_at=dt.datetime(2026, 7, 1))
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["kpi"]["overdue"] == 0
    assert agg["kpi"]["not_started"] == 700        # 1차 70% 조각이 지남
    assert agg["kpi"]["unconfirmed_future"] == 300  # 잔여 30% 는 아직 미래
    assert agg["kpi"]["total_uncollected"] == 1000  # 사라지는 돈 0원


def test_마켓이_준_날짜가_지난_것은_진짜_입금일_지남():
    """실측 날짜가 지났으면 확정 전이어도 진짜 「지남」이다 — 마켓이 그날 준다고 했다."""
    ln = _line(status="배송완료", market="eleven11", date="2026-08-01", incl=400)
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["kpi"]["overdue"] == 400
    assert agg["kpi"]["not_started"] == 0


def test_정산시작전에도_사유와_지난일수가_붙는다():
    ln = _line(status="배송완료", market="coupang", src="estimated",
               status_at=dt.datetime(2026, 7, 1))
    r = SP.resolve(ln, DEFAULT_RULES, today=TODAY)
    ev = [e for e in r["events"] if e["bucket"] == "not_started"][0]
    assert ev["reason"] == "not_confirmed_yet"
    assert ev["days_over"] == 14


def test_정산시작전은_별도_줄로_드러난다():
    """조용히 사라지는 돈 0원 — extras 에 마켓·계정별로 남는다."""
    ln = _line(status="배송완료", market="eleven11", src="estimated", incl=500,
               account="계정A", status_at=dt.datetime(2026, 7, 1))
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["extras"]["not_started"]["eleven11"]["계정A"] == 500


def test_한참_지난_것은_확정_전이어도_이미_받았을_것():
    """30일(규칙표) 넘게 지난 건 기존대로 assumed_paid — 총액이 억 단위로 부푸는 걸 막는
    안전장치를 「정산 시작 전」이 밀어내면 안 된다."""
    ln = _line(status="배송완료", market="lotteon", src="estimated", incl=500,
               status_at=dt.datetime(2026, 4, 1))
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["kpi"]["assumed_paid"] == 500
    assert agg["kpi"]["not_started"] == 0


# ══ [2026-08-12] 「받는 날 기준」 과거 이력 (노션 c-2) ═════════════════════════
#  사장님: "받는날 기준 : 과거 것도 정산 받은 이력 보여줄 것."
#  기간 표가 미래만 보여줘서, 이미 받은 돈이 언제 들어왔는지 화면에서 알 수 없었다.

def test_이미_받은_것은_받은_날_칸에_담긴다():
    """「정산 받은 이력」의 날짜 축은 예정일이 아니라 **실제 받은 날**이다."""
    ln = _line(status="구매확정", date="2026-07-01", paid="2026-07-28", incl=900)
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="week", today=TODAY)
    pb = agg["past_buckets"]
    assert [b["key"] for b in pb] == ["2026-07-27"]      # 7/28 이 든 주(월요일)
    assert pb[0]["paid"] == 900 and pb[0]["total"] == 900
    assert pb[0]["markets"]["gmarket"]["accounts"]["계정A"]["paid"] == 900


def test_가짜_날짜는_받은_것으로_안_친다():
    """ESM 이 빈 값을 0001-01-01 로 내리는데, 그걸 「받았다」로 읽으면 안 된다.
    받은 것이 아니므로 과거 칸에도 「받음」이 아니라 다른 부류로 담긴다."""
    ln = _line(status="구매확정", date="2026-07-01", incl=900)
    ln["row"]["_settle_paid_date"] = "0001-01-01T00:00:00"   # 센티널 = 날짜 아님
    assert SP.classify(ln, today=TODAY) == "confirmed"       # paid 가 아니다
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["kpi"]["paid"] == 0
    assert sum(b["paid"] for b in agg["past_buckets"]) == 0
    assert sum(b["assumed_paid"] for b in agg["past_buckets"]) == 900


def test_과거칸은_미래_본표와_다른_그릇이다():
    """🔴 같은 그릇에 넣으면 기간별 「앞으로 받을 돈」이 과거분까지 먹어 거짓이 된다."""
    lines = [_line(status="구매확정", date="2099-08-20", incl=100),          # 미래
             _line(status="구매확정", date="2026-08-01", incl=700),          # 지남
             _line(status="구매확정", date="2026-07-01", paid="2026-07-02", incl=900)]
    agg = SP.aggregate_payout(lines, DEFAULT_RULES, unit="week", today=TODAY)
    assert sum(b["total"] for b in agg["buckets"]) == 100        # 미래 본표는 그대로
    assert sum(b["total"] for b in agg["past_buckets"]) == 1600  # 700 + 900
    assert agg["kpi"]["total_uncollected"] == 800                # 100 + 700, 안 건드림


def test_과거칸은_최근_날짜가_위():
    lines = [_line(status="구매확정", date="2026-06-01", paid="2026-06-02", incl=1),
             _line(status="구매확정", date="2026-07-01", paid="2026-07-02", incl=2)]
    agg = SP.aggregate_payout(lines, DEFAULT_RULES, unit="month", today=TODAY)
    assert [b["key"] for b in agg["past_buckets"]] == ["2026-07", "2026-06"]


def test_날짜_미정은_과거칸에_못_들어간다():
    ln = _line(status="구매확정", src="estimated")
    ln["status_at"] = None
    ln["row"]["주문일"] = ""
    agg = SP.aggregate_payout([ln], DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["kpi"]["undated"] == 10000
    assert agg["past_buckets"] == []


# ══ [2026-08-12] 주문일 축 판정 단일화 (노션 c-3) ════════════════════════════

def test_주문일축_판정은_집계와_목록이_같은_함수를_쓴다():
    """지급예정일 축에서 겪은 「KPI ↔ 드릴다운 어긋남」을 주문일 축에서도 막는다."""
    ln = _line(status="구매확정", incl=100)
    ln["row"]["_매출기준액"] = 12000
    ln["row"]["주문일"] = "2026-08-01 10:00"
    agg = SP.aggregate_by_order_date([ln], unit="day",
                                     d_from="2026-08-01", d_to="2026-08-31")
    hit = SP.order_axis_row(ln, unit="day")
    assert hit["bucket"] == agg["buckets"][0]["key"] == "2026-08-01"
    assert hit["revenue"] == agg["buckets"][0]["revenue"] == 12000
    assert hit["substituted"] is False


def test_주문일축_매출_대체는_줄마다_표시된다():
    """집계 meta 엔 건수만 있었다 — 어느 주문이 대체됐는지 목록에서도 알아야 한다."""
    ln = _line(status="구매확정", incl=100)
    ln["row"]["상품금액"] = 9000
    ln["row"]["배송비"] = 3000
    ln["row"]["주문일"] = "2026-08-01 10:00"
    hit = SP.order_axis_row(ln, unit="day")
    assert hit["revenue"] == 12000 and hit["substituted"] is True


def test_주문일축_클레임은_목록에서도_빠진다():
    for st in ("취소완료", "반품완료", "반품요청"):
        ln = _line(status=st, incl=100)
        ln["row"]["주문일"] = "2026-08-01 10:00"
        assert SP.order_axis_row(ln, unit="day") is None, st


def test_구매확정일이_오면_그것도_확정_증거다():
    """[2026-08-12] 롯데온 정산 응답에 seStdDt(정산기준일=구매확정일)가 **줄곧 있었는데**
    우리가 안 읽고 있었다(라이브 진단 36개 필드 중 하나로 확인). 날짜가 있으면
    「확정됐다」에 더해 **언제** 확정됐는지까지 아는 것이라 가장 단단한 증거다."""
    ln = _line(status="배송완료", market="lotteon", src="estimated")
    ln["row"]["_settle_confirmed_date"] = "2026-07-15"
    assert SP.classify(ln, today=TODAY) == "confirmed"
