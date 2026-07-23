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
      · 무신사머니   : '무신사머니'+'결제'+'적립' 라인 + 금액 → money_reward_amount, money_active=True
                     (삼성카드 포인트·보유적립금·첫결제·최대적립 라인 제외 — 결제혜택 아님)
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
        # 무신사머니 결제 적립 — '무신사머니 결제 시 X% 적립' 클린 라인만.
        #   ★ 2026-07-05 — 삼성카드 무신사머니 포인트 적립·보유 적립금·첫결제 추가적립·최대적립 요약은
        #     결제혜택(계산 대상)이 아님 → 제외. 기존 max 가 삼성카드/보유적립 라인(예: 9,499)을 긁어
        #     money_reward 과다크롤 → 언더프라이싱하던 것 수정. (정본: 결제적립 트리거='무신사머니 결제',
        #     tests/pricing/test_breakdown_musinsa_fresh GUIDE). l 은 공백 제거됨 → 키워드도 공백 없음.
        if '무신사머니' in l and '결제' in l and '적립' in l \
                and '삼성' not in l and '보유' not in l and '첫' not in l and '최대적립' not in l:
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
#   키 목록 = service.py PRODUCT_DYNAMIC_KEYS **import 파생**(단일 진실 원천).
#   ★ 2026-07-23 드리프트 해소 — 예전엔 수동 사본이라 4키(product_coupon_list·
#   member_price·is_member_price·login_marker_present)가 빠져 있었다. 이제 import 로
#   묶어 재발 불가. 추가 키가 navGrab 경로에 흐르는 영향: 무신사·롯데온은 navGrab
#   소싱처가 아니어서 해당 키가 parse 옵션에 등장할 일이 없다 = 현행 소싱처엔 no-op,
#   미래 드리프트만 방지. (순환 import 없음 — service.py 는 lemouton.pricing 을
#   모듈 레벨에서 import 하지 않는다. 2026-07-23 확인.)
# ─────────────────────────────────────────────────────────────────────────────
from lemouton.sources.service import PRODUCT_DYNAMIC_KEYS as _PRODUCT_DYNAMIC_KEYS


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
