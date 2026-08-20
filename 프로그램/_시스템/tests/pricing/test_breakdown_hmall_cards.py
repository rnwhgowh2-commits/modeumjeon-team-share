# -*- coding: utf-8 -*-
"""[TEST] 2차 T3 — Hmall 카드 즉시할인 경로 (스펙 §3-7 · 사장님 확정 2026-07-23).

■ 무엇을 잠그나
  1) 크롤이 실어 준 `hmall_card_discounts`(창 없이 item-prmo-lst API 수집) 중
     **보유 카드만** 결제 경로(pay_method) 후보가 된다 — 없는 카드로 매입가가
     싸 보이는 것을 차단(보유카드 가드, 롯데온 §3-5와 동일 원칙).
  2) 카드 즉시할인 vs 현대카드 2.73% 플로어는 **경로 열거로 큰 쪽이 이긴다**
     (택1 — 둘 다 차감되면 이중차감).
  3) `min_order`(최소 결제금액) 미달 카드는 후보에서 제외 — 조건 미충족인데
     깎으면 매입가 과소(마진 착시)가 된다.
  4) 카드 목록이 없거나 수집 실패(None)면 **기존 동작 그대로**
     (현대카드 2.73% + N페이 1%) — 폴백 금지·무회귀.

  ※ Hmall 표면가(bbprc)는 카드 미포함(실측)이라 롯데온과 달리 **가산 로직이 없다**.
    카드 행을 결제 경로로 주입만 하면 된다.

  라이브 미접속 — 인메모리 SQLite 픽스처(test_catalog_source_benefits.py 규약 재사용).
"""
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.sources.models import SourceProduct, SourceOption, OptionSourceLink
from lemouton.margin.purchase_card_store import seed_purchase_cards
from webapp.routes.api_benefits import compute_breakdown

SKU = "SKU-HMALL-CARD"
SURFACE = 100_000


def _make_session(dynamic_benefits):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    seed_purchase_cards(s)          # 카드 마스터 17종 — 보유 가드의 기준
    sp = SourceProduct(
        site="hmall", url="https://www.hmall.com/md/pda/itemPtc?slitmCd=1",
        product_name="테스트", dynamic_benefits_json=json.dumps(dynamic_benefits, ensure_ascii=False))
    s.add(sp)
    s.flush()
    so = SourceOption(source_product_id=sp.id, color_text="블랙", size_text="270")
    s.add(so)
    s.flush()
    s.add(OptionSourceLink(canonical_sku=SKU, source_option_id=so.id))
    s.commit()
    return s


def _on_names(res):
    """steps = 실제 채택된 경로의 차감 항목만 담긴다(롯데온 테스트 규약과 동일)."""
    return [st["name"] for st in (res.get("steps") or [])]


def test_owned_card_5pct_beats_hyundai_273():
    """국민카드 5% > 현대카드 2.73% → 국민 경로 채택, 현대 fallback 은 비활성(택1).

    '국민카드' 는 PurchaseCard 마스터에 실재(완전일치) — 보유 가드 통과 케이스.
    """
    s = _make_session({"hmall_card_discounts": [
        {"label": "국민카드", "rate": 5, "amount": 0, "min_order": 50_000}]})
    try:
        res = compute_breakdown(s, sku=SKU, source_id="key:hmall", sale_price=SURFACE)
        on = _on_names(res)
        assert any("국민카드" in n for n in on), f"카드 경로 미주입: {on}"
        assert not any("fallback" in n for n in on), f"택1 위반(이중차감): {on}"
    finally:
        s.close()


def test_unowned_card_ignored_keeps_hyundai():
    """카드 마스터에 없는 카드는 후보 제외 → 현대카드 2.73% 유지.

    '삼성카드'(사이트) ↔ '삼성셀렉트'(마스터) 는 부분일치가 아니라 **미보유**가 정답
    (match_owned_card_label 규칙 ② — 애매하면 안 가진 걸로). 실측 사례 그대로다:
    2026-07-23 Hmall 카드 = 삼성·현대 5% 인데 사장님 보유는 넥슨현대카드·삼성셀렉트라
    현대만 인정된다.
    """
    s = _make_session({"hmall_card_discounts": [
        {"label": "삼성카드", "rate": 9, "amount": 0, "min_order": 0}]})
    try:
        res = compute_breakdown(s, sku=SKU, source_id="key:hmall", sale_price=SURFACE)
        on = _on_names(res)
        assert not any("삼성카드" in n for n in on), f"미보유 카드가 채택됨: {on}"
        assert any("현대카드" in n for n in on), f"플로어 소실: {on}"
    finally:
        s.close()


def test_small_card_loses_to_hyundai():
    """카드 2% < 현대 2.73% → 경로 열거로 현대 승."""
    s = _make_session({"hmall_card_discounts": [
        {"label": "국민카드", "rate": 2, "amount": 0, "min_order": 0}]})
    try:
        res = compute_breakdown(s, sku=SKU, source_id="key:hmall", sale_price=SURFACE)
        on = _on_names(res)
        assert any("현대카드" in n for n in on), f"큰 쪽 선택 실패: {on}"
    finally:
        s.close()


def test_min_order_not_met_card_excluded():
    """최소 결제금액 20만원 조건인데 표면가 10만원 → 그 카드는 후보 제외."""
    s = _make_session({"hmall_card_discounts": [
        {"label": "국민카드", "rate": 5, "amount": 0, "min_order": 200_000}]})
    try:
        res = compute_breakdown(s, sku=SKU, source_id="key:hmall", sale_price=SURFACE)
        on = _on_names(res)
        assert not any("국민카드" in n for n in on), f"조건 미충족 카드 채택: {on}"
        assert any("현대카드" in n for n in on)
    finally:
        s.close()


def test_no_cards_keeps_existing_behavior():
    """카드 목록 없음 → 기존과 동일(현대 2.73% + N페이 1%) — 무회귀 핀."""
    s = _make_session({})
    try:
        res = compute_breakdown(s, sku=SKU, source_id="key:hmall", sale_price=SURFACE)
        on = _on_names(res)
        assert any("현대카드" in n for n in on), f"{on}"
        assert any("네이버페이" in n for n in on), f"{on}"
        # T11b 핀과 동일 계산: 100,000 −리뷰100 → −OK캐 2,427 → −N페이 974 → −현대 2,634
        assert res["final_price"] == 93_800
    finally:
        s.close()
