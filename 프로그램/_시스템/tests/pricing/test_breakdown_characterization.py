# -*- coding: utf-8 -*-
"""compute_breakdown 박제(characterization) 테스트 — 금액 리팩터링 안전망.

왜 있나
------
`compute_breakdown`(api_benefits.py, 660줄)은 최종 매입가의 단일 원천인데,
소싱처마다 다른 돈 규칙이 한 함수 안에 쌓여 있다(SSG 카드혜택가, 무신사 등급적립·
무신사머니 택1, 롯데아이몰 포인트, 현대카드 2.73% 플로어 …).

여기서 조립부를 떼어내 다른 화면(지도 예시주소 「▶ 크롤」)도 **같은 계산**을 쓰게
만들려 한다. 그런데 금액 함수는 "안 바뀌었을 것"이라고 말로 주장하면 안 된다.
→ 리팩터링 **전** 결과를 이 테스트로 박제하고, **후** 한 원이라도 달라지면 깨지게 한다.

무엇을 지키나
------------
· 소싱처별 분기(§5 per-source rule)를 **하나씩** 태운다.
· 최종가뿐 아니라 **영수증 단계(steps)** 까지 비교한다 — 합계만 같고 과정이 달라지면
  사용자가 보는 영수증이 바뀐다.
· 기대값은 **현재 동작을 떠온 것**이다. 이 숫자가 '옳다'는 뜻이 아니라
  '리팩터링으로 바뀌면 안 된다'는 뜻이다(그래서 박제다).

주의: 값을 고칠 일이 생기면 반드시 **의도한 금액 변경**일 때만, 이유를 커밋에 남기고 고친다.
"""
import json

import pytest

from shared.db import SessionLocal
from lemouton.sourcing.models import (
    SourceBenefitTemplate, OptionBenefitOverride,
)
from lemouton.sourcing.models_pricing import OptionSourceUrl
from lemouton.sources.models import SourceProduct
from webapp.routes.api_benefits import compute_breakdown


# ── 소싱처 번호 체계 ────────────────────────────────────────────────────────
# ★ compute_breakdown 이 쓰는 번호는 _SITE_BY_SRC(api_benefits.py:555) 다.
#   소싱처 화면(SourcingSource.id)과 **다른 체계**이니 섞지 말 것.
SRC = {'lemouton': 1, 'ss_lemouton': 2, 'musinsa': 3, 'ssf': 4, 'lotteon': 5, 'ssg': 6}
# 카탈로그 소싱처는 정수 id 가 없어 'key:' 합성 id 를 쓴다(api_pricing.py:728).
KEY_HMALL, KEY_LOTTEIMALL = 'key:hmall', 'key:lotteimall'

PREFIX = 'CHARTEST-'


def _mk_url(tag):
    return f'https://example.test/chartest/{tag}'


@pytest.fixture(scope='module', autouse=True)
def _tables():
    for m in ('lemouton.sourcing.models', 'lemouton.sourcing.models_pricing',
              'lemouton.sources.models', 'lemouton.templates.models',
              'lemouton.inventory.models', 'lemouton.mapping.models'):
        try:
            __import__(m)
        except ImportError:
            pass
    from shared.db import Base, engine, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()


def _wipe(s):
    """이 테스트가 만든 행만 지운다(다른 테스트 데이터 보존)."""
    s.query(OptionBenefitOverride).filter(
        OptionBenefitOverride.canonical_sku.like(PREFIX + '%')).delete(
        synchronize_session=False)
    s.query(OptionSourceUrl).filter(
        OptionSourceUrl.canonical_sku.like(PREFIX + '%')).delete(
        synchronize_session=False)
    s.query(SourceProduct).filter(
        SourceProduct.url.like('https://example.test/chartest/%')).delete(
        synchronize_session=False)
    # ★ test_benefits_unavailable_keeps_full_price 가 새로 만들 때 쓰는 이름표.
    #   기존 id 를 재사용한 경우(SourceRegistry.id=sid)엔 이름이 안 바뀌므로
    #   여기 안 걸리는데, 그 경우는 crawl_guide 를 매번 같은 값으로 덮어써서
    #   재실행해도 결과가 달라지지 않는다(멱등) — 이름 충돌만 막으면 충분.
    from lemouton.sourcing.models_pricing import SourceRegistry
    s.query(SourceRegistry).filter(
        SourceRegistry.name.like('박제-%')).delete(synchronize_session=False)
    s.commit()


