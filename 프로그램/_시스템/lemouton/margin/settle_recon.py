# -*- coding: utf-8 -*-
"""마켓 정산 대조 — 마켓 정산 화면 엑셀 ↔ 우리 정산예정금액 (노션 주문관리 c-4).

사장님: "실마켓 계정 접속해서 실제 정산받는 금액과 비교 및 정합성 검사."

🔴 이 파일의 존재 이유 — 지금까지 정산 쪽엔 「업로드 → 전수 비교 → 저장·이력」 구조가
   **없었다**. 있던 건 읽기 전용 진단(`settle_parity` 쿠팡 회차 총액, `/diag/ss-settle`)
   뿐이라 사장님이 마켓 화면과 우리 숫자를 나란히 놓고 볼 방법이 없었다.
   판정 규율은 샵마인 대조(`markets/shopmine_recon.py`)와 **같은 결**을 쓴다 —
   애매한 것을 「일치」로 뭉개지 않는다.

🔴 기준일 규칙이 틀리면 대조 자체가 거짓이 된다. 그래서 노션에 적힌 규칙을 **코드에
   못 박고 화면에도 그대로 보여준다**(사장님이 마켓에서 어떤 기준일로 뽑았는지 확인 가능).

     쿠팡 로켓그로스 : 정산>로켓그로스 정산현황 (빠른정산금 제외됨)
                       기준일 매출인식일 2달 → 오늘 이후 정산일의 최종지급액 합
     쿠팡 일반 구매확정 : 정산>정산현황>정산예정, 기준일 정산일 2달
                       (빠른정산 제외분만 나옴 · 공제금액 F = 빠른정산 계좌인출액)
     쿠팡 일반 미구매확정 : 같은 화면, 기준일 결제일
     스마트스토어      : 정산관리>정산 내역(일별) > 정산예정일 1달
                       일반정산금액 + 빠른정산금액 (집하일 기준 선지급)

🔴 엑셀 양식을 우리가 정하지 못한다(마켓이 준다). 그래서 **열 이름을 추측으로 고르지
   않고**, 못 찾으면 파일에서 본 열 이름을 그대로 돌려주며 실패한다. 조용히 0원으로
   넘어가면 「대조했는데 일치」라는 가장 나쁜 거짓말이 된다.
"""
from __future__ import annotations

import datetime as dt
import io
import re

# ── 대조 항목 (노션 규칙 그대로) ──────────────────────────────────────────────
#  window_days = 마켓 화면에서 뽑으라고 안내한 기간(우리 값도 같은 창으로 잰다)
#  fast_excluded = 마켓 화면 숫자에 빠른정산 선인출분이 **빠져 있는가**
ITEMS = {
    "coupang_rg": {
        "라벨": "쿠팡 로켓그로스",
        "마켓화면": "정산 > 로켓그로스 정산현황",
        "기준일": "매출인식일 2달 → 오늘 이후 정산일의 최종지급액 합",
        "market": "coupang", "window_days": 60,
        "fast_excluded": True, "axis": "rocket_growth",
    },
    "coupang_confirmed": {
        "라벨": "쿠팡 일반정산 · 구매확정",
        "마켓화면": "정산 > 정산현황 > 정산예정 (구매확정)",
        "기준일": "정산일 2달 → 오늘 이후 정산일의 최종지급액 합 "
                  "(빠른정산 제외분만 나옴 · 공제금액 F = 빠른정산 계좌인출액)",
        "market": "coupang", "window_days": 60,
        "fast_excluded": True, "axis": "confirmed",
    },
    "coupang_unconfirmed": {
        "라벨": "쿠팡 일반정산 · 미구매확정",
        "마켓화면": "정산 > 정산현황 > 정산예정 (미구매확정)",
        "기준일": "결제일 기준 (빠른정산 해당 없음)",
        "market": "coupang", "window_days": 60,
        "fast_excluded": False, "axis": "unconfirmed",
    },
    "smartstore": {
        "라벨": "스마트스토어 정산예정",
        "마켓화면": "정산관리 > 정산 내역(일별) > 일별 정산내역",
        "기준일": "정산예정일 1달 · 일반정산금액 + 빠른정산금액 (집하일 기준 선지급)",
        "market": "smartstore", "window_days": 30,
        "fast_excluded": False, "axis": "both",
    },
}

