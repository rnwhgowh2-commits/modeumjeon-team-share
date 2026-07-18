# -*- coding: utf-8 -*-
"""롯데아이몰 표면노출가 = **카드 미적용 할인가** (2026-07-18 사용자 확정).

배경:
  구 정책은 ``dataBenefit.commonDiscountObj.benefitPrc`` (= 롯데홈쇼핑 "최대할인가",
  카드 청구할인 **포함**) 를 crawled_price 에 담았다. 그런데 현대H몰은 표면가 =
  ``bbprc`` (카드 미포함) 이고 카드할인은 ``hmall_card_discount`` 로 분리한다.
  두 소싱처가 같은 "표면노출가" 슬롯에 다른 의미의 값을 담아 매트릭스 비교가
  성립하지 않았다 → 롯데아이몰을 H몰 규약에 맞춘다.

라이브 실측 (르무통 메이트 메리노울 운동화):
    정가 149,000
    → 할인 −32,100 → **116,900 (22% 할인가) = 표면노출가**
    → 삼성카드 7% 청구할인 −8,180 → 108,720 (= benefitPrc, 최대할인가)
"""
import json

import pytest
from bs4 import BeautifulSoup

from lemouton.sourcing.crawlers.lotteon import (
    LotteCrawler,
    _is_lotteon,
    _resolve_surface_price,
)

URL = "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559417201"

# 사용자 제공 라이브 실측값
ORIGIN_PRICE = 149000       # 정가
SURFACE_PRICE = 116900      # 표면노출가 = 카드 미적용 22% 할인가  ★ 이게 정답
CARD_AMOUNT = 8180          # 삼성카드 7% 청구할인액
MAX_PRICE = 108720          # 최대할인가 (카드 포함) = benefitPrc  ★ 이건 표면가 아님


def _data_benefit(*, benefit_prc="108,720", card_list=None,
                  label_txt="(삼성카드 7%)"):
    """실제 dataBenefit JSON 구조(문서화된 필드만) 축약 재현."""
    payload = {
        "data": {
            "commonDiscountObj": {
                "benefitPrc": benefit_prc,
                "benefitPrcLabelTxt": label_txt,
            },
            "fullDiscountObj": {
                "cardDiscountList": card_list if card_list is not None else [{
                    "discountNm": "삼성카드 7% 청구할인",
                    "discountCardNm": "삼성",
                    "discountRt": 7,
                    "discountAmount": "-8,180",
                }],
                "lPointObj": {
                    "nMbrPoint": "+116P", "lMbrPoint": "+584P",
                    "pointLabelTxt": "구매적립 L.POINT",
                    "nMbrSaveamt": "+300원", "lMbrSaveamt": "+600원",
                    "gdasLabelTxt": "리뷰작성 적립금",
                },
            },
        }
    }
    return "dataBenefit = " + json.dumps(payload, ensure_ascii=False) + ";"


