# -*- coding: utf-8 -*-
"""샵마인 대조 엔진 — 정답지 엑셀 ↔ 우리 적재분(order_store) 전수 대조.

스펙: docs/superpowers/specs/2026-07-22-샵마인-대조탭-design.md (사장님 승인 A안).
1건=5만원 정합성 — 판정은 일치/허용차이(±6원)/정의차이(재현식)/불일치/판정불가만
존재하고, 애매한 것을 '일치'로 뭉개지 않는다.

★ A안: 우리 값(마켓 원본)은 그대로 두고, 샵마인 돈 숫자([정가→실결제→정산]
  자체 항등식 체인 = 계산값)를 재현식으로 재현해 대조한다. 재현되면 「정의차이」
  (노랑 — 샵마인이 계산값이라 다른 것), 재현식으로도 안 맞으면 「불일치」(빨강 —
  작업필요)로 정직 표시.

★ 파싱은 margin.sell_source.from_shopmine_excel 을 재사용하지 않는다 — 그쪽은
  마진계산 목적이라 쿠팡 '알수없음' 정산을 보정(날조)해 넣는다. 대조는 파일의
  원값을 그대로 봐야 하므로 여기서 무보정 파싱한다(목적이 달라 원천 분리가 맞음).

⚠️ pandas itertuples 금지 — 괄호 컬럼명('정산예상금액（배송비포함）')이 깨진다.
   반드시 to_dict("records").
"""
from __future__ import annotations

import html as _html
import io
import re
from collections import defaultdict

# 샵마인 '쇼핑몰' 접두 → 우리 마켓 키
_MALL_PREFIX = {
    "01": "gmarket", "02": "auction", "03": "eleven11",
    "04": "smartstore", "06": "coupang", "18": "lotteon",
}
# 우리 행 '판매처' 한글 ↔ 마켓 키
_PANMAECHEO = {
    "스마트스토어": "smartstore", "쿠팡": "coupang", "롯데온": "lotteon",
    "11번가": "eleven11", "옥션": "auction", "G마켓": "gmarket",
}
MARKET_LABEL = {v: k for k, v in _PANMAECHEO.items()}

FIELDS = ("date", "qty", "unit", "paid", "settle")
FIELD_LABEL = {"date": "주문일", "qty": "수량", "unit": "단가",
               "paid": "실결제", "settle": "정산(배송비포함)"}
VERDICTS = ("match", "tol", "def", "diff", "ours_blank", "shop_blank")

_TOL_WON = 6            # ±6원 = 반올림 규칙 차이(허용) — 실측 스스331·쿠팡580
_DETAIL_CAP = 800       # 상세 목록 상한(요약 수치는 전수 — 잘림은 *_total 로 표기)


# ── 정규화 유틸 ───────────────────────────────────────────────────────────

def _norm_col(c) -> str:
    """컬럼명 정규화 — 전각공백(　) 포함 공백 제거·오타·괄호 컬럼 통일."""
    s = re.sub(r"[\s　]+", "", str(c or ""))
    if s == "삼품명":
        return "상품명"
    if "오픈마켓" in s and "주문번호" in s:
        return "오픈마켓주문번호"
    if "샵마인" in s and "주문고유코드" in s:
        return "샵마인주문고유코드"
    if "정산예상금액" in s and "배송비" in s:
        return "정산예상금액_배송비포함"
    return s


def _market_of(mall) -> str | None:
    """샵마인 '쇼핑몰'(예: '01.지마켓') → 마켓 키. 미지원 몰은 None."""
    head = str(mall or "").split(".", 1)[0].strip()
    return _MALL_PREFIX.get(head)