def _seed(s, *, sku, source_id, site, templates=(), dynamic=None, overrides=()):
    """한 시나리오의 최소 데이터 — 템플릿 · 동적혜택 · 옵션 override."""
    # 소싱처 템플릿은 source_id 로 붙는다. 매번 지우고 다시 심어 다른 시나리오와 안 섞이게.
    s.query(SourceBenefitTemplate).filter_by(source_id=source_id).delete(
        synchronize_session=False)
    for i, t in enumerate(templates):
        s.add(SourceBenefitTemplate(
            source_id=source_id, benefit_name=t['name'],
            benefit_type=t.get('type', 'amount'), value=t.get('value', 0),
            apply_mode=t.get('apply_mode'), enabled=t.get('enabled', True),
            base_ratio=t.get('base_ratio'), pay_method=t.get('pay_method'),
            sort_order=i))
    url = _mk_url(sku)
    s.add(OptionSourceUrl(canonical_sku=sku, source_id=source_id, product_url=url))
    s.add(SourceProduct(site=site, url=url,
                        dynamic_benefits_json=json.dumps(dynamic or {},
                                                         ensure_ascii=False)))
    for i, o in enumerate(overrides):
        s.add(OptionBenefitOverride(
            canonical_sku=sku, source_id=source_id, benefit_name=o['name'],
            benefit_type=o.get('type', 'amount'), value=o.get('value', 0),
            enabled=o.get('enabled', True), base_ratio=o.get('base_ratio'),
            sort_order=i))
    s.commit()


def _run(sku, source_id, sale_price):
    s = SessionLocal()
    try:
        r = compute_breakdown(s, sku=sku, source_id=source_id, sale_price=sale_price)
        return {
            'final': r.get('final_price'),
            'steps': [(st['name'], st['type'], round(float(st['value']), 6),
                       st['deduct']) for st in (r.get('steps') or [])],
            'base': r.get('sale_price'),
        }
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def sess():
    s = SessionLocal()
    _wipe(s)
    yield s
    _wipe(s)
    s.close()


# ── 시나리오 ────────────────────────────────────────────────────────────────
# 각 케이스는 §5 의 소싱처별 분기를 하나씩 태운다.

def test_template_only_no_dynamic(sess):
    """가장 단순 — 템플릿 정액 + 정률. 동적혜택 없음(르무통형)."""
    sku = PREFIX + 'tplonly'
    _seed(sess, sku=sku, source_id=SRC['lemouton'], site='lemouton',
          templates=[{'name': '리뷰적립', 'type': 'amount', 'value': 5000},
                     {'name': '네이버페이 적립', 'type': 'rate', 'value': 0.01}])
    got = _run(sku, SRC['lemouton'], 116900.0)
    # [2026-07-23 T11b] 현대카드 2.73% 플로어 르무통 확장(스펙 §3-1) 후:
    #   116,900 −5,000(리뷰) = 111,900 − int(111,900×0.01)=1,119(N페이) → 110,781
    #   − int(110,781×0.0273)=3,024(현대) → 107,757 → 백원 버림 107,700.
    #   (종전 110,700 = 플로어가 롯데온·SSG·무신사만 커버하던 값)
    assert got['final'] == 107700
    assert got['steps'] == [
        ('리뷰적립', 'amount', 5000.0, 5000),
        ('네이버페이 적립', 'rate', 0.01, 1119),
        ('현대카드 2.73% (청구할인 fallback)', 'rate', 0.0273, 3024),
    ]


