# -*- coding: utf-8 -*-
"""source_product_id 명시 지정이 낡은(legacy) 조회를 이겨야 한다 — 라이브 금전 버그.

배경 (2026-07-20 라이브 실측)
---------------------------
모음전 1건에 무신사 상품이 7개 붙어 있는데, `compute_breakdown`(api_benefits.py:487)의
97개 옵션 전부가 **상품 1개(4046672)** 의 동적혜택으로 계산됐다. 그 상품은 129,890원 +
「르무통 상반기 결산 10% 상품쿠폰」(12,980원)을 갖고 있고, 나머지 6개 상품(119,900원·
쿠폰 없음)에 속한 옵션들도 전부 129,890원 기준·쿠폰 12,980원 차감으로 계산됐다.
63개(65%) 옵션이 **남의 상품** 가격·쿠폰으로 매입가가 산출된 것 — 실제보다 싸게 나와
손해 매입.

원인은 api_benefits.py:608 의 가드:

    if source_product_id and not _dynamic_benefits:

호출자(매트릭스, _matrix_v3.html:3498)가 그 옵션이 속한 **정확한** SourceProduct.id 를
`source_product_id` 로 넘겨줘도, 그보다 먼저 도는 낡은 OptionSourceUrl→product_url 조회가
**뭔가**(엉뚱한 행)를 찾아버리면 `_dynamic_benefits` 가 이미 채워져 있어 이 가드를 안 탄다.
무신사는 낡은 조회가 항상 뭔가는 찾는다 — 문제는 그게 늘 옳은 행이 아니라는 것.

이 테스트는 "호출자가 행을 지목하면 그 행이 이긴다"를 고정한다. 아직 수정 전이므로
1·2번은 RED(낡은 행 A 의 데이터가 이김), 3번은 GREEN(기존 동작 보존 확인)이어야 한다.
"""
import json

import pytest

from shared.db import SessionLocal
from lemouton.sourcing.models import SourceBenefitTemplate
from lemouton.sourcing.models_pricing import OptionSourceUrl
from lemouton.sources.models import SourceProduct
from webapp.routes.api_benefits import compute_breakdown


# ★ compute_breakdown 이 쓰는 번호는 _SITE_BY_SRC(api_benefits.py) 다. SourcingSource.id 와
#   다른 체계 — tests/pricing/test_breakdown_characterization.py 와 동일한 표를 그대로 쓴다.
SRC = {'lemouton': 1, 'ss_lemouton': 2, 'musinsa': 3, 'ssf': 4, 'lotteon': 5, 'ssg': 6}

PREFIX = 'SPIDWINS-'


def _mk_url(tag):
    return f'https://example.test/spidwins/{tag}'


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
    """이 테스트가 만든 행만 지운다(다른 테스트 데이터 보존).

    ★ SourceBenefitTemplate 은 source_id 로만 걸리고(canonical_sku 무관), DB 는
      테스트 간 공유(트랜잭션 롤백 없음) — 다른 파일(test_breakdown_characterization.py
      의 무신사 케이스들)이 source_id=3 에 남겨둔 템플릿이 여기로 새어 들어와 계산에
      섞인다(실측: '리뷰적립' 5,000원 유입). 이 파일은 동적혜택(dynamic_benefits_json)
      만으로 검증하므로 musinsa 템플릿은 항상 비워 둔다.
    """
    s.query(OptionSourceUrl).filter(
        OptionSourceUrl.canonical_sku.like(PREFIX + '%')).delete(
        synchronize_session=False)
    s.query(SourceProduct).filter(
        SourceProduct.url.like('https://example.test/spidwins/%')).delete(
        synchronize_session=False)
    s.query(SourceBenefitTemplate).filter_by(
        source_id=SRC['musinsa']).delete(synchronize_session=False)
    s.commit()


@pytest.fixture
def sess():
    s = SessionLocal()
    _wipe(s)
    yield s
    _wipe(s)
    s.close()


def _seed_two_rows(s, *, sku, dynamic_a, dynamic_b):
    """행 A(낡은 조회가 찾는 「엉뚱한」 상품) · 행 B(매트릭스가 지목하는 「정답」 상품).

    A 는 OptionSourceUrl 로 연결해 legacy lookup 이 반드시 A 를 찾게 만든다.
    B 는 아무 것도 연결하지 않는다 — 오직 source_product_id 로만 도달 가능해야
    "명시 지정이 이긴다"를 검증할 수 있다.
    """
    url_a = _mk_url(sku + '-A')
    url_b = _mk_url(sku + '-B')
    s.add(OptionSourceUrl(canonical_sku=sku, source_id=SRC['musinsa'],
                           product_url=url_a))
    sp_a = SourceProduct(
        site='musinsa', url=url_a,
        dynamic_benefits_json=json.dumps(dynamic_a, ensure_ascii=False))
    sp_b = SourceProduct(
        site='musinsa', url=url_b,
        dynamic_benefits_json=(json.dumps(dynamic_b, ensure_ascii=False)
                                if dynamic_b else None))
    s.add(sp_a)
    s.add(sp_b)
    s.commit()
    return sp_a, sp_b


