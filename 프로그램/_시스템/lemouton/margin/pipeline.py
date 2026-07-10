# -*- coding: utf-8 -*-
"""매입 DF + 매출 DF → 매칭 결과 + 파생 플래그.

원본: C:\\dev\\대량등록 마진계산기\\app.py `_run_full_pipeline` (262행)
차이: supplements(주문번호 보완)는 ② 블랙스팟 사이클로 이월 — 여기서는 다루지 않는다.

matcher._make_result_row 은 고정 dict 를 만들고 `_settle_source` 를 버린다(matcher 는
frozen). 태그가 UI 까지 닿지 않으면 쿠팡 추정 정산액(양수)이 실정산과 구별되지 않는다.
그래서 run() 이 matched 행을 sell_df 로 되짚어 태그를 재부착한다(Part B).
"""
import logging
from datetime import datetime

import pandas as pd

from lemouton.margin.buy_parser import split_by_site_order_no
from lemouton.margin.config import DEFAULT_PRICE_RANGES
from lemouton.margin.matcher import match_data, order_match_keys

logger = logging.getLogger(__name__)


def _is_empty(v) -> bool:
    return str(v or "").strip() in ("", "nan", "None", "0", "0.0", "NaN")


def _has_real_trace(r: dict) -> bool:
    """진짜 매입 흔적 — 송장번호 / 메모의 URL / 구매가격 > 0."""
    if not _is_empty(r.get("국내송장번호")):
        return True
    if "http" in str(r.get("간단메모", "") or "").lower():
        return True
    try:
        bp = float(str(r.get("구매가격", 0) or 0).replace(",", ""))
        if bp > 0 and bp != 999999999.99:
            return True
    except (ValueError, TypeError):
        pass
    return False


