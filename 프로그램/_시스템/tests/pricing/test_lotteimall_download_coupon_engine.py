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

# ── [2026-07-23 사장님 지시] "수집은 전부, 반영은 플러스면 한 개만" ──────
def test_collect_all_but_apply_only_one_plus_coupon():
    """쿠폰을 **여러 장 다 수집**해도 플러스 칸에는 **한 장만** 반영된다.

    사장님 지시 원문: 「일반화부터 하지 말고, 우선 정보 수집에는 전부 하고,
    로직에 플러스쿠폰이면 한 개만 반영하도록」.
    근거: 쿠폰함 「카드할인을 제외한 모든 쿠폰은 상품(옵션)별로 적용됩니다」 +
          사장님 확정 「플러스쿠폰을 여러 개 쓰는 건 안 된다」.
    """
    s, spid = _sess({"lotteimall_download_coupons": [
                        {"label": "[A] 3% 다운로드 쿠폰", "rate": 0.03},
                        {"label": "[B] 5% 다운로드 쿠폰", "rate": 0.05},
                        {"label": "[C] 2천원 쿠폰", "amount": 2_000}]},
                    "SKU-IM-DC6")
    try:
        res = compute_breakdown(s, sku="SKU-IM-DC6", source_id="key:lotteimall",
                                sale_price=100_000, source_product_id=spid)
        hit = _find(res, "플러스 할인쿠폰")
        assert len(hit) == 1, f"플러스 칸에 {len(hit)}개 반영됨: {_names(res)}"
        assert int(hit[0]["deduct"]) == 5_000, hit[0]   # 3장 중 가장 큰 1장
    finally:
        s.close()


def test_only_one_across_download_and_naver_pool():
    """다운로드 쿠폰 여러 장 + 경유 쿠폰까지 **한 풀에서 단 1장**만 반영."""
    s, spid = _sess({"lotteimall_download_coupons": [
                        {"label": "[A] 3%", "rate": 0.03},
                        {"label": "[B] 5%", "rate": 0.05}],
                     "naver_via_rate": 0.07,
                     "naver_via_label": "네이버 7%플러스할인쿠폰"}, "SKU-IM-DC7")
    try:
        res = compute_breakdown(s, sku="SKU-IM-DC7", source_id="key:lotteimall",
                                sale_price=100_000, source_product_id=spid)
        plus = _find(res, "플러스 할인쿠폰")
        via = _find(res, "N쇼핑")
        assert len(plus) + len(via) == 1, f"플러스 칸 중복 반영: {_names(res)}"
        assert via, f"큰 쪽(경유 7%) 미채택: {_names(res)}"
    finally:
        s.close()


def test_all_coupons_are_collected_even_if_only_one_applies():
    """수집 자체는 **전부** 남아 있어야 한다 — 반영 1장과 별개(진단·검산용)."""
    from lemouton.sources.service import PRODUCT_DYNAMIC_KEYS
    assert 'lotteimall_download_coupons' in PRODUCT_DYNAMIC_KEYS
    assert 'lotteimall_preapplied_coupon' in PRODUCT_DYNAMIC_KEYS
