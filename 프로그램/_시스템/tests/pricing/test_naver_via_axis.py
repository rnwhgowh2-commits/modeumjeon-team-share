# -*- coding: utf-8 -*-
"""[TEST] 2차 T4·T5 — N쇼핑 경유(naver_via) 축 배선 (스펙 §11-4, 2026-07-23 실측 확정).

■ 무엇을 잠그나
  1) `_DynBenefit` 이 `channel='naver_via'` 를 실을 수 있고, 엔진이 그걸 **경유 축**으로
     열거한다(final_price.py:154 `_is_tagged` · :320 `has_naver_via` · :341 차감).
  2) **선반영 판별 게이트** — 표시가에 이미 반영된 몰(Hmall 「네이버가격비교」·
     롯데온 「제휴할인」)은 `naver_via_preapplied=True` 로 오고, 그때는 **주입 자체를
     하지 않는다**(재차감 = 이중차감 = 매입가 과소).
  3) 미반영형(SSG 쿠폰·아이몰 플러스쿠폰)은 그대로 차감된다.
  4) 제약② — 경유 경로가 채택되면 같은 경로에서 OK캐시백은 꺼진다(엔진 기존 규칙).
  5) 값 없음/0 이면 아무것도 안 깎는다(폴백 금지).

  실측 근거(스펙 §11-4):
    · Hmall  = 「네이버가격비교」 8% — 경유+로그인 시 혜택가에 **선반영**
    · 롯데온 = 「제휴할인」 정액 — 경유 시 자동 반영(선반영)
    · SSG    = 「네이버 쇼핑 최대 8% 쿠폰」 — 표시가 미반영 → 차감
    · 아이몰 = 「네이버 N%플러스할인쿠폰」 — 발급형·표시가 미반영 → 차감

  라이브 미접속 — 인메모리 SQLite 픽스처.
"""
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.sources.models import SourceProduct, SourceOption, OptionSourceLink
from lemouton.margin.purchase_card_store import seed_purchase_cards
from webapp.routes.api_benefits import compute_breakdown

SURFACE = 100_000


def _sess(site, dyn, sku):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    seed_purchase_cards(s)
    sp = SourceProduct(site=site, url=f"https://www.{site}.com/p/1",
                       product_name="테스트",
                       dynamic_benefits_json=json.dumps(dyn, ensure_ascii=False))
    s.add(sp)
    s.flush()
    so = SourceOption(source_product_id=sp.id, color_text="블랙", size_text="270")
    s.add(so)
    s.flush()
    s.add(OptionSourceLink(canonical_sku=sku, source_option_id=so.id))
    s.commit()
    return s


def _names(res):
    return [st["name"] for st in (res.get("steps") or [])]


def test_ssg_naver_coupon_is_deducted():
    """SSG: 「네이버 쇼핑 8% 쿠폰」은 표시가 미반영 → 경유 경로에서 차감된다."""
    s = _sess("ssg", {"naver_via_rate": 0.08, "naver_via_label": "네이버 쇼핑 쿠폰"},
              "SKU-SSG-VIA")
    try:
        res = compute_breakdown(s, sku="SKU-SSG-VIA", source_id=6, sale_price=SURFACE)
        on = _names(res)
        assert any("N쇼핑" in n or "네이버 쇼핑" in n for n in on), f"경유 미차감: {on}"
    finally:
        s.close()


def test_hmall_preapplied_is_not_deducted():
    """Hmall: 「네이버가격비교」가 혜택가에 선반영된 상태 → 재차감 금지(이중차감 방지)."""
    s = _sess("hmall", {"naver_via_rate": 0.08, "naver_via_preapplied": True,
                        "naver_via_label": "네이버가격비교"}, "SKU-HM-VIA")
    try:
        res = compute_breakdown(s, sku="SKU-HM-VIA", source_id="key:hmall",
                                sale_price=SURFACE)
        on = _names(res)
        assert not any("N쇼핑" in n or "네이버가격비교" in n for n in on), f"이중차감: {on}"
    finally:
        s.close()