def _parse_date(s):
    s = str(s).strip()
    for fmt in ("%y.%m.%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).date()
        except Exception:  # noqa: BLE001
            continue
    return None


def _classify_price(v, ranges):
    try:
        v = float(v or 0)
    except Exception:  # noqa: BLE001
        v = 0
    for lo, hi, lbl in ranges:
        if lo <= v < hi:
            return lbl
    return "기타"


# ── _settle_source 재부착 (Part B) ────────────────────────────────────────
#
# 신뢰도 낮은 쪽이 이긴다 — 추정치를 실값이라 부르는 일은 절대 없어야 한다.
_TAG_RANK = {"none": 0, "estimated": 1, "real": 2}


def _pick(tags):
    return min(tags, key=lambda t: _TAG_RANK.get(t, 0))


def _attach_settle_source(matched, buy_df, sell_df) -> int:
    """matched 행 ↔ sell_df 조인으로 _settle_source 재부착. unknown 개수 반환.

    naive 조인(마켓주문번호 ↔ 오픈마켓주문번호)은 두 번 빗나간다:
      1) 스마트스토어 'A(B)': 매칭은 A 로 성사되는데 matched 행은 B(=keys[-1])를 든다.
         → buy_df 로 별칭표(keys[-1] → 그 행이 쓴 모든 후보키)를 재구성해 복구.
      2) 한 주문번호에 정상행 + 클레임행(none)이 공존 → 태그가 다르다.
         → (주문번호, 상품명, 옵션) 3중키로 좁혀 후보 태그를 모두 모은다.
    """
    # 1) 별칭표: _order_key(=keys[-1]) → 그 매입 행이 매칭에 쓴 모든 후보 키
    alias: dict = {}
    for _, br in buy_df.iterrows():
        keys = order_match_keys(br.get("마켓주문번호"), br.get("마켓명"))
        if keys:
            alias.setdefault(str(keys[-1]), set()).update(str(k) for k in keys)

    # 2) widened 매출 인덱스: (주문번호, 상품명, 옵션) → 그 키에 걸린 _settle_source 집합
    sell_tags: dict = {}
    for _, sr in sell_df.iterrows():
        k = (str(sr.get("오픈마켓주문번호", "")).strip(),
             str(sr.get("상품명", "")),
             str(sr.get("옵션", "")))
        sell_tags.setdefault(k, set()).add(str(sr.get("_settle_source", "none")))

    # 3) 태그 부착 — 가장 보수적인 태그가 이긴다
    unknown = 0
    for r in matched:
        mon = str(r.get("마켓주문번호", ""))
        candidates = alias.get(mon, {mon})
        tags = set()
        for k in candidates:
            hit = sell_tags.get((k, str(r.get("상품명", "")), str(r.get("옵션_매출", ""))))
            if hit:
                tags |= hit
        if tags:
            r["_settle_source"] = _pick(tags)
        else:
            r["_settle_source"] = "unknown"
            unknown += 1

    if unknown:
        # 조용한 갭 = 배지 없는 추정치. 반드시 표면화한다.
        logger.warning(
            "settle_source 재부착: matched 행 %d개를 매출과 조인하지 못해 unknown 처리", unknown
        )
    return unknown


# ── JSON 안전 (Part C) ────────────────────────────────────────────────────

def _json_safe(rec: dict) -> dict:
    """NaN / NaT / pd.NA → '' 로 치환. jsonify 가 뱉는 bare NaN 리터럴을
    브라우저 JSON.parse 가 거부해 마진탭 전체가 안 뜨는 사고를 막는다(Task 7 동종 버그)."""
    out = {}
    for k, v in rec.items():
        try:
            if pd.isna(v):
                out[k] = ""
                continue
        except (ValueError, TypeError):
            pass  # 배열 등 스칼라 아님 → 그대로 둔다
        out[k] = v
    return out


# ── 메인 파이프라인 ────────────────────────────────────────────────────────

def run(buy_df, sell_df, price_ranges=None) -> dict:
    """매입 DF + 매출 DF → 매칭 결과 dict.

    Returns:
        {
            "matched": list[dict],        # 파생 플래그·일자·월·금액대·_settle_source 포함
            "unmatched_buy": list[dict],
            "unmatched_sell": list[dict],
            "buy_missing": list[dict],    # G열 미기입 매입 행 (JSON-safe records)
            "settle_unknown": int,        # 조인 실패로 _settle_source=unknown 된 matched 수
        }
    """
    ranges = price_ranges or DEFAULT_PRICE_RANGES

    buy_valid, buy_missing = split_by_site_order_no(buy_df)

    # ── 매칭 대상 = buy_valid + buy_missing (전체 더망고).
    #   buy_missing(사이트주문번호 미기입) 도 매칭 시도 → 마켓주문번호 동일하면 매칭.
    if buy_missing is not None and len(buy_missing) > 0:
        full_buy_df = pd.concat([buy_valid, buy_missing], ignore_index=True)
    else:
        full_buy_df = buy_valid

    matched, unmatched_buy, unmatched_sell = match_data(full_buy_df, sell_df)

    # ── 2단계 매입흔적 플래그 (원본 314~319)
    for r in matched:
        if _is_empty(r.get("사이트주문번호")):
            r["_주문미이행"] = True
            if _has_real_trace(r):
                r["_매입흔적"] = True
                r["매칭타입"] = (r.get("매칭타입") or "") + "_매입흔적"

    # ── 파생 필드: 일자·월·금액대 (원본 343~348)
    for r in matched:
        dt = _parse_date(r.get("주문일", ""))
        r["일자"] = dt.strftime("%Y-%m-%d") if dt else ""
        r["월"] = dt.strftime("%Y-%m") if dt else ""
        r["금액대"] = _classify_price(r.get("판매가", 0), ranges)

    # ── _settle_source 재부착 (Part B) — sanitize 전에(파생값 읽어야 함)
    settle_unknown = _attach_settle_source(matched, buy_df, sell_df)

    # ── JSON 안전 (Part C)
    matched = [_json_safe(r) for r in matched]
    unmatched_buy = [_json_safe(r) for r in unmatched_buy]
    unmatched_sell = [_json_safe(r) for r in unmatched_sell]
    buy_missing_records = [_json_safe(r) for r in buy_missing.to_dict("records")]

    return {
        "matched": matched,
        "unmatched_buy": unmatched_buy,
        "unmatched_sell": unmatched_sell,
        "buy_missing": buy_missing_records,
        "settle_unknown": settle_unknown,
    }
