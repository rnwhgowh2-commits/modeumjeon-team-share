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
    _seed_market_cat(s, code='50000200', path='패션잡화>가방>백팩')   # 사전 자체는 살아 있다
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


def test_11번가는_상품ID_컬럼이_없어_지금은_한_건도_회수되지_않는다():
    """[2026-07-23 리뷰 C2] `models` 에 eleven11 상품ID 컬럼이 아직 없다 = 늘 None.

    맵핑표에 11번가 칸이 영영 비는 이유가 '조회 실패'가 아니라 '컬럼 미존재'임을 못 박는다.
    컬럼이 생기는 날 이 테스트가 깨지면서 `MARKET_ID_FIELDS` 주석을 갱신하게 만든다.
    """
    assert om.MARKET_ID_FIELDS['eleven11'] == 'eleven11_product_id'
    assert not hasattr(SM.Model, 'eleven11_product_id')

    s = _mem()
    _seed_market_cat(s, market='eleven11', code='19021', path='패션>신발')
    _seed_market_cat(s)                                  # 스스 사전(대조군 — 이쪽은 조회된다)
    _seed_model(s, naver_product_id='777')
    f = _fetch({('eleven11', '777'): '19021'})
    om.build_observed_map(s, f, now=NOW)
    assert [m for m, _ in f.calls] == ['smartstore']   # 11번가는 호출 자체가 없다


# ── [리뷰 C1] URL 조인은 정규화해서 비교한다 ────────────────────────────
def test_붙여넣기_URL에_트래킹_파라미터가_붙어도_소싱처와_짝이_붙는다():
    """SourceProduct.url 은 정규화 저장인데 Model.url_* 은 붙여넣기 원문(NaPm 등)이다.

    문자열 완전일치로 조인하면 짝이 조용히 사라지고 '소싱처 카테고리 없음'으로 집계돼
    **조인 버그가 크롤 미수집으로 위장**된다(조용한 실패). 정규화 후 비교해야 붙는다.
    """
    s = _mem()
    _seed_market_cat(s)
    s.add(SM.Model(model_code='M1', model_name_raw='t', naver_product_id='777',
                   url_musinsa='https://musinsa.com/1?NaPm=abc&utm_source=x'))
    s.add(SRC.SourceProduct(site='musinsa', url='https://musinsa.com/1',
                            category_path='신발>스니커즈>여성운동화'))
    s.commit()

    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)
    assert out['mapped'] == 1 and out['skipped_no_source_path'] == 0
    assert out['unmatched_urls'] == 0
    assert s.query(CategoryMapRow).one().source_id == 'musinsa'


def test_다중URL_BundleSourceUrl_도_정규화해서_붙는다():
    s = _mem()
    _seed_market_cat(s)
    s.add(SM.Model(model_code='M1', model_name_raw='t', naver_product_id='777'))
    s.add(SM.BundleSourceUrl(model_code='M1', source_key='ssf',
                             url='https://ssf.com/9?utm_medium=share'))
    s.add(SRC.SourceProduct(site='ssf', url='https://ssf.com/9', category_path='신발>스니커즈'))
    s.commit()

    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)
    assert out['mapped'] == 1 and out['unmatched_urls'] == 0
    assert s.query(CategoryMapRow).one().source_id == 'ssf'


def test_정규화_후에도_못_붙은_URL은_별도_카운터로_표면화된다():
    """다음에 같은 위장(조인 실패 → '소싱처 카테고리 없음')이 안 생기게 따로 센다."""
    s = _mem()
    _seed_market_cat(s)
    s.add(SM.Model(model_code='M1', model_name_raw='t', naver_product_id='777',
                   url_musinsa='https://musinsa.com/없는상품'))
    s.commit()

    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)
    assert out['unmatched_urls'] == 1
    assert out['skipped_no_source_path'] == 1        # 기존 집계도 그대로(정직)
    assert out['unmatched_url_samples'] and 'musinsa' in out['unmatched_url_samples'][0]


