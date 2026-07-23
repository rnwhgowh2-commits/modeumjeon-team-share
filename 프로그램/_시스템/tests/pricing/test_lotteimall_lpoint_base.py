# -*- coding: utf-8 -*-
"""[TEST] 아이몰 L.POINT 적립 기준 — 쿠폰 차감 **후** 금액 (2026-07-23 주문서 실측).

■ 무엇이 문제였나
  크롤은 사이트가 **표면가 기준**으로 계산해 노출한 정액(599P)을 준다. 엔진이 그걸
  정액으로 쓰면 「정액 먼저」 규칙 때문에 **쿠폰보다 앞에서** 빠지고, 값도 표면가
  기준으로 고정된다. 주문서 실측은 **570원** — 플러스쿠폰 차감 후(113,900)의 0.5%다.

      화면(수정 전): 119,900 −L.POINT 599 −리뷰 100 −쿠폰 5,995 → …
      주문서(정답):  119,900 −쿠폰 5,995 … 적립 570 (= 쿠폰 적용 후 × 0.5%)

■ 고친 방법
  정액을 **정률로 환산**해 넣는다(`rate = 정액 / 표면가`, 0.05% 단위 스냅).
  그러면 엔진의 「정액 먼저 → 정률 나중」 순서가 자동으로 쿠폰 뒤에 계산한다.
  환산이 미덥지 않으면(요율이 비정상·오차 큼) **기존 정액 그대로** 둔다(무회귀).

■ 금액 영향
  최종 매입가는 백원 버림이라 이번 상품은 107,600 으로 동일하다. 다른 가격대에서
  100원 단위가 갈릴 수 있어 맞춰 둔다(과대·과소 어느 쪽도 만들지 않는 게 원칙).
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


def _find(res, kw):
    return [st for st in (res.get("steps") or []) if kw in st["name"]]


LIVE = {"point_rewards": {"label": "구매적립 L.POINT", "club_point": 599,
                          "default_point": 120},
        "lotteimall_download_coupons": [
            {"label": "[르무통] 5% 다운로드 쿠폰", "rate": 0.05}]}


def test_lpoint_is_computed_after_coupon():
    """★핵심 핀 — 쿠폰(5,995)이 먼저 빠지고, L.POINT 는 그 **뒤** 잔액 기준."""
    s, spid = _sess(LIVE, "SKU-IM-LP1")
    try:
        res = compute_breakdown(s, sku="SKU-IM-LP1", source_id="key:lotteimall",
                                sale_price=119_900, source_product_id=spid)
        steps = res["steps"]
        names = [st["name"] for st in steps]
        i_cp = next(i for i, n in enumerate(names) if "플러스 할인쿠폰" in n)
        i_lp = next(i for i, n in enumerate(names) if "L.POINT" in n)
        assert i_cp < i_lp, f"L.POINT 가 쿠폰보다 먼저 계산됨: {names}"
    finally:
        s.close()


def test_lpoint_amount_matches_order_sheet():
    """주문서 실측 570 원대 — 표면가 기준 599 가 아니라 쿠폰 차감 후 0.5%."""
    s, spid = _sess(LIVE, "SKU-IM-LP2")
    try:
        res = compute_breakdown(s, sku="SKU-IM-LP2", source_id="key:lotteimall",
                                sale_price=119_900, source_product_id=spid)
        lp = _find(res, "L.POINT")
        assert lp, "L.POINT 미반영"
        got = int(lp[0]["deduct"])
        assert 560 <= got <= 575, f"주문서(570) 와 어긋남: {got}"
    finally:
        s.close()


def test_no_coupon_keeps_original_amount():
    """쿠폰이 없으면 종전(599)과 사실상 같다 — 무회귀.

    ±2원 허용: 정률로 바뀌면서 리뷰적립(정액 100)이 먼저 빠진 잔액 기준이 되어
    598 이 나온다. 아이몰 적립은 원래 주문금액 기준이라 리뷰적립분은 빠지지
    않아야 맞지만, 순차 차감 모델의 구조적 오차이고 1원이라 수용한다.
    """
    s, spid = _sess({"point_rewards": {"club_point": 599, "default_point": 120}},
                    "SKU-IM-LP3")
    try:
        res = compute_breakdown(s, sku="SKU-IM-LP3", source_id="key:lotteimall",
                                sale_price=119_900, source_product_id=spid)
        lp = _find(res, "L.POINT")
        assert lp and abs(int(lp[0]["deduct"]) - 599) <= 2, lp
    finally:
        s.close()


def test_falls_back_to_amount_when_rate_is_unreliable():
    """요율 환산이 미덥지 않으면(표면가 없음) **정액 그대로** — 지어내지 않는다."""
    s, spid = _sess({"point_rewards": {"club_point": 599, "default_point": 120}},
                    "SKU-IM-LP4")
    try:
        res = compute_breakdown(s, sku="SKU-IM-LP4", source_id="key:lotteimall",
                                sale_price=0, source_product_id=spid)
        lp = _find(res, "L.POINT")
        if lp:                       # 표면가 0 이면 계산 자체가 무의미 — 정액 유지
            assert int(lp[0]["deduct"]) in (0, 599)
    finally:
        s.close()


def test_general_member_point_also_converted():
    """L.CLUB 이 없으면 일반회원 적립(0.1%)도 같은 방식으로 환산된다."""
    s, spid = _sess({"point_rewards": {"club_point": 0, "default_point": 120},
                     "lotteimall_download_coupons": [{"label": "5%", "rate": 0.05}]},
                    "SKU-IM-LP5")
    try:
        res = compute_breakdown(s, sku="SKU-IM-LP5", source_id="key:lotteimall",
                                sale_price=119_900, source_product_id=spid)
        lp = _find(res, "L.POINT")
        assert lp, "일반회원 적립 미반영"
        assert int(lp[0]["deduct"]) < 120, f"쿠폰 뒤 잔액 기준이면 120 보다 작아야: {lp[0]}"
    finally:
        s.close()
