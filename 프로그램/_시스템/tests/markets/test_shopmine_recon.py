# -*- coding: utf-8 -*-
"""샵마인 대조 엔진 계약 테스트 — 스펙 docs/superpowers/specs/2026-07-22-샵마인-대조탭-design.md.

핵심 계약:
- 애매한 것은 절대 '일치'로 뭉개지 않는다 — 일치/정의·허용차이/불일치/판정불가만 존재.
- 샵마인 돈 숫자는 [정가→실결제→정산] 자체 항등식 체인(계산값) — 재현식이 맞으면
  「정의차이」(노랑), 재현식으로도 안 맞으면 「불일치」(빨강, 작업필요)로 정직 표시.
- 계정 매핑은 이름표 무시, 주문번호 교집합이 진실(11번가 박스↔브랜드위시 이름 교차 실측).
"""
import lemouton.markets.models_orders  # noqa: F401
import lemouton.markets.models_shopmine  # noqa: F401
from lemouton.markets import shopmine_recon as R


# ── 파싱 정규화 ────────────────────────────────────────────────────────────

def test_norm_col_full_width_space_and_typo():
    assert R._norm_col("삼품명") == "상품명"
    assert R._norm_col("정산예상금액（배송비포함）") == "정산예상금액_배송비포함"
    assert R._norm_col("오픈마켓　주문번호") == "오픈마켓주문번호"
    assert R._norm_col("  단가  ") == "단가"


def test_market_from_mall_prefix():
    assert R._market_of("01.지마켓") == "gmarket"
    assert R._market_of("02.옥션") == "auction"
    assert R._market_of("03.11번가") == "eleven11"
    assert R._market_of("04.스마트스토어") == "smartstore"
    assert R._market_of("06.쿠팡") == "coupang"
    assert R._market_of("18.롯데온") == "lotteon"
    assert R._market_of("99.미지몰") is None      # 미지원 몰은 None(제외 목록행)


def test_norm_date_two_digit_year():
    assert R._norm_date("26.04.22") == "2026-04-22"
    assert R._norm_date("2026-04-22 09:00:00") == "2026-04-22"
    assert R._norm_date("") == ""
    assert R._norm_date(None) == ""


def test_to_int_no_zero_fallback():
    assert R._num("32,400") == 32400
    assert R._num("32400.0") == 32400
    assert R._num("") is None       # 공란은 0 이 아니라 None(0원 날조 금지)
    assert R._num("알수없음") is None
    assert R._num(None) is None


# ── 샘플 행 빌더 ──────────────────────────────────────────────────────────

def _sm(mk="coupang", no="A1", alias="계정1", paid=32400, unit=32400, opt_add=0,
        qty=1, settle=28000, fee=4400, ship=0, option="블랙/95", date="2026-04-22",
        **kw):
    r = {"market": mk, "sm_alias": alias, "order_no": no, "sm_uid": f"u{no}",
         "order_date": date, "product": "상품", "option": option, "qty": qty,
         "unit": unit, "opt_add": opt_add, "paid": paid, "ship": ship,
         "settle_incl": settle, "fee": fee, "status": "정산완료"}
    r.update(kw)
    return r


def _ours(mk="쿠팡", no="A1", acct="우리계정1", paid=32400, unit=32400, qty=1,
          settle=28000, fee=4400, ship=0, option="블랙/95",
          date="2026-04-22 09:12:00", kind=None, src="real", **kw):
    r = {"판매처": mk, "오픈마켓주문번호": no, "쇼핑몰별칭": acct, "주문일": date,
         "상품명": "상품", "옵션": option, "수량": qty, "단가": unit,
         "실결제금액": paid, "정산예정금액": settle, "마켓수수료": fee,
         "배송비": ship, "_settle_source": src}
    if kind:
        r["_kind"] = kind
    r.update(kw)
    return r


# ── 계정 매핑 (주문번호 교집합 — 이름 무시) ───────────────────────────────

def test_account_mapping_by_order_no_intersection_ignores_labels():
    # 이름표가 교차돼 있어도(박스↔위시) 주문번호 교집합으로 매핑한다
    sm = [_sm(mk="eleven11", no=f"B{i}", alias="박스(11번가)") for i in range(5)] \
       + [_sm(mk="eleven11", no=f"W{i}", alias="위시(11번가)") for i in range(4)]
    ours = [_ours(mk="11번가", no=f"B{i}", acct="브랜드위시") for i in range(5)] \
         + [_ours(mk="11번가", no=f"W{i}", acct="브랜드박스") for i in range(4)]
    m = R.map_accounts(sm, ours)
    by = {(a["market"], a["sm_alias"]): a for a in m}
    assert by[("eleven11", "박스(11번가)")]["our_account"] == "브랜드위시"
    assert by[("eleven11", "박스(11번가)")]["hits"] == 5
    assert by[("eleven11", "위시(11번가)")]["our_account"] == "브랜드박스"


