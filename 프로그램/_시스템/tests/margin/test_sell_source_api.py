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


def test_settlement_comes_from_orders_tab_field():
    """SellRow 의 정산예상금액_배송비포함 ← 주문내역이 뿌리는 `정산예정금(배송비포함)`.

    마진계산기는 정산액을 **다시 계산하지 않는다**. 예전엔 `정산예정금액`(상품분)을
    읽어 마켓별로 배송비를 손으로 더했는데, 주문내역이 규약을 바꿀 때마다 이쪽만
    옛 정의로 남아 조용히 어긋났다(쿠팡 배송비 누락 등).
    """
    row = _oe_row(**{"정산예정금액": 71000, "정산예정금(배송비포함)": 74000})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 74000


def test_lotteon_real_settlement_taken_as_is():
    """롯데온 실정산: 주문내역이 이미 상품분/배송비분을 나눠 두었다.

    실결제 100,000(배송비 3,000 포함) − 수수료 12,000 = 실정산 88,000 이면
    주문내역 `정산예정금액` = 85,000(상품분) / `정산예정금(배송비포함)` = 88,000.
    마진계산기는 뒤쪽을 그대로 쓴다.
    """
    row = _oe_row(판매처="롯데온", 실결제금액=100000, 마켓수수료=12000,
                  배송비=3000, **{"정산예정금액": 85000, "정산예정금(배송비포함)": 88000,
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


def test_eleven11_real_settlement_kept():
    """11번가 stlPlnAmt 확보분: 주문내역 `정산예정금(배송비포함)` 그대로."""
    row = _oe_row(판매처="11번가", 단가=90000, 실결제금액=85000,
                  **{"정산예정금액": 83000, "정산예정금(배송비포함)": 83000,
                     "_settle_source": "real"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 83000
    assert df.loc[0, "_settle_source"] == "real"


def test_eleven11_unsettled_estimates_from_paid():
    """11번가 미정산(배송완료 = stlPlnAmt 없음): 실결제×0.964 추정."""
    row = _oe_row(판매처="11번가", 단가=90000, 실결제금액=85000, 마켓수수료="",
                  **{"정산예정금액": "", "_settle_source": "none"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == round(85000 * 0.964)
    assert df.loc[0, "_settle_source"] == "estimated"


def test_eleven11_unsettled_no_paid_estimates_from_unit():
    """실결제 없고 단가만 있으면 단가×수량×0.869 추정."""
    row = _oe_row(판매처="11번가", 단가=50000, 수량=2, 실결제금액="",
                  **{"정산예정금액": "", "_settle_source": "none"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == round(100000 * 0.869)
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
    assert "[coupang] 키 없음" in df.attrs["warnings"]


def test_store_only_analysis_says_so(monkeypatch):
    """저장분만 읽었다는 사실을 반드시 화면에 알린다.

    분석은 기본적으로 라이브 조회를 하지 않는다(6마켓 한 요청 = 61.7초 → 서버 상한
    초과 → 502). 그 대가로 최근 주문이 빠질 수 있는데, 말없이 빠지면 '주문이 없다'로
    오해한다 — 조용한 실패 금지.
    """
    monkeypatch.setattr(SS, "_fetch_rows", lambda *a, **k: ([_oe_row()], []))
    df = SS.from_api(SINCE, UNTIL)
    assert any("최신까지 불러오기" in w for w in df.attrs["warnings"])


def test_live_tail_requested_means_no_store_only_notice(monkeypatch):
    """라이브 보충을 실제로 했다면 그 안내는 붙이지 않는다(거짓 경고 금지)."""
    seen = {}

    def _fake(since, until, markets, live_tail_days=0):
        seen["days"] = live_tail_days
        return [_oe_row()], []

    monkeypatch.setattr(SS, "_fetch_rows", _fake)
    df = SS.from_api(SINCE, UNTIL, live_tail_days=5)
    assert seen["days"] == 5
    assert not any("최신까지 불러오기" in w for w in df.attrs["warnings"])


# ── 배송비: 주문내역이 한 번만 더한다 (마진계산기는 재가산 금지) ──────────

def test_margin_never_re_adds_shipping():
    """마진계산기는 배송비를 스스로 더하지 않는다 — 더하면 두 번 세인다.

    배송비를 한 번 더하는 책임은 주문내역(order_export._finalize_rows)에 있고,
    그 결과가 `정산예정금(배송비포함)` 이다. 여기서 또 더하면 배송건당 마진이
    배송비만큼 부풀려진다.
    """
    row = _oe_row(판매처="스마트스토어", 배송비=3000,
                  **{"정산예정금액": 70000, "정산예정금(배송비포함)": 73000,
                     "_settle_source": "real"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 73000, "주문내역 값 그대로여야 한다"


def test_coupang_settlement_includes_customer_shipping():
    """🔴 회귀 방지 — 쿠팡 배송비 누락.

    주문내역은 2026-07-23 부터 쿠팡 `정산예정금액` 을 **상품정산만** 담게 바꿨고
    (샵마인 45건 전수 실측), 고객배송비는 `정산예정금(배송비포함)` 에서 더한다.
    마진계산기가 앞쪽을 계속 읽는 바람에 배송비 붙은 쿠팡 주문의 마진이 그만큼
    과소였다. 두 화면이 같은 숫자를 보는지 못 박는다.
    """
    row = _oe_row(판매처="쿠팡", 배송비=3000, 실결제금액="",
                  **{"정산예정금액": 45000,               # 상품정산만
                     "정산예정금(배송비포함)": 48000,      # + 고객배송비 = 주문내역 화면값
                     "_settle_source": "real"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 48000


def test_coupang_estimate_uses_orders_tab_value():
    """쿠팡 미정산 추정도 주문내역이 만든 배송비포함 값을 그대로 쓴다."""
    row = _oe_row(판매처="쿠팡", 배송비=2500, 실결제금액="",
                  **{"정산예정금액": 11270,
                     "정산예정금(배송비포함)": 13770,
                     "_settle_source": "estimated"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 13770
    assert df.loc[0, "_settle_source"] == "estimated"


# ── 취소완료 = 정산 0 (주문내역과 동일 규약) ──────────────────────────────

def test_lotteon_cancelled_order_is_zero_not_estimated():
    """🔴 회귀 방지 — 롯데온 취소완료에 가짜 추정 정산이 붙던 버그.

    주문내역은 취소완료 행의 `정산예정금액`·`마켓수수료` 를 0 으로 확정하고
    `실결제금액` 을 원금으로 되돌린다. 옛 마진계산기는 '수수료 0 = 아직 미정산'
    으로 오해해 실결제×0.947 추정을 만들어 냈다 — 취소된 주문이 매출로 잡혀
    마진이 통째로 부풀려졌다.
    """
    row = _oe_row(판매처="롯데온", 주문상태="취소완료", 실결제금액=50000,
                  마켓수수료=0, 배송비=3000, 단가=50000, 수량=1,
                  **{"정산예정금액": 0, "정산예정금(배송비포함)": 3000,
                     "_settle_source": "zero_cancel"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 0
    assert df.loc[0, "_settle_source"] == "zero_cancel"


def test_esm_cancelled_order_does_not_keep_shipping():
    """옥션·G마켓 취소완료: 배송비가 정산으로 잔존하면 안 된다."""
    for market in ("옥션", "G마켓"):
        row = _oe_row(판매처=market, 주문상태="취소완료", 배송비=3000,
                      **{"정산예정금액": 0, "정산예정금(배송비포함)": 3000,
                         "_settle_source": "zero_cancel"})
        df = SS._rows_to_df([row])
        assert df.loc[0, "정산예상금액_배송비포함"] == 0, market


def test_cancelled_detected_by_status_when_tag_missing():
    """적재분에 zero_cancel 태그가 없던 시절 행도 주문상태로 같은 판정이 나온다."""
    row = _oe_row(판매처="롯데온", 주문상태="취소완료(배송)", 실결제금액=50000,
                  마켓수수료="", **{"_settle_source": "none"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 0
    assert df.loc[0, "_settle_source"] == "zero_cancel"


# ── 주문내역 매출 필드 동기화 (사장님 지시 2026-07-23) ────────────────────

def test_order_revenue_fields_are_carried_verbatim():
    """매출 금액을 마진계산기가 다시 만들지 않고 주문내역 값을 그대로 싣는다."""
    row = _oe_row(단가=80000, 수량=2, 옵션추가금=5000,
                  상품금액=160000, 총주문금액=165000)
    df = SS._rows_to_df([row])
    assert df.loc[0, "옵션추가금"] == 5000
    assert df.loc[0, "상품금액"] == 160000
    assert df.loc[0, "총주문금액"] == 165000


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


def test_settlement_survives_formatted_strings():
    """쉼표·소수점 문자열로 온 정산액이 조용히 사라지면 안 된다."""
    row = _oe_row(판매처="롯데온", 실결제금액="103,000", 마켓수수료="12,000.0",
                  **{"정산예정금(배송비포함)": "91,000.0", "_settle_source": "real"})
    df = SS._rows_to_df([row])
    assert df.loc[0, "정산예상금액_배송비포함"] == 91000
    assert df.loc[0, "_settle_source"] == "real"


def test_ESM_정산은_주문내역_배송비포함값을_그대로():
    """샵마인 정답지 대사(2026-07-22): 옥션 7/7·G마켓 20/21 불일치가 정확히 배송비
    (+3,000)만큼 작았다 — ESM 정산조회 SettlementPrice 는 상품 정산만이라 배송비를
    더해야 샵마인 `정산예상금액(배송비포함)` 정의와 같아진다. 그 덧셈은 이제
    주문내역이 하고, 마진계산기는 결과만 읽는다."""
    from lemouton.margin.sell_source import _settlement_for
    settle, src = _settlement_for({"판매처": "옥션", "정산예정금액": 10000,
                                   "정산예정금(배송비포함)": 13000,
                                   "_settle_source": "real", "배송비": 3000})
    assert (settle, src) == (13000, "real")
    # 배송비 0(무료·정규화로 뒷행 0)이면 그대로
    settle2, _ = _settlement_for({"판매처": "G마켓", "정산예정금액": 10000,
                                  "정산예정금(배송비포함)": 10000,
                                  "_settle_source": "real", "배송비": 0})
    assert settle2 == 10000
    # 미정산(none)은 여전히 0 — 지어내지 않는다
    settle3, src3 = _settlement_for({"판매처": "옥션", "정산예정금액": "",
                                     "정산예정금(배송비포함)": "",
                                     "_settle_source": "none", "배송비": 3000})
    assert (settle3, src3) == (0, "none")


def test_untrusted_tag_does_not_borrow_orders_value():
    """태그가 none 인데 값만 남아 있으면 믿지 않는다(배송비만 정산으로 새던 경로)."""
    from lemouton.margin.sell_source import _settlement_for
    settle, src = _settlement_for({"판매처": "쿠팡", "정산예정금액": 0,
                                   "정산예정금(배송비포함)": 3000,
                                   "_settle_source": "none", "배송비": 3000})
    assert (settle, src) == (0, "none")
