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

import numpy as np
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
    """가장 신뢰도 낮은 태그를 고른다.

    같은 (주문번호·상품명·옵션) 에 정상행과 클레임행이 함께 걸리면 real 과 none 이 섞인다.
    이때 none 을 택하므로, 실제로 정산된 주문의 배지가 '확인 불가'로 보수적으로 표시될 수
    있다. 값(정산예상금액)은 matcher 가 고른 실제 매출행에서 오므로 숫자는 옳다 —
    배지만 보수적이다. 의도된 편향이니 '고치지' 말 것.
    """
    return min(tags, key=lambda t: _TAG_RANK.get(t, 0))


def _norm_sell_key(v) -> str:
    """매출 주문번호 정규화 — matcher.match_data 안의 중첩함수 `_sell_order_key` 와 동일.

    matcher 는 동결(가드 테스트)이라 그 함수를 import 할 수 없어 여기 복제한다.
    이 정규화를 빠뜨리면 '1001.0' 로 색인해 두고 '1001' 로 찾게 되어, 매칭은 성공했는데
    태그 조인만 빗나가 settle_unknown 이 이유 없이 부풀어 오른다.
    """
    if pd.isna(v):
        return ""
    try:
        return str(v.item()) if hasattr(v, "item") else str(int(v))
    except (ValueError, TypeError, OverflowError):
        s = str(v).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s


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

    # 2) widened 매출 인덱스: (주문번호, 상품명, 옵션) → 그 키에 걸린 _settle_source 집합 + 배송비
    #    주문번호는 matcher 가 매칭에 쓴 것과 같은 방식으로 정규화한다(_norm_sell_key).
    #    ★배송비도 같은 조인으로 부착 — matcher(_make_result_row)는 원본과 바이트 동치라 배송비를
    #    출력하지 않으므로(verbatim), 여기서 sell_df 의 배송비(order_export 가 배송건 첫 행에만 실음)를
    #    되짚어 붙인다. 샵마인 고객배송비와 건별 대조·정산 검증용.
    sell_tags: dict = {}
    sell_ship: dict = {}
    for _, sr in sell_df.iterrows():
        k = (_norm_sell_key(sr.get("오픈마켓주문번호", "")),
             str(sr.get("상품명", "")),
             str(sr.get("옵션", "")))
        sell_tags.setdefault(k, set()).add(str(sr.get("_settle_source", "none")))
        try:
            ship = int(pd.to_numeric(sr.get("배송비", 0), errors="coerce") or 0)
        except (TypeError, ValueError):
            ship = 0
        sell_ship[k] = max(sell_ship.get(k, 0), ship)   # 배송건 첫 행 값(나머지 0) 보존

    # 3) 태그 부착 — 가장 보수적인 태그가 이긴다. 배송비도 같은 후보키로 부착.
    unknown = 0
    for r in matched:
        mon = str(r.get("마켓주문번호", ""))
        candidates = alias.get(mon, {mon})
        tags = set()
        ship = 0
        for k in candidates:
            trip = (k, str(r.get("상품명", "")), str(r.get("옵션_매출", "")))
            hit = sell_tags.get(trip)
            if hit:
                tags |= hit
            ship = max(ship, sell_ship.get(trip, 0))
        r["배송비"] = ship
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
#
# 숫자 칸은 숫자로 남는다. NaN → 0 (이 시스템의 '값 없음' 부호, Task 7 참조 —
# margin_rules.js 가 정산 0 + 매입>0 을 '의심손실'로 읽는다). 문자 칸은 NaN → "".
# 숫자 칸에 ""를 넣으면 컬럼이 object dtype 이 되어 aggregator 의
# df['순마진'].sum() 이 str+float TypeError 로 죽는다(원인에서 멀리 떨어진 곳에서).
_NUMERIC_FIELDS = {
    "단가", "판매가", "실결제금액", "정산예상금액", "구매가격",
    "순마진", "마진율", "수량_매출",
}


def _to_py(v):
    """numpy 스칼라 → 파이썬 기본형.

    pandas 를 거친 값은 np.int64 / np.bool_ 로 나온다. np.float64 는 float 의
    하위클래스라 통과하지만 **np.int64 는 int 의 하위클래스가 아니다** — json.dumps 와
    flask.jsonify 가 `Object of type int64 is not JSON serializable` 로 죽는다.
    라우트·store·export 가 각자 방어하면 언젠가 한 곳이 빠진다. 여기서 한 번에 막는다.
    """
    if isinstance(v, np.generic):
        return v.item()
    return v


def _json_safe(rec: dict, coerce_numeric: bool, counter: list) -> dict:
    """NaN / NaT / pd.NA 정리 + numpy 스칼라 → 파이썬 기본형.

    jsonify 가 뱉는 bare NaN 리터럴을 브라우저 JSON.parse 가 거부해 마진탭 전체가
    안 뜨는 사고를 막는다(Task 7 동종 버그).

    coerce_numeric=True: 숫자 칸(_NUMERIC_FIELDS) NaN → 0(counter[0] 증가),
      그 외 NaN → "". aggregator 로 흘러가는 matched/unmatched 용.
    coerce_numeric=False: 모든 NaN → "". buy_missing(원본 더망고, 표시 전용, 하류 집계 없음).
    """
    out = {}
    for k, v in rec.items():
        try:
            is_na = pd.isna(v)
        except (ValueError, TypeError):
            is_na = False  # 배열 등 스칼라 아님 → 그대로 둔다
        if is_na:
            if coerce_numeric and k in _NUMERIC_FIELDS:
                out[k] = 0
                counter[0] += 1
            else:
                out[k] = ""
        else:
            out[k] = _to_py(v)
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
            "nan_coerced": int,           # 숫자 칸 NaN → 0 으로 보정된 셀 수 (정상=0)
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

    # ── JSON 안전 (Part C) — 숫자 칸은 0 으로 남긴다(aggregator sum 보호)
    counter = [0]
    matched = [_json_safe(r, True, counter) for r in matched]
    unmatched_buy = [_json_safe(r, True, counter) for r in unmatched_buy]
    unmatched_sell = [_json_safe(r, True, counter) for r in unmatched_sell]
    # buy_missing 은 원본 더망고 표시 전용 — 하류 집계 없음 → 전부 "" 로.
    buy_missing_records = [_json_safe(r, False, counter) for r in buy_missing.to_dict("records")]

    nan_coerced = counter[0]
    if nan_coerced:
        # 두 생산자가 정상이면 항상 0. 0 이 아니면 생산자 회귀 신호 → 라우트가 표면화.
        logger.warning("pipeline: 숫자 칸 NaN %d개를 0 으로 보정", nan_coerced)

    return {
        "matched": matched,
        "unmatched_buy": unmatched_buy,
        "unmatched_sell": unmatched_sell,
        "buy_missing": buy_missing_records,
        "settle_unknown": settle_unknown,
        "nan_coerced": nan_coerced,
    }
