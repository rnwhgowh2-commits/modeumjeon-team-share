"""정산예정금액 탭 엔진 — 분류·지급이벤트·기간 버킷 집계 (순수 함수, DB 없음).

스펙: docs/superpowers/specs/2026-08-06-settle-plan-tab-design.md

■ 부류 상호배타 (스펙 §2 — 중복 원천 차단):
    excluded  = 클레임 행(_kind=change)·취소완료(zero_cancel)·송장 전 단계
    risk      = 반품·교환·취소 **진행 중** (예정액에서 빼고 별도 줄 — 돈 부풀리기 방지)
    paid      = 수령 확인(_settle_paid_date 있음 — ESM RemitDate·스스 settleCompleteDate)
    overdue   = 지급예정일 < 오늘인데 수령 확인 불가 (**조용히 빼지 않는다** — 별도 줄 상시)
    confirmed / unconfirmed = 미래 예정분 (본표). 상태 문자열로만 갈려 한 행은 한 곳에만.

■ 금액 = margin.sell_source._settlement_for(row) 그대로 (재계산 금지 — 마진계산기와
  같은 숫자를 보게 하는 단일 원천 규약을 이 탭도 따른다. 2026-07-23 「따로 논다」 사고 참조).

■ 지급예정일 = 실값(row.정산예정일 — 스윕이 저장) → 규칙 추정(settle_plan_rules) 순.
  추정 기준점(anchor)은 마켓 응답에 없는 값이라 **우리 관측 시각(status_at)** 근사 —
  그래서 항상 date_source='estimated' 배지가 붙는다(정직 표기).
  쿠팡 분할지급: 실값 두 날짜(settlementDate+finalSettlementDate)가 오면 실값으로,
  없으면 규칙(split_ratio·split_rest_days)으로 두 조각. 합=원금(반올림 유실 금지).
"""
from __future__ import annotations

import datetime as dt

from lemouton.margin.sell_source import _settlement_for

# 예정일이 이만큼 넘게 지났으면 「이미 받았을 것(확인 불가)」로 본다(규칙표에서 조정).
#  🔴 왜 필요한가 — 지급 완료를 알려주는 마켓이 사실상 없다(2026-08-06 라이브 실측:
#    ESM 은 SettleExpectDate·RemitDate 가 전 기준일에서 null, 쿠팡도 settlementDate 미도래).
#    그래서 오래 지난 건을 「입금일 지남·미수령」으로 두면 총액이 몇 억씩 부풀어 자금계획이
#    통째로 못 쓰게 된다. 단정 대신 별도 부류로 빼고 그 사실을 화면에 적는다.
ASSUME_PAID_AFTER_DAYS = 30

# 반품·교환·취소 "진행 중" — 완료(취소완료=excluded·반품완료 등 클레임 경로)와 구분.
_RISK_MARKERS = ("반품요청", "반품진행", "반품접수", "교환요청", "교환진행",
                 "취소요청", "취소접수", "취소철회대기", "미수취신고")
# 구매확정을 뜻하는 말 — 🔴 옥션·G마켓은 「구매결정」이라 쓴다(2026-08-06 라이브에서
#  1건이 미확정으로 잘못 분류돼 발견). 사유 판정(overdue_reason)은 이미 둘 다 확정으로
#  보고 있었는데 classify 만 「구매확정」 하나만 봐서 **같은 프로그램 안에서 기준이 어긋났다**.
_CONFIRMED_WORDS = ("구매확정", "구매결정")
_CONFIRMED = "구매확정"      # 하위호환(기존 참조)
# 🔴 [2026-08-12 사장님 신고] 마켓마다 확정을 부르는 말이 또 다르다 — **마켓별로 좁힌다**.
#  롯데온 odPrgsStepCd 에는 구매확정 코드가 **아예 없고** 「수취완료」(15)가 그 자리다
#  (order_export._STATUS_KO). 그래서 롯데온은 confirmed 부류가 **구조적으로 0건**이었고,
#  ①확정건에도 auto_confirm_days(7)가 덧붙어 예정일이 7일 이르게 잡히고
#  ②overdue_reason 이 늘 not_confirmed_yet 하나로 고정됐다(주석 실측 「롯데온 212건」).
#  ★ 전 마켓에 「수취완료」를 풀면 안 된다 — 다른 마켓에선 확정 전 단계일 수 있다.
_CONFIRMED_BY_MARKET = {"lotteon": ("수취완료",)}
# 송장 입력 후·확정 전 단계 — 스펙 2)번 부류의 근거 상태.
_SHIPPED_MARKERS = ("배송중", "배송완료", "발송완료", "수취완료")


def _is_confirmed(status: str, market: str = "") -> bool:
    words = _CONFIRMED_WORDS + _CONFIRMED_BY_MARKET.get(market, ())
    return any(w in status for w in words)


