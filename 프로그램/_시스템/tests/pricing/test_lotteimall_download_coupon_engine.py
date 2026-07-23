# -*- coding: utf-8 -*-
"""[TEST] 아이몰 다운로드 쿠폰이 엔진 계산까지 도달하는지 (2026-07-23 주문서 실측).

파서 단위 테스트는 `tests/sourcing/test_lotteimall_download_coupon.py`.
여기서는 **매트릭스 계산식이 실제로 그렇게 나오는가**를 잠근다.

🔴 처음엔 「할인쿠폰 칸 택1」로 잘못 판정했다. 사장님 주문서 실측이 정답:
      149,000 −할인쿠폰 29,100(=표면가 119,900) −**플러스 할인쿠폰 6,000** = 113,900
   → 할인쿠폰과 **동시 적용**, 기준은 **표면가**, 대신 경유 네이버 플러스쿠폰과 택1.
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


def _find(res, kw):
    return [st for st in (res.get("steps") or []) if kw in st["name"]]


def test_live_case_plus_coupon_is_deducted():
    """★핵심 핀 — 주문서 실측 상품: 표면 119,900 에서 5% 가 **실제로 깎인다**.

    선반영 쿠폰할인 29,100 이 있어도 플러스 칸은 별개라 차감된다(종전 오판 방지).
    """
    s, spid = _sess({"lotteimall_download_coupons": [
                        {"label": "[르무통] 5% 다운로드 쿠폰", "rate": 0.05}],
                     "lotteimall_preapplied_coupon": 29100}, "SKU-IM-DC1")
    try:
        res = compute_breakdown(s, sku="SKU-IM-DC1", source_id="key:lotteimall",
                                sale_price=119_900, source_product_id=spid)
        hit = _find(res, "플러스 할인쿠폰")
        assert hit, f"미차감: {_names(res)}"
        assert int(hit[0]["deduct"]) == 5_995, hit[0]
    finally:
        s.close()


def test_naver_via_wins_plus_slot():
    """플러스 칸 택1 — 경유 네이버 쿠폰(7%)이 더 크면 **다운로드 쿠폰은 안 붙는다**."""
    s, spid = _sess({"lotteimall_download_coupons": [{"label": "5%", "rate": 0.05}],
                     "naver_via_rate": 0.07,
                     "naver_via_label": "네이버 7%플러스할인쿠폰"}, "SKU-IM-DC2")
    try:
        res = compute_breakdown(s, sku="SKU-IM-DC2", source_id="key:lotteimall",
                                sale_price=100_000, source_product_id=spid)
        on = _names(res)
        assert not any("플러스 할인쿠폰" in n for n in on), f"둘 다 차감(칸 중복): {on}"
    finally:
        s.close()


def test_download_coupon_wins_plus_slot():
    """반대로 다운로드 쿠폰(9%)이 크면 그쪽이 붙고 **경유 쿠폰은 안 붙는다**."""
    s, spid = _sess({"lotteimall_download_coupons": [{"label": "9%", "rate": 0.09}],
                     "naver_via_rate": 0.07,
                     "naver_via_label": "네이버 7%플러스할인쿠폰"}, "SKU-IM-DC3")
    try:
        res = compute_breakdown(s, sku="SKU-IM-DC3", source_id="key:lotteimall",
                                sale_price=100_000, source_product_id=spid)
        on = _names(res)
        assert any("플러스 할인쿠폰" in n for n in on), f"미차감: {on}"
        assert not any("N쇼핑" in n for n in on), f"둘 다 차감(칸 중복): {on}"
    finally:
        s.close()


def test_preapplied_naver_via_is_not_a_rival():
    """경유가 **선반영형**이면 플러스 칸을 안 쓰므로 다운로드 쿠폰이 그대로 붙는다."""
    s, spid = _sess({"lotteimall_download_coupons": [{"label": "5%", "rate": 0.05}],
                     "naver_via_rate": 0.08,
                     "naver_via_preapplied": True}, "SKU-IM-DC4")
    try:
        res = compute_breakdown(s, sku="SKU-IM-DC4", source_id="key:lotteimall",
                                sale_price=100_000, source_product_id=spid)
        assert _find(res, "플러스 할인쿠폰"), f"미차감: {_names(res)}"
    finally:
        s.close()


def test_no_coupon_no_regression():
    """쿠폰 키가 없으면 종전 계산 그대로 — 무회귀."""
    s, spid = _sess({}, "SKU-IM-DC5")
    try:
        res = compute_breakdown(s, sku="SKU-IM-DC5", source_id="key:lotteimall",
                                sale_price=100_000, source_product_id=spid)
        assert not any("플러스 할인쿠폰" in n for n in _names(res))
    finally:
        s.close()