#: 판정 — 샵마인 대조와 같은 어휘. 애매한 것을 「일치」로 뭉개지 않는다.
VERDICTS = ("match", "tol", "def", "diff", "unknown")
VERDICT_KO = {"match": "일치", "tol": "허용차이", "def": "정의차이",
              "diff": "불일치", "unknown": "판정불가"}

#: 반올림 누적 허용 — 건당 10원, 최소 100원. 합계 대조라 건수에 비례한다.
_TOL_PER_ROW = 10
_TOL_MIN = 100
#: 「정의차이」로 인정하는 폭 — 설명 항목 금액과 이만큼 안에서 맞으면 구조 차이로 본다.
_DEF_BAND = 0.005          # 0.5%
_DETAIL_CAP = 500          # 상세 목록 상한(요약 수치는 전수 — 잘림은 *_total 로 표기)


# ── 엑셀 읽기 ────────────────────────────────────────────────────────────────

def _norm_col(c) -> str:
    """열 이름 정규화 — 전각공백 포함 공백·괄호·쉼표 제거."""
    return re.sub(r"[\s　()（）,]+", "", str(c or ""))


def _num(v):
    """숫자만 남겨 정수로. 못 읽으면 None(0 으로 채우지 않는다)."""
    s = re.sub(r"[^0-9.\-]", "", str(v or ""))
    if s in ("", "-", ".", "-."):
        return None
    try:
        return int(round(float(s)))
    except (TypeError, ValueError):
        return None


def _ymd(v) -> str:
    t = str(v or "").strip().replace("/", "-").replace(".", "-")[:10]
    if len(t) == 8 and t.isdigit():
        t = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    try:
        dt.date.fromisoformat(t)
    except ValueError:
        return ""
    return t


#: 금액 열 후보 — 앞에 있을수록 우선. 「최종지급액」이 노션이 지목한 값이다.
_AMOUNT_ALIASES = ("최종지급액", "최종정산금액", "지급예정금액", "정산예정금액",
                   "정산금액", "지급액", "정산예정액", "최종지급금액")
#: 그 밖에 알아보면 좋은 열(있으면 쓴다 — 없다고 실패하지 않는다)
_DATE_ALIASES = ("정산일", "지급일", "정산예정일", "지급예정일", "매출인식일", "결제일")
_ORDER_ALIASES = ("주문번호", "오픈마켓주문번호", "묶음배송번호", "상품주문번호")
_FAST_ALIASES = ("빠른정산금액", "빠른정산", "추가상계금액", "빠른정산이용액")


def _pick(cols, aliases):
    for a in aliases:
        if a in cols:
            return a
    # 별칭이 열 이름 **안에** 들어 있는 경우(예: 「최종지급액(원)」 → 정규화로 이미 붙음)
    for a in aliases:
        for c in cols:
            if a in c:
                return c
    return ""