def line_confirmed(line: dict) -> bool:
    """이 주문 줄이 **구매확정됐는가** — 한 곳에서만 판정한다.

    서열: ①마켓 정산조회에 잡힌 증거 ②상태 문자열(마켓별 낱말).

    ①이 왜 먼저인가 — 롯데온 `SettleItmdSales` 는 **정산기준일 = 구매확정일**이라
    거기 잡혔다는 것 자체가 「구매확정됐다」는 마켓의 증언이다. 상태 문자열은 우리가
    별도 API(140 진행단계)로 따로 받아 오는 값이라 시차가 있고, 추측이 섞인다.

    🔴 `_settle_confirmed` 는 **True 만** 저장한다(order_ingest) — False 를 쓰면
    다음 회차(창 밖 주문)에서 확정을 지워 버린다.
    🔴 [2026-08-12 정정] 「응답에 구매확정 날짜가 없다」던 앞선 판단은 **틀렸다**.
    라이브 진단으로 원본 필드를 눈으로 보니 `seStdDt`(정산기준일=구매확정일)가
    36개 필드 중에 줄곧 있었다. 이제 그 날짜를 `_settle_confirmed_date` 로 적고,
    롯데온 지급내역(같은 날짜 축)에서 실입금일까지 찾아 붙인다.
    """
    row = line.get("row") or {}
    if row.get("_settle_confirmed") is True:
        return True
    # 🔴 [2026-08-12] 이제 **구매확정일 자체**가 온다(롯데온 seStdDt). 날짜가 있으면
    #   그게 가장 단단한 증거다 — 언제 확정됐는지까지 아는 것이다.
    if _norm_date(row.get("_settle_confirmed_date")):
        return True
    return _is_confirmed(str(row.get("주문상태") or ""), line.get("market") or "")


def _norm_date(s) -> str | None:
    """'2026-08-06'·'…T00:00:00'·'2026/08/06'·'20260806' → 'YYYY-MM-DD'.

    2000-01-01 이전은 센티널 → None. ESM 은 보류 사유를 1991-01-01 류 가짜 날짜로
    표현하고(SettleExceptName), 빈 값을 0001-01-01 로 내린다 — 날짜가 아니다.
    """
    t = str(s or "").strip().replace("/", "-")
    if not t:
        return None
    t = t[:10]
    if len(t) == 8 and t.isdigit():
        t = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    try:
        d = dt.date.fromisoformat(t)
    except ValueError:
        return None
    return t if d.year >= 2000 else None


# 반품·교환이 **끝난** 말 — 금액이 확정적으로 바뀐다(진행 중은 _RISK_MARKERS).
#  취소완료는 위에서 이미 excluded 로 빠지므로 여기 넣지 않는다.
_CLAIM_DONE_MARKERS = ("반품완료", "교환완료", "반품수거완료", "교환수거완료")


def annotate_claims(lines: list) -> list:
    """클레임 행을 **주문번호로 원래 주문행에 이어** 표식(`_claim`)을 남긴다.

    🔴 왜 필요한가 (2026-08-13 라이브 실측) — 클레임은 `_kind='change'` **별도 행**으로
       저장되고, 원래 주문행의 `주문상태` 는 **배송완료인 채 그대로**다. 그래서 반품이
       끝난 주문도 「받을 돈」에 살아 있었다: 쿠팡 미수령 22,487,606원 중 **51주문
       3,864,383원**. 두 행은 서로를 모른다 — 여기서 이어 준다.

    🔴 마켓 상태가 원래 행에 붙는 마켓(11번가·ESM)은 `_RISK_MARKERS` 로도 걸리지만,
       쿠팡은 원래 행 상태가 배송완료·상품준비중·결제완료·배송중·배송지시 **다섯뿐**이라
       (창내 3,343행 전수) 상태 문자열로는 영영 못 잡는다.

    표식: 'open'(진행 중 — 받을지 모름) / 'done'(끝남 — 금액이 확정적으로 바뀜).
    한 주문에 둘 다 달려 있으면 **done 이 이긴다**(요청 뒤에 완료가 오므로 완료가 최신).
    라이브에 그런 주문이 56건 있다.
    """
    state: dict = {}
    for ln in lines:
        row = ln.get("row") or {}
        if str(row.get("_kind") or "") != "change":
            continue
        key = (ln.get("market") or "", str(row.get("오픈마켓주문번호") or ""))
        if not key[1]:
            continue
        st = str(row.get("주문상태") or "")
        if any(m in st for m in _CLAIM_DONE_MARKERS):
            state[key] = "done"
        elif any(m in st for m in _RISK_MARKERS) and state.get(key) != "done":
            state[key] = "open"
    if not state:
        return lines
    for ln in lines:
        row = ln.get("row") or {}
        if str(row.get("_kind") or "") == "change":
            continue
        v = state.get((ln.get("market") or "", str(row.get("오픈마켓주문번호") or "")))
        if v:
            row["_claim"] = v
    return lines


