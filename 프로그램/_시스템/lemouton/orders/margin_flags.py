# -*- coding: utf-8 -*-
"""주문 내역 가로 탭 판정 — 마진 계산기 규칙을 **그대로 옮긴 것**.

설계서 `docs/superpowers/specs/2026-08-06-실매입가-주문통합-design.md` §6.1 (2단계).

## 🔴 재구현이 아니다 — 어디서 옮겨 왔는지

| 옮긴 것 | 원본 | 원본 위치 |
|---|---|---|
| 손실(블랙스팟)·고마진·계산불가·분류 | `MR.*` | `webapp/static/margin_rules.js` (전체) |
| 고마진 임계값 40% · 5,000원 | `window.userSettings` 기본값 | `webapp/templates/orders/margin_embed.html:1735` |
| `isHighMargin(rate, amt)` | 같은 이름 함수 | `margin_embed.html:1783` |
| 이상마진 한 줄 판정 | `isAbnormalMarginRow` | `margin_embed.html:2222` |
| 이상마진 **건수**의 거르개 | `renderAbnormalBanner` | `margin_embed.html:2233` |
| 순마진·마진율·이상가 산식 | `recomputeRow` | `margin_embed.html:3327` |
| 취소·반품 제외 | `isExcluded` | `webapp/static/order_claim_scope.js:48` |

임계값을 여기서 새로 정하지 않는다. 바꿔야 하면 **원본을 바꾸고 이 파일을 따라 고친다**
(대조 시험 `tests/orders/test_margin_flags.py` 가 원본 JS 를 Node 로 돌려 맞춰 본다).

마진 계산기 자체는 **읽기만** 한다 — 이 파일은 그 화면의 동작을 하나도 바꾸지 않는다.

## 왜 주문 내역에서 다시 판정하나

마진 계산기의 판정은 브라우저 안에서만 살아 있어, 주문 내역 표는 「이 줄이 이상한지」를
알 수 없었다. 같은 규칙을 서버에 두면 주문 표가 **이미 받아 온 행**을 거르는 것만으로
같은 답을 낸다(탭을 눌러도 서버를 다시 부르지 않는다).

## 🔴 매입가를 모르면 판정하지 않는다

이상마진·블랙스팟은 매입가가 있어야 나온다. 없으면 **추측하지 않고** 「매입가 미입력」
탭으로 보낸다. 정산예정금을 못 읽은 줄도 마찬가지로 판정에서 빠진다(0 으로 채우면
멀쩡한 주문이 「돈 못 받음」으로 둔갑한다).
"""
from __future__ import annotations

import re

# ── 이식한 임계값 (원본 위치는 위 표) ─────────────────────────────
HIGH_MARGIN_RATE = 40           # margin_embed.html:1735 highMarginRate
HIGH_MARGIN_AMOUNT = 5000       # margin_embed.html:1735 highMarginAmount
BLACKSPOT_MEMO_KW = ("블랙",)     # margin_rules.js:14 기본 키워드
BLACKSPOT_MANGO_KW = ("오류입고",)
ABNORMAL_PRICE_MULT = 3         # margin_embed.html:3340 이상가
ABNORMAL_PRICE_ABS = 500000

# 마진 계산기 행이 쓰는 칸 이름 (여기 값을 바꾸면 원본과 갈린다)
F_SETTLE = "정산예상금액"
F_BUY = "구매가격"
F_MEMO = "간단메모"
F_MANGO = "더망고주문상태 (사용자 연동)"


# ══════════════════════════════════════════════════════════════════
#  1. margin_rules.js 이식 — 분류 단일 원천
# ══════════════════════════════════════════════════════════════════

def num(v) -> float:
    """`MR.num` — `Number(String(v).replace(/,/g,''))`, 못 읽으면 0."""
    if v is None:
        return 0.0                       # JS: String(null)='null' → NaN → 0
    if isinstance(v, bool):
        return 1.0 if v else 0.0         # JS: Number(true)===1
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def jsnum(v) -> float:
    """JS `Number(v) || 0` — 🔴 `num()` 과 달리 **쉼표를 안 지운다**.

    원본 `recomputeRow`·`isAbnormalMarginRow` 는 `MR.num` 이 아니라 맨 `Number()` 를 쓴다.
    그래서 `'70,000'` 같은 문자열이 오면 원본은 **0** 으로 읽는다. 여기서 쉼표를
    지워 주면 「고쳐 준 것」이 되어 원본과 답이 갈린다(대조 시험이 실제로 잡아냈다).
    """
    if v is None:
        return 0.0                       # JS: Number(null)===0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v) or 0.0
    s = str(v).strip()
    if not s:
        return 0.0                       # JS: Number('')===0
    try:
        return float(s) or 0.0
    except ValueError:
        return 0.0                       # NaN → `|| 0`