def _norm_date(v) -> str:
    """주문일 → 'YYYY-MM-DD'. 샵마인 '26.04.22' 2자리 연도 지원. 못 읽으면 ''."""
    s = str(v or "").strip()
    if not s or s.lower() in ("none", "nan"):
        return ""
    m = re.match(r"^(\d{2,4})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if not m:
        return ""
    y, mo, d = m.groups()
    if len(y) == 2:
        y = "20" + y
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def _num(v):
    """정수 변환. 못 하면 None — 0 폴백 금지(0원 날조는 '정산 0원'과 모순)."""
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if not s or s.lower() in ("none", "nan"):
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _norm_opt(v) -> str:
    """옵션 정규화 — 공백 제거·HTML unescape·소문자 (롯데온 &lt; 대응)."""
    s = _html.unescape(str(v or ""))
    return re.sub(r"\s+", "", s).lower()


# ── 파싱 ─────────────────────────────────────────────────────────────────

def parse_master(file_bytes: bytes) -> list[dict]:
    """샵마인 마스터 .xls(OLE2) → 정규화 행 리스트. 무보정(원값 그대로)."""
    import pandas as pd
    df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    df.columns = [_norm_col(c) for c in df.columns]
    required = ["쇼핑몰", "쇼핑몰별칭", "오픈마켓주문번호", "주문일", "수량", "단가"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"샵마인 엑셀에 필수 컬럼이 없습니다: {missing}")
    rows = []
    for r in df.to_dict("records"):        # ⚠️ itertuples 금지(괄호 컬럼 깨짐)
        no = str(r.get("오픈마켓주문번호") or "").strip()
        if not no or no.lower() in ("none", "nan"):
            continue
        rows.append({
            "market": _market_of(r.get("쇼핑몰")),
            "mall": str(r.get("쇼핑몰") or "").strip(),
            "sm_alias": str(r.get("쇼핑몰별칭") or "").strip(),
            "order_no": no,
            "sm_uid": str(r.get("샵마인주문고유코드") or "").strip(),
            "order_date": _norm_date(r.get("주문일")),
            "product": str(r.get("상품명") or "").strip(),
            "option": str(r.get("옵션") or "").strip(),
            "qty": _num(r.get("수량")),
            "unit": _num(r.get("단가")),
            "opt_add": _num(r.get("옵션추가금액")),
            "paid": _num(r.get("실결제금액")),
            "ship": _num(r.get("고객배송비")),
            "settle_incl": _num(r.get("정산예상금액_배송비포함")),
            "fee": _num(r.get("마켓수수료")),
            "status": str(r.get("주문상태") or "").strip(),
        })
    return rows


# ── 계정 매핑 (이름표 무시 — 주문번호 교집합이 진실) ─────────────────────

def map_accounts(sm_rows: list[dict], our_rows: list[dict]) -> list[dict]:
    """마켓별 (샵마인별칭 × 우리계정) 주문번호 교집합 → 최다 계정으로 확정.

    교집합 0 = unregistered(미등록 — 제외 목록). 복수 계정 분산 = ambiguous
    (중복 등록 의심). 이름표는 판정에 쓰지 않는다(11번가 박스↔브랜드위시 교차 실측).
    """
    ours_no_acct: dict[tuple, set] = defaultdict(set)
    for r in our_rows:
        mk = _PANMAECHEO.get(str(r.get("판매처") or "").strip())
        no = str(r.get("오픈마켓주문번호") or "").strip()
        acct = str(r.get("쇼핑몰별칭") or "").strip()
        # 빈 별칭은 집계 제외 — 옥션·G마켓 일부 적재분이 별칭 미기록이라, 빈 문자열이
        # 1위 계정으로 잡혀 「중복 등록 의심」 오표시를 만든다(2026-07-22 라이브 실측).
        if mk and no and acct:
            ours_no_acct[(mk, no)].add(acct)

    groups: dict[tuple, set] = defaultdict(set)
    for r in sm_rows:
        if r.get("market"):
            groups[(r["market"], r.get("sm_alias") or "")].add(r["order_no"])

    out = []
    for (mk, alias), nos in sorted(groups.items()):
        counts: dict[str, int] = defaultdict(int)
        for no in nos:
            for acct in ours_no_acct.get((mk, no), ()):
                counts[acct] += 1
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])
        if not ranked:
            status, acct, hits = "unregistered", "", 0
        elif len(ranked) > 1 and ranked[1][1] > 0:
            status, acct, hits = "ambiguous", ranked[0][0], ranked[0][1]
        else:
            status, acct, hits = "mapped", ranked[0][0], ranked[0][1]
        out.append({"market": mk, "sm_alias": alias, "our_account": acct,
                    "hits": hits, "total": len(nos), "status": status,
                    "spread": {a: c for a, c in ranked[1:3]} if len(ranked) > 1 else {}})
    return out


# ── 우리 쪽 정산값 (배송비포함 정의로 정렬 — real/store 만 비교) ─────────

def _our_settle_incl(row: dict):
    """우리 행의 '정산(배송비포함)' 비교값. (값, 비교가능여부).

    sell_source._settlement_for 가 단일 원천(ESM +배송비·롯데온 실결제−실수수료).
    추정(estimated)·없음(none)은 비교하지 않는다 — 추정을 정답지에 대조하면
    '추정이 틀렸다'는 가짜 빨강이 생긴다(정직 원칙).
    """
    from lemouton.margin.sell_source import _settlement_for
    val, src = _settlement_for(dict(row))
    if src in ("real", "store"):
        return val, True
    return None, False


# ── 필드 판정 ────────────────────────────────────────────────────────────