def test_override_beats_template_same_name(sess):
    """같은 이름이면 옵션 override 가 템플릿을 덮는다(이름 기준 병합)."""
    sku = PREFIX + 'ovr'
    _seed(sess, sku=sku, source_id=SRC['lemouton'], site='lemouton',
          templates=[{'name': '리뷰적립', 'type': 'amount', 'value': 5000},
                     {'name': '기타적립', 'type': 'amount', 'value': 1000}],
          overrides=[{'name': '리뷰적립', 'type': 'amount', 'value': 7000}])
    got = _run(sku, SRC['lemouton'], 100000.0)
    # override 7,000 + 안 덮인 템플릿 1,000 = 8,000 (템플릿 통째 드롭 아님)
    # [2026-07-23 T11b] 현대카드 플로어 확장 후: 92,000 − int(92,000×0.0273)=2,511
    #   → 89,489 → 백원 버림 89,400 (종전 92,000)
    assert got['final'] == 89400


def test_ssf_gift_point_inactive_without_crawl(sess):
    """SSF 기프트포인트는 항상 보이되, 크롤에 금액이 없으면 비활성."""
    sku = PREFIX + 'ssf_nogp'
    _seed(sess, sku=sku, source_id=SRC['ssf'], site='ssf',
          templates=[{'name': '기본적립', 'type': 'amount', 'value': 1000}],
          dynamic={'point_rate': 0.05})
    got = _run(sku, SRC['ssf'], 100000.0)
    names = [n for n, *_ in got['steps']]
    assert '기프트포인트 (멤버십 한정)' not in names   # 비활성 → 차감단계에 안 나옴
    assert '멤버십포인트 (사이트 적립)' in names
    # 100,000 −1,000(기본적립) = 99,000 → ×5%(멤버십포인트) = 4,950 → 94,050
    # [2026-07-23 T11b] 현대카드 플로어 SSF 확장(스펙 §3-4) 후:
    #   94,050 − int(94,050×0.0273)=2,567 → 91,483 → 백원 버림 91,400 (종전 94,000)
    assert got['final'] == 91400


def test_ssf_gift_point_active_when_crawled(sess):
    """크롤에 기프트포인트가 잡히면 10% 활성."""
    sku = PREFIX + 'ssf_gp'
    _seed(sess, sku=sku, source_id=SRC['ssf'], site='ssf',
          dynamic={'gift_point_amount': 9000, 'point_rate': 0.05})
    got = _run(sku, SRC['ssf'], 100000.0)
    names = [n for n, *_ in got['steps']]
    assert '기프트포인트 (멤버십 한정)' in names
    # [2026-07-23 T11b] 현대카드 플로어 SSF 확장 후:
    #   100,000 −10,000(기프트10%) → 90,000 −4,500(멤버십5%) → 85,500
    #   − int(85,500×0.0273)=2,334 → 83,166 → 백원 버림 83,100 (종전 85,500)
    assert got['final'] == 83100


def test_ssg_card_benefit_price_flat_deduct(sess):
    """SSG 카드혜택가 = 표면가와의 차액을 정액 차감. 하한 미만이면 비활성."""
    sku = PREFIX + 'ssg_cbp'
    _seed(sess, sku=sku, source_id=SRC['ssg'], site='ssg',
          dynamic={'card_benefit_price': 90000,
                   'card_benefit_condition': '5만원 이상 결제 시'})
    got_hi = _run(sku, SRC['ssg'], 100000.0)     # 10만 ≥ 5만 → 활성
    assert any('카드혜택가' in n for n, *_ in got_hi['steps'])
    got_lo = _run(sku, SRC['ssg'], 40000.0)      # 4만 < 5만 → 비활성
    assert not any('카드혜택가' in n for n, *_ in got_lo['steps'])