def settle(r) -> float:
    """`MR.settle`"""
    return num((r or {}).get(F_SETTLE))


def buy(r) -> float:
    """`MR.buy`"""
    return num((r or {}).get(F_BUY))


def is_keyword_blackspot(r) -> bool:
    """`MR.isKeywordBlackspot` — 메모에 「블랙」 / 더망고 상태에 「오류입고」."""
    if not r:
        return False
    memo = str(r.get(F_MEMO) or "")
    mg = str(r.get(F_MANGO) or "")
    return (any(k in memo for k in BLACKSPOT_MEMO_KW)
            or any(k in mg for k in BLACKSPOT_MANGO_KW))


def is_excluded_like(r) -> bool:
    """`MR.isExcludedLike` — 수기 제외 / 매입흔적 없는 주문미이행."""
    if not r:
        return True
    if r.get("_excluded"):
        return True
    return bool(r.get("_주문미이행")) and not r.get("_매입흔적")


def is_loss_row(r) -> bool:
    """`MR.isLossRow` — **블랙스팟**. 정산 0 + (키워드 or 매입>0).

    정산이 실제로 잡힌 행은 키워드보다 우선해 손실이 아니다(원본 주석 그대로).
    """
    if not r or is_excluded_like(r):
        return False
    if settle(r) > 0:
        return False
    if is_keyword_blackspot(r):
        return True
    return buy(r) > 0


def is_high_margin_row(r) -> bool:
    """`MR.isHighMarginRow` — 정산은 있는데 매입이 0(= 매입 미입력으로 부푼 마진)."""
    if not r or is_excluded_like(r) or is_loss_row(r):
        return False
    return settle(r) > 0 and buy(r) == 0


def is_margin_uncomputable(r) -> bool:
    """`MR.isMarginUncomputable` — 정산 0 · 매입 0 → 계산 불가."""
    if not r or is_excluded_like(r):
        return False
    if is_loss_row(r):
        return False
    return settle(r) == 0 and buy(r) == 0


def classify(r) -> str:
    """`MR.classify` — none/excluded/unfulfilled/loss/uncomputable/highmargin/normal."""
    if not r:
        return "none"
    if r.get("_excluded"):
        return "excluded"
    if r.get("_주문미이행") and not r.get("_매입흔적"):
        return "unfulfilled"
    if is_loss_row(r):
        return "loss"
    if is_margin_uncomputable(r):
        return "uncomputable"
    if is_high_margin_row(r):
        return "highmargin"
    return "normal"


def row_margin(r) -> float:
    """`MR.rowMargin` — 손실행은 −매입, 그 외는 정산−매입."""
    if is_loss_row(r):
        return -buy(r)
    return settle(r) - buy(r)


# ══════════════════════════════════════════════════════════════════
#  2. margin_embed.html 이식 — 고마진 · 이상마진 · 이상가 · 순마진/마진율
# ══════════════════════════════════════════════════════════════════

def is_high_margin(margin_rate, margin_amt) -> bool:
    """`isHighMargin` (margin_embed.html:1783) — 율·액 **둘 다** 넘어야 한다."""
    return (margin_rate >= HIGH_MARGIN_RATE
            and margin_amt >= HIGH_MARGIN_AMOUNT)


def is_abnormal_margin_row(r) -> bool:
    """`isAbnormalMarginRow` (margin_embed.html:2222) — 마이너스 **또는** 고마진."""
    if not r:
        return False
    if r.get("_주문미이행") and not r.get("_매입흔적"):
        return False
    rate = jsnum(r.get("마진율"))      # 원본은 맨 Number() 다 — jsnum 이유는 그 함수 주석
    amt = jsnum(r.get("순마진"))
    contrib = row_margin(r)
    return contrib < 0 or is_high_margin(rate, amt)


