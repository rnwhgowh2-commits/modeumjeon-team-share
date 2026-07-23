# -*- coding: utf-8 -*-
"""[TEST] 롯데아이몰 PDP 다운로드 쿠폰 — 「플러스 할인쿠폰」 칸 (2026-07-23 주문서 실측).

■ 사장님 질문에서 출발: 「[르무통] 5% 다운로드 쿠폰」이 계산식에 안 뜬다
   → 조사 결과 **수집 자체를 안 하고 있었다**.

■ 🔴 처음엔 「할인쿠폰 칸 택1」로 잘못 판정했다. 사장님 **주문서 실측**이 정답:
       총 주문금액        149,000
       할인쿠폰 6장       −29,100   ← 표면가(119,900)에 이미 반영
       플러스 할인쿠폰    − 6,000   ← **다운로드 쿠폰이 여기로 들어간다**
       최종결제금액       113,900
   → 할인쿠폰과 **동시 적용**이고, 기준은 정가가 아니라 **표면가**(119,900×5%=5,995≈6,000).

■ 대신 택1은 플러스 칸 안에서 — 쿠폰함 문구 "**플러스/즉시적립할인은 1개만 적용**".
   경유 「네이버 N%플러스할인쿠폰」과 같은 칸이라 **큰 쪽 하나만** 쓴다.

■ 수집은 확장이 이미 받는 원본 SSR HTML 안(`div.layer_down_coupon`) — **추가 API 호출 0**.
"""
import pytest

bs4 = pytest.importorskip("bs4")
from bs4 import BeautifulSoup  # noqa: E402

from lemouton.sourcing.crawlers.lotteon import (  # noqa: E402
    _parse_download_coupons,
    _parse_preapplied_coupon_amount,
    resolve_download_coupon_saving,
)

# 라이브 실측 구조 그대로 (goods_no=2559138690)
LIVE_HTML = """
<div class="layer_product_detail layer_down_coupon renew_pop_detail">
  <div class="box renew_pop_dim">
    <div class="header_layer">유영빈님을 위한 쿠폰</div>
    <div class="body_layer couponwrap">
      <h3 class="layer_sub_title">지금 적용 가능한 할인 혜택이 있어요!</h3>
      <div class="coupon_list"><ul>
        <li><span class="coupon">
          <span class="price">5<span class="per">%</span></span>
          <span class="name">[르무통] 5% 다운로드 쿠폰</span>
          <button class="btn btnCouponDown">쿠폰받기</button>
        </span></li>
      </ul></div>
    </div>
  </div>
</div>
<script>
  var dataBenefit = {"data":{"commonDiscountObj":{"benefitPrc":"119,900",
  "benefitPrcLabelTxt":"\\uc720\\uc601\\ube48\\ub2d8 \\ucd5c\\ub300\\ud560\\uc778\\uac00","lclubYn":"Y"},
  "fullDiscountObj":{"discountList":[{"discountNm":"\\ucfe0\\ud3f0\\ud560\\uc778","discountAmount":"-29,100"}]}}};
</script>
"""

# 위 유니코드 이스케이프를 쓰지 않는 평문 버전(파서는 둘 다 봐야 한다)
PLAIN_DISCOUNT = ('<script>var dataBenefit = {"data":{"fullDiscountObj":'
                  '{"discountList":[{"discountNm":"쿠폰할인","discountAmount":"-29,100"}]}}};</script>')


# ── 수집 ────────────────────────────────────────────────────────
def test_download_coupon_is_parsed():
    """PDP 쿠폰 레이어에서 쿠폰명·요율을 뽑는다(추가 API 호출 없이 원본 HTML 에서)."""
    soup = BeautifulSoup(LIVE_HTML, "html.parser")
    cps = _parse_download_coupons(soup)
    assert len(cps) == 1, cps
    c = cps[0]
    assert c["label"] == "[르무통] 5% 다운로드 쿠폰"
    assert c["rate"] == pytest.approx(0.05)
    assert not c.get("amount")


def test_no_coupon_layer_returns_empty():
    """쿠폰 레이어가 없으면 빈 목록 — 폴백으로 지어내지 않는다."""
    assert _parse_download_coupons(BeautifulSoup("<div></div>", "html.parser")) == []


