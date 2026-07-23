# -*- coding: utf-8 -*-
"""M3 Task 6 — 등록 실적에서 카테고리를 되받아와 observed 맵핑을 만든다.

'추측(이름 유사도)'이 아니라 '그때 실제로 고른 코드'라 정확도가 훨씬 높다.
마켓 호출은 전부 주입 콜러블(fetch_category)로 대체 — 라이브 호출 0.
"""
import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
import lemouton.sourcing.models as SM          # noqa: F401  (Model·BundleSourceUrl 등록)
import lemouton.sources.models as SRC          # noqa: F401  (SourceProduct 등록)
from lemouton.registration.models import CategoryMapRow, MarketCategory
from lemouton.registration import observed_map as om

NOW = datetime.datetime(2026, 7, 23, 12, 0, 0)


def _mem():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _seed_market_cat(s, market='smartstore', code='50000167',
                     path='패션잡화>여성신발>여성운동화', removed=False):
    s.add(MarketCategory(market=market, code=code, name=path.split('>')[-1],
                         full_path=path, depth=3, is_leaf=True,
                         harvested_at=NOW,
                         removed_at=(NOW if removed else None)))
    s.commit()


def _seed_model(s, model_code='M1', url='https://musinsa.com/1', site='musinsa',
                category_path='신발>스니커즈>여성운동화', **market_ids):
    s.add(SM.Model(model_code=model_code, model_name_raw='테스트',
                   url_musinsa=(url if site == 'musinsa' else None),
                   **market_ids))
    if url:
        s.add(SRC.SourceProduct(site=site, url=url, category_path=category_path))
    s.commit()


def _fetch(mapping):
    """(market, product_id) → 코드. 없으면 None. 호출 순서를 기록한다."""
    calls = []

    def _f(market, product_id):
        calls.append((market, product_id))
        return mapping.get((market, str(product_id)))
    _f.calls = calls
    return _f


# ── 기본 동작 ───────────────────────────────────────────────────────────
def test_등록상품의_카테고리를_되받아_observed_제안을_만든다():
    s = _mem()
    _seed_market_cat(s)
    _seed_model(s, naver_product_id='777')
    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)

    row = s.query(CategoryMapRow).one()
    assert (row.source_id, row.source_path, row.market) == (
        'musinsa', '신발>스니커즈>여성운동화', 'smartstore')
    assert row.market_cat_code == '50000167'
    assert row.market_cat_path == '패션잡화>여성신발>여성운동화'   # 표시용 경로도 채운다
    assert (row.method, row.status, row.confidence) == ('observed', 'suggested', 0.99)
    assert out['scanned'] == 1 and out['mapped'] == 1


def test_소싱처_카테고리_경로가_없으면_맵핑을_만들지_않는다():
    """짝이 반쪽이면 맵핑이 아니다 — 마켓 코드만 알고 소싱처 경로를 모르면 건너뛴다."""
    s = _mem()
    _seed_market_cat(s)
    _seed_model(s, category_path=None, naver_product_id='777')
    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)

    assert s.query(CategoryMapRow).count() == 0
    assert out['skipped_no_source_path'] == 1 and out['mapped'] == 0


def test_마켓_상품ID가_없는_마켓은_아예_조회하지_않는다():
    s = _mem()
    _seed_market_cat(s)
    _seed_model(s, naver_product_id='777')
    f = _fetch({('smartstore', '777'): '50000167'})
    om.build_observed_map(s, f, now=NOW)
    assert f.calls == [('smartstore', '777')]   # 쿠팡·ESM·11번가는 호출조차 안 한다


# ── 사전에 없는 코드는 채택 금지 ────────────────────────────────────────
def test_회수한_코드가_사전에_없으면_채택하지_않는다():
    """confirm 이 400 으로 거부할 코드를 제안으로 박아 넣지 않는다(M2 게이트와 같은 기준)."""
    s = _mem()
    _seed_market_cat(s, code='50000167')
    _seed_model(s, naver_product_id='777')
    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '99999999'}), now=NOW)

    assert s.query(CategoryMapRow).count() == 0
    assert out['skipped_code_unknown'] == 1


def test_사전에서_사라진_코드도_채택하지_않는다():
    s = _mem()
    _seed_market_cat(s, code='50000167', removed=True)
    _seed_model(s, naver_product_id='777')
    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)
    assert s.query(CategoryMapRow).count() == 0
    assert out['skipped_code_unknown'] == 1


def test_마켓이_코드를_안_주면_확인불가로_넘어간다():
    s = _mem()
    _seed_market_cat(s)
    _seed_model(s, naver_product_id='777')
    out = om.build_observed_map(s, _fetch({}), now=NOW)
    assert s.query(CategoryMapRow).count() == 0
    assert out['skipped_code_unknown'] == 1 and out['errors'] == 0