def abnormal_margin_rows(rows) -> list:
    """`renderAbnormalBanner` 의 거르개 (margin_embed.html:2233) — 화면 「이상마진 N건」."""
    out = []
    for r in (rows or []):
        if r.get("_주문미이행") and not r.get("_매입흔적"):
            continue
        if r.get("_excluded") or r.get("이상가"):
            continue
        if is_abnormal_margin_row(r):
            out.append(r)
    return out


def recompute_row(r) -> dict:
    """`recomputeRow` (margin_embed.html:3327) — 판매가·순마진·마진율·이상가를 채운다.

    🔴 새 산식이 아니다. 임계값·기준(매출=실결제+배송비 우선)까지 원본 그대로다.
    🔴 숫자 읽기도 원본 그대로 `jsnum`(맨 Number) 이다 — `num`(쉼표 제거)이 아니다.
    """
    단가 = jsnum(r.get("단가"))
    수량 = jsnum(r.get("수량_매출")) or 1
    정산 = jsnum(r.get(F_SETTLE))
    매입가 = jsnum(r.get(F_BUY))
    판매가 = 단가 * 수량
    r["판매가"] = 판매가
    r["순마진"] = 정산 - 매입가
    _paid = jsnum(r.get("실결제금액"))
    _ship = jsnum(r.get("배송비"))
    _rate_base = (_paid + _ship) if _paid > 0 else (판매가 if 판매가 > 0 else 정산)
    r["마진율"] = round(r["순마진"] / _rate_base * 100, 2) if _rate_base > 0 else 0
    r["이상가"] = bool((매입가 > 판매가 * ABNORMAL_PRICE_MULT and 판매가 > 0)
                     or 매입가 > ABNORMAL_PRICE_ABS)
    return r


# ══════════════════════════════════════════════════════════════════
#  3. order_claim_scope.js 이식 — 취소·반품 제외
# ══════════════════════════════════════════════════════════════════

# order_claim_scope.js:48-51 정규식 그대로. 「취소철회·반품철회」는 되돌린 클레임이라
# 살리고, 단독 「철회」(롯데온 취소)는 CLAIM_RE 가 잡는다.
_KEEP_RE = re.compile(r"교환|(?:취소|반품)\s*철회")
_CLAIM_RE = re.compile(r"취소|반품|철회|회수(?:지시|진행|완료|확정)")


def is_claim_excluded(status) -> bool:
    """`MOUM_ORDER_SCOPE.isExcluded` — 상태를 모르면 **빼지 않는다**(지어내기 금지)."""
    s = str("" if status is None else status).strip()
    if not s:
        return False
    if _KEEP_RE.search(s):
        return False
    return bool(_CLAIM_RE.search(s))


# ══════════════════════════════════════════════════════════════════
#  4. 주문 행 → 탭 판정
# ══════════════════════════════════════════════════════════════════

TAB_ABNORMAL = "abnormal"     # 이상마진
TAB_BLACKSPOT = "blackspot"   # 블랙스팟
TAB_NOPP = "nopp"             # 매입가 미입력

# 설계서 §8 — 정산예정금은 이 칸을 **읽기만** 한다(재계산 금지).
ORDER_SETTLE_FIELD = "정산예정금(배송비포함)"

BASIS_REAL = "real"
BASIS_STOCK = "stock"
BASIS_ESTIMATE = "estimate"
# 설계서 §4 — 소싱 예상가로 낸 마진은 「예상」으로만 쓰고 실적에 섞지 않는다.
ESTIMATE_BASES = (BASIS_ESTIMATE,)


def _blank(v) -> bool:
    return v is None or str(v).strip() == ""


def to_margin_row(order_row, price=None) -> dict:
    """주문 줄(+매입가) → 마진 계산기가 쓰는 모양의 행. 판정은 이 행으로만 한다."""
    o = order_row or {}
    r = {
        F_SETTLE: o.get(ORDER_SETTLE_FIELD),
        F_BUY: price if price is not None else 0,
        "단가": o.get("단가"),
        "수량_매출": o.get("수량"),
        "실결제금액": o.get("실결제금액"),
        "배송비": o.get("배송비"),
        # 취소·반품은 마진 계산기의 「수기 제외」와 같은 자리다 — 집계에서 뺀다.
        "_excluded": is_claim_excluded(o.get("주문상태")),
        # 🔴 주문 적재분에는 더망고 메모·상태 칸이 없다 → 키워드 블랙스팟은 안 걸린다.
        #   없는 값을 지어내지 않는다(더망고 엑셀을 올린 줄도 매입가만 들어온다).
        F_MEMO: o.get(F_MEMO),
        F_MANGO: o.get(F_MANGO),
    }
    return recompute_row(r)