def test_amount_type_coupon():
    """정액(원) 쿠폰도 읽는다 — `.per` 가 '%' 가 아니면 정액."""
    html = ('<div class="layer_down_coupon"><div class="coupon_list"><ul><li>'
            '<span class="price">3,000<span class="per">원</span></span>'
            '<span class="name">[테스트] 3천원 쿠폰</span></li></ul></div></div>')
    c = _parse_download_coupons(BeautifulSoup(html, "html.parser"))[0]
    assert c["amount"] == 3000 and not c.get("rate")


def test_preapplied_coupon_amount_is_parsed():
    """표면가에 이미 반영된 「쿠폰할인」 금액을 dataBenefit 에서 뽑는다."""
    assert _parse_preapplied_coupon_amount(PLAIN_DISCOUNT) == 29100


def test_preapplied_ignores_non_coupon_rows():
    """「쿠폰」이 아닌 할인 항목은 선반영 쿠폰액으로 세지 않는다."""
    html = ('<script>var dataBenefit = {"data":{"fullDiscountObj":{"discountList":'
            '[{"discountNm":"기본할인","discountAmount":"-10,000"}]}}};</script>')
    assert _parse_preapplied_coupon_amount(html) == 0


# ── 차감 계산 (플러스 칸) ────────────────────────────────────────
def test_live_case_matches_order_sheet():
    """★핵심 핀 — 주문서 실측: 표면 119,900 · 5% → **5,995**(화면 6,000, 단수 내림).

    할인쿠폰 29,100 과 **동시 적용**이므로 선반영액을 이유로 0 이 되면 안 된다.
    """
    saving = resolve_download_coupon_saving(
        surface_price=119_900,
        coupons=[{"label": "[르무통] 5% 다운로드 쿠폰", "rate": 0.05}])
    assert saving == 5_995


def test_base_is_surface_price_not_list_price():
    """기준은 **할인쿠폰 적용 후 금액(표면가)** — 정가(149,000) 기준이면 7,450 이 나온다."""
    saving = resolve_download_coupon_saving(
        surface_price=119_900, coupons=[{"label": "5%", "rate": 0.05}])
    assert saving != 7_450 and saving == 5_995


def test_amount_coupon_is_used_as_is():
    """정액 쿠폰은 그대로."""
    assert resolve_download_coupon_saving(
        surface_price=100_000, coupons=[{"label": "3천원", "amount": 3_000}]) == 3_000


def test_best_of_multiple_coupons():
    """쿠폰이 여러 장이어도 **1장만** 쓸 수 있으므로 가장 큰 것으로."""
    saving = resolve_download_coupon_saving(
        surface_price=100_000,
        coupons=[{"label": "3%", "rate": 0.03}, {"label": "7%", "rate": 0.07},
                 {"label": "정액", "amount": 5_000}])
    assert saving == 7_000


def test_loses_plus_slot_to_bigger_naver_coupon():
    """플러스 칸 택1 — 경유 네이버 쿠폰(7%)이 더 크면 다운로드 쿠폰은 **0**."""
    saving = resolve_download_coupon_saving(
        surface_price=100_000, coupons=[{"label": "5%", "rate": 0.05}],
        rival_saving=7_000)
    assert saving == 0


def test_wins_plus_slot_when_bigger():
    """반대로 다운로드 쿠폰이 크면 그대로 쓴다(경유 쿠폰은 호출부가 뺀다)."""
    saving = resolve_download_coupon_saving(
        surface_price=100_000, coupons=[{"label": "9%", "rate": 0.09}],
        rival_saving=7_000)
    assert saving == 9_000


def test_no_coupon_means_no_saving():
    """쿠폰 없음 → 0. 지어내지 않는다(폴백 금지)."""
    assert resolve_download_coupon_saving(surface_price=100_000, coupons=[]) == 0


def test_garbage_input_is_safe():
    """망가진 입력에도 예외 없이 0 — 쿠폰 실패가 가격·재고 크롤을 죽이면 안 된다."""
    assert resolve_download_coupon_saving(surface_price=0, coupons=[{"label": "x"}]) == 0
