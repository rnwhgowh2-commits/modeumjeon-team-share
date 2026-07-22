# -*- coding: utf-8 -*-
"""[TEST] Phase 1B M1-6 — 카탈로그 소싱처('key:xxx' source_id) 혜택 배선.

■ 무엇을 잠그나
  1) `compute_breakdown` 이 `'key:lotteimall'` / `'key:hmall'` 같은 **문자열 합성
     source_id** 에서 site 를 해석한다(`_SITE_BY_SRC` 경로). 이게 안 되면
     `_site_for=None` → 동적혜택 폴백 로더가 통째로 죽어 두 소싱처는 혜택 0건 =
     최종매입가가 표면가와 같아진다(사용자 보고 증상).
  2) 롯데아이몰 카드 청구할인(`lotteimall_card_discount`)이 **정확히 한 번** 차감된다.
     표면가 116,900 − 삼성카드 7% 8,180 = **108,720**(차감 직후 잔액).
     이중차감(100,540)이면 실패한다.

  ※ 헤드라인 `final_price` 는 [2026-07-22 Task 3] 카탈로그 상수(OK캐시백·리뷰) 주입
    이후 106,100 이다 (EXPECTED_FINAL 주석 참조). 아래 108,700 언급은 상수 주입 전
    당시 값 — base_after=108,720 잠금은 지금도 그대로 유효하다. — 프로젝트 기존 규칙
    `_FINAL_FLOOR_UNIT=100` (최종매입가 백원 단위 버림, final_price.py:255,
    2026-07-02 사용자 규칙) 이 마지막에 한 번 걸리기 때문. 차감액 자체는 정확히
    8,180 이고 `steps[-1]['base_after'] == 108720` 로 잠근다. 이 20원 차이는
    M1-6 이 만든 게 아니라 전 소싱처 공통 규칙이라 여기서 바꾸지 않는다.

■ 왜 108,720 이 정답인가
  M1-5 가 `crawled_price` 를 '최대할인가(카드 포함)' → '표면노출가(카드 미적용)' 로
  바꿨다. 그 최대할인가가 바로 108,720 이다. 즉 M1-5+M1-6 을 합치면 매입가는
  M1-5 이전과 같아야 한다(무회귀). 여기서 116,900 이 나오면 카드분 8,180 이
  조용히 증발한 것이고, 100,540 이면 두 번 뺀 것이다.

  라이브 미접속 — 전부 인메모리 SQLite 픽스처.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.sources.models import SourceProduct, SourceOption, OptionSourceLink
from webapp.routes.api_benefits import compute_breakdown

SKU = "SKU-LOTTEIMALL-TEST"
SURFACE_PRICE = 116_900          # 표면노출가 (카드 미적용 할인가)
CARD_DISCOUNT = 8_180            # 삼성카드 7% 청구할인액
EXPECTED_BASE_AFTER = 108_720    # 카드 차감 직후 잔액 = 사이트 '최대할인가'
# [2026-07-22 Task 3] 카탈로그 상수 주입 후 헤드라인:
#   108,720 − 리뷰 100 = 108,620 − OK캐시백 int(108,620×0.9×0.025)=2,443 → 106,177
#   → 백원 버림 106,100. (종전 108,700 = 상수 주입 전 값)
EXPECTED_FINAL = 106_100
DOUBLE_DEDUCTED = 100_540        # 이중차감 시 나오는 값 (절대 나오면 안 됨)


def _make_session(*, site, dynamic_benefits, sku=SKU):
    """site 소싱처 상품 1건 + 옵션 1건 + 옵션 매핑 1건을 심은 인메모리 세션."""
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    sp = SourceProduct(
        site=site,
        url=f"https://www.{site}.com/p/1",
        product_name="테스트 상품",
        dynamic_benefits_json=json.dumps(dynamic_benefits, ensure_ascii=False),
    )
    s.add(sp)
    s.flush()
    so = SourceOption(source_product_id=sp.id, color_text="블랙", size_text="270")
    s.add(so)
    s.flush()
    s.add(OptionSourceLink(canonical_sku=sku, source_option_id=so.id))
    s.commit()
    return s, sp


# ─────────────────────────────────────────────────────────────
# 1) 'key:' 규약 해석 — 이게 깨지면 아래 전부 무의미
# ─────────────────────────────────────────────────────────────
def test_key_prefixed_source_id_resolves_site_and_loads_dynamic_benefits():
    """'key:lotteimall' → site='lotteimall' 로 해석돼 동적혜택이 실제로 실린다."""
    s, _ = _make_session(site="lotteimall", dynamic_benefits={
        "lotteimall_card_discount": CARD_DISCOUNT,
        "lotteimall_card_label": "삼성카드 7%",
    })
    try:
        res = compute_breakdown(s, sku=SKU, source_id="key:lotteimall",
                                sale_price=SURFACE_PRICE)
        names = [it["name"] for it in res["items_used"]]
        assert any("삼성카드 7%" in n for n in names), (
            f"카드 청구할인이 혜택 목록에 없음 — 'key:' 해석 실패 의심. items={names}")
    finally:
        s.close()


def test_key_prefixed_hmall_resolves_site():
    """H몰도 같은 규약 — H.Point 적립(기존 코드)이 살아난다."""
    s, _ = _make_session(site="hmall", dynamic_benefits={"hmall_point_amount": 1_200},
                         sku="SKU-HMALL-TEST")
    try:
        res = compute_breakdown(s, sku="SKU-HMALL-TEST", source_id="key:hmall",
                                sale_price=100_000)
        names = [it["name"] for it in res["items_used"]]
        assert any("H.Point" in n for n in names), f"items={names}"
        # [2026-07-22 Task 3] 카탈로그 상수(OK캐 2.7%×0.9·리뷰100·N페이1%) 주입 후:
        #   100,000 − 1,200(H.Point) − 100(리뷰) = 98,700
        #   − int(98,700×0.9×0.027)=2,398 → 96,302 − int(96,302×0.01)=963 → 95,339
        #   → 백원 버림 95,300. (종전 98,800 = 상수 주입 전 값)
        assert res["final_price"] == 95_300
    finally:
        s.close()


def test_unknown_key_source_stays_none_and_does_not_crash():
    """등록 안 된 key 는 매칭 상품이 없으니 혜택 0건 — 조용한 폴백·예외 없이 표면가 그대로."""
    s, _ = _make_session(site="lotteimall", dynamic_benefits={
        "lotteimall_card_discount": CARD_DISCOUNT})
    try:
        res = compute_breakdown(s, sku=SKU, source_id="key:nonexistent",
                                sale_price=SURFACE_PRICE)
        assert res["final_price"] == SURFACE_PRICE
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# 2) ★ 이중차감 방지 — 이 파일의 핵심
# ─────────────────────────────────────────────────────────────
def test_lotteimall_card_discount_deducted_exactly_once():
    """116,900 − 8,180 = 108,720. 100,540(이중차감)·116,900(미차감) 둘 다 실패."""
    s, _ = _make_session(site="lotteimall", dynamic_benefits={
        "lotteimall_card_discount": CARD_DISCOUNT,
        "lotteimall_card_label": "삼성카드 7%",
    })
    try:
        res = compute_breakdown(s, sku=SKU, source_id="key:lotteimall",
                                sale_price=SURFACE_PRICE)
        # 차감 스텝이 정확히 1건, 금액이 정확히 8,180 — '한 번만' 의 직접 증거
        _card_steps = [st for st in res["steps"] if "청구할인" in st["name"]]
        assert len(_card_steps) == 1, f"카드할인 차감 스텝 {len(_card_steps)}건: {res['steps']}"
        assert _card_steps[0]["deduct"] == CARD_DISCOUNT
        assert _card_steps[0]["base_after"] == EXPECTED_BASE_AFTER  # 116,900 − 8,180

        assert res["final_price"] != DOUBLE_DEDUCTED, (
            "이중차감 — 카드할인이 두 번 빠졌다")
        assert res["final_price"] != SURFACE_PRICE, (
            "미차감 — 카드할인이 매입가에 반영되지 않았다(M1-5 중간상태 그대로)")
        assert res["final_price"] == EXPECTED_FINAL
    finally:
        s.close()


def test_lotteimall_card_and_lpoint_both_deducted():
    """카드 청구할인 + L.POINT 구매적립이 각각 한 번씩 차감된다."""
    s, _ = _make_session(site="lotteimall", dynamic_benefits={
        "lotteimall_card_discount": CARD_DISCOUNT,
        "lotteimall_card_label": "삼성카드 7%",
        "point_rewards": {"label": "구매적립 L.POINT", "default_point": 126,
                          "club_point": 633},
    })
    try:
        res = compute_breakdown(s, sku=SKU, source_id="key:lotteimall",
                                sale_price=SURFACE_PRICE)
        # 카드·L.POINT 가 각각 정확히 1스텝씩 (이 테스트의 원래 목적)
        assert len([st for st in res["steps"] if "청구할인" in st["name"]]) == 1
        assert len([st for st in res["steps"] if "L.POINT" in st["name"]]) == 1
        # [2026-07-22 Task 3] 카탈로그 상수(OK캐 2.5%×0.9·리뷰100) 주입 후 4스텝:
        #   116,900 − 633(L.CLUB) − 8,180(카드) − 100(리뷰) = 107,987
        #   − int(107,987×0.9×0.025)=2,429 → 105,558 → 백원 버림 105,500
        assert res["steps"][-1]["base_after"] == SURFACE_PRICE - 633 - CARD_DISCOUNT - 100 - 2_429
        assert res["final_price"] == 105_500
        assert len(res["steps"]) == 4, res["steps"]
    finally:
        s.close()


def test_no_card_discount_key_means_no_deduction_not_estimate():
    """폴백 금지 — 카드할인 키가 없으면 추정하지 않고 미차감(표면가 그대로)."""
    s, _ = _make_session(site="lotteimall", dynamic_benefits={
        "point_rewards": {"label": "구매적립 L.POINT", "default_point": 126,
                          "club_point": 0},
    })
    try:
        res = compute_breakdown(s, sku=SKU, source_id="key:lotteimall",
                                sale_price=SURFACE_PRICE)
        # [2026-07-22 Task 3] 카탈로그 상수 주입 후:
        #   116,900 − 126(L.POINT) − 100(리뷰) = 116,674
        #   − int(116,674×0.9×0.025)=2,625 → 114,049 → 백원 버림 114,000
        assert res["steps"][-1]["base_after"] == SURFACE_PRICE - 126 - 100 - 2_625
        assert res["final_price"] == 114_000
        names = [it["name"] for it in res["items_used"]]
        assert not any("청구할인" in n for n in names), f"없는 카드할인을 지어냈다: {names}"
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# 3) 회귀 가드 — 기존 정수 source_id 경로 무변경
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sid,site", [(3, "musinsa"), (5, "lotteon"), (6, "ssg")])
def test_integer_source_id_path_unchanged(sid, site):
    """정수 source_id 는 종전대로 _SITE_BY_SRC 로 해석된다."""
    s, _ = _make_session(site=site, dynamic_benefits={}, sku=f"SKU-{site}")
    try:
        res = compute_breakdown(s, sku=f"SKU-{site}", source_id=sid,
                                sale_price=100_000)
        assert isinstance(res.get("final_price"), (int, float))
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# 4) [Task 3] 카탈로그 소싱처 엔진 상수 주입 — 사장님 확정 2026-07-22 (스펙 §3-7/§3-8/§5/§6)
#    hmall/lotteimall 은 source_id 가 문자열('key:...')이라 SourceBenefitTemplate
#    (Integer 컬럼)에 행을 못 만든다 → compute_breakdown 이 상수로 주입한다.
#    ★ 경로 문서화: 주입 항목엔 pay_method/channel 이 없어 _is_tagged 는 False —
#      카탈로그 소싱처는 **legacy 경로** 그대로다. OK캐시백은 apply_mode='cashback'
#      이라 _compute_legacy 의 결제 택1 후보에서 제외돼(final_price.py:241~242)
#      다른 혜택과 **동시 차감**된다 = 스펙 §4-1 방향과 일치.
# ─────────────────────────────────────────────────────────────
def test_hmall_cashback_review_npay_injected():
    """hmall: OK캐시백 2.7%×0.9 + 리뷰 100원 + N페이 1% 주입 (사장님 확정 2026-07-22)."""
    s, _ = _make_session(site="hmall", dynamic_benefits={}, sku="SKU-HMALL-CONST")
    try:
        res = compute_breakdown(s, sku="SKU-HMALL-CONST", source_id="key:hmall",
                                sale_price=100_000)
        steps = {st["name"]: st for st in res["steps"]}
        assert "OK캐시백 2.7%" in steps, f"steps={list(steps)}"
        assert steps["OK캐시백 2.7%"]["base_ratio"] == 0.9  # 계수는 기준금액에만
        assert steps["OK캐시백 2.7%"]["value"] == 0.027     # 적립율 원본 유지 (0.0243 금지)
        assert "리뷰적립(텍스트)" in steps
        assert steps["리뷰적립(텍스트)"]["deduct"] == 100
        assert "네이버페이 적립 1%" in steps
        # 정액(리뷰 100) → 정률(OK캐 → N페이) 순 누적:
        #   100,000 − 100 = 99,900
        #   − int(99,900×0.9×0.027)=2,427 → 97,473
        #   − int(97,473×0.01)=974 → 96,499 → 백원 버림 96,400
        assert res["final_price"] == 96_400
    finally:
        s.close()


def test_lotteimall_cashback_review_injected():
    """lotteimall: OK캐시백 2.5%×0.9 + 리뷰 100원, 네이버페이 없음 (사장님 제외 확정)."""
    s, _ = _make_session(site="lotteimall", dynamic_benefits={}, sku="SKU-LIM-CONST")
    try:
        res = compute_breakdown(s, sku="SKU-LIM-CONST", source_id="key:lotteimall",
                                sale_price=100_000)
        steps = {st["name"]: st for st in res["steps"]}
        assert "OK캐시백 2.5%" in steps, f"steps={list(steps)}"
        assert steps["OK캐시백 2.5%"]["base_ratio"] == 0.9
        assert "리뷰적립(텍스트)" in steps
        names = [it["name"] for it in res["items_used"]]
        assert not any("네이버" in n for n in names), (
            f"롯데아이몰에 네이버페이는 사장님 제외 확정인데 주입됨: {names}")
        # 100,000 − 100 = 99,900 − int(99,900×0.9×0.025)=2,247 → 97,653 → 97,600
        assert res["final_price"] == 97_600
    finally:
        s.close()


@pytest.mark.parametrize("site,src", [("hmall", "key:hmall"),
                                      ("lotteimall", "key:lotteimall")])
def test_catalog_constants_injected_exactly_once(site, src):
    """★ 이중차감 tripwire — OK캐시백·리뷰적립이 steps 에 **정확히 1번**씩만 나온다.

    카탈로그 소싱처가 언젠가 DB 템플릿 지원(supports_benefit_templates=True)을 얻으면
    엔진 상수 주입은 자동 중단돼야 한다(api_benefits.py 가드). DB행+상수가 동시에
    들어오는 날 이 테스트가 크게 깨진다 — 조용한 이중차감(매입가 과소=금전손실) 방지.
    """
    s, _ = _make_session(site=site, dynamic_benefits={}, sku=f"SKU-TRIP-{site}")
    try:
        res = compute_breakdown(s, sku=f"SKU-TRIP-{site}", source_id=src,
                                sale_price=100_000)
        cashback_steps = [st["name"] for st in res["steps"] if "OK캐시백" in st["name"]]
        review_steps = [st["name"] for st in res["steps"] if "리뷰적립" in st["name"]]
        assert len(cashback_steps) == 1, (
            f"OK캐시백 스텝 {len(cashback_steps)}건 — 0=주입 누락 / 2+=이중차감: {res['steps']}")
        assert len(review_steps) == 1, (
            f"리뷰적립 스텝 {len(review_steps)}건 — 0=주입 누락 / 2+=이중차감: {res['steps']}")
    finally:
        s.close()


def test_catalog_cashback_deduct_amount_exact():
    """hmall 표면가 100,000 → OK캐시백 차감 = int(잔액 × 0.9 × 0.027) — 계수는 기준금액에만.

    리뷰 100원(정액)이 먼저 빠진 잔액 99,900 이 캐시백 기준금액이다(legacy 누적 차감).
    """
    s, _ = _make_session(site="hmall", dynamic_benefits={}, sku="SKU-HMALL-EXACT")
    try:
        res = compute_breakdown(s, sku="SKU-HMALL-EXACT", source_id="key:hmall",
                                sale_price=100_000)
        cb = next(st for st in res["steps"] if st["name"] == "OK캐시백 2.7%")
        assert cb["deduct"] == int((100_000 - 100) * 0.9 * 0.027)  # = 2,427
        assert cb["deduct"] == 2_427
        assert cb.get("base_note") == "공급가 기준"  # 영수증 투명성
    finally:
        s.close()


def test_hmall_card_discount_still_off_by_default():
    """H몰 카드 즉시할인은 종전대로 기본 비활성(조건부) — 롯데아이몰과 근거가 다르다.

    H몰 표면가(bbprc)에는 카드할인이 애초에 들어간 적이 없다. 여기를 켜면 진짜
    매입가 인하 회귀가 난다 → M1-6 은 H몰 기본값을 바꾸지 않는다.
    """
    s, _ = _make_session(site="hmall", dynamic_benefits={
        "hmall_card_discount": 5_000, "hmall_card_label": "현대카드",
    }, sku="SKU-HMALL-CARD")
    try:
        res = compute_breakdown(s, sku="SKU-HMALL-CARD", source_id="key:hmall",
                                sale_price=100_000)
        # 카드 즉시할인 5,000 은 여전히 비활성 → 차감 스텝 없음 (이 테스트의 원래 목적)
        assert not any("즉시할인" in st["name"] for st in res["steps"])
        # [2026-07-22 Task 3] 카탈로그 상수만 차감:
        #   100,000 − 100(리뷰) − int(99,900×0.9×0.027)=2,427 → 97,473
        #   − int(97,473×0.01)=974 → 96,499 → 백원 버림 96,400
        assert res["final_price"] == 96_400
        _card = next((it for it in res["items_used"] if "즉시할인" in it["name"]), None)
        assert _card is not None, "항목 자체는 노출돼야 한다(사용자 토글 대상)"
        assert not _card["enabled"]
    finally:
        s.close()