def flag_order_row(order_row, pp=None) -> dict:
    """한 주문 줄이 어느 탭에 들어가는지.

    Args:
        order_row: 주문 적재 행(dict). 화면이 이미 들고 있는 것 그대로.
        pp: `purchase_price.resolve_purchase_price` 가 낸 한 줄 —
            `{'price': int|None, 'tier': 'real'|'stock'|'estimate'|None}`.

    Returns:
        {'abnormal': bool, 'blackspot': bool, 'nopp': bool,
         'basis': 'real'|'stock'|'estimate'|None,   # 무슨 값으로 판정했나
         'judged': bool,                            # 판정을 했나 못 했나
         'reason': str}                             # 못 했으면 왜
    """
    pp = pp or {}
    price = pp.get("price")
    basis = pp.get("tier") if price is not None else None
    # 실매입가가 아니면 「채워야 할 것」이다 — 예상가가 들어와도 미입력이다.
    nopp = basis != BASIS_REAL

    out = {"abnormal": False, "blackspot": False, "nopp": nopp,
           "basis": basis, "judged": False, "reason": ""}

    if price is None:
        out["reason"] = "매입가를 못 구했어요 — 이상마진·블랙스팟을 판정할 수 없습니다"
        return out
    if _blank((order_row or {}).get(ORDER_SETTLE_FIELD)):
        # 0 으로 채우면 멀쩡한 주문이 「정산 0 = 돈 못 받음」으로 둔갑한다.
        out["reason"] = "정산예정금을 아직 못 읽었어요 — 판정에서 뺐습니다"
        return out

    mr = to_margin_row(order_row, price)
    if mr.get("_excluded"):
        out["reason"] = "취소·반품 주문이라 마진 집계에서 뺍니다"
        return out

    out["judged"] = True
    out["blackspot"] = is_loss_row(mr)
    # 이상마진 건수는 화면 배너와 **같은 거르개**(이상가 행은 뺀다).
    out["abnormal"] = bool(abnormal_margin_rows([mr]))
    return out


def flag_rows(order_rows, prices=None) -> dict:
    """여러 줄 한꺼번에. line_uid → `flag_order_row` 결과."""
    prices = prices or {}
    out = {}
    for r in (order_rows or []):
        uid = str((r or {}).get("_line_uid") or "")
        if not uid:
            continue
        out[uid] = flag_order_row(r, prices.get(uid))
    return out


def summarize_tabs(order_rows, prices=None) -> dict:
    """탭 건수 집계. 화면 배지와 **같은 숫자**를 서버에서도 낼 수 있게 한다.

    Returns:
        {'total', 'abnormal', 'blackspot', 'nopp',
         'abnormal_estimate'  — 이상마진 중 **예상가로 판정한** 건수(설계서 §4),
         'abnormal_real'      — 이상마진 중 실매입가로 판정한 건수,
         'blackspot_estimate', 'unjudged'}
    """
    flags = flag_rows(order_rows, prices)
    s = {"total": len(list(order_rows or [])), "abnormal": 0, "blackspot": 0,
         "nopp": 0, "abnormal_estimate": 0, "abnormal_real": 0,
         "blackspot_estimate": 0, "unjudged": 0}
    for f in flags.values():
        if f["nopp"]:
            s["nopp"] += 1
        if not f["judged"]:
            s["unjudged"] += 1
        if f["abnormal"]:
            s["abnormal"] += 1
            if f["basis"] in ESTIMATE_BASES:
                s["abnormal_estimate"] += 1
            elif f["basis"] == BASIS_REAL:
                s["abnormal_real"] += 1
        if f["blackspot"]:
            s["blackspot"] += 1
            if f["basis"] in ESTIMATE_BASES:
                s["blackspot_estimate"] += 1
    return s
