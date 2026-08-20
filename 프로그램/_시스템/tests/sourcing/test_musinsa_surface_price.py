# -*- coding: utf-8 -*-
"""무신사 표면노출가 — **현재 코드 동작 스냅샷** (서버 비로그인 API 경로).

정본: ``docs/소싱처별-정답지-읽는법.md`` §무신사 — **확인 상태 ⚠️ 정의 4개 충돌**.

  표면가로 잡는 값 : ``api2/goods/{id}`` → ``data.goodsPrice.salePrice``
                     (`crawlers/musinsa.py:_fetch_via_api` `:457`)
                     ``normalPrice`` 는 **정가**이며 표면가가 아니다 (`:458`)
  선반영된 것      : 「쿠폰적용가」 라벨이 뜬 상품은 **쿠폰이 이미 먹은 값**
  표면가 아님      : 「나의 할인가」(회원가) — 등급할인·적립이 전부 먹은 값
  ★ 캡처 조건      : 「적립금 사용」 체크박스 **OFF** (사이트 기본값 ON) ·
                     「구매 적립」 쪽 · 결제수단 할인 무시

🔴 **이 값이 옳은지는 미확정 — 코드 현재 동작을 고정한 것이다.**
정답지 §1 이 기록한 대로 표면가 정의가 문서 4곳에서 충돌한다
(``background.js`` = salePrice / ``크롤링-가이드.md`` = 회원가 /
``profile.yaml`` = "salePrice 는 부적합" / ``api_benefits.py`` = 회원가).
사장님이 라이브 대조로 확정하면 기대값을 바꾼다.

⚠️ **덮는 범위** — 본 테스트는 **서버 비로그인 API 경로**(``_fetch_via_api``,
= ``prefer_member_price=False`` 다중 색상 모드)만 덮는다. 다음은 **덮지 않는다**:
  · 라이브 경로 = 크롬확장 ``extension/moum-crawler/background.js`` (JS. 이 저장소에
    JS 테스트 러너가 없다 — ``package.json`` 부재)
  · 서버 Playwright 경로 ``musinsa_playwright.py`` (브라우저 필요, 라이브 접속 금지)
정답지 D2·D3 이 지적한 라이브 경로의 「적립금 사용」·「쿠폰적용가」 가드 부재는
**여기서 검증되지 않는다.**

픽스처 출처: ``api2/goods`` · ``/options`` · ``/prioritized-inventories`` 응답을
**코드가 읽는 필드만 축약 재구성**했다(라이브 응답 미수신). 실제와 다를 수 있다.
"""
import pytest

from lemouton.sourcing.crawlers.musinsa import MusinsaCrawler

URL = "https://www.musinsa.com/products/4677240"
PRODUCT_ID = "4677240"

NORMAL_PRICE = 275400     # goodsPrice.normalPrice = 정가       ✗ 표면가 아님
SALE_PRICE = 220320       # goodsPrice.salePrice                ★ 현재 표면가
MEMBER_PRICE = 198000     # 「나의 할인가」(회원가) — 참고용     ✗ 표면가 아님


def _install(monkeypatch, *, sale_price=SALE_PRICE, normal_price=NORMAL_PRICE,
             extra_meta=None, out_of_stock=False, remain=None, inv=True):
    """네트워크 3콜을 픽스처로 대체 (라이브 접속 없음)."""
    meta = {"data": {
        "goodsNm": "르무통 클래식2 메리노울 운동화 블랙",
        "brandName": "르무통",
        "goodsPrice": {"salePrice": sale_price, "normalPrice": normal_price,
                       **(extra_meta or {})},
    }}
    opts = {"data": {
        "basic": [
            {"optionValues": [{"no": 11}]},
            {"optionValues": [{"no": 12}]},
        ],
        "optionItems": [
            {"no": 11, "managedCode": "블랙^250"},
            {"no": 12, "managedCode": "블랙^260"},
        ],
    }}
    inv_rows = [] if not inv else [
        {"productVariantId": 11, "outOfStock": out_of_stock, "remainQuantity": remain},
        {"productVariantId": 12, "outOfStock": False, "remainQuantity": None},
    ]
    monkeypatch.setattr(MusinsaCrawler, "_fetch_meta",
                        lambda self, pid, url: meta)
    monkeypatch.setattr(MusinsaCrawler, "_fetch_options",
                        lambda self, pid, url: opts)
    monkeypatch.setattr(MusinsaCrawler, "_fetch_inventories",
                        lambda self, pid, url, nos: {"data": inv_rows})


