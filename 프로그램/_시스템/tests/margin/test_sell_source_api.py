# -*- coding: utf-8 -*-
"""sell_source.from_api — order_export 행 → SellRow DF + 정산 정책."""
import datetime as dt

import pytest

from lemouton.margin import sell_source as SS

KST = dt.timezone(dt.timedelta(hours=9))
SINCE = dt.datetime(2026, 7, 1, tzinfo=KST)
UNTIL = dt.datetime(2026, 7, 8, tzinfo=KST)


def _oe_row(**kw):
    base = {
        "주문일": "2026-07-04 09:00:00", "판매처": "스마트스토어", "주문상태": "배송완료",
        "상품명": "코트 12345", "옵션": "블랙/95", "수량": 1, "수령자": "홍길동",
        "단가": 80000, "배송비": 0, "정산예정금액": 70000, "실결제금액": 80000,
        "마켓수수료": 10000, "수수료율": "12.5%", "오픈마켓주문번호": "1001",
        "송장입력": "1234", "정산예정금(배송비포함)": 70000, "_settle_source": "real",
    }
    base.update(kw)
    return base


def test_market_name_mapped_to_shopmine_form(monkeypatch):
    monkeypatch.setattr(SS, "_fetch_rows", lambda *a, **k: ([_oe_row()], []))
    df = SS.from_api(SINCE, UNTIL)
    assert df.loc[0, "쇼핑몰"] == "04.스마트스토어"
    assert df.loc[0, "_sell_origin"] == "api"


def test_all_markets_mapped():
    for api_name, ko in [("스마트스토어", "04.스마트스토어"), ("쿠팡", "06.쿠팡"),
                         ("롯데온", "18.롯데온"), ("11번가", "03.11번가"),
                         ("옥션", "02.옥션"), ("G마켓", "01.지마켓")]:
        assert SS.market_to_shopmine(api_name) == ko


def test_settlement_column_renamed_from_order_export():
    """SellRow 의 정산예상금액_배송비포함 ← order_export 의 `정산예정금액`.
    (`정산예정금(배송비포함)` 이 아니다 — 그건 고객배송비를 한 번 더 더한 값이라
     배송비 이중계상이 된다. test_settlement_does_not_double_count_shipping 참조.)"""
    row = _oe_row(**{"정산예정금액": 71000, "정산예정금(배송비포함)": 74000})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 71000