def classify(line: dict, *, today: dt.date) -> str:
    """한 라인의 부류 — **다섯 가지**만. 조건 순서가 상호배타를 보장한다.

        excluded / risk / returned / paid / confirmed / unconfirmed

    🔴 [2026-08-06 교정] overdue·undated·assumed_paid 는 여기서 정하지 않는다 —
       **이벤트 단위**(resolve) 판정이다. 예전엔 여기서도 overdue 를 정하고
       aggregate 는 이벤트로 또 정해, KPI 는 5.5억인데 드릴다운은 0건인 어긋남이
       라이브에 나갔다. 판정은 resolve() 한 곳에서만 한다.
    """
    row = line["row"]
    if str(row.get("_kind") or "") == "change":
        return "excluded"
    st = str(row.get("주문상태") or "")
    if "취소완료" in st or str(row.get("_settle_source") or "") == "zero_cancel":
        return "excluded"
    if any(m in st for m in _RISK_MARKERS):
        return "risk"
    if _norm_date(row.get("_settle_paid_date")):
        return "paid"                       # 마켓이 「송금했다」고 알려준 것만
    # 🔴 [2026-08-13 사장님 확정] 반품·교환은 진행 중이든 끝났든 **받을 돈에서 뺀다**.
    #   다만 **반품비는 우리가 받는 돈**이라 남긴다(resolve 가 그 이벤트만 만든다).
    #   `paid` **뒤에** 본다 — 이미 받은 돈은 받을 돈이 아니라 지나간 이력이다.
    #   여기서 옮기면 「이미 받은 것」 이력이 흔들린다(라이브 15행 1,384,546원).
    _cl = str(row.get("_claim") or "")
    if _cl == "open":
        return "risk"
    if _cl == "done":
        return "returned"
    if line_confirmed(line):
        return "confirmed"
    if any(m in st for m in _SHIPPED_MARKERS):
        return "unconfirmed"
    return "excluded"      # 신규주문·발송대기 등 — 송장 전 단계는 스펙상 대상 아님


def _anchor(line: dict) -> tuple:
    """추정 기준점 (날짜, 주문일폴백여부).

    🔴 [2026-08-06 라이브 실측] status_at(우리가 그 상태를 처음 본 시각)은 **옛 저장분에
       없다** — 라이브 6,084건이 그래서 날짜를 못 정했다. 주문일은 거의 항상 있으므로
       폴백으로 쓴다(정확도는 낮지만 '추정' 배지가 그대로 붙어 정직하다).
    """
    at = line.get("status_at")
    if at is not None:
        return (at.date() if isinstance(at, dt.datetime) else at), False
    od = _norm_date(str(line["row"].get("주문일") or "")[:10])
    if od:
        return dt.date.fromisoformat(od), True
    return None, False


def _estimated_payout(line: dict, rules: dict) -> str | None:
    """규칙 추정 지급예정일. 기준점이 아예 없으면 None(날조 금지 — 「미정」으로 표기)."""
    anchor, from_order = _anchor(line)
    if anchor is None:
        return None
    market = line["market"]
    m = (rules.get("markets") or {}).get(market) or {}
    fast = line.get("account") in ((rules.get("fast_accounts") or {}).get(market) or [])
    st = str(line["row"].get("주문상태") or "")
    if from_order:
        # 주문일부터의 **전 여정**(배송 → 자동확정 → 지급). 현재 상태는 쓰지 않는다 —
        # 주문일 기준이면 그 사이 단계를 이미 다 거쳤다고 보는 게 일관적이다.
        days = int(m.get("order_to_delivered_days") or 0)
        days += (int(m.get("fast_cycle_days") or 1) if fast
                 else int(m.get("auto_confirm_days") or 0) + int(m.get("cycle_days") or 0))
        return (anchor + dt.timedelta(days=days)).isoformat()
    if fast:
        # 빠른정산 = 발송(집화) 기준 선지급. 관측시각 ≈ 발송 이후이므로 anchor 그대로.
        return (anchor + dt.timedelta(days=int(m.get("fast_cycle_days") or 1))).isoformat()
    days = int(m.get("cycle_days") or 0)
    if not line_confirmed(line):
        days += int(m.get("auto_confirm_days") or 0)
        if "배송중" in st or "발송완료" in st:
            days += int(m.get("transit_days") or 0)
    return (anchor + dt.timedelta(days=days)).isoformat()


def payout_events(line: dict, rules: dict, *, today: dt.date) -> list[dict]:
    """한 라인의 지급 이벤트(0~2개). 쿠팡 분할지급은 두 조각, 합=원금(유실 금지)."""
    row = line["row"]
    amount, _src = _settlement_for(row)
    if not amount:
        return []
    market = line["market"]
    m = (rules.get("markets") or {}).get(market) or {}
    real = _norm_date(row.get("정산예정일"))
    final = _norm_date(row.get("_settle_final_date"))
    if real:
        if final and final != real:
            first = round(amount * float(m.get("split_ratio") or 1.0))
            return [{"date": real, "amount": first, "date_source": "real"},
                    {"date": final, "amount": amount - first, "date_source": "real"}]
        return [{"date": real, "amount": amount, "date_source": "real"}]
    est = _estimated_payout(line, rules)
    if est is None:
        return [{"date": None, "amount": amount, "date_source": None}]
    ratio = float(m.get("split_ratio") or 1.0)
    if ratio < 1.0:
        first = round(amount * ratio)
        rest_d = (dt.date.fromisoformat(est)
                  + dt.timedelta(days=int(m.get("split_rest_days") or 0))).isoformat()
        return [{"date": est, "amount": first, "date_source": "estimated"},
                {"date": rest_d, "amount": amount - first, "date_source": "estimated"}]
    return [{"date": est, "amount": amount, "date_source": "estimated"}]