def _verdict_eq(shop, ours):
    if shop is None or shop == "":
        return "shop_blank"
    if ours is None or ours == "":
        return "ours_blank"
    return "match" if shop == ours else "diff"


def _paid_reproductions(sm: dict, our: dict) -> set:
    """샵마인 '실결제' 재현식 후보값들 — 스펙 §2.4 표(전건 실측 확정)."""
    cand = set()
    unit, qty = sm.get("unit"), sm.get("qty") or 1
    opt_add = sm.get("opt_add") or 0
    if unit is not None:
        cand.add((unit + opt_add) * qty)                    # 정가총액(스스·쿠팡·G일부)
    st, fee = sm.get("settle_incl"), sm.get("fee")
    if st is not None and fee is not None:
        cand.add(st + fee)                                  # 정산예상+수수료(11·옥·G)
        cand.add(st + fee - (sm.get("ship") or 0))          # 일부 −고객배송비
    if sm.get("market") == "lotteon" and unit is not None:
        dc = _num(our.get("_lo_seller_dc"))
        if dc is not None:
            cand.add(unit * qty - dc)                       # 정가−셀러부담할인
    return cand


def _settle_reproductions(sm: dict) -> set:
    """샵마인 '정산' 재현식 — 샵 실결제 − 수수료 (일부 +고객배송비)."""
    cand = set()
    paid, fee = sm.get("paid"), sm.get("fee")
    if paid is not None and fee is not None:
        cand.add(paid - fee)
        cand.add(paid - fee + (sm.get("ship") or 0))
    return cand


def _judge_money(shop, ours, repro: set) -> str:
    if shop is None:
        return "shop_blank"
    if ours is None:
        return "ours_blank"
    if shop == ours:
        return "match"
    if abs(shop - ours) <= _TOL_WON:
        return "tol"
    if shop in repro:
        return "def"
    return "diff"


def _compare(sm: dict, our: dict) -> dict:
    """페어 1건의 필드별 판정."""
    out = {}
    out["date"] = _verdict_eq(sm.get("order_date") or None,
                              (_norm_date(our.get("주문일")) or None))
    out["qty"] = _verdict_eq(sm.get("qty"), _num(our.get("수량")))
    out["unit"] = _verdict_eq(sm.get("unit"), _num(our.get("단가")))
    out["paid"] = _judge_money(sm.get("paid"), _num(our.get("실결제금액")),
                               _paid_reproductions(sm, our))
    st_ours, comparable = _our_settle_incl(our)
    out["settle"] = _judge_money(sm.get("settle_incl"),
                                 st_ours if comparable else None,
                                 _settle_reproductions(sm))
    return out


# ── 페어링 ───────────────────────────────────────────────────────────────

def _pair_lines(sm_lines: list[dict], our_lines: list[dict]):
    """주문 안 라인 짝짓기 — ①단일:단일 ②옵션 정규화 ③(단가,수량). 남으면 판정불가."""
    if len(sm_lines) == 1 and len(our_lines) == 1:
        return [(sm_lines[0], our_lines[0])], []
    pairs, used = [], set()
    remaining = []
    by_opt: dict[str, list[int]] = defaultdict(list)
    for i, o in enumerate(our_lines):
        by_opt[_norm_opt(o.get("옵션"))].append(i)
    for s in sm_lines:
        idxs = by_opt.get(_norm_opt(s.get("option")))
        hit = next((i for i in (idxs or []) if i not in used), None)
        if hit is not None:
            used.add(hit)
            pairs.append((s, our_lines[hit]))
        else:
            remaining.append(s)
    still = []
    for s in remaining:
        hit = next((i for i, o in enumerate(our_lines)
                    if i not in used
                    and _num(o.get("단가")) == s.get("unit")
                    and _num(o.get("수량")) == s.get("qty")), None)
        if hit is not None:
            used.add(hit)
            pairs.append((s, our_lines[hit]))
        else:
            still.append(s)
    return pairs, still


# ── 본체 ─────────────────────────────────────────────────────────────────