def test_lotteon_affiliate_preapplied_is_not_deducted():
    """롯데온: 「제휴할인」 항목 존재 = 경유 선반영 → 재차감 금지."""
    s = _sess("lotteon", {"naver_via_amount": 8000, "naver_via_preapplied": True,
                          "naver_via_label": "제휴할인"}, "SKU-LO-VIA")
    try:
        res = compute_breakdown(s, sku="SKU-LO-VIA", source_id=5, sale_price=SURFACE)
        on = _names(res)
        assert not any("N쇼핑" in n or "제휴할인" in n for n in on), f"이중차감: {on}"
    finally:
        s.close()


def test_lotteimall_plus_coupon_amount_is_deducted():
    """아이몰: 플러스쿠폰은 발급형·표시가 미반영 → 차감(정률)."""
    s = _sess("lotteimall", {"naver_via_rate": 0.07,
                             "naver_via_label": "네이버 7%플러스할인쿠폰"},
              "SKU-IM-VIA")
    try:
        res = compute_breakdown(s, sku="SKU-IM-VIA", source_id="key:lotteimall",
                                sale_price=SURFACE)
        on = _names(res)
        assert any("N쇼핑" in n or "플러스" in n for n in on), f"경유 미차감: {on}"
    finally:
        s.close()


def test_naver_via_turns_cashback_off_in_same_path():
    """제약②: 경유 경로가 채택되면 그 경로에서 OK캐시백은 꺼진다(둘 다 차감 금지)."""
    s = _sess("hmall", {"naver_via_rate": 0.08}, "SKU-HM-VIA2")
    try:
        res = compute_breakdown(s, sku="SKU-HM-VIA2", source_id="key:hmall",
                                sale_price=SURFACE)
        on = _names(res)
        via = any("N쇼핑" in n for n in on)
        cb = any("OK캐시백" in n for n in on)
        assert not (via and cb), f"경유·캐시백 동시 차감(제약② 위반): {on}"
    finally:
        s.close()


def test_no_value_means_no_deduction():
    """값 없음 → 아무것도 안 깎음(폴백 금지·무회귀)."""
    s = _sess("ssg", {}, "SKU-SSG-NONE")
    try:
        res = compute_breakdown(s, sku="SKU-SSG-NONE", source_id=6, sale_price=SURFACE)
        on = _names(res)
        assert not any("N쇼핑" in n for n in on), f"{on}"
    finally:
        s.close()


def test_preapplied_false_is_persisted_and_allows_deduction():
    """경유 아님(False)도 저장돼야 한다 — stale True 가 남아 영영 안 깎이는 것 방지.

    [2026-07-23 · 2차 T6 실측 발견] crawl-result 병합 필터가 `False` 를 버려서,
    경유 상태에서 True 가 한 번 박히면 이후 False 를 보내도 덮이지 않았다.
    플래그 키는 예외로 통과시켜 False 도 저장한다(api_pricing `_BOOL_KEYS`).
    """
    from lemouton.sources.service import PRODUCT_DYNAMIC_KEYS
    assert 'naver_via_preapplied' in PRODUCT_DYNAMIC_KEYS

    # 엔진 쪽: preapplied=False + rate 있으면 **차감된다**
    s = _sess("hmall", {"naver_via_preapplied": False, "naver_via_rate": 0.08,
                        "naver_via_label": "네이버 쇼핑 쿠폰"}, "SKU-HM-VIA3")
    try:
        res = compute_breakdown(s, sku="SKU-HM-VIA3", source_id="key:hmall",
                                sale_price=SURFACE)
        on = _names(res)
        assert any("N쇼핑" in n for n in on), f"False 인데 미차감: {on}"
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# [2026-07-23 사장님 확정] "경유는 N쇼핑 or OK캐시백 中 택1, 할인 큰 쪽. 중복 금지."
#   SSG 제휴할인 쿠폰(ckwhere 경유로 노출되는 「[제휴할인] …」)은 상품쿠폰으로
#   파싱되지만 **경유 축**이므로 channel='naver_via' 를 줘야 캐시백과 배타된다.
# ─────────────────────────────────────────────────────────────
def test_ssg_affiliate_coupon_is_naver_via_axis():
    """「[제휴할인] SSG 5% 쿠폰」 = 경유 축 → OK캐시백과 **동시 차감 금지**."""
    s = _sess("ssg", {"product_coupon_rate": 0.05,
                      "product_coupon_label": "[제휴할인] SSG 5% 쿠폰"}, "SKU-SSG-AFF")
    try:
        res = compute_breakdown(s, sku="SKU-SSG-AFF", source_id=6, sale_price=SURFACE)
        on = _names(res)
        aff = [n for n in on if "제휴" in n]
        cb = [n for n in on if "캐시백" in n]
        assert not (aff and cb), f"경유·캐시백 동시 차감(사장님 확정 위반): {on}"
    finally:
        s.close()