def _return_fee_events(line: dict, rules: dict, *, today: dt.date) -> list:
    """반품·교환 걸린 주문에서 **반품비만** 남긴 지급 이벤트 (0~1개).

    🔴 사장님 확정(2026-08-13): *"반품진행중과 반품 완료건은 금액에서 제외해줘야지.
       다만 반품비정도 추가해야지."*

    🔴 **더하지 않는다 — 마켓이 준 부호를 그대로 싣는다.** 라이브 전건 확인 결과
       쿠팡은 배송비 정산이 **받는 게 4건 · 내는(음수) 게 15건**이다(−9,670 형태).
       무조건 더하면 15건에서 반대로 틀린다. 11번가는 양수로 온다(clmReqSeq 라인).

    🔴 실값(`_ship_settle`)이 없으면 **아무것도 안 만든다.** 반품비를 규칙으로 지어내면
       없는 돈이 총액에 선다 — 반품 건은 규칙이 맞을 근거가 아예 없다.
       (그래서 쿠팡 말고는 대개 0건이다 — 다른 마켓은 아직 배송비 실값을 안 싣는다.)
    """
    fee = line["row"].get("_ship_settle")
    try:
        fee = int(fee)
    except (TypeError, ValueError):
        return []
    if not fee:
        return []
    real = _norm_date(line["row"].get("정산예정일"))
    d = real or _estimated_payout(line, rules)
    if d is None:
        return [{"date": None, "amount": fee, "date_source": None, "bucket": "undated"}]
    # 반품비 금액 자체는 마켓이 정한 실값이라 「확정」으로 담는다(날짜만 추정일 수 있다).
    bucket = "confirmed" if dt.date.fromisoformat(d) >= today else "overdue"
    return [{"date": d, "amount": fee, "bucket": bucket, "reason": "return_fee",
             "date_source": "real" if real else "estimated"}]


# 「입금했다」를 실제로 알려주는 마켓 — 2026-08-06 실측으로 확정.
#  · 쿠팡  = 지급내역조회(settlement-histories) status DONE
#  · 스스  = 정산 완료일(settleCompleteDate)
#  나머지 4곳(롯데온·11번가·옥션·G마켓)은 **입금 여부를 알려주는 창구가 없다** →
#  받는 날이 지나도 우리가 확인할 방법이 없다(통장·마켓 화면 대조가 유일).
_PAID_CONFIRM_MARKETS = ("coupang", "smartstore")

_MK_KO = {"coupang": "쿠팡", "smartstore": "스마트스토어", "lotteon": "롯데온",
          "eleven11": "11번가", "auction": "옥션", "gmarket": "G마켓"}


def overdue_reason(line: dict, *, market: str) -> str:
    """「받는 날이 지났는데 확인 안 됨」의 사유 코드.

    라이브 실측(2026-08-06, 393건) — 대부분은 **돈이 밀린 게 아니다**:
      not_confirmed_yet  289건 (롯데온 212·쿠팡 74·옥션 2·스스 1)
        = 배송완료인데 아직 구매확정 전. 정산은 구매확정 뒤에 시작하므로 「지남」이 아니라
          「아직 시작 안 함」이다. 추정 날짜가 이른 것.
      no_confirm_channel 104건 (11번가)
        = 마켓이 준 송금예정일이 지났는데, 그 마켓은 입금 완료를 알려주지 않는다.
    """
    if not line_confirmed(line):
        return "not_confirmed_yet"
    if market not in _PAID_CONFIRM_MARKETS:
        return "no_confirm_channel"
    return "not_in_batch"


def reason_text(code: str, market: str) -> dict:
    """사유 코드 → 사장님이 읽는 말 {뜻, 확인}. 화면·API 가 같은 문구를 쓴다."""
    mk = _MK_KO.get(market, market)
    if code == "not_confirmed_yet":
        return {"뜻": f"아직 구매확정 전이에요 (배송은 끝남) — 정산은 구매확정 뒤에 시작합니다",
                "확인": f"{mk}에서 구매확정이 됐는지 보세요. 배송완료로 오래 머물면 "
                        f"주문 상태를 다시 불러오거나 {mk}에 문의가 필요합니다"}
    if code == "no_confirm_channel":
        return {"뜻": f"{mk}이(가) 알려준 받는 날이 지났어요 — {mk}은(는) 입금했는지를 "
                      f"알려주지 않아 우리가 확인할 수 없습니다",
                "확인": f"통장 또는 {mk} 판매자센터 정산 화면과 대조해 보세요"}
    if code == "not_in_batch":
        return {"뜻": f"{mk} 정산 회차에 아직 안 잡혔어요",
                "확인": f"며칠 뒤 다시 보시거나 {mk} 정산 화면에서 확인하세요"}
    return {"뜻": "", "확인": ""}