def test_lotteon_settlement_is_paid_minus_fee():
    """롯데온: 정산 = 실결제(actualAmt, 배송비 포함) − 실수수료. 배송비 재가산 금지."""
    row = _oe_row(판매처="롯데온", 실결제금액=100000, 마켓수수료=12000,
                  배송비=3000, **{"정산예정금액": 100000, "정산예정금(배송비포함)": 103000,
                                  "_settle_source": "real"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 88000
    assert df.loc[0, "_settle_source"] == "real"


def test_lotteon_without_fee_estimates_from_paid():
    """롯데온 미정산(구매확정 전 → 마켓수수료 미기록): 실결제 있으면 실결제×0.947 추정.
    옛 동작(0·none)은 최근 주문을 손실로 둔갑시켜 마진 마이너스를 유발했다(라이브 실측)."""
    row = _oe_row(판매처="롯데온", 실결제금액=100000, 마켓수수료="",
                  **{"_settle_source": "none"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == round(100000 * 0.947)  # 94700
    assert df.loc[0, "_settle_source"] == "estimated"


def test_lotteon_without_paid_estimates_from_list_price():
    """실결제(actualAmt)도 미확보면 단가×수량×0.884 로 추정(원본 대조 역산)."""
    row = _oe_row(판매처="롯데온", 실결제금액="", 단가=50000, 수량=2, 마켓수수료="",
                  **{"_settle_source": "none"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == round(100000 * 0.884)  # 88400
    assert df.loc[0, "_settle_source"] == "estimated"


def test_lotteon_no_basis_stays_none():
    """실결제·단가 모두 없으면 추정 근거 없음 → 0·none (조용한 추정 금지)."""
    row = _oe_row(판매처="롯데온", 실결제금액="", 단가="", 마켓수수료="",
                  **{"_settle_source": "none"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 0
    assert df.loc[0, "_settle_source"] == "none"


def test_coupang_estimated_is_passed_through_and_tagged():
    """쿠팡 추정치는 order_export 계산식 그대로. 실결제금액이 API 에 없어 통일 불가(스펙 §4)."""
    row = _oe_row(판매처="쿠팡", 실결제금액="", 단가=10000, 수량=1, 배송비=0,
                  **{"정산예정금액": 8845, "정산예정금(배송비포함)": 8845,
                     "_settle_source": "estimated"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 8845
    assert df.loc[0, "_settle_source"] == "estimated"


def test_settle_source_none_yields_zero_not_blank():
    row = _oe_row(**{"정산예정금(배송비포함)": "", "_settle_source": "none"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 0


def test_none_settlement_does_not_produce_nan_through_matcher():
    """정산 없음 → NaN 금지. NaN 이면 JSON 이 깨지고 pandas sum 이 손실을 지운다."""
    import math
    import pandas as pd
    from lemouton.margin import matcher as M

    # 추정 근거(실결제·단가) 없는 진짜 none 행 — 정산 0(빈칸 아님)이라야 손실이 총합에 남는다.
    sell = SS._rows_to_df([_oe_row(판매처="롯데온", 실결제금액="", 단가="",
                                   마켓수수료="", **{"_settle_source": "none"})])
    buy = pd.DataFrame([{
        "마켓주문일자": "26.07.04", "마켓명": "롯데ON", "마켓주문번호": "1001",
        "수령인명": "홍길동", "마켓상품명": "코트 12345", "옵션1": "블랙/95",
        "구매가격": 50000, "사이트주문번호": "SO-1", "간단메모": "",
    }])
    matched, _, _ = M.match_data(buy, sell)
    assert len(matched) == 1
    r = matched[0]
    assert not math.isnan(float(r["정산예상금액"]))
    assert not math.isnan(float(r["순마진"]))
    assert r["순마진"] == -50000        # 매입 손실이 총합에서 사라지지 않는다


def test_none_settlement_row_is_json_serializable():
    import json
    import pandas as pd
    from lemouton.margin import matcher as M

    # 추정 근거(실결제·단가) 없는 진짜 none 행 — 정산 0(빈칸 아님)이라야 손실이 총합에 남는다.
    sell = SS._rows_to_df([_oe_row(판매처="롯데온", 실결제금액="", 단가="",
                                   마켓수수료="", **{"_settle_source": "none"})])
    buy = pd.DataFrame([{
        "마켓주문일자": "26.07.04", "마켓명": "롯데ON", "마켓주문번호": "1001",
        "수령인명": "홍길동", "마켓상품명": "코트 12345", "옵션1": "블랙/95",
        "구매가격": 50000, "사이트주문번호": "SO-1", "간단메모": "",
    }])
    matched, _, _ = M.match_data(buy, sell)
    assert len(matched) == 1
    json.dumps(matched, default=float, allow_nan=False)   # 던지면 실패


def test_market_fetch_failure_propagates(monkeypatch):
    """마켓 1개 실패 → 분석 전체 중단. 부분 성공 숨김 금지 (스펙 §9)."""
    def _boom(*a, **k):
        raise RuntimeError("롯데온 IP 미등록")
    monkeypatch.setattr(SS, "_fetch_rows", _boom)
    with pytest.raises(RuntimeError, match="롯데온"):
        SS.from_api(SINCE, UNTIL)


def test_account_warnings_are_surfaced(monkeypatch):
    monkeypatch.setattr(SS, "_fetch_rows",
                        lambda *a, **k: ([_oe_row()], ["[coupang] 키 없음"]))
    df = SS.from_api(SINCE, UNTIL)
    assert df.attrs["warnings"] == ["[coupang] 키 없음"]


# ── 배송비 이중계상 (코드리뷰 C1) ──────────────────────────────────────────

def test_settlement_does_not_double_count_shipping():
    """order_export 의 `정산예정금액` 은 이미 '상품정산 + 배송비정산' 이다
    (COLUMN_META desc). `정산예정금(배송비포함)` 은 거기에 **고객배송비 총액**을 또 더한다
    → 배송비가 두 번. 배송건당 마진이 배송비만큼 부풀려진다.

    샵마인 실파일 확인: 정산예상금액 25330 + 고객배송비 3000 = (배송비포함) 28330.
    즉 샵마인의 (배송비포함) 은 '상품정산 + 고객배송비'. 우리 `정산예정금액` 은
    '상품정산 + 배송비정산' 이므로, 여기에 배송비를 또 더하면 안 된다.
    """
    row = _oe_row(판매처="스마트스토어", 배송비=3000,
                  **{"정산예정금액": 70000,              # 상품정산 + 배송비정산
                     "정산예정금(배송비포함)": 73000,     # + 고객배송비 (이중)
                     "_settle_source": "real"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 70000, "배송비를 두 번 세면 안 된다"


def test_coupang_estimate_uses_settlement_not_plus_shipping():
    """쿠팡 미정산 추정도 `정산예정금액`(=상품추정+배송비추정) 을 그대로 쓴다."""
    row = _oe_row(판매처="쿠팡", 배송비=2500, 실결제금액="",
                  **{"정산예정금액": 11270,
                     "정산예정금(배송비포함)": 13770,
                     "_settle_source": "estimated"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 11270
    assert df.loc[0, "_settle_source"] == "estimated"


def test_free_shipping_order_is_unaffected():
    """배송비 0 이면 두 필드가 같으므로 값이 바뀌지 않는다 (회귀 안전망)."""
    row = _oe_row(배송비=0, **{"정산예정금액": 63510,
                              "정산예정금(배송비포함)": 63510,
                              "_settle_source": "real"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 63510


# ── _to_int_or_blank 견고성 (코드리뷰 I2) ─────────────────────────────────

def test_to_int_handles_comma_and_float_strings():
    """쉼표·소수점 문자열이 조용히 0/none 으로 떨어지면 정산액이 사라진다."""
    assert SS._to_int_or_blank("103,000") == 103000
    assert SS._to_int_or_blank("88000.0") == 88000
    assert SS._to_int_or_blank(88000.0) == 88000
    assert SS._to_int_or_blank("") == ""
    assert SS._to_int_or_blank(None) == ""
    assert SS._to_int_or_blank("알수없음") == ""


def test_lotteon_settlement_survives_formatted_strings():
    row = _oe_row(판매처="롯데온", 실결제금액="103,000", 마켓수수료="12,000.0",
                  **{"_settle_source": "real"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 91000
    assert df.loc[0, "_settle_source"] == "real"
