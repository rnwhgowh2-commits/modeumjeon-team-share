# -*- coding: utf-8 -*-
"""[2026-08-13] 쿠팡 바코드(GTIN) — 우리 내부 번호를 표준상품코드라고 보내면 안 된다.

■ 쿠팡이 정의한 것 (webapp/data/marketplace_api_map.json · coupang.products.product-creation)

    items.barcode           "바코드 — 상품에 **부착된 유효한 표준상품 코드**"
    items.emptyBarcode      "바코드 없음 — 바코드가 없으면 true"
    items.emptyBarcodeReason "바코드 없음에 대한 사유 — 최대 100자"

  즉 쿠팡은 둘 중 하나를 요구한다: **진짜 표준코드**를 주거나, **없다고 밝히고 사유**를 대거나.
  지금 우리는 `barcode: ""` 만 보낸다 — 코드도 아니고 없다는 선언도 아닌 어중간한 값이다.

■ 🔴 우리 `Option.barcode` 는 표준상품코드가 **아니다**

  `shared/sku_format.gen_barcode()` = `'200' + 무작위 9자리 + 체크섬`.
  EAN-13 에서 **200~299**(그리고 020~029 · 040~049)는 GS1 이 어느 제조사에도 할당하지 않는
  **매장 내부 전용(restricted distribution)** 대역이다. 세계에서 유일하지 않아,
  다른 가게가 같은 번호를 쓸 수 있다. 코드 주석도 「내부용」이라 적혀 있다.

  → 이 번호를 쿠팡에 보내면 **거짓 표준코드를 등록**하는 것이다. 보내지 않는다.

■ 그래서 올바른 값

  · 사장님이 직접 넣은 **진짜 제조사 바코드**(내부 대역 아님 + 체크섬 통과) → 그대로 보낸다
  · 우리가 만든 내부 번호 · 없음 · 형식 불량 → **보내지 않고** 「없음 + 사유」를 밝힌다
"""
from types import SimpleNamespace as NS

import pytest

from lemouton.registration.coupang import (
    CoupangRegistrationInputs, _build_payload,
)
from lemouton.registration.options import coupang_barcode_fields
from shared.sku_format import gen_barcode, is_internal_barcode


# ── 내부 대역 판별 ────────────────────────────────────────────

def test_우리가_만든_바코드는_내부용으로_판별된다():
    """🔴 이 시험이 무너지면 그 뒤 모든 판단이 무너진다."""
    for _ in range(20):
        b = gen_barcode()
        assert b.startswith("200")
        assert is_internal_barcode(b), f'우리 번호인데 내부용으로 안 잡힌다: {b}'


@pytest.mark.parametrize("code", [
    "2001234567893",   # 200번대 — 우리 생성기
    "2991234567897",   # 299번대
    "0201234567899",   # 020번대
    "0401234567893",   # 040번대
])
def test_제한대역_접두는_전부_내부용(code):
    assert is_internal_barcode(code)


@pytest.mark.parametrize("code", [
    "8801234567893",   # 880 = 대한민국 GS1
    "4901234567894",   # 490 = 일본
    "0012345678905",   # 001 = 미국(UPC)
])
def test_진짜_제조사_대역은_내부용이_아니다(code):
    assert not is_internal_barcode(code)


# ── 쿠팡 3칸 만들기 ───────────────────────────────────────────

def test_내부번호는_안_보내고_없다고_밝힌다():
    f = coupang_barcode_fields(gen_barcode())
    assert f.get("barcode") in ("", None), '내부 번호를 표준코드라고 보냈다'
    assert f["emptyBarcode"] is True
    assert f["emptyBarcodeReason"]
    assert len(f["emptyBarcodeReason"]) <= 100, '쿠팡 한도 100자를 넘었다'


def test_바코드가_아예_없어도_없다고_밝힌다():
    """🔴 종전엔 `barcode: ""` 만 보냈다 — 코드도 아니고 없다는 선언도 아니었다."""
    for 빈값 in (None, "", "   "):
        f = coupang_barcode_fields(빈값)
        assert f["emptyBarcode"] is True
        assert f["emptyBarcodeReason"]


def test_진짜_제조사_바코드는_그대로_보낸다():
    f = coupang_barcode_fields("8801234567893")
    assert f["barcode"] == "8801234567893"
    assert "emptyBarcode" not in f, '실제 코드를 보내면서 「없음」이라고도 말했다'


def test_형식이_깨진_값은_지어내지_않고_없다고_한다():
    """체크섬이 안 맞거나 자릿수가 다르면 표준코드가 아니다 — 고쳐서 보내지 않는다."""
    for 이상 in ("8801234567890", "12345", "88012345678AB"):
        f = coupang_barcode_fields(이상)
        assert f["emptyBarcode"] is True, f'형식이 깨진 값을 보냈다: {이상}'


# ── 실제 등록 페이로드까지 ────────────────────────────────────

def _payload(barcode):
    o = NS(market_visible_coupang=True, color_code="블랙", size_code="250",
           option_coupang_price_override=None, canonical_sku="SKU-1",
           barcode=barcode)
    b = NS(model_code="테스트모델", coupang_product_name_override=None,
           model_name_display="테스트 상품", model_name_raw="테스트 상품")
    return _build_payload(bundle=b, options=[o], sale_price=100000,
                          inputs=CoupangRegistrationInputs(display_category_code=1))


def test_등록_페이로드가_내부번호를_안_싣는다():
    내부 = gen_barcode()
    it = _payload(내부)["items"][0]
    assert it.get("barcode") in ("", None)
    assert it["emptyBarcode"] is True
    assert 내부 not in str(it), '어딘가에 내부 번호가 실려 나간다'


def test_등록_페이로드가_진짜_바코드는_싣는다():
    it = _payload("8801234567893")["items"][0]
    assert it["barcode"] == "8801234567893"
    assert "emptyBarcode" not in it


def test_대량등록_경로도_같은_규약이다():
    """두 경로가 갈리면 어느 문으로 등록했느냐로 값이 달라진다(정상가 때와 같은 함정)."""
    from lemouton.registration.options import build_coupang_items
    items, _ = build_coupang_items(
        [{"sku": "SKU-1", "color": "블랙", "size": "250", "stock": 5}],
        sale_price=100000, image_url="")
    assert items[0]["emptyBarcode"] is True, \
        '대량등록은 바코드 자료가 아예 없는데 「없음」을 안 밝힌다'
    assert items[0]["emptyBarcodeReason"]
