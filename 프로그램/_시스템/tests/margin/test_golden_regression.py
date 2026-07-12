# -*- coding: utf-8 -*-
r"""골든테스트 1단계 — 옛 마진계산기와의 회귀 동치(cycle ①).

매출원을 옛 프로그램이 읽던 샵마인 엑셀로 고정(API·네트워크 없음)한다. 그러면
옛 출력과 신 출력의 차이는 오직 "포팅 결함"만 남는다.

  옛(baseline, 고정): scripts/margin_capture_baseline.py 가 옛 app.py 를 in-process
      로 구동해 store['matched'] + _aggregate(...) 의 순수 cycle ① 산출물을 저장.
      (라우트 응답의 cycle ② 오염 — card_* 덮어쓰기·mango_*·unmatched_buy augment·
       classified·blackspot_summary — 은 baseline 에 애초에 담지 않는다.)
  신(new): parse_buy → from_shopmine_excel → pipeline.run → aggregator.aggregate.

규칙: 옛·신이 어긋나면 신코드가 틀린 것. baseline 을 만지지 말고 이식 모듈을 고친다.

비교 대상(과제 명시):
  1) matched — 행 단위 전 필드 완전 일치(부동소수 approx)
  2) summary — baseline 의 모든 키 일치
  3) unmatched_buy / unmatched_sell — 길이 + 마켓주문번호 multiset
  4) 6종 집계(market/daily/monthly/brand/priceRange/product) — 그룹 수 + 그룹별 매출·순마진
  5) filters — brands / markets / priceRange

의도적 차이(결함 아님, 무시): pipeline.run 이 붙이는 _settle_source(비교 필드 아님),
반환 dict 의 settle_unknown·nan_coerced(별도 키). 이들은 비교하지 않는다.
"""
import gzip
import json
import os

import pytest

from lemouton.margin import aggregator, pipeline
from lemouton.margin.buy_parser import parse_buy
from lemouton.margin.config import DEFAULT_PRICE_RANGES
from lemouton.margin.sell_source import from_shopmine_excel

# 옛 프로그램 데이터 폴더(로컬 전용, CI 에는 없음) + baseline 마스킹·정규화 헬퍼 재사용
from scripts.margin_capture_baseline import OLD, mask_pii, _jsonable

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")

DATES = ["260704", "260706"]

# matched 행에서 완전 일치를 요구하는 필드(과제 지정).
# _주문미이행 / _매입흔적 은 buy_missing 출신 행에만 존재 → 없으면 양쪽 모두 None(=동치).
MATCHED_FIELDS = [
    "마켓주문번호", "마켓", "상품명", "브랜드", "옵션_매출", "옵션_매입",
    "단가", "판매가", "실결제금액", "정산예상금액", "구매가격", "순마진",
    "마진율", "수수료율", "수량_매출", "상품코드", "매칭타입", "일자", "월",
    "금액대", "동일인연속", "수량2이상", "이상가", "_주문미이행", "_매입흔적",
]
# 항상 존재해야 하는 필드(오타/키 누락 방어 — 아래 가드에서 검사).
CORE_FIELDS = [f for f in MATCHED_FIELDS if f not in ("_주문미이행", "_매입흔적")]

# 6종 집계의 그룹 라벨 필드
GROUP_LABEL = {
    "market": "마켓",
    "daily": "일자",
    "monthly": "월",
    "brand": "브랜드",
    "priceRange": "금액대",
}


# ── fixture 로드 / 소스 엑셀 위치 ─────────────────────────────────────────────