def test_ssg_money_charge_condition(sess):
    """SSG MONEY '충전' 문구면 3% 이상일 때만 적용."""
    sku = PREFIX + 'ssg_money'
    _seed(sess, sku=sku, source_id=SRC['ssg'], site='ssg',
          dynamic={'ssg_money_rate': 0.01, 'ssg_money_text': '충전결제 시 1% 적립'})
    lo = _run(sku, SRC['ssg'], 100000.0)
    assert not any('SSG MONEY' in n for n, *_ in lo['steps'])
    _wipe(sess)
    _seed(sess, sku=sku, source_id=SRC['ssg'], site='ssg',
          dynamic={'ssg_money_rate': 0.05, 'ssg_money_text': '충전결제 시 5% 적립'})
    hi = _run(sku, SRC['ssg'], 100000.0)
    assert any('SSG MONEY' in n for n, *_ in hi['steps'])


def test_musinsa_base_override_and_rewards(sess):
    """★ 무신사 — 표면가로 베이스를 갈아끼우고 등급적립·무신사머니를 주입한다.

    이 케이스가 이번 리팩터링의 핵심(지도 「▶ 크롤」이 재현해야 하는 계산).
    """
    sku = PREFIX + 'musinsa'
    _seed(sess, sku=sku, source_id=SRC['musinsa'], site='musinsa',
          dynamic={'surface_price': 119900, 'grade_reward_amount': 4460,
                   'money_reward_amount': 4050, 'money_active': True})
    got = _run(sku, SRC['musinsa'], 101510.0)   # 회원가로 불러도
    assert got['base'] == 119900.0              # 베이스는 표면가로 교체된다
    names = [n for n, *_ in got['steps']]
    assert '등급적립' in names
    assert '무신사머니 결제 적립' in names
    assert got['final'] == 111300


def test_musinsa_card_floor_only_when_no_money(sess):
    """무신사머니가 잡히면 현대카드 2.73% 는 비활성(택1)."""
    sku = PREFIX + 'musinsa_nomoney'
    _seed(sess, sku=sku, source_id=SRC['musinsa'], site='musinsa',
          dynamic={'surface_price': 100000, 'money_reward_amount': 0,
                   'money_active': False})
    got = _run(sku, SRC['musinsa'], 100000.0)
    assert any('현대카드' in n for n, *_ in got['steps'])


def test_lotteon_card_floor_applies(sess):
    """롯데온은 현대카드 2.73% 플로어가 기본 활성."""
    sku = PREFIX + 'lotteon'
    _seed(sess, sku=sku, source_id=SRC['lotteon'], site='lotteon',
          dynamic={'lotte_member_discount_rate': 0.05})
    got = _run(sku, SRC['lotteon'], 100000.0)
    names = [n for n, *_ in got['steps']]
    assert any('현대카드' in n for n in names)
    assert any('롯데' in n or '회원' in n for n in names)


def test_hmall_point_and_card(sess):
    """현대H몰 — H.Point 는 활성, 카드 즉시할인은 비활성이 기본."""
    sku = PREFIX + 'hmall'
    _seed(sess, sku=sku, source_id=KEY_HMALL, site='hmall',
          dynamic={'hmall_point_amount': 3000, 'hmall_card_discount': 5000})
    got = _run(sku, KEY_HMALL, 100000.0)
    names = [n for n, *_ in got['steps']]
    assert any('POINT' in n.upper() or '포인트' in n for n in names)
    # 카드 즉시할인 5,000 은 여전히 안 빠진다 (비활성 기본 — 이 테스트의 원래 목적)
    assert not any('즉시할인' in n for n in names)
    # [2026-07-22 Task 3] 카탈로그 상수(OK캐 2.7%×0.9·리뷰100·N페이1%) 주입 후:
    #   100,000 − 3,000(H.Point) − 100(리뷰) = 96,900
    #   − int(96,900×0.9×0.027)=2,354 → 94,546 − int(94,546×0.01)=945 → 93,601
    # [2026-07-23 T11b] 현대카드 플로어 Hmall 확장(스펙 §3-7) 후:
    #   93,601 − int(93,601×0.0273)=2,555 → 91,046 → 백원 버림 91,000
    #   (종전 93,600 = T3 시점 / 97,000 = 상수 주입 전)
    assert got['final'] == 91000


