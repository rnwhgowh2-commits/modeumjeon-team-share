"""판매처 수집 어댑터 — 가격/재고 필드 매핑 정직성.

확정 결함 재발 방지:
 - 스마트스토어 현재가 = 실판매가(salePrice) + 옵션추가금(add_price). (옛 버그: add_price만 → 전량 0원)
 - 쿠팡 재고 = None(미제공). 가격 없으면 None(0으로 붕괴 금지).
"""
import types

from lemouton.uploader import market_fetch as mf


def test_smartstore_price_is_saleprice_plus_addprice(monkeypatch):
    from shared.platforms.smartstore.get_options import FetchOptionsResult, OptionRow
    fake = FetchOptionsResult(
        success=True, origin_product_no=1, product_name="P", sale_price=123900,
        options=[
            OptionRow(option_id=11, name1="블랙", name2="260", stock=3, add_price=0),
            OptionRow(option_id=22, name1="블랙", name2="270", stock=1, add_price=5000),
        ],
    )
    monkeypatch.setattr(
        "shared.platforms.smartstore.get_options.fetch_product_options",
        lambda pid, client=None: fake)
    monkeypatch.setattr(
        "shared.platforms.smartstore.get_channel_no.resolve_product_ids",
        lambda pid, client=None: {"origin_product_no": pid})

    r = mf.fetch_market_options("smartstore", "555")
    assert r.success
    prices = {o.option_id: o.price for o in r.options}
    # 옛 버그면 둘 다 0. 실판매가 반영이면 123900 / 128900.
    assert prices["11"] == 123900
    assert prices["22"] == 128900


def test_coupang_stock_none_and_missing_price_none(monkeypatch):
    def fake_extract(detail):
        return [
            {"vendor_item_id": 1, "color": "블랙", "size": "260", "sale_price": 133900},
            {"vendor_item_id": 2, "color": "블랙", "size": "270", "sale_price": None},
        ]
    # get_product/extract_vendor_items 는 함수 내부 import 라 원 모듈에 패치
    monkeypatch.setattr(
        "shared.platforms.coupang.products.get_product",
        lambda spid, client=None: {"sellerProductName": "P"})
    monkeypatch.setattr(
        "shared.platforms.coupang.products.extract_vendor_items", fake_extract)

    r = mf.fetch_market_options("coupang", "999")
    assert r.success
    by = {o.option_id: o for o in r.options}
    # 재고는 항상 None(쿠팡 미제공) — 0 하드코딩 금지
    assert by["1"].stock is None and by["2"].stock is None
    # 가격 없으면 None(0으로 붕괴 금지)
    assert by["1"].price == 133900
    assert by["2"].price is None
