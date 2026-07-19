# -*- coding: utf-8 -*-
"""SSG 표면노출가 = 「최적가」 ``bestAmt`` (없으면 ``sellprc``).

정본: ``docs/소싱처별-정답지-읽는법.md`` §SSG.

  표면가로 잡는 값 : 인라인 JS ``uitemObj`` 의 ``bestAmt`` → 0/누락이면 ``sellprc``
                     (`crawlers/ssg.py:_parse_uitem_options`)
  선반영된 것      : 상품 즉시할인 + (패턴 A/C 인 경우) SSG MONEY 즉시할인
  표면가 밖(별도)  : 카드혜택가 · SSG MONEY 적립(패턴 B/E) · 상품쿠폰
  캡처 조건        : 페이지 토글 조작 없음 (익명 HTML 파싱)

⚠️ **용어 충돌 미해결** — 정답지 §4 가 기록한 대로 ``populate_ssg_guide.py`` 는
「표면 노출가」를 **최적가 이전 값**이라 부른다. 본 테스트는 **코드가 실제로
``sale_price`` 에 넣는 값(=bestAmt)** 을 고정한 것이고, 그게 옳은 정의인지는
**미확정**이다. 사장님이 정의를 확정하면 기대값을 바꾼다.
그래도 "표면가 정의가 조용히 바뀌는 것"은 이 테스트가 잡는다.

픽스처 출처: ``tests/sourcing/fixtures/ssg_sample.html`` — 기존 픽스처 재사용
(라이브 캡처 실 HTML). 폴백·경계 케이스는 ``uitemObj`` 블록만 축약 재구성했고
실제 응답과 다를 수 있다.
"""
from lemouton.sourcing.crawlers.ssg import SsgCrawler, _parse_uitem_options

URL = ("https://www.ssg.com/item/itemView.ssg"
       "?itemId=1000809938058&siteNo=6009&salestrNo=1004")

# 실 픽스처 실측값 (남성 나이키 리엑스 8 IR5118-200)
SURFACE_PRICE = 66640       # bestAmt = 최적가          ★ 이게 표면가
SELLPRC = 83300             # sellprc = 정가            ✗ 표면가 아님
CARD_BENEFIT_PRICE = 61976  # 카드혜택가                ✗ 표면가 아님


def _uitem(*, uitem_id="00001", optn1="250", type1="사이즈",
           sellprc="83300", best_amt="66640", inv="5"):
    """SSG 인라인 JS ``uitemObj`` 블록 축약 재현 (파서가 읽는 필드만)."""
    best = f"bestAmt:'{best_amt}'," if best_amt is not None else ""
    return (
        "uitemObj = {itemId:'1000809938058', uitemId:'%s',"
        "uitemOptnTypeNm1:'%s', uitemOptnNm1:'%s',"
        "uitemOptnTypeNm2:'', uitemOptnNm2:'',"
        "sellprc:parseInt('%s', 10) || 0, %s"
        "usablInvQty:'%s'}; uitemObjArr.push(uitemObj);"
        % (uitem_id, type1, optn1, sellprc, best, inv)
    )


# ─────────────────────────────────────────────────────────────
# ① 표면가로 무엇을 잡는가 — bestAmt(최적가)
# ─────────────────────────────────────────────────────────────
def test_surface_price_is_best_amt(html_of):
    """라이브 픽스처: bestAmt 66,640 이 전 옵션 price 로 들어가야 한다."""
    res = SsgCrawler().parse_html(html_of("ssg"), URL)
    assert res.options
    assert {o["price"] for o in res.options} == {SURFACE_PRICE}
    assert {o["sale_price"] for o in res.options} == {SURFACE_PRICE}


def test_surface_price_is_best_amt_unit():
    """단위 레벨: bestAmt 가 있으면 sellprc 를 무시한다."""
    opts = _parse_uitem_options(_uitem(), "1000809938058")
    assert len(opts) == 1
    assert opts[0]["price"] == SURFACE_PRICE
    assert opts[0]["price"] != SELLPRC


# ─────────────────────────────────────────────────────────────
# ② 선반영/별도 값을 표면가로 잡으면 실패해야 한다
# ─────────────────────────────────────────────────────────────
def test_sellprc_is_not_used_as_surface_when_best_amt_exists(html_of):
    """정가(sellprc 83,300)가 표면가로 새면 즉시할인만큼 매입가가 부풀려진다."""
    res = SsgCrawler().parse_html(html_of("ssg"), URL)
    assert SELLPRC not in {o["price"] for o in res.options}


def test_card_benefit_price_is_not_used_as_surface(html_of):
    """카드혜택가(61,976)를 표면가로 잡으면 카드분 이중차감 → 언더프라이싱."""
    res = SsgCrawler().parse_html(html_of("ssg"), URL)
    prices = {o["price"] for o in res.options}
    assert CARD_BENEFIT_PRICE not in prices
    # 카드혜택가는 표면가가 아니라 **별도 키**로만 실린다
    assert res.options[0]["card_benefit_price"] == CARD_BENEFIT_PRICE


def test_product_coupon_is_not_baked_into_surface_price(html_of):
    """상품쿠폰 12% 는 표면가 밖(별도 키). 표면가는 쿠폰 미적용 값이어야 한다."""
    o = SsgCrawler().parse_html(html_of("ssg"), URL).options[0]
    assert o["product_coupon_rate"] == 0.12
    assert o["price"] == SURFACE_PRICE                      # 쿠폰 차감 전
    assert o["price"] != round(SURFACE_PRICE * (1 - 0.12))  # 쿠폰이 먹은 값이 아니다


def test_ssg_money_preapplied_flag_is_preserved(html_of):
    """★ 이중차감 차단 장치 — SSG MONEY 즉시할인이 bestAmt 에 선반영이면 True.

    이 픽스처는 **적립(패턴 B)** 이라 False 가 정답이다. 이 플래그가 조용히 사라지거나
    뒤집히면 ``api_benefits`` 게이트가 무력화돼 SSG MONEY 가 두 번 빠진다.
    """
    o = SsgCrawler().parse_html(html_of("ssg"), URL).options[0]
    assert o["ssg_money_already_applied"] is False
    assert o["ssg_money_rate"] == 1.5


# ─────────────────────────────────────────────────────────────
# ③ 폴백이 엉뚱한 값으로 떨어지지 않는가
# ─────────────────────────────────────────────────────────────
def test_falls_back_to_sellprc_only_when_best_amt_absent():
    """bestAmt 필드가 아예 없을 때만 sellprc(정가) 폴백."""
    opts = _parse_uitem_options(_uitem(best_amt=None), "1000809938058")
    assert opts[0]["price"] == SELLPRC


def test_falls_back_to_sellprc_when_best_amt_zero():
    opts = _parse_uitem_options(_uitem(best_amt="0"), "1000809938058")
    assert opts[0]["price"] == SELLPRC


def test_zero_price_option_is_dropped_not_zero_filled():
    """bestAmt·sellprc 둘 다 0 이면 0원 옵션을 만들지 않고 제외.

    0원이 매트릭스에 흘러 최저가로 오인되면 금전 손실.
    """
    opts = _parse_uitem_options(
        _uitem(sellprc="0", best_amt="0"), "1000809938058")
    assert opts == []
