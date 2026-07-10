# -*- coding: utf-8 -*-
"""pipeline.run — 매칭 + 파생 플래그 + _settle_source 재부착."""
import json

import pandas as pd

from lemouton.margin import pipeline as P


def _buy(**kw):
    base = {"마켓주문일자": "26.07.04", "마켓명": "쿠팡", "마켓주문번호": "1001",
            "수령인명": "홍길동", "마켓상품명": "코트 12345", "옵션1": "블랙/95",
            "구매가격": 50000, "사이트주문번호": "SO-1", "간단메모": "",
            "국내송장번호": "", "_uid": "0_1001_홍길동"}
    base.update(kw)
    return base


def _sell(**kw):
    base = {"오픈마켓주문번호": "1001", "상품명": "코트 12345", "옵션": "블랙/95",
            "단가": 80000, "수량": 1, "실결제금액": 80000,
            "정산예상금액_배송비포함": 70000, "쇼핑몰": "06.쿠팡",
            "수취고객명": "홍길동", "주문일": "2026-07-04", "수수료율": "11.55%",
            "주문상태": "배송완료", "송장입력": "1", "마켓수수료": 10000,
            "_settle_source": "real", "_sell_origin": "api"}
    base.update(kw)
    return base


def test_matched_gets_derived_date_and_pricerange():
    out = P.run(pd.DataFrame([_buy()]), pd.DataFrame([_sell()]))
    r = out["matched"][0]
    assert r["일자"] == "2026-07-04"
    assert r["월"] == "2026-07"
    assert r["금액대"] == "5~10만"


def test_missing_site_order_no_is_unfulfilled():
    out = P.run(pd.DataFrame([_buy(사이트주문번호="", 구매가격=0, 간단메모="s")]),
                pd.DataFrame([_sell()]))
    r = out["matched"][0]
    assert r["_주문미이행"] is True
    assert not r.get("_매입흔적")


def test_missing_site_order_no_with_trace_is_flagged():
    out = P.run(pd.DataFrame([_buy(사이트주문번호="", 국내송장번호="1234567")]),
                pd.DataFrame([_sell()]))
    r = out["matched"][0]
    assert r["_주문미이행"] is True and r["_매입흔적"] is True
    assert r["매칭타입"].endswith("_매입흔적")


def test_buy_missing_rows_still_matched():
    out = P.run(pd.DataFrame([_buy(사이트주문번호="")]), pd.DataFrame([_sell()]))
    assert len(out["matched"]) == 1
    assert not out["unmatched_buy"]


def test_unmatched_sell_when_no_buy():
    out = P.run(pd.DataFrame([_buy(마켓주문번호="9999")]), pd.DataFrame([_sell()]))
    assert len(out["unmatched_buy"]) == 1
    assert len(out["unmatched_sell"]) == 1


def test_buy_missing_records_returned():
    out = P.run(pd.DataFrame([_buy(사이트주문번호="")]), pd.DataFrame([_sell()]))
    assert len(out["buy_missing"]) == 1
    # buy_valid 인 행은 buy_missing 에 없음
    out2 = P.run(pd.DataFrame([_buy()]), pd.DataFrame([_sell()]))
    assert out2["buy_missing"] == []


# ── _settle_source 재부착 ──

def test_settle_source_reattached():
    out = P.run(pd.DataFrame([_buy()]), pd.DataFrame([_sell(_settle_source="estimated")]))
    assert out["matched"][0]["_settle_source"] == "estimated"
    assert out["settle_unknown"] == 0


def test_settle_source_survives_smartstore_paren_order_key():
    """스마트스토어 'A(B)' — 매칭은 A 로 성사되고 matched 행은 B 를 든다. 별칭표로 복구."""
    buy = pd.DataFrame([_buy(마켓명="스마트스토어", 마켓주문번호="7777(8888)")])
    sell = pd.DataFrame([_sell(오픈마켓주문번호="7777", _settle_source="estimated")])
    out = P.run(buy, sell)
    assert len(out["matched"]) == 1
    assert out["matched"][0]["마켓주문번호"] == "8888"      # 매칭키는 괄호 안
    assert out["matched"][0]["_settle_source"] == "estimated"
    assert out["settle_unknown"] == 0


def test_ambiguous_tags_pick_least_trusted():
    """같은 (주문번호·상품명·옵션) 에 real 과 estimated 가 공존하면 estimated 를 택한다."""
    sell = pd.DataFrame([_sell(_settle_source="real"),
                         _sell(_settle_source="estimated")])
    out = P.run(pd.DataFrame([_buy()]), sell)
    assert out["matched"][0]["_settle_source"] == "estimated"


def test_no_sell_match_marks_unknown_and_counts():
    """조인이 빗나가면 조용히 넘기지 않고 unknown 으로 세어 표면화한다.

    matcher._sell_order_key 는 주문번호의 꼬리 '.0' 을 떼고 매칭하지만(→ '1001' 로 성사),
    pipeline 의 widened 조인은 매출 원본 문자열('1001.0')을 그대로 키로 쓴다.
    별칭표에는 '1001' 만 있어 조인이 빗나가고 → unknown. 상품명/옵션은 matched 행이
    매출값을 그대로 복사하므로 조인 실패를 만들 수 없다(원 스케치의 상품명-불일치는
    unknown 을 못 만든다). 주문키 정규화 잔차가 유일한 실제 갭이다.
    """
    buy = pd.DataFrame([_buy(마켓주문번호="1001")])
    sell = pd.DataFrame([_sell(오픈마켓주문번호="1001.0")])
    out = P.run(buy, sell)
    assert len(out["matched"]) == 1
    assert out["matched"][0]["_settle_source"] == "unknown"
    assert out["settle_unknown"] == 1