def _lotteimall_html(*, benefit_prc="108,720", card_list=None,
                     label_txt="(삼성카드 7%)", sizes=("240", "250", "260")):
    """롯데아이몰 SSR HTML 축약 재현 (V7 셀렉터 + dataBenefit 인라인 JSON)."""
    size_lis = "".join(
        f'<li><p class="txt_option">{s}</p></li>' for s in sizes
    )
    return f"""<html><head><title>르무통 메이트 메리노울 운동화 | 롯데아이몰</title></head>
<body>
  <div class="title">르무통 메이트 발 편한 메리노울 운동화</div>
  <div class="name">르무통</div>
  <div class="ir_price"><span class="num">149,000</span></div>
  <div class="price"><span class="num">116,900</span></div>
  <div class="final"><span class="num">108,720</span></div>
  <em class="txt_em">108,720원 (삼성카드 7%)</em>
  <div class="inp_option inpOptList">
    <p class="txt_option">사이즈 선택</p>
    {size_lis}
  </div>
  <script>{_data_benefit(benefit_prc=benefit_prc, card_list=card_list,
                         label_txt=label_txt)}</script>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# ① 표면가로 116,900 이 나오는가
# ─────────────────────────────────────────────────────────────
def test_surface_price_is_card_unapplied_discount_price():
    res = LotteCrawler().parse_html(_lotteimall_html(), URL)
    assert res.options, "옵션이 비면 안 됨"
    for o in res.options:
        assert o["price"] == SURFACE_PRICE
        assert o["sale_price"] == SURFACE_PRICE


# ─────────────────────────────────────────────────────────────
# ③ 최대할인가(카드 포함)를 표면가로 담지 않는다
# ─────────────────────────────────────────────────────────────
def test_max_discount_price_is_not_used_as_surface():
    res = LotteCrawler().parse_html(_lotteimall_html(), URL)
    prices = {o["price"] for o in res.options}
    assert MAX_PRICE not in prices, "최대할인가(카드 포함)가 표면가로 새면 안 됨"
    assert ORIGIN_PRICE not in prices, "정가가 표면가로 새면 안 됨"


def test_surface_price_identity_benefitprc_plus_card_amount():
    """항등식: 표면가 = benefitPrc + 카드청구할인액."""
    soup = BeautifulSoup(_lotteimall_html(), "lxml")
    price, source = _resolve_surface_price(
        soup, _lotteimall_html(),
        {"issuer": "삼성카드", "rate": 7.0, "amount": CARD_AMOUNT},
    )
    assert price == MAX_PRICE + CARD_AMOUNT == SURFACE_PRICE
    assert source == "benefitPrc+cardDiscountAmount"


# ─────────────────────────────────────────────────────────────
# ② 카드할인 8,180 + 카드명이 분리 저장되는가
# ─────────────────────────────────────────────────────────────
def test_card_discount_is_stored_separately():
    res = LotteCrawler().parse_html(_lotteimall_html(), URL)
    for o in res.options:
        assert o["lotteimall_card_discount"] == CARD_AMOUNT
        assert o["lotteimall_card_label"] == "삼성카드 7%"


def test_card_discount_not_baked_into_surface_price():
    """분리 보관 = 표면가에 미반영. included_in_sale_price 는 False 여야 한다.

    True 로 남으면 api_pricing 의 '카드 OFF 시 환원'(price/(1-rate)) 이 걸려
    이미 카드가 빠진 가격을 한 번 더 부풀린다.
    """
    res = LotteCrawler().parse_html(_lotteimall_html(), URL)
    acd = res.options[0]["auto_card_discount"]
    assert acd is not None
    assert acd["amount"] == CARD_AMOUNT
    assert acd["issuer"] == "삼성카드"
    assert acd["included_in_sale_price"] is False
    # 표면가 − 카드할인 = 최대할인가 (사이트 노출값과 일치)
    assert res.options[0]["price"] - acd["amount"] == MAX_PRICE


def test_card_keys_are_whitelisted_for_persistence():
    """분리 보관 키가 동적 혜택 화이트리스트에 없으면 저장 단계에서 조용히 증발한다."""
    from lemouton.sources.service import OPTION_DYNAMIC_KEYS
    from lemouton.pricing.benefit_parse import _PRODUCT_DYNAMIC_KEYS
    for key in ("lotteimall_card_discount", "lotteimall_card_label"):
        assert key in OPTION_DYNAMIC_KEYS
        assert key in _PRODUCT_DYNAMIC_KEYS


# ─────────────────────────────────────────────────────────────
# 카드할인 없는 상품 = 노출가가 곧 카드 미적용가 (회귀 방지)
# ─────────────────────────────────────────────────────────────
def test_no_card_discount_uses_benefit_prc_as_is():
    """검증 SKU 2559417201(카드할인 미노출) 처럼 카드가 없으면 benefitPrc 그대로."""
    html = _lotteimall_html(benefit_prc="99,900", card_list=[], label_txt="")
    html = html.replace('<em class="txt_em">108,720원 (삼성카드 7%)</em>', "")
    res = LotteCrawler().parse_html(html, URL)
    assert all(o["price"] == 99900 for o in res.options)
    assert res.options[0]["auto_card_discount"] is None
    assert "lotteimall_card_discount" not in res.options[0]


# ─────────────────────────────────────────────────────────────
# 폴백 금지 — 복원 불가 시 실패로 드러낸다
# ─────────────────────────────────────────────────────────────
def test_card_present_but_amount_missing_fails_loudly():
    """카드율만 알고 금액을 모르면 역산(나눗셈) 대신 실패.

    사이트가 10원 절사를 하므로 나눗셈 역산은 원 단위가 어긋난다 →
    틀린 가격보다 실패가 낫다(금전 직결).
    """
    html = _lotteimall_html(card_list=[{
        "discountNm": "삼성카드 7% 청구할인",
        "discountCardNm": "삼성",
        "discountRt": 7,
        "discountAmount": "",          # 금액 결측
    }])
    with pytest.raises(RuntimeError) as ei:
        LotteCrawler().parse_html(html, URL)
    assert "표면노출가" in str(ei.value)


def test_unparseable_card_list_fails_instead_of_leaking_max_price():
    """카드 항목은 있는데 구조화 실패(rate 결측) → benefitPrc 를 표면가로 둔갑시키지 않는다."""
    html = _lotteimall_html(label_txt="", card_list=[{
        "discountNm": "제휴카드 청구할인",   # 카드사·율 파싱 불가
        "discountCardNm": "",
        "discountRt": 0,
        "discountAmount": "-8,180",
    }])
    html = html.replace('<em class="txt_em">108,720원 (삼성카드 7%)</em>', "")
    with pytest.raises(RuntimeError) as ei:
        LotteCrawler().parse_html(html, URL)
    assert "표면노출가" in str(ei.value)


def test_card_present_but_benefitprc_missing_fails_loudly():
    html = _lotteimall_html(benefit_prc="")     # benefitPrc 결측
    with pytest.raises(RuntimeError) as ei:
        LotteCrawler().parse_html(html, URL)
    assert "표면노출가" in str(ei.value)


# ─────────────────────────────────────────────────────────────
# ④ 롯데온(lotteon.com) 경로는 안 바뀐다
# ─────────────────────────────────────────────────────────────
def test_lotteon_domain_routing_unchanged():
    assert _is_lotteon("https://www.lotteon.com/p/product/LM1234567890") is True
    assert _is_lotteon(URL) is False
    assert _is_lotteon("https://www.lottehomeshopping.com/goods/x?goods_no=1") is False


def test_lotteon_fetch_bypasses_lotteimall_parser(monkeypatch):
    """lotteon.com 은 _fetch_lotteon(pbf API) 로만 가고 SSR 파서를 타지 않는다."""
    import lemouton.sourcing.crawlers.lotteon as mod

    sentinel = object()
    called = {}

    def _fake_fetch_lotteon(url, timeout):
        called["url"] = url
        return sentinel

    monkeypatch.setattr(mod, "_fetch_lotteon", _fake_fetch_lotteon)
    monkeypatch.setattr(
        mod.LotteCrawler, "parse_html",
        lambda *a, **k: pytest.fail("롯데온이 lotteimall SSR 파서를 타면 안 됨"),
    )
    out = LotteCrawler().fetch("https://www.lotteon.com/p/product/LM1234567890")
    assert out is sentinel
    assert called["url"] == "https://www.lotteon.com/p/product/LM1234567890"