def resolve(line: dict, rules: dict, *, today: dt.date) -> dict:
    """행 하나의 **최종 판정** — 부류 + 지급 이벤트(각 이벤트에 bucket 표식).

    🔴 aggregate(집계)와 detail(드릴다운)이 **같은 이 함수**를 쓴다. 예전엔 둘이 따로
       판정해 「KPI 5.5억 · 드릴다운 0건」이 라이브에 나갔다(2026-08-06).

    bucket ∈ confirmed | unconfirmed | overdue | not_started | undated | assumed_paid
      · undated      = 날짜를 정할 근거가 없음(실값도 기준점도 없음) — **기한 경과 아님**
      · not_started  = **아직 정산이 시작도 안 됨** — 구매확정 전인데 우리 **추정** 날짜만
        지난 것. 돈이 밀린 게 아니라 추정일이 이른 것이다(2026-08-12 사장님 신고:
        "쿠팡 배송완료인데 왜 입금일 지남에 있음?"). 총액에는 그대로 넣되(받을 돈은
        맞다) 「지남·미확인」 경고에서 빼 별도 줄로 적는다.
      · assumed_paid = 예정일이 한참(규칙표 assume_paid_after_days) 지남 → 이미 받았다고
        본다. 지급 완료를 알려주는 마켓이 사실상 없어(ESM·쿠팡 날짜 null 실측) 「안 받았다」
        고 단정할 수 없기 때문이다. 총액에서 빼되 화면에 별도로 적는다(숨기지 않는다).
        🔴 not_started 보다 **먼저** 본다 — 한참 지난 건 총액을 억 단위로 부풀리는 쪽이
        더 위험하다(이 안전장치를 새 부류가 밀어내면 안 된다).
    """
    cat = classify(line, today=today)
    if cat in ("risk", "returned"):
        # 🔴 상품분은 「받을 돈」에서 빠지고(별도 줄), **반품비만** 이벤트로 남는다.
        return {"category": cat, "events": _return_fee_events(line, rules, today=today)}
    if cat in ("excluded", "paid"):
        return {"category": cat, "events": []}
    evs = payout_events(line, rules, today=today)
    limit = int(rules.get("assume_paid_after_days") or ASSUME_PAID_AFTER_DAYS)
    confirmed = line_confirmed(line)
    for ev in evs:
        if ev["date"] is None:
            ev["bucket"] = "undated"
            continue
        d = dt.date.fromisoformat(ev["date"])
        if d >= today:
            ev["bucket"] = cat
            continue
        if (today - d).days > limit:
            ev["bucket"] = "assumed_paid"
            continue
        # 마켓이 준 날짜(real)가 지난 것만 진짜 「지남」이다. 확정 전 주문의 **추정**
        #  날짜는 우리 규칙이 이르게 잡은 것일 뿐이라 「지남」이라 부르면 거짓말이 된다.
        ev["bucket"] = ("overdue" if (ev["date_source"] == "real" or confirmed)
                        else "not_started")
        # 왜 그 자리에 있는지를 같이 들려 보낸다 — 숫자만으론 뭘 해야 할지 알 수 없다.
        ev["reason"] = overdue_reason(line, market=line["market"])
        ev["days_over"] = (today - d).days
    return {"category": cat, "events": evs}


def bucket_key(date_str: str, unit: str) -> str:
    d = dt.date.fromisoformat(date_str[:10])
    if unit == "week":
        return (d - dt.timedelta(days=d.weekday())).isoformat()   # 월요일 시작
    if unit == "month":
        return date_str[:7]
    return d.isoformat()