# ── confirmed 불변 (M2 원칙) ────────────────────────────────────────────
def test_확정된_행은_절대_건드리지_않는다():
    s = _mem()
    _seed_market_cat(s, code='50000167')
    _seed_market_cat(s, code='OLD', path='옛>경로')
    _seed_model(s, naver_product_id='777')
    s.add(CategoryMapRow(source_id='musinsa', source_path='신발>스니커즈>여성운동화',
                         market='smartstore', market_cat_code='OLD',
                         market_cat_path='옛>경로', status='confirmed', method='manual'))
    s.commit()

    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)
    row = s.query(CategoryMapRow).one()
    assert (row.market_cat_code, row.status, row.method) == ('OLD', 'confirmed', 'manual')
    assert out['skipped_confirmed'] == 1 and out['mapped'] == 0


def test_재확정필요_행은_코드만_갱신하고_상태는_되돌리지_않는다():
    """re_confirm 을 suggested 로 내리면 「재확정 필요」 표시가 조용히 지워진다(M2 선례)."""
    s = _mem()
    _seed_market_cat(s, code='50000167')
    _seed_model(s, naver_product_id='777')
    s.add(CategoryMapRow(source_id='musinsa', source_path='신발>스니커즈>여성운동화',
                         market='smartstore', market_cat_code='GONE',
                         status='re_confirm', method='name_sim'))
    s.commit()

    om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)
    row = s.query(CategoryMapRow).one()
    assert row.market_cat_code == '50000167'
    assert (row.method, row.status, row.confidence) == ('observed', 're_confirm', 0.99)


# ── 실패 격리 ───────────────────────────────────────────────────────────
def test_한_상품_조회가_실패해도_전체가_멈추지_않는다():
    s = _mem()
    _seed_market_cat(s)
    _seed_model(s, model_code='M1', url='https://musinsa.com/1', naver_product_id='777')
    _seed_model(s, model_code='M2', url='https://musinsa.com/2',
                category_path='가방>백팩', naver_product_id='888')
    _seed_market_cat(s, code='50000200', path='패션잡화>가방>백팩')

    def _f(market, product_id):
        if str(product_id) == '777':
            raise RuntimeError('401 인증 실패')
        return '50000200'

    out = om.build_observed_map(s, _f, now=NOW)
    assert out['errors'] == 1 and out['mapped'] == 1
    assert s.query(CategoryMapRow).one().source_path == '가방>백팩'
    assert out['error_samples'] and '401' in out['error_samples'][0]


def test_같은_상품을_두_소싱처경로가_가리켜도_마켓은_한_번만_부른다():
    """같은 (마켓, 상품ID) 조회 결과는 캐시한다 — 마켓 호출 수백 건을 두 배로 만들지 않는다."""
    s = _mem()
    _seed_market_cat(s)
    s.add(SM.Model(model_code='M1', model_name_raw='t', naver_product_id='777',
                   url_musinsa='https://musinsa.com/1'))
    s.add(SM.BundleSourceUrl(model_code='M1', source_key='ssf', url='https://ssf.com/9'))
    s.add(SRC.SourceProduct(site='musinsa', url='https://musinsa.com/1',
                            category_path='신발>스니커즈>여성운동화'))
    s.add(SRC.SourceProduct(site='ssf', url='https://ssf.com/9', category_path='신발>스니커즈'))
    s.commit()

    f = _fetch({('smartstore', '777'): '50000167'})
    out = om.build_observed_map(s, f, now=NOW)
    assert len(f.calls) == 1                      # 조회는 1회
    assert out['mapped'] == 2                     # 맵핑은 소싱처 경로마다 1건씩
    assert {r.source_id for r in s.query(CategoryMapRow)} == {'musinsa', 'ssf'}


def test_경로_구분자_공백은_소싱처_사전과_같은_방식으로_정규화된다():
    s = _mem()
    _seed_market_cat(s)
    _seed_model(s, category_path=' 신발 > 스니커즈 ', naver_product_id='777')
    om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)
    assert s.query(CategoryMapRow).one().source_path == '신발>스니커즈'


# ── 롯데온 제외 ─────────────────────────────────────────────────────────
def test_롯데온은_회수_대상이_아니다():
    """롯데온 등록은 본보기 상품번호(spdNo) 방식 — 카테고리 코드 개념이 없다."""
    s = _mem()
    _seed_model(s, lotteon_product_id='55555')
    f = _fetch({})
    out = om.build_observed_map(s, f, now=NOW)
    assert f.calls == [] and out['scanned'] == 0
    assert 'lotteon' not in om.MARKET_ID_FIELDS