def test_ssg_affiliate_coupon_wins_when_bigger():
    """제휴 5% > OK캐시백 2.0% → 큰 쪽(제휴)이 채택된다."""
    s = _sess("ssg", {"product_coupon_rate": 0.05,
                      "product_coupon_label": "[제휴할인] SSG 5% 쿠폰"}, "SKU-SSG-AFF2")
    try:
        res = compute_breakdown(s, sku="SKU-SSG-AFF2", source_id=6, sale_price=SURFACE)
        on = _names(res)
        assert any("제휴" in n for n in on), f"큰 쪽(제휴 5%) 미채택: {on}"
    finally:
        s.close()


def test_ssg_normal_coupon_keeps_manual_toggle():
    """제휴가 아닌 일반 상품쿠폰은 기존대로 수동 토글(자동 차감 안 함) — 무회귀."""
    s = _sess("ssg", {"product_coupon_rate": 0.12,
                      "product_coupon_label": "명품/잡화 쓱세일 백화점 12% 상품쿠폰"},
              "SKU-SSG-NORM")
    try:
        res = compute_breakdown(s, sku="SKU-SSG-NORM", source_id=6, sale_price=SURFACE)
        on = _names(res)
        assert not any("상품쿠폰" in n for n in on), f"일반 쿠폰이 자동 차감됨: {on}"
    finally:
        s.close()


# ═══════════════════════════════════════════════════════════════════════
# [2026-07-23] 실측 픽스처 → 엔진 끝단까지 (SSG 다운로드 쿠폰 레이어 구현)
#   사장님이 저장해 준 실제 PDP 로 크롤러를 돌려 나온 값을 그대로 엔진에 넣는다.
#   중간에 사람이 손으로 넣은 숫자가 없다 = 배선이 실제로 이어졌다는 증거.
# ═══════════════════════════════════════════════════════════════════════
def _ssg_fixture_fields():
    import io as _io
    import os as _os
    from bs4 import BeautifulSoup as _BS
    from lemouton.sourcing.crawlers.ssg import coupon_fields_from_layer
    p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                      'sourcing', 'fixtures', 'ssg_download_coupon_layer.html')
    return coupon_fields_from_layer(_BS(_io.open(p, encoding='utf-8').read(), 'lxml'))


def test_실측픽스처_제휴쿠폰이_경유축으로_차감된다():
    """71,638원 상품의 「[제휴할인] 백화점 8% 쿠폰」 = 5,731원이 경유 축에서 깎인다."""
    dyn = _ssg_fixture_fields()
    assert dyn.get('product_coupon_rate') == 0.08, dyn
    s = _sess("ssg", dyn, "SKU-SSG-FIX")
    try:
        res = compute_breakdown(s, sku="SKU-SSG-FIX", source_id=6, sale_price=71638)
        steps = res.get("steps") or []
        aff = [st for st in steps if "제휴" in st["name"]]
        assert aff, f"제휴쿠폰 미차감: {[st['name'] for st in steps]}"
        # 71,638 × 8% = 5,731 — 사이트 레이어가 보여 준 금액과 **원 단위까지** 같다
        assert int(aff[0]["deduct"]) == 5731, aff[0]
        assert int(aff[0]["base_after"]) == 65907, aff[0]
        cb = [st for st in steps if "캐시백" in st["name"]]
        assert not cb, f"경유·캐시백 동시 차감(사장님 확정 위반): {[st['name'] for st in steps]}"
    finally:
        s.close()