def _run(sku, source_id, sale_price, *, source_product_id=None):
    s = SessionLocal()
    try:
        r = compute_breakdown(s, sku=sku, source_id=source_id,
                               sale_price=sale_price,
                               source_product_id=source_product_id)
        return {
            'final': r.get('final_price'),
            'steps': [(st['name'], st['type'], round(float(st['value']), 6),
                       st['deduct']) for st in (r.get('steps') or [])],
            'base': r.get('sale_price'),
        }
    finally:
        s.rollback()
        s.close()


# 행 A — 낡은 조회가 잡는 「엉뚱한」 무신사 상품(라이브의 4046672 에 대응).
_DYNAMIC_A = {
    'surface_price': 129890,
    'grade_reward_amount': 4830,
    'product_coupon_list': [{'name': '옛상품 쿠폰', 'amount': 12980}],
}
# 행 B — 이 셀이 실제로 속한 「정답」 무신사 상품. 쿠폰 없음·가격 다름.
_DYNAMIC_B = {
    'surface_price': 119900,
    'grade_reward_amount': 4000,
}


def _grade_reward_value(steps):
    """steps 에서 '등급적립' 단계의 금액. 없으면 None(비활성=차감단계 자체가 안 나옴)."""
    for n, _t, v, _d in steps:
        if n == '등급적립':
            return v
    return None


def test_explicit_row_wins_over_legacy_lookup(sess):
    """매트릭스가 넘긴 source_product_id(행 B)가 낡은 조회가 찾은 행 A 를 이겨야 한다.

    라이브에서 97개 옵션 중 63개(65%)가 이 가드 때문에 129,890원(행 A)으로 계산됐다.
    행 B(119,900원)로 지목했으면 베이스도 119,900원·등급적립도 B 의 4,000원이어야
    한다 — 아니면 옵션마다 다른 무신사 상품에 속해도 전부 같은 상품 데이터로
    계산되는 사고가 재현된다. 상품쿠폰(행 A 전용, 12,980원)도 스며들면 안 된다.
    """
    sku = PREFIX + 'wins'
    sp_a, sp_b = _seed_two_rows(sess, sku=sku, dynamic_a=_DYNAMIC_A, dynamic_b=_DYNAMIC_B)
    got = _run(sku, SRC['musinsa'], 101510.0, source_product_id=sp_b.id)
    assert got['base'] == 119900.0
    assert _grade_reward_value(got['steps']) == 4000.0    # 행 A 의 4,830 이 아니다
    names = [n for n, *_ in got['steps']]
    assert '상품쿠폰' not in names   # 행 A 전용 쿠폰(12,980원)이 새 나오면 안 된다


def test_explicit_row_without_benefits_does_not_fall_back(sess):
    """지목한 행(B)에 혜택이 없으면 남의 행(A)의 혜택으로 메우지 않는다.

    남의 상품 쿠폰·등급적립을 몰래 빌려 쓰면 그만큼 차감이 생겨 계산된 매입가가
    실제보다 **싸게** 나온다 — 손해 매입(사장님이 실제보다 낮은 원가로 판매가를
    잡게 됨). 혜택 없이 계산해 더 비싼 쪽(안전한 쪽)으로 두는 게 낫다는 것이
    확정 정책(2026-07-19, docs 상품쿠폰 게이트 및 §5 규칙과 동일한 방향).
    """
    sku = PREFIX + 'nofallback'
    sp_a, sp_b = _seed_two_rows(sess, sku=sku, dynamic_a=_DYNAMIC_A, dynamic_b=None)
    got = _run(sku, SRC['musinsa'], 101510.0, source_product_id=sp_b.id)
    names = [n for n, *_ in got['steps']]
    assert '상품쿠폰' not in names        # 행 A 의 쿠폰(12,980원)이 스며들면 안 된다
    assert _grade_reward_value(got['steps']) is None   # 행 A 의 등급적립(4,830원)도 안 된다


def test_no_source_product_id_keeps_legacy_behavior(sess):
    """source_product_id 를 안 넘기는 호출자는 기존 동작 그대로 — 회귀 방지.

    아직 이 파라미터를 안 넘기는 호출부(예: 단건 API, 일괄 계산 캐시가 못 채운 경로)가
    있을 수 있으므로, 안 넘긴 경우는 낡은 조회(=행 A)가 그대로 이겨야 한다.
    """
    sku = PREFIX + 'legacy'
    sp_a, sp_b = _seed_two_rows(sess, sku=sku, dynamic_a=_DYNAMIC_A, dynamic_b=_DYNAMIC_B)
    got = _run(sku, SRC['musinsa'], 101510.0)  # source_product_id 미전달
    assert got['base'] == 129890.0
    assert _grade_reward_value(got['steps']) == 4830.0
    names = [n for n, *_ in got['steps']]
    assert '상품쿠폰' in names