def parse_sheet(file_bytes: bytes) -> dict:
    """마켓 정산 엑셀 → {columns, amount_col, rows, ...}. 못 읽으면 ValueError.

    🔴 열 이름을 **추측하지 않는다**. 금액 열을 못 찾으면 파일에서 본 열 이름을 그대로
      담아 실패한다 — 조용히 0원으로 넘어가면 「대조했는데 일치」라는 거짓말이 된다.
    """
    import pandas as pd
    last_err = None
    df = None
    for kw in ({"dtype": str}, {"dtype": str, "header": 1}, {"dtype": str, "header": 2}):
        try:
            cand = pd.read_excel(io.BytesIO(file_bytes), **kw)
        except Exception as e:      # noqa: BLE001 — 다음 후보로 넘어간다
            last_err = e
            continue
        cols = [_norm_col(c) for c in cand.columns]
        if _pick(cols, _AMOUNT_ALIASES):
            cand.columns = cols
            df = cand
            break
        if df is None:
            cand.columns = cols
            df = cand               # 못 찾아도 첫 시도 결과는 들고 있는다(오류 문구용)
    if df is None:
        raise ValueError(f"엑셀을 읽지 못했습니다: {type(last_err).__name__}: {last_err}")
    cols = list(df.columns)
    amount_col = _pick(cols, _AMOUNT_ALIASES)
    if not amount_col:
        raise ValueError(
            "정산 금액 열을 찾지 못했습니다. 이 파일에서 본 열 이름은 "
            f"{cols[:40]} 입니다. 「최종지급액」·「정산예정금액」 같은 열이 있는 시트를 "
            "올려 주세요(머리글이 첫 줄이 아니면 그 줄까지 포함해 저장해 주세요).")
    date_col = _pick(cols, _DATE_ALIASES)
    order_col = _pick(cols, _ORDER_ALIASES)
    fast_col = _pick(cols, _FAST_ALIASES)
    rows, total, fast_total, dates = [], 0, 0, []
    for r in df.to_dict("records"):        # ⚠️ itertuples 금지(괄호 컬럼 깨짐)
        amt = _num(r.get(amount_col))
        if amt is None:
            continue                       # 합계줄·빈 줄 — 금액이 없으면 건너뛴다
        d = _ymd(r.get(date_col)) if date_col else ""
        f = _num(r.get(fast_col)) if fast_col else None
        total += amt
        if f:
            fast_total += f
        if d:
            dates.append(d)
        if len(rows) < _DETAIL_CAP:
            rows.append({"금액": amt, "날짜": d, "빠른정산": f or 0,
                         "주문번호": str(r.get(order_col) or "").strip() if order_col else ""})
    return {"columns": cols, "amount_col": amount_col, "date_col": date_col,
            "order_col": order_col, "fast_col": fast_col,
            "건수": int(df.shape[0]), "금액건수": len(
                [1 for r in df.to_dict("records") if _num(r.get(amount_col)) is not None]),
            "합계": total, "빠른정산합계": fast_total,
            "기간시작": min(dates) if dates else "", "기간끝": max(dates) if dates else "",
            "rows": rows, "상세잘림": int(df.shape[0]) > _DETAIL_CAP}


# ── 우리 값 ──────────────────────────────────────────────────────────────────

def ours_for(item_key: str, lines: list, rules: dict, *, today: dt.date,
             rg_summary: dict | None = None, fast_summary: dict | None = None) -> dict:
    """대조 항목별 **우리 값** — 마켓 화면과 같은 창·같은 축으로 잰다.

    재료가 없으면 금액을 지어내지 않고 `가능=False` 로 돌려준다(판정불가).
    """
    from lemouton.margin import settle_plan as SP
    from lemouton.margin.sell_source import _settlement_for
    spec = ITEMS.get(item_key)
    if spec is None:
        return {"가능": False, "왜": f"모르는 대조 항목입니다: {item_key}"}

    if spec["axis"] == "rocket_growth":
        rg = rg_summary or {}
        if not rg.get("회차수"):
            return {"가능": False, "금액": 0, "건수": 0,
                    "왜": "로켓그로스 정산 회차를 아직 안 가져왔어요 — "
                          "정산예정금액 탭의 「🚀 로켓그로스 가져오기」를 먼저 눌러 주세요."}
        # 마켓 화면이 「빠른정산금 제외」라 우리도 선인출을 뺀 값(=받을돈)으로 맞춘다.
        return {"가능": True, "금액": int(rg.get("받을돈") or 0),
                "건수": int(rg.get("회차수") or 0),
                "구성": f"지급액 {rg.get('지급액', 0):,} − 빠른정산 {rg.get('빠른정산', 0):,}"}

    until = today + dt.timedelta(days=spec["window_days"])
    want = ({"confirmed", "unconfirmed"} if spec["axis"] == "both"
            else {spec["axis"]})
    total, n = 0, 0
    for ln in lines:
        if ln.get("market") != spec["market"]:
            continue
        r = SP.resolve(ln, rules, today=today)
        if not r["events"]:
            continue
        amount, _src = _settlement_for(ln["row"])
        if not amount:
            continue
        for ev in r["events"]:
            if ev.get("bucket") not in want or not ev.get("date"):
                continue
            d = dt.date.fromisoformat(ev["date"])
            if today <= d <= until:
                total += ev["amount"]
                n += 1
    out = {"가능": True, "금액": total, "건수": n,
           "구성": f"{today.isoformat()} ~ {until.isoformat()} 지급예정 합"}
    if spec["fast_excluded"]:
        # 마켓 화면에서 빠져 있는 몫은 우리 쪽에서도 빼야 같은 것을 비교하게 된다.
        fw = int((fast_summary or {}).get("차감액") or 0)
        if fw:
            out["금액"] = max(0, out["금액"] - fw)
            out["구성"] += f" − 빠른정산 선인출 {fw:,}"
            out["빠른정산차감"] = fw
    return out


