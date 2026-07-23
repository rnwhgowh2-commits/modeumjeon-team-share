# -*- coding: utf-8 -*-
"""[TEST] 아이몰 다운로드 쿠폰이 엔진 계산까지 도달하는지 (2026-07-23).

파서 단위 테스트는 `tests/sourcing/test_lotteimall_download_coupon.py`.
여기서는 **매트릭스 계산식이 실제로 그렇게 나오는가**를 잠근다.

라이브 실측(goods_no=2559138690): 표면 119,900 · 선반영 쿠폰 29,100 · 5% 다운로드
→ **추가 차감 0** = 사장님 화면의 113,300 이 맞다.
"""
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.sources.models import SourceProduct, SourceOption, OptionSourceLink
from lemouton.margin.purchase_card_store import seed_purchase_cards
from webapp.routes.api_benefits import compute_breakdown


def _sess(dyn, sku):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    seed_purchase_cards(s)
    sp = SourceProduct(site="lotteimall",
                       url="https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=1",
                       product_name="테스트",
                       dynamic_benefits_json=json.dumps(dyn, ensure_ascii=False))
    s.add(sp)
    s.flush()
    so = SourceOption(source_product_id=sp.id, color_text="블랙", size_text="270")
    s.add(so)
    s.flush()
    s.add(OptionSourceLink(canonical_sku=sku, source_option_id=so.id))
    s.commit()
    return s, sp.id


def _names(res):
    return [st["name"] for st in (res.get("steps") or [])]


def test_live_case_download_coupon_is_not_deducted():
    """★ 선반영 쿠폰(29,100)이 5% 보다 크므로 다운로드 쿠폰은 **안 붙는다**."""
    s, spid = _sess({"lotteimall_download_coupons": [
                        {"label": "[르무통] 5% 다운로드 쿠폰", "rate": 0.05}],
                     "lotteimall_preapplied_coupon": 29100}, "SKU-IM-DC1")
    try:
        res = compute_breakdown(s, sku="SKU-IM-DC1", source_id="key:lotteimall",
                                sale_price=119_900, source_product_id=spid)
        on = _names(res)
        assert not any("다운로드 쿠폰" in n for n in on), f"택1 위반(이중차감): {on}"
    finally:
        s.close()


def test_download_coupon_is_deducted_when_slot_is_empty():
    """할인쿠폰 칸이 비었으면(선반영 0) 다운로드 쿠폰이 실제로 깎인다."""
    s, spid = _sess({"lotteimall_download_coupons": [
                        {"label": "[테스트] 5% 다운로드 쿠폰", "rate": 0.05}],
                     "lotteimall_preapplied_coupon": 0}, "SKU-IM-DC2")
    try:
        res = compute_breakdown(s, sku="SKU-IM-DC2", source_id="key:lotteimall",
                                sale_price=100_000, source_product_id=spid)
        hit = [st for st in res["steps"] if "다운로드 쿠폰" in st["name"]]
        assert hit, f"미차감: {_names(res)}"
        assert int(hit[0]["deduct"]) == 5_000, hit[0]
    finally:
        s.close()


def test_no_coupon_no_regression():
    """쿠폰 키가 없으면 종전 계산 그대로 — 무회귀."""
    s, spid = _sess({}, "SKU-IM-DC3")
    try:
        res = compute_breakdown(s, sku="SKU-IM-DC3", source_id="key:lotteimall",
                                sale_price=100_000, source_product_id=spid)
        assert not any("다운로드 쿠폰" in n for n in _names(res))
    finally:
        s.close()