def test_ModelSourceLink_정본_링크로도_짝이_붙는다():
    """URL 이 서로 어긋나도 크롤이 만든 정본 링크(ModelSourceLink)가 있으면 붙는다."""
    s = _mem()
    _seed_market_cat(s)
    s.add(SM.Model(model_code='M1', model_name_raw='t', naver_product_id='777'))
    sp = SRC.SourceProduct(site='musinsa', url='https://musinsa.com/1',
                           category_path='신발>스니커즈>여성운동화')
    s.add(sp)
    s.flush()
    s.add(SRC.ModelSourceLink(model_code='M1', source_product_id=sp.id))
    s.commit()

    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)
    assert out['mapped'] == 1
    assert s.query(CategoryMapRow).one().source_id == 'musinsa'


def test_지워진_소싱처_상품은_경로_사전에_넣지_않는다():
    """[리뷰 M1] deleted_at 이 찍힌 행의 옛 카테고리를 되살려 맵핑하지 않는다."""
    s = _mem()
    _seed_market_cat(s)
    s.add(SM.Model(model_code='M1', model_name_raw='t', naver_product_id='777',
                   url_musinsa='https://musinsa.com/1'))
    s.add(SRC.SourceProduct(site='musinsa', url='https://musinsa.com/1',
                            category_path='신발>스니커즈>여성운동화', deleted_at=NOW))
    s.commit()

    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167'}), now=NOW)
    assert s.query(CategoryMapRow).count() == 0
    assert out['unmatched_urls'] == 1


# ── [리뷰 I1] 충돌은 조용히 승자를 정하지 않는다 ────────────────────────
def _seed_two_models_same_source_path(s):
    """같은 소싱처 카테고리 경로를 쓰는 모델 2개 — 마켓 카테고리는 서로 다르게 관측된다."""
    _seed_market_cat(s, code='50000167', path='패션잡화>여성신발>여성운동화')
    _seed_market_cat(s, code='50000200', path='패션잡화>여성신발>여성구두')
    for code, url, pid in (('M1', 'https://musinsa.com/1', '777'),
                           ('M2', 'https://musinsa.com/2', '888')):
        s.add(SM.Model(model_code=code, model_name_raw='t',
                       naver_product_id=pid, url_musinsa=url))
        s.add(SRC.SourceProduct(site='musinsa', url=url,
                                category_path='신발>스니커즈>여성운동화'))
    s.commit()


def test_같은_키에_다른_코드가_관측되면_채택하지_않고_후보와_샘플로_남긴다():
    s = _mem()
    _seed_two_models_same_source_path(s)
    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167',
                                           ('smartstore', '888'): '50000200'}), now=NOW)

    assert out['conflicts'] == 1 and out['mapped'] == 0
    # 먼저 본 쪽이 조용히 이기는 일이 없다 — 아무 코드도 안 박힌다
    assert s.query(CategoryMapRow).count() == 0
    sample = out['conflict_samples'][0]
    assert (sample['source_path'], sample['market']) == ('신발>스니커즈>여성운동화', 'smartstore')
    assert sorted(sample['codes']) == ['50000167', '50000200']


def test_충돌_전에_이번_실행이_만든_행은_회수된다():
    """쿼리 순서에 따라 먼저 쓰였더라도, 충돌이 드러나면 그 제안은 없던 일이 된다."""
    s = _mem()
    _seed_two_models_same_source_path(s)
    om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167',
                                     ('smartstore', '888'): '50000200'}),
                          now=NOW, commit_every=1)
    assert s.query(CategoryMapRow).count() == 0


def test_충돌이면_기존_제안행은_코드를_안_바꾸고_후보만_기록한다():
    s = _mem()
    _seed_two_models_same_source_path(s)
    s.add(CategoryMapRow(source_id='musinsa', source_path='신발>스니커즈>여성운동화',
                         market='smartstore', market_cat_code='OLD',
                         market_cat_path='옛>경로', status='suggested', method='name_sim',
                         confidence=0.5))
    s.commit()

    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167',
                                           ('smartstore', '888'): '50000200'}),
                                now=NOW, commit_every=1)
    row = s.query(CategoryMapRow).one()
    assert (row.market_cat_code, row.method, row.confidence) == ('OLD', 'name_sim', 0.5)
    assert '50000167' in (row.candidates_json or '')
    assert '50000200' in (row.candidates_json or '')
    assert out['conflicts'] == 1 and out['mapped'] == 0