def test_lotteimall_point_rewards(sess):
    """롯데아이몰 — point_rewards 로 적립을 정액 주입, 카드 청구할인은 활성."""
    sku = PREFIX + 'lotteimall'
    _seed(sess, sku=sku, source_id=KEY_LOTTEIMALL, site='lotteimall',
          dynamic={'point_rewards': {'default_point': 2000},
                   'lotteimall_card_discount': 7000})
    got = _run(sku, KEY_LOTTEIMALL, 100000.0)
    # 적립 2,000 + 카드 7,000 은 각각 1스텝씩 차감 (이 테스트의 원래 목적)
    assert any('L.POINT' in n or '구매적립' in n for n, *_ in got['steps'])
    assert any('청구할인' in n for n, *_ in got['steps'])
    # [2026-07-22 Task 3] 카탈로그 상수(OK캐 2.5%×0.9·리뷰100) 주입 후:
    #   100,000 − 2,000 − 7,000 − 100(리뷰) = 90,900
    #   − int(90,900×0.9×0.025)=2,045 → 88,855 → 백원 버림 88,800
    #   (종전 91,000 = 상수 주입 전 값)
    # [2026-07-23 T11b] 아이몰 플로어 확장 후에도 **불변** — 크롤 청구할인 7,000 이
    #   결제 택1에서 현대카드 2.73%(≈2,730)를 이겨 플로어는 비활성(fallback 의미).
    #   청구할인 없는 케이스의 플로어 차감은 test_hyundai_floor_all_sources.py 가 핀.
    assert got['final'] == 88800


def test_benefits_unavailable_keeps_full_price(sess):
    """★ 혜택을 크롤로 가져오는 소싱처인데 못 가져왔으면 템플릿도 안 쓴다.

    싸게 잡으면 손해 매입 — 더 비싼 쪽으로 둔다(2026-07-19 사용자 확정).
    ⚠ 이 가드가 읽는 곳은 SourceRegistry.crawl_guide 다(api_benefits.py:472).
      화면이 쓰는 SourcingSource.crawl_guide 와 **다른 저장소** — 저장소가 갈라져 있다는
      사실 자체가 이번 개편에서 고칠 대상이라, 지금은 가드가 실제로 읽는 쪽에 심는다.
    """
    from lemouton.sourcing.models_pricing import SourceRegistry
    from lemouton.sourcing import crawl_guide as cg
    sku, sid = PREFIX + 'unavail', SRC['musinsa']
    _seed(sess, sku=sku, source_id=sid, site='musinsa',
          templates=[{'name': '등급적립', 'type': 'amount', 'value': 5000}],
          dynamic={})
    g = cg.empty_skeleton()
    g['fields']['benefit'].update({'method': 'crawl_per_product',
                                   'mechanism': 'html', 'status': 'ok'})
    reg = sess.get(SourceRegistry, sid)
    if reg is None:
        reg = SourceRegistry(id=sid, name=f'박제-{sid}')
        sess.add(reg)
    reg.crawl_guide = cg.dumps(cg.validate_guide(g))
    sess.commit()
    got = _run(sku, sid, 100000.0)
    names = [n for n, *_ in got['steps']]
    assert '등급적립' not in names   # 가드 발동 — 템플릿 5,000 은 안 빠진다
    # 그런데 무신사 현대카드 2.73% 플로어는 템플릿이 아니라 소싱처 고정 규칙이라
    # 가드 대상이 아니다(money_reward 도 못 크롤했으니 그대로 활성 — §5 무신사 분기).
    # 100,000 × 2.73% = 2,730 → 97,270 → 백원버림 97,200.
    # ⚠ 이 값이 "옳다"는 뜻이 아니다 — 카드플로어까지 막아야 하는지는 별도 판단거리.
    # 지금은 리팩터링 중 이 라인이 안 바뀌었는지만 지킨다.
    assert got['final'] == 97200