def reconcile(sm_rows: list[dict], our_rows: list[dict]) -> dict:
    """전수 대조 — 존재(누락)·계정매핑·필드 3분류·판정불가. 요약 수치는 전수."""
    known = [r for r in sm_rows if r.get("market")]
    excluded = defaultdict(int)
    for r in sm_rows:
        if not r.get("market"):
            excluded[r.get("mall") or "(쇼핑몰 없음)"] += 1

    accounts = map_accounts(known, our_rows)
    acct_map = {(a["market"], a["sm_alias"]): a for a in accounts}

    ours_idx: dict[tuple, dict] = defaultdict(lambda: {"orders": [], "claims": []})
    for r in our_rows:
        mk = _PANMAECHEO.get(str(r.get("판매처") or "").strip())
        no = str(r.get("오픈마켓주문번호") or "").strip()
        if not (mk and no):
            continue
        kind = "claims" if r.get("_kind") == "change" else "orders"
        ours_idx[(mk, no)][kind].append(r)

    sm_groups: dict[tuple, list] = defaultdict(list)
    for r in known:
        sm_groups[(r["market"], r["order_no"])].append(r)

    fields: dict = {}
    missing, mismatch, undecided = [], [], []
    missing_total = mismatch_total = undecided_total = 0
    found_orders = 0
    per_acct_missing: dict[tuple, int] = defaultdict(int)

    def _f(mk, fld):
        return fields.setdefault(mk, {}).setdefault(
            fld, {v: 0 for v in VERDICTS})

    for (mk, no), sm_lines in sorted(sm_groups.items()):
        grp = ours_idx.get((mk, no))
        if not grp or not (grp["orders"] or grp["claims"]):
            missing_total += len(sm_lines)
            for s in sm_lines:
                per_acct_missing[(mk, s.get("sm_alias") or "")] += 1
                if len(missing) < _DETAIL_CAP:
                    a = acct_map.get((mk, s.get("sm_alias") or ""), {})
                    missing.append({
                        "market": mk, "order_no": no,
                        "sm_alias": s.get("sm_alias") or "",
                        "our_account": a.get("our_account", ""),
                        "date": s.get("order_date"), "product": s.get("product"),
                        "paid": s.get("paid"), "status": s.get("status")})
            continue
        found_orders += 1
        # 주문행 우선, 없으면 클레임행 (스펙 §2.3)
        our_lines = grp["orders"] or grp["claims"]
        pairs, leftover = _pair_lines(sm_lines, our_lines)
        undecided_total += len(leftover)
        for s in leftover:
            if len(undecided) < _DETAIL_CAP:
                undecided.append({
                    "market": mk, "order_no": no, "sm_alias": s.get("sm_alias") or "",
                    "option": s.get("option"), "unit": s.get("unit"),
                    "qty": s.get("qty"),
                    "our_options": [str(o.get("옵션") or "") for o in our_lines][:6]})
        for s, o in pairs:
            verdicts = _compare(s, o)
            for fld, v in verdicts.items():
                _f(mk, fld)[v] += 1
                if v == "diff":
                    mismatch_total += 1
                    if len(mismatch) < _DETAIL_CAP:
                        mismatch.append({
                            "market": mk, "order_no": no, "field": fld,
                            "sm_alias": s.get("sm_alias") or "",
                            "product": (s.get("product") or "")[:60],
                            "shop": _shop_field_value(s, fld),
                            "ours": _our_field_value(o, fld)})

    for a in accounts:
        a["missing"] = per_acct_missing.get((a["market"], a["sm_alias"]), 0)

    dates = sorted(d for d in (r.get("order_date") for r in known) if d)
    sm_order_total = len(sm_groups)
    return {
        "period": [dates[0], dates[-1]] if dates else ["", ""],
        "sm_rows": len(known),
        "sm_orders": sm_order_total,
        "excluded_malls": dict(excluded),
        "existence": {"total": sm_order_total, "found": found_orders,
                      "missing": sm_order_total - found_orders},
        "accounts": accounts,
        "fields": fields,
        "missing": missing, "missing_total": missing_total,
        "mismatch": mismatch, "mismatch_total": mismatch_total,
        "undecided": undecided, "undecided_total": undecided_total,
    }


def _shop_field_value(s: dict, fld: str):
    return {"date": s.get("order_date"), "qty": s.get("qty"),
            "unit": s.get("unit"), "paid": s.get("paid"),
            "settle": s.get("settle_incl")}.get(fld)


def _our_field_value(o: dict, fld: str):
    if fld == "settle":
        val, ok = _our_settle_incl(o)
        return val if ok else None
    return {"date": _norm_date(o.get("주문일")), "qty": _num(o.get("수량")),
            "unit": _num(o.get("단가")), "paid": _num(o.get("실결제금액"))}.get(fld)


def run_against_store(file_bytes: bytes, *, session=None) -> dict:
    """파일 파싱 → 파일 기간으로 order_store 로드 → 대조. 기간 = 파일이 결정."""
    from lemouton.markets import order_store
    sm_rows = parse_master(file_bytes)
    dates = sorted(d for d in (r.get("order_date") for r in sm_rows) if d)
    since = dates[0] if dates else None
    until = dates[-1] if dates else None
    our_rows = order_store.load(since=since, until=until, session=session)
    return reconcile(sm_rows, our_rows)
