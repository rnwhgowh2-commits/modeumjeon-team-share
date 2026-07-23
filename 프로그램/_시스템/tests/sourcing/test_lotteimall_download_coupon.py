# -*- coding: utf-8 -*-
"""[TEST] 롯데아이몰 다운로드 쿠폰 — 「할인쿠폰 칸 택1」 모델 (2026-07-23 라이브 실측).

■ 사장님 질문에서 출발: PDP 「쿠폰받기」의 「[르무통] 5% 다운로드 쿠폰」이
   계산식에 안 뜬다 → 조사 결과 **수집 자체를 안 하고 있었다**.

■ 실측으로 확정된 규칙 (goods_no=2559138690, 르무통 메이트 블랙)
   · 원본 SSR HTML(403KB, 확장이 same-origin fetch 로 이미 받는 그 HTML)에
     `div.layer_down_coupon .coupon_list li` 로 쿠폰이 들어 있다 → **추가 API 호출 0**.
   · `dataBenefit.fullDiscountObj.discountList` = [{"discountNm":"쿠폰할인",
     "discountAmount":"-29,100"}] → 표면가 119,900 은 **이미 쿠폰할인이 적용된 값**.
   · 아이몰 쿠폰함 공식 문구(스펙 §11): "상품별로 **할인쿠폰/카드할인/TV쇼핑할인
     중 1개만 선택**" → 다운로드 쿠폰은 선반영 쿠폰과 **같은 칸 = 택1**.

■ 그래서 계산은 "무조건 차감"이 아니라 **택1 비교**다:
       정가      = 표면가 + 선반영 쿠폰액
       대안가    = 정가 − (정가 × rate  또는  정액)
       추가 차감 = max(0, 표면가 − 대안가)
   이 상품: 정가 149,000 · 대안가 141,550 > 표면가 119,900 → **추가 차감 0**
   (= 5% 로 바꾸면 21,650원 더 비싸다. 안 깎는 게 정답이고 현행 계산식이 맞다.)

   🔴 이 규칙을 모르고 "쿠폰이 있으니 5% 깎자"고 하면 **매입가 과소 = 마진 착시**
      (SSG 제휴쿠폰 P30 과 같은 사고 클래스).
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


# ── 택1 계산 ─────────────────────────────────────────────────────
def test_live_case_saving_is_zero_because_preapplied_wins():
    """★핵심 핀 — 실측 상품: 선반영 29,100 ≫ 5%(7,450) → **추가 차감 0**.

    이걸 안 지키면 5,995~7,450 원을 잘못 깎아 매입가가 과소해진다(마진 착시).
    """
    saving = resolve_download_coupon_saving(
        surface_price=119_900, preapplied_coupon=29_100,
        coupons=[{"label": "[르무통] 5% 다운로드 쿠폰", "rate": 0.05}])
    assert saving == 0


def test_saving_applies_when_no_preapplied_coupon():
    """선반영 쿠폰이 없으면(할인쿠폰 칸이 빔) 다운로드 쿠폰을 그대로 쓴다."""
    saving = resolve_download_coupon_saving(
        surface_price=100_000, preapplied_coupon=0,
        coupons=[{"label": "5% 쿠폰", "rate": 0.05}])
    assert saving == 5_000


def test_saving_is_difference_when_download_coupon_wins():
    """다운로드 쿠폰이 더 크면 **차액만** 추가로 깎는다(선반영분 이중차감 금지)."""
    # 정가 = 100,000 + 2,000 = 102,000 · 대안가 = 102,000 − 10% = 91,800
    # 표면가 100,000 − 91,800 = 8,200
    saving = resolve_download_coupon_saving(
        surface_price=100_000, preapplied_coupon=2_000,
        coupons=[{"label": "10% 쿠폰", "rate": 0.10}])
    assert saving == 8_200


def test_best_of_multiple_coupons():
    """쿠폰이 여러 장이면 **1장만** 쓸 수 있으므로 가장 큰 것으로."""
    saving = resolve_download_coupon_saving(
        surface_price=100_000, preapplied_coupon=0,
        coupons=[{"label": "3%", "rate": 0.03}, {"label": "7%", "rate": 0.07},
                 {"label": "정액", "amount": 5_000}])
    assert saving == 7_000


def test_no_coupon_means_no_saving():
    """쿠폰 없음 → 0. 값이 없을 때 지어내지 않는다(폴백 금지)."""
    assert resolve_download_coupon_saving(surface_price=100_000,
                                          preapplied_coupon=0, coupons=[]) == 0


def test_garbage_input_is_safe():
    """망가진 입력에도 예외 없이 0 — 쿠폰 파싱 실패가 가격·재고 크롤을 죽이면 안 된다."""
    assert resolve_download_coupon_saving(surface_price=0, preapplied_coupon=None,
                                          coupons=[{"label": "x"}]) == 0