def aggregate_payout(lines: list, rules: dict, *, unit: str,
                     today: dt.date) -> dict:
    """지급예정일 축 집계 — 본표(미래 확정/미확정) + 별도 줄들.

    🔴 사라지는 돈 0원 원칙 — 어느 부류든 kpi·extras 로 항상 노출한다.
    total_uncollected = 미래예정 + 기한경과 + 정산시작전 + 날짜미정.
      · risk(반품·취소 진행)와 assumed_paid(이미 받았을 것)는 **합산 제외**하고 따로 적는다.
      · not_started(정산 시작 전)는 **합산에 넣는다** — 받을 돈이 맞고, 다만 「지남」이
        아닐 뿐이다. 총액에서 빼면 자금계획이 거꾸로 쪼그라든다.
    """
    kpi = {"confirmed_future": 0, "unconfirmed_future": 0, "overdue": 0,
           "not_started": 0, "undated": 0, "assumed_paid": 0, "risk": 0,
           # 🔴 [2026-08-13] 반품·교환이 **끝난** 몫 — 받을 돈에서 빼되 숨기지 않는다.
           "returned": 0, "paid": 0,
           "total_uncollected": 0}
    counts = {"real_dates": 0, "estimated_dates": 0, "undated": 0}
    buckets: dict = {}
    extras = {"overdue": {}, "not_started": {}, "undated": {},
              "assumed_paid": {}, "risk": {}, "returned": {}}
    reasons: dict = {}      # 「지남」이 무엇 때문인지 — 카드 옆 한눈 요약
    # 🔴 [2026-08-12 노션 c-2] 「받는 날 기준」인데 **미래만** 보였다. 과거 칸(이미 받은
    #   이력·아직 못 받은 지난 것)을 날짜 칸으로 따로 만든다.
    #   ★ buckets(미래 본표)와 **다른 그릇**에 담는다 — 같은 그릇에 넣으면 b["total"]
    #     과 빠른정산 차감(apply_fast_withdrawn)이 과거분까지 먹어 기간 표가 거짓이 된다.
    #   ★ kpi/total_uncollected 는 손대지 않는다 — 이건 **보여주기**지 새 합계가 아니다.
    past: dict = {}
    _PAST_KINDS = ("paid", "assumed_paid", "overdue", "not_started")

    def _acc(d, market, account, amt):
        mk = d.setdefault(market, {})
        mk[account] = mk.get(account, 0) + amt

    def _past_acc(dstr, market, account, kind, amt):
        z = dict.fromkeys(_PAST_KINDS, 0)
        b = past.setdefault(bucket_key(dstr, unit), {"markets": {}, "total": 0, **z})
        b[kind] += amt
        b["total"] += amt
        mk = b["markets"].setdefault(market, {**z, "accounts": {}})
        mk[kind] += amt
        a = mk["accounts"].setdefault(account, dict(z))
        a[kind] += amt

    for ln in lines:
        r = resolve(ln, rules, today=today)
        cat = r["category"]
        if cat == "excluded":
            continue
        amount, _src = _settlement_for(ln["row"])
        if not amount:
            continue
        market, account = ln["market"], ln.get("account") or ""
        if cat == "paid":
            kpi["paid"] += amount
            # 마켓이 「이 날 송금했다」고 알려준 것 — 이게 진짜 「정산 받은 이력」이다.
            #  날짜를 모르면 칸에 안 넣는다(날조 금지). 총액 kpi["paid"] 에는 그대로 남는다.
            _pd = _norm_date(ln["row"].get("_settle_paid_date"))
            if _pd:
                _past_acc(_pd, market, account, "paid", amount)
            continue
        if cat in ("risk", "returned"):
            # 🔴 상품분은 **별도 줄**로만 적는다(받을 돈 총액엔 안 들어간다).
            #   그리고 `continue` 하지 않는다 — 아래 공통 경로로 **반품비 이벤트**를
            #   흘려보내야 「반품비는 받는 돈」이 총액에 선다(사장님 확정 2026-08-13).
            kpi[cat] += amount
            _acc(extras[cat], market, account, amount)
        for ev in r["events"]:
            if ev["date_source"] == "real":
                counts["real_dates"] += 1
            elif ev["date_source"] == "estimated":
                counts["estimated_dates"] += 1
            else:
                counts["undated"] += 1
            b_name = ev["bucket"]
            if b_name in ("overdue", "not_started", "undated", "assumed_paid"):
                kpi[b_name] += ev["amount"]
                _acc(extras[b_name], market, account, ev["amount"])
                # 지난 날짜가 있는 것은 과거 칸에도 담는다 — 「그 주에 뭐가 있었나」를
                #  보려는 것이다(undated 는 날짜가 없으니 칸에 못 넣는다).
                if b_name != "undated" and ev.get("date"):
                    _past_acc(ev["date"], market, account, b_name, ev["amount"])
                if b_name == "overdue" and ev.get("reason"):
                    rs = reasons.setdefault(ev["reason"], {"금액": 0, "건수": 0, "마켓": {}})
                    rs["금액"] += ev["amount"]
                    rs["건수"] += 1
                    rs["마켓"][market] = rs["마켓"].get(market, 0) + ev["amount"]
                continue
            kpi[f"{b_name}_future"] += ev["amount"]
            b = buckets.setdefault(bucket_key(ev["date"], unit),
                                   {"markets": {}, "total": 0})
            slot = b["markets"].setdefault(market, {"confirmed": 0, "unconfirmed": 0,
                                                    "accounts": {}})
            slot[b_name] += ev["amount"]
            a = slot["accounts"].setdefault(account, {"confirmed": 0, "unconfirmed": 0})
            a[b_name] += ev["amount"]
            b["total"] += ev["amount"]
    kpi["total_uncollected"] = (kpi["confirmed_future"] + kpi["unconfirmed_future"]
                                + kpi["overdue"] + kpi["not_started"] + kpi["undated"])
    return {"kpi": kpi, "meta": counts, "extras": extras,
            "overdue_reasons": reasons,
            "buckets": [{"key": k, **v} for k, v in sorted(buckets.items())],
            # 최근 날짜가 위 — 「이력」은 뒤에서부터 읽는 게 자연스럽다.
            "past_buckets": [{"key": k, **v}
                             for k, v in sorted(past.items(), reverse=True)]}


