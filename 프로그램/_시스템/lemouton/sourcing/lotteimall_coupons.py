# -*- coding: utf-8 -*-
"""롯데아이몰 플러스쿠폰(네이버 경유 발급형) 파싱·매칭 — 2026-07-23 (스펙 §11-5).

■ 왜 필요한가
  아이몰의 N쇼핑 경유 혜택은 **발급형**이다. 경유하면 「네이버 N%플러스할인쿠폰」이
  쿠폰함에 쌓이고, 주문서의 "플러스 할인쿠폰" 칸에서 적용된다(표시가엔 미반영).
  쿠폰함(`GET /mypage/searchCouponList.lotte?order_gubun=regi_dt&coupon_type=P&pageIdx=N`,
  로그인·15페이지)은 **보유 쿠폰을 전량** 주지만, "이 상품에 어느 쿠폰이 붙는지"는
  주문서에서만 100% 확정된다.

■ 원칙 (사장님 확정 2026-07-23: "확실한 매핑만 차감 + 실구매 피드백")
  상품 카테고리와 쿠폰명 접미사가 **확실히** 대응할 때만 채택하고, 애매하면 None =
  안 깎는다. 매입가 과대(마진 과소) 방향이 안전하기 때문이다. 정밀도는 실구매 주문서
  피드백으로 보정한다.

■ 쿠폰함 공식 규칙(화면 문구 실측)
  "상품별로 할인쿠폰/카드할인/TV쇼핑할인 중 1개만 선택 가능"
  "플러스/즉시적립할인은 1개만 적용 가능"
  → 플러스쿠폰은 **1장만** 적용되므로 매칭 후보 중 최대 요율 1장을 고른다.
"""
import re

# 쿠폰명 예: "■ 네이버 7%플러스할인쿠폰_잡화" / "26년7월_10%플러스할인쿠폰_백화점5"
_NAME_RE = re.compile(
    r'(?P<rate>\d+(?:\.\d+)?)\s*%\s*플러스할인쿠폰(?:_(?P<cat>[가-힣]+\d*))?')

# 쿠폰 접미사 → 상품 카테고리 키워드.
#   ★ 확실한 것만 넣는다. 모르는 접미사는 매핑하지 않아 자동으로 '안 깎음'이 된다.
#   (넓게 잡으면 조건 미충족 차감 = 매입가 과소 = 금전 위험 방향)
CATEGORY_MAP = {
    '잡화': ('잡화', '신발', '슈즈', '스니커즈', '운동화', '가방', '지갑', '벨트'),
    '의류': ('의류', '티셔츠', '셔츠', '아우터', '점퍼', '팬츠', '바지', '원피스', '니트'),
    '남성캐주얼': ('남성캐주얼', '남성의류'),
}


def parse_coupon_name(name):
    """쿠폰명 → {is_naver, rate, category} · 플러스쿠폰이 아니면 None.

    '백화점5' 처럼 뒤에 붙는 일련번호는 떼어 카테고리만 남긴다.
    """
    m = _NAME_RE.search(name or '')
    if not m:
        return None
    try:
        rate = float(m.group('rate'))
    except (TypeError, ValueError):
        return None
    cat = (m.group('cat') or '').strip()
    cat = re.sub(r'\d+$', '', cat)          # '백화점5' → '백화점'
    return {
        'is_naver': '네이버' in (name or ''),
        'rate': rate,
        'category': cat,
    }


def pick_naver_coupon(coupons, product_category):
    """보유 쿠폰 중 상품에 **확실히** 맞는 네이버 플러스쿠폰 1장. 없으면 None(안 깎음).

    Args:
        coupons: [{'name': '쿠폰명', ...}, ...] — 쿠폰함 수집 결과
        product_category: 상품 카테고리 경로 문자열(breadcrumb 등)
    """
    pc = (product_category or '').replace(' ', '')
    if not pc:
        return None                          # 카테고리 불명 = 안 깎음
    best = None
    for c in (coupons or []):
        info = parse_coupon_name((c or {}).get('name') or '')
        if not info or not info['is_naver'] or info['rate'] <= 0:
            continue
        keys = CATEGORY_MAP.get(info['category'])
        if not keys:
            continue                         # 모르는 접미사 = 안 깎음
        if not any(k in pc for k in keys):
            continue                         # 카테고리 불일치 = 안 깎음
        if best is None or info['rate'] > best['rate']:
            best = info
    return best