# ─────────────────────────────────────────────────────────────
# ① 표면가로 무엇을 잡는가 — goodsPrice.salePrice
# ─────────────────────────────────────────────────────────────
def test_surface_price_is_goods_price_sale_price(monkeypatch):
    _install(monkeypatch)
    res = MusinsaCrawler(prefer_member_price=False)._fetch_via_api(URL)
    assert res.options
    assert {o["price"] for o in res.options} == {SALE_PRICE}


# ─────────────────────────────────────────────────────────────
# ② 정가·회원가를 표면가로 잡으면 실패해야 한다
# ─────────────────────────────────────────────────────────────
def test_normal_price_is_not_used_as_surface(monkeypatch):
    """``normalPrice``(정가 275,400)가 표면가로 새면 할인분만큼 매입가가 부풀려진다."""
    _install(monkeypatch)
    res = MusinsaCrawler(prefer_member_price=False)._fetch_via_api(URL)
    assert NORMAL_PRICE not in {o["price"] for o in res.options}


def test_member_price_is_not_used_as_surface(monkeypatch):
    """「나의 할인가」(회원가)는 등급할인·적립이 **전부 먹은 값** → 표면가로 쓰면 이중차감.

    응답에 회원가류 필드가 섞여 들어와도 이 경로는 ``salePrice`` 만 본다.
    """
    _install(monkeypatch, extra_meta={
        "memberPrice": MEMBER_PRICE,
        "benefitPrice": MEMBER_PRICE,
        "couponAppliedPrice": 165000,
    })
    res = MusinsaCrawler(prefer_member_price=False)._fetch_via_api(URL)
    prices = {o["price"] for o in res.options}
    assert prices == {SALE_PRICE}
    assert MEMBER_PRICE not in prices
    assert 165000 not in prices          # 「쿠폰적용가」도 표면가로 새면 안 됨


# ─────────────────────────────────────────────────────────────
# ③ 폴백이 엉뚱한 값으로 떨어지지 않는가
# ─────────────────────────────────────────────────────────────
def test_falls_back_to_normal_price_only_when_sale_price_absent(monkeypatch):
    """salePrice 가 없을 때만 정가 승격 (V7 규약: 할인 없는 상품 = 판매가가 곧 정가)."""
    _install(monkeypatch, sale_price=0)
    res = MusinsaCrawler(prefer_member_price=False)._fetch_via_api(URL)
    assert {o["price"] for o in res.options} == {NORMAL_PRICE}


def test_both_prices_missing_fails_loudly(monkeypatch):
    """둘 다 없으면 0원 옵션을 만들지 않고 크롤 실패로 표면화 (0원 = 최저가 오인 = 손실)."""
    _install(monkeypatch, sale_price=0, normal_price=0)
    with pytest.raises(ValueError) as ei:
        MusinsaCrawler(prefer_member_price=False)._fetch_via_api(URL)
    assert "가격 파싱 실패" in str(ei.value)


def test_option_rows_share_one_surface_price(monkeypatch):
    """옵션(사이즈)마다 다른 값이 섞여 들어가지 않는다 — 표면가는 상품 단위 1개."""
    _install(monkeypatch, remain=3)
    res = MusinsaCrawler(prefer_member_price=False)._fetch_via_api(URL)
    assert len(res.options) == 2
    assert len({o["price"] for o in res.options}) == 1
    by_size = {o["size_text"]: o["stock"] for o in res.options}
    assert by_size == {"250": 3, "260": 999}


def test_no_options_still_carries_surface_price(monkeypatch):
    """단품(optionItems 0개) 폴백 행도 표면가를 그대로 실어야 한다."""
    _install(monkeypatch)
    monkeypatch.setattr(MusinsaCrawler, "_fetch_options",
                        lambda self, pid, url: {"data": {"basic": [], "optionItems": []}})
    res = MusinsaCrawler(prefer_member_price=False)._fetch_via_api(URL)
    assert len(res.options) == 1
    assert res.options[0]["price"] == SALE_PRICE