# ── 판정 ─────────────────────────────────────────────────────────────────────

def judge(market_total: int, ours: dict, *, rows: int,
          explains: dict | None = None) -> dict:
    """마켓 값 ↔ 우리 값 판정. 애매한 것을 「일치」로 뭉개지 않는다.

    explains = {이름: 금액} — 빠른정산 선인출·셀러월렛처럼 **구조적으로** 다를 수 있는
    항목. 차이가 그중 하나로 설명되면 「정의차이」(노랑)로 표기한다.
    """
    if not ours.get("가능"):
        return {"판정": "unknown", "차이": None, "왜": ours.get("왜") or "재료 없음"}
    gap = int(market_total) - int(ours["금액"])
    if gap == 0:
        return {"판정": "match", "차이": 0, "왜": "숫자가 정확히 같습니다"}
    tol = max(_TOL_MIN, _TOL_PER_ROW * max(rows, 1))
    if abs(gap) <= tol:
        return {"판정": "tol", "차이": gap,
                "왜": f"반올림 차이로 볼 수 있는 범위입니다(허용 ±{tol:,}원)"}
    for name, amt in (explains or {}).items():
        amt = int(amt or 0)
        if not amt:
            continue
        band = max(tol, int(abs(amt) * _DEF_BAND))
        if abs(abs(gap) - abs(amt)) <= band:
            return {"판정": "def", "차이": gap,
                    "왜": f"차이가 「{name}」({amt:,}원)와 거의 같습니다 — "
                          f"구조적으로 다른 항목이라 틀린 게 아닐 수 있어요"}
    pct = round(abs(gap) / market_total * 100, 2) if market_total else None
    return {"판정": "diff", "차이": gap,
            "왜": ("설명되지 않는 차이입니다"
                   + (f" (마켓 값의 {pct}%)" if pct is not None else "")
                   + " — 기준일·기간을 마켓 화면과 같게 뽑았는지 먼저 확인하세요")}


def reconcile(item_key: str, parsed: dict, lines: list, rules: dict, *,
              today: dt.date, rg_summary=None, fast_summary=None,
              wallet_summary=None) -> dict:
    """한 항목 대조 결과 — 화면·저장이 같은 dict 를 쓴다."""
    spec = ITEMS[item_key]
    ours = ours_for(item_key, lines, rules, today=today,
                    rg_summary=rg_summary, fast_summary=fast_summary)
    explains = {}
    if not spec["fast_excluded"]:
        # 마켓 화면에 빠른정산이 포함된 항목인데 우리가 못 담았다면 그만큼 차이가 난다.
        fw = int((fast_summary or {}).get("차감액") or 0)
        if fw:
            explains["빠른정산 선인출"] = fw
    wb = int((wallet_summary or {}).get("합계") or 0)
    if wb:
        explains["셀러월렛 미인출 잔액"] = wb
    v = judge(parsed["합계"], ours, rows=parsed.get("금액건수") or 0, explains=explains)
    return {
        "항목": item_key, "라벨": spec["라벨"], "마켓화면": spec["마켓화면"],
        "기준일규칙": spec["기준일"],
        "마켓값": parsed["합계"], "마켓건수": parsed.get("금액건수") or 0,
        "마켓기간": f"{parsed.get('기간시작') or '?'} ~ {parsed.get('기간끝') or '?'}",
        "읽은열": parsed.get("amount_col") or "",
        "우리값": ours.get("금액"), "우리건수": ours.get("건수"),
        "우리구성": ours.get("구성") or "",
        "판정": v["판정"], "판정한글": VERDICT_KO[v["판정"]],
        "차이": v["차이"], "왜": v["왜"],
        "설명후보": explains,
    }