def test_account_mapping_unregistered_and_ambiguous():
    sm = [_sm(no="X1", alias="미등록몰"), _sm(no="X2", alias="미등록몰")]
    m = R.map_accounts(sm, [])
    assert m[0]["status"] == "unregistered"      # 교집합 0 = 미등록(제외 목록)
    # 복수 계정 분산 = 중복 등록 의심
    sm2 = [_sm(no=f"D{i}", alias="분산몰") for i in range(4)]
    ours2 = [_ours(no="D0", acct="갑"), _ours(no="D1", acct="갑"),
             _ours(no="D2", acct="을"), _ours(no="D3", acct="을")]
    m2 = R.map_accounts(sm2, ours2)
    assert m2[0]["status"] == "ambiguous"


# ── 페어링 (3분류 — 뭉개기 금지) ─────────────────────────────────────────

def test_pairing_single_line_exact():
    res = R.reconcile([_sm()], [_ours()])
    assert res["existence"]["missing"] == 0
    assert res["undecided_total"] == 0


def test_pairing_multi_line_by_option_then_price_qty():
    sm = [_sm(no="M1", option="블랙/95", paid=10000, unit=10000),
          _sm(no="M1", option="화이트/100", paid=20000, unit=20000, sm_uid="u2")]
    ours = [_ours(no="M1", option="화이트 / 100", paid=20000, unit=20000),
            _ours(no="M1", option="블랙/95", paid=10000, unit=10000)]
    res = R.reconcile(sm, ours)
    assert res["undecided_total"] == 0
    # 옵션 문자열이 달라도 (단가,수량) 으로 짝지어진다
    sm2 = [_sm(no="M2", option="옵A", unit=10000, paid=10000),
           _sm(no="M2", option="옵B", unit=20000, paid=20000, sm_uid="u3")]
    ours2 = [_ours(no="M2", option="전혀다른A", unit=10000, paid=10000),
             _ours(no="M2", option="전혀다른B", unit=20000, paid=20000)]
    res2 = R.reconcile(sm2, ours2)
    assert res2["undecided_total"] == 0


def test_pairing_leftover_is_undecided_not_forced():
    # 다품에서 옵션도 (단가,수량)도 못 짝지으면 판정불가 — 억지 짝짓기 금지
    sm = [_sm(no="U1", option="옵A", unit=10000, paid=10000),
          _sm(no="U1", option="옵B", unit=10000, paid=10000, sm_uid="u2")]
    ours = [_ours(no="U1", option="옵C", unit=11000, paid=11000),
            _ours(no="U1", option="옵D", unit=12000, paid=12000)]
    res = R.reconcile(sm, ours)
    assert res["undecided_total"] == 2


def test_prefers_order_row_over_claim_row():
    ours = [_ours(no="C1", paid=99999, kind="change"),
            _ours(no="C1", paid=32400)]
    res = R.reconcile([_sm(no="C1")], ours)
    f = res["fields"]["coupang"]["paid"]
    assert f["match"] == 1 and f["diff"] == 0


# ── 존재(누락) ────────────────────────────────────────────────────────────

def test_missing_orders_reported_per_account():
    sm = [_sm(no="E1"), _sm(no="E2", sm_uid="u9")]
    res = R.reconcile(sm, [_ours(no="E1")])
    assert res["existence"]["missing"] == 1
    assert res["missing"][0]["order_no"] == "E2"


# ── 필드 판정: 실결제 ─────────────────────────────────────────────────────

def test_paid_match_and_tolerated():
    assert R.reconcile([_sm()], [_ours()])["fields"]["coupang"]["paid"]["match"] == 1
    res = R.reconcile([_sm(paid=32403)], [_ours(paid=32400)])
    assert res["fields"]["coupang"]["paid"]["tol"] == 1   # ±6원 = 허용차이(반올림)


def test_paid_defined_diff_gross_total():
    # 샵 실결제 = (단가+옵션추가금)×수량 (정가총액) — 우리(할인 반영 원본)와 다르면 정의차이
    res = R.reconcile([_sm(paid=32400, unit=30000, opt_add=2400, qty=1)],
                      [_ours(paid=29000, unit=30000)])
    f = res["fields"]["coupang"]["paid"]
    assert f["def"] == 1 and f["diff"] == 0