def test_같은_코드를_여러_모델이_관측하면_충돌이_아니다():
    s = _mem()
    _seed_two_models_same_source_path(s)
    out = om.build_observed_map(s, _fetch({('smartstore', '777'): '50000167',
                                           ('smartstore', '888'): '50000167'}), now=NOW)
    assert out['conflicts'] == 0 and out['mapped'] == 1
    assert s.query(CategoryMapRow).one().market_cat_code == '50000167'


# ── [리뷰 I3] 전량 1회 커밋 금지 — N건마다 커밋 ─────────────────────────
def test_중간에_죽어도_그때까지_회수한_맵핑은_남는다():
    s = _mem()
    _seed_market_cat(s, code='50000167')
    _seed_market_cat(s, code='50000200', path='패션잡화>가방>백팩')
    _seed_model(s, model_code='M1', url='https://musinsa.com/1', naver_product_id='777')
    _seed_model(s, model_code='M2', url='https://musinsa.com/2',
                category_path='가방>백팩', naver_product_id='888')

    def _f(market, product_id):
        if str(product_id) == '888':
            raise KeyboardInterrupt('프로세스 강제 종료')      # 실행이 통째로 죽는 상황
        return '50000167'

    try:
        om.build_observed_map(s, _f, now=NOW, commit_every=1)
    except KeyboardInterrupt:
        pass
    s.rollback()      # 죽은 뒤 새 세션이 보는 것 = 커밋된 것뿐
    assert s.query(CategoryMapRow).count() == 1


# ── [리뷰 I4] 진행률은 시도 단위로 뛴다 ─────────────────────────────────
def test_실패와_스킵에서도_진행률_콜백이_불린다():
    """성공 fetch 에서만 부르면 실패·스킵투성이 실행이 '멈춘 것'으로 오판돼(스테일 회수)
    두 번째 스레드가 떠 마켓을 이중 호출한다."""
    s = _mem()
    _seed_market_cat(s)
    _seed_model(s, model_code='M1', url='https://musinsa.com/1', naver_product_id='777')
    _seed_model(s, model_code='M2', url=None, category_path=None,
                naver_product_id='888')          # 소싱처 경로 없음 → 스킵

    seen = []

    def _f(market, product_id):
        raise RuntimeError('401 인증 실패')       # 전부 실패

    om.build_observed_map(s, _f, now=NOW, on_progress=lambda n: seen.append(n))
    assert seen and seen == sorted(seen)          # 단조 증가
    assert seen[-1] >= 2                          # 실패 1 + 스킵 1 이상은 세어야 한다


# ── [리뷰 I6] 사전이 비면 그 마켓은 조회 자체를 건너뛴다 ────────────────
def test_카테고리_사전이_빈_마켓은_호출하지_않고_사유를_남긴다():
    s = _mem()
    # 스스 사전만 채우고 쿠팡 사전은 비워 둔다
    _seed_market_cat(s, market='smartstore', code='50000167')
    s.add(SM.Model(model_code='M1', model_name_raw='t', naver_product_id='777',
                   coupang_seller_product_id='C777', url_musinsa='https://musinsa.com/1'))
    s.add(SRC.SourceProduct(site='musinsa', url='https://musinsa.com/1',
                            category_path='신발>스니커즈>여성운동화'))
    s.commit()

    f = _fetch({('smartstore', '777'): '50000167', ('coupang', 'C777'): '9999'})
    out = om.build_observed_map(s, f, now=NOW)
    assert [m for m, _ in f.calls] == ['smartstore']      # 쿠팡은 콜을 태우지 않는다
    assert out['skipped_no_dict'] == 1
    assert any('coupang' in n and '사전' in n for n in out['market_notes'])
