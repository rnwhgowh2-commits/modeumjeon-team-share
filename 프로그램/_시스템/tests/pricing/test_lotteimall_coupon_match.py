# -*- coding: utf-8 -*-
"""[TEST] 2차 T7 — 롯데아이몰 네이버 플러스쿠폰 파싱·카테고리 매칭 (스펙 §11-5).

■ 사장님 확정(2026-07-23): "확실한 매핑만 차감 + 실구매 피드백"
  쿠폰함(`/mypage/searchCouponList.lotte?coupon_type=P`)은 보유 쿠폰을 **전량** 주지만,
  "이 상품에 어느 쿠폰이 붙는지"는 주문서에서만 100% 확정된다. 따라서 상품 카테고리와
  쿠폰명 접미사가 **확실히** 대응할 때만 차감하고, 애매하면 **안 깎는다**
  (매입가 과대 = 안전 방향).

■ 실측 쿠폰명(스펙 §11-5)
  「■ 네이버 7%플러스할인쿠폰_잡화」 · 「네이버 3%플러스할인쿠폰_잡화」
  「26년7월_10%플러스할인쿠폰_백화점5」 · 「26년7월_15%플러스할인쿠폰_남성캐주얼」
"""
from lemouton.sourcing.lotteimall_coupons import parse_coupon_name, pick_naver_coupon


def test_parse_naver_coupon():
    got = parse_coupon_name("■ 네이버 7%플러스할인쿠폰_잡화")
    assert got["is_naver"] is True and got["rate"] == 7.0 and got["category"] == "잡화"


def test_parse_general_coupon_strips_trailing_number():
    """'백화점5' → '백화점' (뒤 일련번호 제거). 네이버 쿠폰이 아님도 구분."""
    got = parse_coupon_name("26년7월_10%플러스할인쿠폰_백화점5")
    assert got["is_naver"] is False and got["rate"] == 10.0 and got["category"] == "백화점"


def test_parse_unknown_returns_none():
    assert parse_coupon_name("무료배송 쿠폰") is None
    assert parse_coupon_name("") is None


def test_pick_matches_only_confident_category():
    """상품 카테고리가 쿠폰 접미사와 확실히 맞을 때만 채택."""
    coupons = [{"name": "■ 네이버 7%플러스할인쿠폰_잡화"},
               {"name": "■ 네이버 9%플러스할인쿠폰_의류"}]
    got = pick_naver_coupon(coupons, "패션잡화 > 여성신발 > 스니커즈")
    assert got is not None and got["rate"] == 7.0      # 신발 → 잡화


def test_pick_returns_none_when_no_match():
    """매칭 없음 → None(안 깎음). 카테고리 불명도 None."""
    coupons = [{"name": "■ 네이버 7%플러스할인쿠폰_잡화"}]
    assert pick_naver_coupon(coupons, "식품 > 건강식품") is None
    assert pick_naver_coupon(coupons, "") is None
    assert pick_naver_coupon([], "패션잡화 > 여성신발") is None


def test_pick_takes_max_rate_among_matches():
    """같은 카테고리 쿠폰이 여러 장이면 요율이 큰 쪽."""
    coupons = [{"name": "■ 네이버 3%플러스할인쿠폰_잡화"},
               {"name": "■ 네이버 7%플러스할인쿠폰_잡화"}]
    got = pick_naver_coupon(coupons, "패션잡화 > 여성신발")
    assert got["rate"] == 7.0


def test_pick_ignores_non_naver_coupons():
    """일반 플러스쿠폰(네이버 아님)은 경유 혜택이 아니므로 제외."""
    coupons = [{"name": "26년7월_15%플러스할인쿠폰_잡화"}]
    assert pick_naver_coupon(coupons, "패션잡화 > 여성신발") is None


def test_pick_ignores_unknown_category_suffix():
    """접미사가 매핑표에 없으면(모르는 카테고리) 안 깎는다."""
    coupons = [{"name": "■ 네이버 9%플러스할인쿠폰_리빙"}]
    assert pick_naver_coupon(coupons, "리빙 > 주방") is None
