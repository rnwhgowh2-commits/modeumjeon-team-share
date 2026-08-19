# -*- coding: utf-8 -*-
"""[2026-08-13 사장님 확정] 쿠팡 등록 — **정상가 = 할인가**로 통일한다.

`/bundles/<code>` 화면의 쿠팡 칸 「🚀 신규 등록」 단추가 타는 경로
(`api.py:/bundles/<code>/register/coupang` → `registration/coupang.py::_build_payload`)만
정상가와 할인가를 **다르게** 내보내고 있었다:

    originalPrice = 판매가            (정가)
    salePrice     = 옵션별 쿠팡 가격  (있으면 그걸로, 없으면 판매가)

옵션별 쿠팡 가격이 판매가보다 낮으면 쿠팡 화면에 **없는 할인**(취소선)이 붙는다.
사장님 확정은 「정상가 = 할인가」다.

★ 대량등록 경로(`compile_coupang` → `registration/options.py::build_coupang_items`)는
  **이미** `originalPrice == salePrice` 다. 두 경로가 갈려 있던 것이라, 여기를
  맞추면 한 벌이 된다(원천 분열 해소).
"""
from types import SimpleNamespace as NS

from lemouton.registration.coupang import (
    CoupangRegistrationInputs, _build_payload,
)


def _opt(sku="SKU-1", color="블랙", size="250", override=None):
    return NS(market_visible_coupang=True, color_code=color, size_code=size,
              option_coupang_price_override=override, canonical_sku=sku)


def _bundle():
    return NS(model_code="테스트모델", coupang_product_name_override=None,
              model_name_display="테스트 상품", model_name_raw="테스트 상품")


def _items(options, sale_price=100000):
    p = _build_payload(bundle=_bundle(), options=options, sale_price=sale_price,
                       inputs=CoupangRegistrationInputs(display_category_code=1))
    return p["items"]


def test_옵션별_쿠팡가격이_있으면_정상가도_그_값이다():
    """🔴 여기가 갈려 있었다 — 정상가 100,000 · 할인가 89,000 으로 나가
    쿠팡 화면에 **우리가 준 적 없는 11% 할인**이 붙었다."""
    it = _items([_opt(override=89000)])[0]
    assert it["salePrice"] == 89000
    assert it["originalPrice"] == it["salePrice"], (
        f'정상가({it["originalPrice"]})와 할인가({it["salePrice"]})가 다르다 '
        '— 쿠팡 화면에 없는 할인이 붙는다')


def test_옵션별_가격이_없으면_판매가로_둘_다():
    it = _items([_opt(override=None)], sale_price=120000)[0]
    assert it["originalPrice"] == it["salePrice"] == 120000


def test_대량등록_경로와_같은_규약이다():
    """두 경로가 같은 답을 내야 한다 — 갈리면 어느 문으로 등록했느냐로 값이 달라진다."""
    from lemouton.registration.options import build_coupang_items
    쪽문 = _items([_opt(override=89000)], sale_price=100000)[0]
    대량, _ = build_coupang_items(
        [{"sku": "SKU-1", "color": "블랙", "size": "250", "stock": 5,
          "price": 89000}],
        sale_price=89000, image_url="")
    assert (쪽문["originalPrice"] == 쪽문["salePrice"])
    assert (대량[0]["originalPrice"] == 대량[0]["salePrice"])


def test_옵션을_안_판다고_해두면_안_나간다():
    """맞던 것까지 바꾸지 않는다 — 이 갈래는 그대로여야 한다."""
    o = _opt()
    o.market_visible_coupang = False
    assert _items([o]) == []