def apply_fast_withdrawn(agg: dict, ledger_rows: list, *, unit: str) -> dict:
    """빠른정산으로 **이미 받은 돈**을 그 회차 지급일이 속한 칸에서 뺀다.

    🔴 왜 칸에서 빼나(2026-08-06 사장님) — "결국 기간내 얼마 받을지 아는게 중요해.
      이미 받은걸로 헷갈리게 안했으면 좋겠어." 총액에서만 빼면 **기간별 표는 그대로 부풀어**
      「8월 2주차에 얼마 들어오나」가 거짓이 된다. 그 회차가 지급될 칸에서 빼야 칸이 진실이 된다.

    규칙(전부 「없는 돈을 깎지 않는다」로 수렴):
      · 지급 끝난 회차(DONE)는 **건드리지 않는다** — 그 주문은 이미 「받은 것」이라 칸에 없다.
      · 상태를 모르는 옛 장부도 안 뺀다 — 근거 없이 깎으면 거짓 안심이 된다.
      · 뺄 칸이 없거나 칸 잔액이 모자라면 **뺀 만큼만** 반영하고 나머지는 `빠른정산_칸밖` 으로 드러낸다.

    확정/미확정 내역은 손대지 않는다 — 회차 단위 금액이라 부류로 나눌 근거가 없다.
    대신 칸·마켓·계정에 `fast` 를 적어 화면이 「−N」을 보여줄 수 있게 한다.
    """
    by_key = {b["key"]: b for b in (agg.get("buckets") or [])}
    칸밖 = 0
    뺀합 = 0
    for r in ledger_rows or []:
        amt = int(r.get("fastWithdrawn") or 0)
        st = str(r.get("status") or "")
        if amt <= 0 or not st or st == "DONE":
            continue
        sd = str(r.get("settlementDate") or "")[:10]
        b = by_key.get(bucket_key(sd, unit)) if sd else None
        if b is None:
            칸밖 += amt
            continue
        뺄 = min(amt, int(b.get("total") or 0))
        if 뺄 < amt:
            칸밖 += amt - 뺄
        if 뺄 <= 0:
            continue
        b["total"] -= 뺄
        뺀합 += 뺄
        mk = b.setdefault("markets", {}).setdefault(
            r.get("market") or "", {"confirmed": 0, "unconfirmed": 0, "accounts": {}})
        mk["fast"] = int(mk.get("fast") or 0) + 뺄
        acc = mk.setdefault("accounts", {}).setdefault(
            r.get("account") or "", {"confirmed": 0, "unconfirmed": 0})
        acc["fast"] = int(acc.get("fast") or 0) + 뺄
    kpi = agg.setdefault("kpi", {})
    kpi["fast_withdrawn"] = 뺀합
    kpi["net_uncollected"] = max(0, int(kpi.get("total_uncollected") or 0) - 뺀합)
    agg["빠른정산_칸밖"] = 칸밖
    return agg


# 마켓별 기대 수수료율(%) — 2026-08-02 사장님 확정분(market_fee_defaults 시드와 같은 값).
#  정산율이 이것과 크게 어긋나면 돈이 틀어진 신호다.
#  🔴 lotteon 18.0 → 13.0 (2026-08-06 사장님 확인) — 18% 는 어디서도 뒷받침되지 않아
#     라이브에 **9.6%p 거짓 경고**를 띄우고 있었다. 기본 계약율은 13%(+배송 3.3%,
#     유입경로가 「제휴」면 상품가의 2% 추가)이고 `lotteon_settlement.compute_settlement`
#     의 rate_product 도 0.13 이다. 정산액 자체는 마켓 실값(pymtTgtAmt)이라 문제없었다.
#     ★ 판매자부담수수료·유입경로에 따라 실효율이 흔들리므로 단일 숫자로는 근사일 뿐이다
#       (그래서 임계 RATE_WARN_GAP_PCT 를 5%p 로 넉넉히 둔다).
_EXPECT_FEE_PCT = {"coupang": 11.55, "smartstore": 6.0, "lotteon": 13.0,
                   "eleven11": 11.0, "auction": 15.0, "gmarket": 15.0}
#: 이 %p 이상 어긋나면 경고 — 카테고리·경유 수수료 편차를 감안한 여유.
RATE_WARN_GAP_PCT = 5.0