def test_sell_df_without_settle_source_defaults_to_none():
    sell = pd.DataFrame([{k: v for k, v in _sell().items() if k != "_settle_source"}])
    out = P.run(pd.DataFrame([_buy()]), sell)
    assert out["matched"][0]["_settle_source"] == "none"


# ── JSON 안전 + 숫자 칸 dtype 보존 ──

def test_numeric_fields_stay_numeric_after_sanitizing():
    """숫자 칸에 ''를 넣으면 컬럼이 object dtype 이 되어 aggregator 의 sum() 이
    TypeError 로 죽는다. NaN 을 실제로 태워야 landmine 을 잡으므로 두 번째 행에
    정산 NaN 을 넣는다(깨끗한 행만으로는 '' 분기가 안 타 landmine 을 못 잡는다)."""
    buy = pd.DataFrame([_buy(), _buy(마켓주문번호="2002", _uid="1_2002_김")])
    sell = pd.DataFrame([_sell(), _sell(오픈마켓주문번호="2002",
                                        정산예상금액_배송비포함=float("nan"))])
    out = P.run(buy, sell)
    df = pd.DataFrame(out["matched"])
    assert len(df) == 2
    for col in ("단가", "판매가", "정산예상금액", "구매가격", "순마진", "마진율"):
        assert pd.api.types.is_numeric_dtype(df[col]), col
    assert df["순마진"].sum() == 20000   # 20000(정상) + 0(NaN→0 보정)


def test_nan_in_numeric_field_becomes_zero_and_is_counted():
    """NaN → 0 (조용히 넘기지 않고 nan_coerced 로 센다).

    주의: matcher(frozen)는 순마진 = 정산 - 매입 을 먼저 계산한다. 정산이 NaN 이면
    `pd.to_numeric(nan) or 0` = nan(nan 은 truthy) 이라 순마진·마진율도 NaN 으로 오염된다.
    → sanitizer 가 세 칸(정산·순마진·마진율)을 모두 0 으로 보정한다. 원 스케치의
    `순마진 == -50000` 은 matcher 결합상 불가능(수정: 순마진도 0). 매입 손실 '신호'는
    정산 0 + 구매가격 50000 으로 살아있다(margin_rules.js 가 읽는 의심손실 조건).
    """
    sell = pd.DataFrame([_sell(정산예상금액_배송비포함=float("nan"))])
    out = P.run(pd.DataFrame([_buy()]), sell)
    r = out["matched"][0]
    assert r["정산예상금액"] == 0
    assert r["구매가격"] == 50000         # 매입 손실 신호는 정산 0 + 매입>0 으로 살아있다
    assert r["순마진"] == 0               # matcher 결합: 정산 NaN → 순마진도 NaN → 0 보정
    assert out["nan_coerced"] >= 1
    pd.DataFrame(out["matched"])["순마진"].sum()   # dtype 안 깨짐


def test_all_outputs_are_json_serializable():
    buy = pd.DataFrame([_buy(), _buy(마켓주문번호="2002", 사이트주문번호=None,
                                     국내송장번호=None, 간단메모=None, _uid="1_2002_김")])
    out = P.run(buy, pd.DataFrame([_sell()]))
    for key in ("matched", "unmatched_buy", "unmatched_sell", "buy_missing"):
        json.dumps(out[key], default=str, allow_nan=False)


def test_clean_data_coerces_nothing():
    out = P.run(pd.DataFrame([_buy()]), pd.DataFrame([_sell()]))
    assert out["nan_coerced"] == 0


def test_blank_settlement_becomes_zero_not_empty_string():
    """정산금액 셀이 비면 matcher 가 NaN 을 만든다 → 숫자 칸은 0(빈문자 금지)."""
    out = P.run(pd.DataFrame([_buy()]),
                pd.DataFrame([_sell(정산예상금액_배송비포함="", 실결제금액="", 단가="")]))
    r = out["matched"][0]
    assert r["정산예상금액"] == 0
    assert r["단가"] == 0
    for key in ("matched", "unmatched_buy", "unmatched_sell", "buy_missing"):
        json.dumps(out[key], default=str, allow_nan=False)


def test_no_numpy_scalars_leak_into_output():
    """pandas 를 거친 값은 np.int64 로 나온다. np.int64 는 int 의 하위클래스가 아니라
    json.dumps / flask.jsonify 가 'Object of type int64 is not JSON serializable' 로 죽는다.
    (np.float64 는 float 하위클래스라 통과 — 그래서 조용히 지나치기 쉽다.)
    """
    import numpy as np

    out = P.run(pd.DataFrame([_buy()]), pd.DataFrame([_sell()]))
    for key in ("matched", "unmatched_buy", "unmatched_sell", "buy_missing"):
        for rec in out[key]:
            for k, v in rec.items():
                assert not isinstance(v, np.generic), f"{key}.{k} = {type(v).__name__}"


def test_matched_is_flask_jsonify_safe():
    from flask import Flask, jsonify

    out = P.run(pd.DataFrame([_buy()]), pd.DataFrame([_sell()]))
    app = Flask(__name__)
    with app.app_context():
        jsonify(matched=out["matched"])   # TypeError 나면 라우트가 500 난다
