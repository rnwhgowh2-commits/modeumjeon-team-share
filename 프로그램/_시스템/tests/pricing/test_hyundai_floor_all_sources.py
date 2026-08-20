# -*- coding: utf-8 -*-
"""[TEST] T11b — 현대카드 2.73% 플로어 전 소싱처 확장 (스펙 §3 확정표 정합).

■ 무엇을 잠그나
  사장님 확정 스펙(2026-07-22 소싱처-표면노출가-혜택-최종매입가-design.md §3)의
  fx 목록에는 **전 소싱처**에 '현대카드 2.73%' 가 있다:
    §3-1 르무통 · §3-2 스스 · §3-3 무신사(택1, 기구현) · §3-4 SSF ·
    §3-5 롯데온(경로규칙, 기구현) · §3-6 SSG(기구현) · §3-7 Hmall · §3-8 아이몰
  그런데 플랜 T4 가 §7-4 를 blast-radius 최소로 축소 구현하면서 플로어 하드코딩
  블록(api_benefits.py)은 롯데온·SSG·무신사만 커버했다 — T11 스냅샷 정직성 발견
  (docs/검증/2026-07-23-혜택엔진-가격diff.md §3-1). T11b 가 잔여 5곳
  (lemouton·ss_lemouton·ssf·hmall·lotteimall)으로 확장했고, 이 파일이 소싱처별로
  ① 플로어 스텝 존재 ② 정확 산술 ③ 동시차감 불변식(N페이·캐시백) ④ fallback
  택1(아이몰 청구할인 우선)을 못 박는다.

■ 동시차감 불변식 (스펙 §4-2/§4-3)
  · N페이 1% — 이름의 '네이버' 로 결제 택1에서 제외(_is_payment) → 플로어와 동시.
  · OK캐시백 — _is_cashback 제외(final_price.py:241~242) → 플로어와 동시.
  · 아이몰 '○○카드 청구할인'(크롤 정액) — legacy 택1에서 차감 큰 쪽이 이긴다 =
    '청구할인 없을 시 현대카드' fallback 의미(롯데온·SSG 종전 규칙과 동일).

  라이브 미접속 — 전부 인메모리 SQLite 픽스처.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
from lemouton.sourcing.models import SourceBenefitTemplate
from lemouton.sourcing.models_pricing import SourceRegistry
from lemouton.sources.models import SourceProduct, SourceOption, OptionSourceLink
from webapp.routes.api_benefits import compute_breakdown

FLOOR_NAME = '현대카드 2.73% (청구할인 fallback)'

# 계산 번호 체계 (lemouton/sourcing/source_ids.py 단일 원천과 동일)
SRC = {'lemouton': 1, 'ss_lemouton': 2, 'ssf': 4}
KEY_HMALL, KEY_LOTTEIMALL = 'key:hmall', 'key:lotteimall'


def _make_session(*, site, source_id, dynamic=None, templates=(), sku='SKU-FLOOR'):
    """소싱처 상품 1건 + 옵션링크 + (있다면) 시드 모양의 템플릿 행을 심은 세션."""
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    s = Session(eng)
    if isinstance(source_id, int):
        s.add(SourceRegistry(id=source_id, name=f'플로어테스트-{site}'))
    for i, t in enumerate(templates):
        s.add(SourceBenefitTemplate(
            source_id=source_id if isinstance(source_id, int) else None,
            benefit_name=t['name'], benefit_type=t.get('type', 'rate'),
            value=t.get('value', 0), apply_mode=t.get('apply_mode'),
            enabled=True, sort_order=i))
    sp = SourceProduct(site=site, url=f'https://www.{site}.example/p/1',
                       product_name='플로어 테스트 상품',
                       dynamic_benefits_json=json.dumps(dynamic or {},
                                                        ensure_ascii=False))
    s.add(sp)
    s.flush()
    so = SourceOption(source_product_id=sp.id, color_text='블랙', size_text='270')
    s.add(so)
    s.flush()
    s.add(OptionSourceLink(canonical_sku=sku, source_option_id=so.id))
    s.commit()
    return s


def _steps(res):
    return {st['name']: st for st in res['steps']}


# ─────────────────────────────────────────────────────────────
# §3-1 르무통 공홈 — 시드 모양(리뷰 포토 5,000 + N페이 1%) 위에 플로어 단독 차감
# ─────────────────────────────────────────────────────────────
def test_lemouton_floor_deducts_with_npay():
    """116,900 −리뷰5,000 →N페이1% 1,119 →현대 2.73% 3,024 = 107,757 → 107,700.

    (소싱처별-가격로직-전체.md §르무통 예시 산술과 동일 — 스펙 §3-1 실현.)
    """
    s = _make_session(site='lemouton', source_id=SRC['lemouton'], templates=[
        {'name': '리뷰적립(포토)', 'type': 'amount', 'value': 5000,
         'apply_mode': 'deduct'},
        {'name': '네이버페이 적립 1%', 'type': 'rate', 'value': 0.01,
         'apply_mode': 'accrue'},
    ])
    try:
        res = compute_breakdown(s, sku='SKU-FLOOR', source_id=SRC['lemouton'],
                                sale_price=116_900)
        st = _steps(res)
        assert FLOOR_NAME in st, f'steps={list(st)}'
        # 정액 먼저: 116,900−5,000=111,900 → N페이 int(111,900×0.01)=1,119 → 110,781
        assert st['네이버페이 적립 1%']['deduct'] == 1_119
        # 현대 2.73% = int(110,781×0.0273) = 3,024 (직전 잔액 기준)
        assert st[FLOOR_NAME]['deduct'] == 3_024
        # N페이는 택1 제외라 플로어와 **동시** 차감 (스펙 §4-3)
        assert st['네이버페이 적립 1%']['deduct'] > 0 and st[FLOOR_NAME]['deduct'] > 0
        assert res['final_price'] == 107_700   # 107,757 → 백원 버림
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# §3-2 스마트스토어(스스) — 구매적립 1% + N페이 1% 와 플로어 동시 차감
# ─────────────────────────────────────────────────────────────
def test_ss_lemouton_floor_deducts_with_accrue_and_npay():
    """100,000 −리뷰5,000 →구매적립1% 950 →N페이1% 940 →현대 2.73% 2,541 → 90,500."""
    s = _make_session(site='ss_lemouton', source_id=SRC['ss_lemouton'], templates=[
        {'name': '리뷰적립(포토)', 'type': 'amount', 'value': 5000,
         'apply_mode': 'deduct'},
        {'name': '구매적립 기본 1%', 'type': 'rate', 'value': 0.01,
         'apply_mode': 'accrue'},
        {'name': '네이버페이 적립 1%', 'type': 'rate', 'value': 0.01,
         'apply_mode': 'accrue'},
    ])
    try:
        res = compute_breakdown(s, sku='SKU-FLOOR', source_id=SRC['ss_lemouton'],
                                sale_price=100_000)
        st = _steps(res)
        assert FLOOR_NAME in st, f'steps={list(st)}'
        # 100,000−5,000=95,000 → 구매적립 int(95,000×0.01)=950 → 94,050
        assert st['구매적립 기본 1%']['deduct'] == 950
        # N페이 int(94,050×0.01)=940 → 93,110
        assert st['네이버페이 적립 1%']['deduct'] == 940
        # 현대 int(93,110×0.0273)=2,541.9→2,541 → 90,569
        assert st[FLOOR_NAME]['deduct'] == 2_541
        assert res['final_price'] == 90_500
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# §3-4 SSF — 기프트포인트·멤버십포인트·N페이와 플로어 동시 차감.
#   토스페이 5% 는 스펙이 이벤트성으로 **제외**한 항목 — 엔진에 주입 로직이 없어야
#   한다(가이드 문서 conditional 항목일 뿐). 여기서 미존재를 함께 핀.
# ─────────────────────────────────────────────────────────────
def test_ssf_floor_deducts_after_points_and_npay():
    """100,000 →기프트10% →멤버십5% →N페이1% →현대 2.73% — 전부 동시(직전 잔액)."""
    s = _make_session(site='ssf', source_id=SRC['ssf'],
                      dynamic={'gift_point_amount': 9000, 'point_rate': 0.05},
                      templates=[
                          {'name': '네이버페이 적립 1%', 'type': 'rate',
                           'value': 0.01, 'apply_mode': 'accrue'},
                      ])
    try:
        res = compute_breakdown(s, sku='SKU-FLOOR', source_id=SRC['ssf'],
                                sale_price=100_000)
        st = _steps(res)
        assert FLOOR_NAME in st, f'steps={list(st)}'
        # 템플릿 N페이가 조립순서상 먼저: int(100,000×0.01)=1,000 → 99,000
        assert st['네이버페이 적립 1%']['deduct'] == 1_000
        # 기프트 10% int(99,000×0.10)=9,900 → 89,100 → 멤버십 5% 4,455 → 84,645
        assert st['기프트포인트 (멤버십 한정)']['deduct'] == 9_900
        assert st['멤버십포인트 (사이트 적립)']['deduct'] == 4_455
        # 현대 int(84,645×0.0273)=2,310.8→2,310 → 82,335 → 백원버림 82,300
        assert st[FLOOR_NAME]['deduct'] == 2_310
        assert res['final_price'] == 82_300
        # 토스페이 5% 는 스펙 §3-4 제외(이벤트성) — 엔진이 지어내면 안 된다
        assert not any('토스' in (it['name'] or '') for it in res['items_used'])
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# §3-7 Hmall — 카탈로그 상수(OK캐·리뷰·N페이)와 플로어 동시 차감
# ─────────────────────────────────────────────────────────────
def test_hmall_floor_deducts_with_cashback_and_npay():
    """100,000 −리뷰100 →OK캐 2,427 →N페이 974 →현대 2,634 = 93,865 → 93,800."""
    s = _make_session(site='hmall', source_id=KEY_HMALL)
    try:
        res = compute_breakdown(s, sku='SKU-FLOOR', source_id=KEY_HMALL,
                                sale_price=100_000)
        st = _steps(res)
        assert FLOOR_NAME in st, f'steps={list(st)}'
        # 100,000−100=99,900 → OK캐 int(99,900×0.9×0.027)=2,427 → 97,473
        assert st['OK캐시백 2.7%']['deduct'] == 2_427
        # N페이 int(97,473×0.01)=974 → 96,499
        assert st['네이버페이 적립 1%']['deduct'] == 974
        # 현대 int(96,499×0.0273)=2,634.4→2,634 → 93,865
        assert st[FLOOR_NAME]['deduct'] == 2_634
        # 캐시백·N페이 둘 다 플로어와 **동시** 차감 (택1로 죽지 않음 — §4-2/§4-3)
        assert res['final_price'] == 93_800
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# §3-8 롯데아이몰 — 캐시백 동시 차감 + 청구할인 fallback 택1
# ─────────────────────────────────────────────────────────────
def test_lotteimall_floor_deducts_with_cashback():
    """100,000 −리뷰100 →OK캐 2,247 →현대 2,665 = 94,988 → 94,900 (청구할인 없음)."""
    s = _make_session(site='lotteimall', source_id=KEY_LOTTEIMALL)
    try:
        res = compute_breakdown(s, sku='SKU-FLOOR', source_id=KEY_LOTTEIMALL,
                                sale_price=100_000)
        st = _steps(res)
        assert FLOOR_NAME in st, f'steps={list(st)}'
        # 100,000−100=99,900 → OK캐 int(99,900×0.9×0.025)=2,247 → 97,653
        assert st['OK캐시백 2.5%']['deduct'] == 2_247
        # 현대 int(97,653×0.0273)=2,665.9→2,665 → 94,988
        assert st[FLOOR_NAME]['deduct'] == 2_665
        assert res['final_price'] == 94_900
    finally:
        s.close()


def test_lotteimall_crawled_card_discount_beats_floor():
    """크롤 청구할인(8,180)이 플로어(2.73%≈3,191)보다 크면 택1에서 이긴다.

    = '청구할인 없을 시 현대카드' fallback 의미 그대로 (롯데온·SSG 종전 규칙 동일).
    둘 다 빠지면 물리적으로 불가능한 조합(카드 2장 결제) = 매입가 과소 — 금지.
    """
    s = _make_session(site='lotteimall', source_id=KEY_LOTTEIMALL,
                      dynamic={'lotteimall_card_discount': 8180,
                               'lotteimall_card_label': '삼성카드 7%'})
    try:
        res = compute_breakdown(s, sku='SKU-FLOOR', source_id=KEY_LOTTEIMALL,
                                sale_price=116_900)
        st = _steps(res)
        assert '삼성카드 7% 청구할인' in st
        assert st['삼성카드 7% 청구할인']['deduct'] == 8_180
        # 플로어는 택1 패자 — 차감 스텝에 없어야 한다 (이중 차감 금지)
        assert FLOOR_NAME not in st, f'청구할인+플로어 이중차감: {list(st)}'
        # 항목 자체는 영수증 목록(items_used)에 비활성으로 노출된다
        floor_item = next((it for it in res['items_used']
                           if it['name'] == FLOOR_NAME), None)
        assert floor_item is not None and floor_item['enabled'] is False
        # 최종가 핀 — 정액(청구할인 → 리뷰) 먼저, 정률(OK캐) 나중:
        #   116,900 − 8,180(청구할인) = 108,720 − 100(리뷰) = 108,620
        #   − int(108,620×0.9×0.025)=2,443(OK캐) → 106,177 → 백원 버림 106,100
        #   (test_catalog_source_benefits.py 의 EXPECTED_FINAL 과 동일 값 — 플로어
        #    확장 전후 불변임을 최종가로도 못 박는다)
        assert res['final_price'] == 106_100
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────
# 회귀 가드 — 기구현 3곳(무신사·롯데온·SSG)의 플로어 로직 불변
# ─────────────────────────────────────────────────────────────
def test_musinsa_keeps_its_own_conditional_floor_name():
    """무신사는 T11b 대상이 아니다 — 종전 '(무신사머니 미적용 시)' 이름 그대로."""
    s = _make_session(site='musinsa', source_id=3,
                      dynamic={'surface_price': 100000, 'money_reward_amount': 0,
                               'money_active': False})
    try:
        res = compute_breakdown(s, sku='SKU-FLOOR', source_id=3,
                                sale_price=100_000)
        names = [it['name'] for it in res['items_used']]
        assert any('무신사머니 미적용 시' in n for n in names)
        assert FLOOR_NAME not in names
    finally:
        s.close()