def rate_watch(market_rows: list) -> dict:
    """매출 대비 정산율을 마켓 기대 수수료율과 대조한다(돈 틀어짐 조기 감시).

    🔴 왜 필요한가(2026-08-06 라이브) — 정산율이 6월 90.5%·7월 92.4% 로 나왔다.
      수수료가 6~18% 인데 7~9% 만 뗀 셈이라 **정산액 과대 또는 매출 과소**가 의심되는데,
      화면 어디에도 그걸 알아챌 장치가 없었다. 숫자를 나란히 놓고 어긋나면 말한다.

    market_rows = [{"market","revenue","settle"}] · 재료 없는 마켓은 담지 않는다(날조 금지).
    """
    out = {}
    for r in market_rows or []:
        mk = r.get("market")
        rev = r.get("revenue") or 0
        stl = r.get("settle") or 0
        if not mk or rev <= 0 or stl <= 0:
            continue
        rate = round(stl / rev * 100, 1)
        exp = _EXPECT_FEE_PCT.get(mk)
        if exp is None:
            out[mk] = {"정산율": rate, "기대수수료": None, "차이": None, "경고": False}
            continue
        gap = round(abs((100 - rate) - exp), 2)       # 실수수료 vs 기대수수료 차이(%p)
        out[mk] = {"정산율": rate, "기대수수료": exp, "실수수료": round(100 - rate, 1),
                   "차이": gap, "경고": gap >= RATE_WARN_GAP_PCT}
    return out


def order_axis_row(line: dict, *, unit: str = "day",
                   d_from: str = "", d_to: str = "") -> dict | None:
    """주문일 축에 **이 줄이 들어가는가** + 그 줄의 매출액·정산액을 한 곳에서 정한다.

    🔴 왜 함수로 뽑았나 — 집계(aggregate_by_order_date)와 드릴다운 목록이 각자
      「무엇을 빼는가」를 정하면 반드시 갈라진다. 지급예정일 축에서 이미 겪은 사고다
      (KPI 5.5억 · 드릴다운 0건, 2026-08-06). 두 쪽이 이 함수 하나만 부른다.

    제외 = 클레임 행(_kind=change) · 취소완료 · 반품완료 · 반품/교환/취소 **진행 중**.
    매출액 = order_export._매출기준액(판매가+배송비, 할인 무관) 그대로 — 마진계산기와
      같은 정의를 쓴다(2026-08-27 「이 화면만 옛 정의로 따로 논다」 사고 교정).
      옛 저장분이라 그 칸이 없으면 상품금액+배송비로 **대체**하고 그 사실을 표시한다.
    """
    from lemouton.markets.order_export import _to_int
    row = line["row"]
    if str(row.get("_kind") or "") == "change":
        return None
    st = str(row.get("주문상태") or "")
    if "취소완료" in st or "반품완료" in st or any(m in st for m in _RISK_MARKERS):
        return None
    od = str(row.get("주문일") or "")[:10]
    if not od or (d_from and od < d_from) or (d_to and od > d_to):
        return None
    rev = _to_int(row.get("_매출기준액"))
    substituted = False
    if not rev:
        p = _to_int(row.get("상품금액"), 0) or 0
        s = _to_int(row.get("배송비"), 0) or 0
        rev = p + s
        substituted = bool(rev)
    settle, src = _settlement_for(row)
    return {"bucket": bucket_key(od, unit), "주문일": od,
            "revenue": rev or 0, "settle": settle or 0,
            "substituted": substituted, "settle_source": src}


def aggregate_by_order_date(lines: list, *, unit: str = "day",
                            d_from: str = "", d_to: str = "") -> dict:
    """주문일 축 — 클레임(취소완료·반품완료·클레임 행·위험 진행분) 제외
    매출액 + 정산예정금 합계.

    매출액 = _매출기준액(판매가+배송비, 할인 무관), 없으면 상품금액+배송비 대체 —
    대체 건수를 meta 로 표기한다(조용한 대체 금지, 스펙 재검토 구멍⑤).
    """
    buckets: dict = {}
    substituted = 0
    for ln in lines:
        hit = order_axis_row(ln, unit=unit, d_from=d_from, d_to=d_to)
        if hit is None:
            continue
        if hit["substituted"]:
            substituted += 1
        rev, settle = hit["revenue"], hit["settle"]
        b = buckets.setdefault(hit["bucket"],
                               {"revenue": 0, "settle": 0, "markets": {}})
        b["revenue"] += rev or 0
        b["settle"] += settle or 0
        mk = b["markets"].setdefault(ln["market"], {"revenue": 0, "settle": 0})
        mk["revenue"] += rev or 0
        mk["settle"] += settle or 0
    # 전 기간 마켓별 합으로 정산율 감시 — 「이 마켓 수수료가 이상하다」를 화면이 말한다.
    tot: dict = {}
    for b in buckets.values():
        for mk, v in (b.get("markets") or {}).items():
            t = tot.setdefault(mk, {"market": mk, "revenue": 0, "settle": 0})
            t["revenue"] += v.get("revenue") or 0
            t["settle"] += v.get("settle") or 0
    return {"meta": {"revenue_substituted": substituted},
            "rate_watch": rate_watch(list(tot.values())),
            "buckets": [{"key": k, **v} for k, v in sorted(buckets.items())]}
