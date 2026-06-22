"""크롤된 혜택 라인 텍스트 → 회원 혜택 금액 추출 (순수 함수, DB·요청 의존 없음).

배경 (2026-06-22):
  확장이 보낸 benefit_lines(혜택 문구 라인)에서 회원 전용 혜택 '금액'을 뽑아
  SourceProduct.dynamic_benefits_json 키로 채운다. 기존엔 이 추출이 어디에도 배선되지
  않아(가이드 미리보기만) 라이브에서 등급적립·무신사머니가 전부 0/OFF 였다.

원칙 (사용자 데이터 무결성):
  · 폴백 금지 — 라인에서 못 읽으면 0 (옛값/추정 금지).
  · 부재신호('불가'/'없음') 가 같은 항목 라인에 있으면 0 확정.
  · 가드 — surface_price 대비 비정상(>40%)이거나 음수면 채택 안 함(0).
  · 라인은 공백 제거 후 키워드 매칭(확장이 '등급 적립(...)4,340원' 처럼 라벨+금액 한 줄로 보냄).
"""
from __future__ import annotations

import re

_AMT_RE = re.compile(r'([\d,]{2,})\s*원')


def _won(text: str) -> int:
    """라인에서 'N원' 금액(첫 매칭) 정수로. 없으면 0."""
    m = _AMT_RE.search(text or '')
    if not m:
        return 0
    try:
        return int(m.group(1).replace(',', ''))
    except ValueError:
        return 0


def parse_musinsa_benefit_amounts(lines, surface_price=None) -> dict:
    """무신사 혜택 라인 → {grade_reward_amount, money_reward_amount,
    grade_discount_amount, coupon_amount, money_active}.

    매칭 규칙(공백 제거 기준):
      · 등급적립    : '등급적립(' 또는 '구매적립' 포함 + 금액 → grade_reward_amount
      · 무신사머니   : '무신사머니' + '적립' 포함 + 금액 → money_reward_amount, money_active=True
      · 등급할인    : '등급할인' 포함 & '불가' 없음 + 금액 → grade_discount_amount
      · 상품쿠폰    : '상품쿠폰' 포함 & '없음' 없음 + 금액 → coupon_amount
    surface_price 주어지면 각 금액이 0<v<=surface*0.4 가드 통과해야 채택(아니면 0).
    """
    out = {
        'grade_reward_amount': 0,
        'money_reward_amount': 0,
        'grade_discount_amount': 0,
        'coupon_amount': 0,
        'money_active': False,
    }
    cap = None
    try:
        if surface_price and int(surface_price) > 0:
            cap = int(int(surface_price) * 0.4)
    except (TypeError, ValueError):
        cap = None

    def ok(v: int) -> bool:
        if v <= 0:
            return False
        if cap is not None and v > cap:
            return False
        return True

    for raw in (lines or []):
        ln = (raw or '')
        l = ln.replace(' ', '')
        # 등급적립 / 구매적립 (= 등급 기반 적립) — '무신사머니'·'최대적립' 라인은 제외
        if ('등급적립(' in l or l.startswith('등급적립') or '구매적립' in l) \
                and '무신사머니' not in l and '최대적립' not in l:
            v = _won(ln)
            if ok(v):
                out['grade_reward_amount'] = max(out['grade_reward_amount'], v)
        # 무신사머니 결제 적립
        if '무신사머니' in l and '적립' in l:
            v = _won(ln)
            if ok(v):
                out['money_reward_amount'] = max(out['money_reward_amount'], v)
                out['money_active'] = True
        # 등급 할인 (불가 = 0)
        if '등급할인' in l and '불가' not in l and '없음' not in l:
            v = _won(ln)
            if ok(v):
                out['grade_discount_amount'] = max(out['grade_discount_amount'], v)
        # 상품 쿠폰 (없음 = 0)
        if '상품쿠폰' in l and '없음' not in l and '불가' not in l:
            v = _won(ln)
            if ok(v):
                out['coupon_amount'] = max(out['coupon_amount'], v)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# navGrab(SSF·SSG·르무통·스스) — 서버 parse 결과 옵션 dict 에서 동적 혜택 키 추출.
#   배경: 확장이 /api/sources/parse 로 HTML 을 보내면 서버 크롤러(ssf/ssg.py)가 옵션마다
#   동적 혜택 키(point_rate·gift_point·ssg_money_rate 등)를 채운다. 그런데 확장의
#   crawlItemInTabBG 가 그 키를 드롭하고 crawl-result 로는 가격/재고만 저장 → 라이브에서
#   SSF 멤버십포인트·SSG MONEY 등이 비어 있었다. parse 엔드포인트가 이 함수로 키를 뽑아
#   SourceProduct.dynamic_benefits_json 에 직접 저장(서버측, 확장 변경 불필요).
#   키 목록은 service.py PRODUCT_DYNAMIC_KEYS 와 동일(단일 진실 원천).
# ─────────────────────────────────────────────────────────────────────────────
_PRODUCT_DYNAMIC_KEYS = (
    'point_rate', 'point_amount',
    'gift_point_amount',
    'ssg_money_rate', 'ssg_money_amount',
    'ssg_money_already_applied', 'ssg_money_text',
    'card_benefit_price', 'card_benefit_condition',
    'product_coupon_rate', 'product_coupon_amount',
    'product_coupon_min_order', 'product_coupon_max_discount',
    'product_coupon_label',
    'point_rewards',
    'review_point_max',
    'lotte_member_discount_rate', 'lotte_member_discount_label',
    'store_jjim_coupon_amount', 'store_jjim_coupon_label',
)


def extract_dynamic_benefits_from_options(options) -> dict:
    """parse 결과 options(list[dict]) → 동적 혜택 dict.

    상품 단위 동일 값 가정 → 첫 non-empty 옵션의 동적 키들만 추출(service.py 와 동일 정책).
    0/None/''/False 는 미수집으로 보고 제외(폴백 금지). 비면 {} 반환(저장 측이 None 처리).
    """
    out = {}
    for o in (options or []):
        if not isinstance(o, dict):
            continue
        cur = {}
        for k in _PRODUCT_DYNAMIC_KEYS:
            if k in o and o[k] not in (None, 0, '', False):
                cur[k] = o[k]
        if cur:
            return cur
    return out


def has_musinsa_member_signal(lines) -> bool:
    """라인에 무신사 회원 적립 신호(등급적립/무신사머니/최대적립 + 금액)가 있는가.

    is_logged_in 플래그(확장 타이밍 버그로 비신뢰)를 대체하는 콘텐츠 기반 판정.
    True = 회원 혜택 영역을 실제로 긁음 → 금액 채택 가능.
    """
    for raw in (lines or []):
        l = (raw or '').replace(' ', '')
        if ('등급적립(' in l or '최대적립' in l or ('무신사머니' in l and '적립' in l)) \
                and _won(raw) > 0:
            return True
    return False