def test_paid_defined_diff_settle_plus_fee():
    # 샵 실결제 = 샵 정산예상+수수료 (11번가·옥션·G마켓 패턴, 일부 −고객배송비)
    res = R.reconcile([_sm(mk="eleven11", paid=31618, settle=27406, fee=4212,
                           unit=99999)],
                      [_ours(mk="11번가", paid=30000, unit=99999)])
    assert res["fields"]["eleven11"]["paid"]["def"] == 1
    res2 = R.reconcile([_sm(mk="gmarket", paid=30406, settle=27406, fee=4212,
                            ship=1212, unit=99999)],
                       [_ours(mk="G마켓", paid=30000, unit=99999)])
    assert res2["fields"]["gmarket"]["paid"]["def"] == 1


def test_paid_lotteon_seller_only_discount():
    # 롯데온: 샵 실결제 = 정가 − 셀러부담할인(이커머스부담 미차감) — _lo_seller_dc 로 재현
    res = R.reconcile(
        [_sm(mk="lotteon", paid=28000, unit=30000, qty=1, settle=None, fee=None)],
        [_ours(mk="롯데온", paid=26500, unit=30000, _lo_seller_dc="2000")])
    assert res["fields"]["lotteon"]["paid"]["def"] == 1


def test_paid_real_mismatch_is_red():
    res = R.reconcile([_sm(paid=50000, unit=32400, settle=28000, fee=4400)],
                      [_ours(paid=32400)])
    f = res["fields"]["coupang"]["paid"]
    assert f["diff"] == 1 and f["match"] == 0
    assert res["mismatch"][0]["field"] == "paid"


def test_paid_blank_buckets():
    res = R.reconcile([_sm(paid=None)], [_ours()])
    assert res["fields"]["coupang"]["paid"]["shop_blank"] == 1
    res2 = R.reconcile([_sm()], [_ours(paid="")])
    assert res2["fields"]["coupang"]["paid"]["ours_blank"] == 1


# ── 필드 판정: 정산 ───────────────────────────────────────────────────────

def test_settle_esm_ours_plus_shipping():
    # 옥션·G마켓 우리 정산(real)에 배송비 가산 후 비교 (sell_source._settlement_for)
    res = R.reconcile([_sm(mk="auction", settle=30406, paid=31618, fee=1212)],
                      [_ours(mk="옥션", settle=27406, ship=3000, paid=31618, fee=1212)])
    assert res["fields"]["auction"]["settle"]["match"] == 1


def test_settle_ours_estimated_not_compared():
    # 우리 정산이 추정(estimated)이면 비교하지 않는다 — 추정을 정답처럼 대조 금지
    res = R.reconcile([_sm(mk="lotteon", settle=28000)],
                      [_ours(mk="롯데온", settle="", fee="", src="estimated")])
    assert res["fields"]["lotteon"]["settle"]["ours_blank"] == 1


def test_settle_defined_diff_identity_chain():
    # 샵 정산 = 샵 실결제 − 수수료(+고객배송비) 재현되면 정의차이
    res = R.reconcile([_sm(paid=31618, settle=27406, fee=4212)],
                      [_ours(paid=31618, settle=27000, fee=4212)])
    assert res["fields"]["coupang"]["settle"]["def"] == 1


# ── 필드 판정: 주문일·단가·수량 ──────────────────────────────────────────

def test_date_qty_unit_compare():
    res = R.reconcile([_sm(date="2026-04-22", qty=2, unit=15000, paid=30000)],
                      [_ours(date="2026-04-22 15:30:00", qty=2, unit=15000,
                             paid=30000)])
    f = res["fields"]["coupang"]
    assert f["date"]["match"] == 1 and f["qty"]["match"] == 1 and f["unit"]["match"] == 1
    res2 = R.reconcile([_sm(qty=3)], [_ours(qty=1)])
    assert res2["fields"]["coupang"]["qty"]["diff"] == 1


# ── 요약·저장 ────────────────────────────────────────────────────────────

def test_summary_shape_and_period_from_file():
    res = R.reconcile([_sm(date="2026-04-15"), _sm(no="A2", date="2026-07-21",
                                                   sm_uid="u8")],
                      [_ours(), _ours(no="A2")])
    assert res["period"] == ["2026-04-15", "2026-07-21"]   # 기간 = 파일이 결정
    assert res["sm_rows"] == 2
    assert set(res["existence"]) >= {"total", "found", "missing"}