def _load_baseline(date):
    plain = os.path.join(FIXTURES, f"{date}_baseline.json")
    gz = plain + ".gz"
    if os.path.exists(gz):
        with gzip.open(gz, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    if os.path.exists(plain):
        with open(plain, encoding="utf-8") as f:
            return json.load(f)
    return None


def _find_excel_pair(date):
    folder = os.path.join(OLD, "데이터", date)
    if not os.path.isdir(folder):
        return None, None
    mango = shop = None
    for fn in os.listdir(folder):
        low = fn.lower()
        if not (low.endswith(".xls") or low.endswith(".xlsx")):
            continue
        if "더망고" in fn:
            mango = os.path.join(folder, fn)
        elif "샵마인" in fn:
            shop = os.path.join(folder, fn)
    return mango, shop


def _build_new(date):
    """신코드로 cycle ① 산출물 생성 후 baseline 과 동일하게 마스킹·정규화."""
    mango, shop = _find_excel_pair(date)
    with open(mango, "rb") as f:
        buy_df = parse_buy(f.read(), os.path.basename(mango))
    with open(shop, "rb") as f:
        sell_df = from_shopmine_excel(f.read(), os.path.basename(shop))

    result = pipeline.run(buy_df, sell_df, DEFAULT_PRICE_RANGES)
    agg = aggregator.aggregate(result["matched"], DEFAULT_PRICE_RANGES)

    new = {
        "matched": result["matched"],
        "unmatched_buy": result["unmatched_buy"],
        "unmatched_sell": result["unmatched_sell"],
        "summary": agg["summary"],
        "market": agg["market"],
        "daily": agg["daily"],
        "monthly": agg["monthly"],
        "brand": agg["brand"],
        "priceRange": agg["priceRange"],
        "product": agg["product"],
        "filters": agg["filters"],
    }
    # baseline 과 완전히 동일한 마스크·정규화(대칭) — 마스킹이 차이를 가릴 수 없게.
    return mask_pii(_jsonable(new))


@pytest.fixture(scope="module")
def golden(request):
    date = request.param
    baseline = _load_baseline(date)
    if baseline is None:
        pytest.skip(f"baseline fixture 없음: {date} (CI 에는 데이터 폴더/픽스처 부재)")
    mango, shop = _find_excel_pair(date)
    if not mango or not shop:
        pytest.skip(f"소스 엑셀 쌍 없음: {date} (옛 데이터 폴더 부재)")
    new = _build_new(date)
    return date, baseline, new


# ── 값 비교 헬퍼 ─────────────────────────────────────────────────────────────

def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _eq(a, b):
    """숫자는 approx, 그 외(None·str·bool)는 정확 일치.

    NaN 은 capture/_jsonable 단계에서 None 으로 정규화되므로 여기 도달하지 않는다.
    None(옛 NaN 흔적) vs 0(신 NaN→0 강제)은 정확히 불일치로 남아 표면화된다.
    """
    if _is_num(a) and _is_num(b):
        return a == pytest.approx(b, rel=1e-9, abs=1e-6)
    return a == b


def _sort_matched(rows):
    """과제 지정 1차 키 + 전 비교필드 tiebreaker 로 결정적 정렬.

    1차 키: (마켓주문번호, 상품명, 옵션_매출, 수령인, 구매가격). 수령인은 양쪽 모두
    '***' 로 마스킹돼 변별력이 없으므로, 전 비교필드 문자열 tuple 을 tiebreaker 로 덧붙여
    동률 행의 인덱스 정렬을 결정적으로 만든다(스왑·불일치는 값 비교에서 잡힌다).
    """
    def key(r):
        primary = (
            str(r.get("마켓주문번호", "")),
            str(r.get("상품명", "")),
            str(r.get("옵션_매출", "")),
            str(r.get("수령인", "")),
            str(r.get("구매가격", "")),
        )
        tie = tuple(str(r.get(f, "")) for f in MATCHED_FIELDS)
        return (primary, tie)

    return sorted(rows, key=key)


# ── 1) matched 행 단위 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("golden", DATES, indirect=True)
def test_matched_rows_equal(golden):
    date, baseline, new = golden
    base_m = baseline["matched"]
    new_m = new["matched"]

    # 오타/키 누락 방어: CORE 필드는 baseline 모든 행에 존재해야 한다.
    for i, r in enumerate(base_m):
        missing = [f for f in CORE_FIELDS if f not in r]
        assert not missing, f"[{date}] baseline matched[{i}] 에 CORE 필드 누락(오타?): {missing}"

    assert len(base_m) == len(new_m), (
        f"[{date}] matched 행 수 불일치: 옛={len(base_m)} 신={len(new_m)}"
    )

    b_sorted = _sort_matched(base_m)
    n_sorted = _sort_matched(new_m)

    for idx, (b, n) in enumerate(zip(b_sorted, n_sorted)):
        order = b.get("마켓주문번호")
        for f in MATCHED_FIELDS:
            bv, nv = b.get(f), n.get(f)
            assert _eq(bv, nv), (
                f"[{date}] matched 필드 '{f}' 불일치 "
                f"(마켓주문번호={order}, 정렬idx={idx}): 옛={bv!r} 신={nv!r}"
            )


# ── 2) summary ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("golden", DATES, indirect=True)
def test_summary_equal(golden):
    date, baseline, new = golden
    b_sum, n_sum = baseline["summary"], new["summary"]
    assert set(b_sum.keys()) <= set(n_sum.keys()), (
        f"[{date}] 신 summary 에 baseline 키 누락: {set(b_sum) - set(n_sum)}"
    )
    for k, bv in b_sum.items():
        nv = n_sum.get(k)
        assert _eq(bv, nv), f"[{date}] summary['{k}'] 불일치: 옛={bv!r} 신={nv!r}"


# ── 3) unmatched_buy / unmatched_sell ────────────────────────────────────────

@pytest.mark.parametrize("golden", DATES, indirect=True)
@pytest.mark.parametrize("side", ["unmatched_buy", "unmatched_sell"])
def test_unmatched_equal(golden, side):
    date, baseline, new = golden
    b_rows, n_rows = baseline[side], new[side]
    assert len(b_rows) == len(n_rows), (
        f"[{date}] {side} 길이 불일치: 옛={len(b_rows)} 신={len(n_rows)}"
    )

    def multiset(rows):
        from collections import Counter
        return Counter(str(r.get("마켓주문번호", "")) for r in rows)

    b_ms, n_ms = multiset(b_rows), multiset(n_rows)
    assert b_ms == n_ms, (
        f"[{date}] {side} 마켓주문번호 multiset 불일치. "
        f"옛-신={ {k: b_ms[k]-n_ms.get(k,0) for k in b_ms if b_ms[k]!=n_ms.get(k,0)} } "
        f"신-옛={ {k: n_ms[k]-b_ms.get(k,0) for k in n_ms if n_ms[k]!=b_ms.get(k,0)} }"
    )


# ── 4) 6종 집계 ──────────────────────────────────────────────────────────────

def _index_groups(rows, kind):
    """그룹 rows 를 라벨→행 dict 로. product 는 (상품코드,상품명) 복합 라벨."""
    out = {}
    if kind == "product":
        for r in rows:
            out[(r.get("상품코드", ""), r.get("상품명", ""))] = r
    else:
        col = GROUP_LABEL[kind]
        for r in rows:
            out[r.get(col)] = r
    return out


@pytest.mark.parametrize("golden", DATES, indirect=True)
@pytest.mark.parametrize("kind", ["market", "daily", "monthly", "brand", "priceRange", "product"])
def test_aggregate_groups_equal(golden, kind):
    date, baseline, new = golden
    b_idx = _index_groups(baseline[kind], kind)
    n_idx = _index_groups(new[kind], kind)

    assert len(b_idx) == len(n_idx), (
        f"[{date}] 집계 '{kind}' 그룹 수 불일치: 옛={len(b_idx)} 신={len(n_idx)}"
    )
    assert set(b_idx.keys()) == set(n_idx.keys()), (
        f"[{date}] 집계 '{kind}' 그룹 라벨 불일치. "
        f"옛-신={set(b_idx)-set(n_idx)} 신-옛={set(n_idx)-set(b_idx)}"
    )
    for label, b in b_idx.items():
        n = n_idx[label]
        for f in ("매출", "순마진"):
            assert _eq(b.get(f), n.get(f)), (
                f"[{date}] 집계 '{kind}' 그룹 {label!r} 의 '{f}' 불일치: "
                f"옛={b.get(f)!r} 신={n.get(f)!r}"
            )


# ── 5) filters ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("golden", DATES, indirect=True)
def test_filters_equal(golden):
    date, baseline, new = golden
    for f in ("brands", "markets", "priceRange"):
        assert baseline["filters"][f] == new["filters"][f], (
            f"[{date}] filters['{f}'] 불일치: 옛={baseline['filters'][f]} 신={new['filters'][f]}"
        )
