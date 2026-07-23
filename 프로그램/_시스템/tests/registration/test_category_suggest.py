"""이름 유사도 후보 — 정확일치 > 리프 부분일치 > 경로 토큰 겹침.
+ 성별 축(2026-07-23 사장님 규칙) — 중립 1순위·같은 성별 2순위·반대 성별 제외.
+ 제안 생성 오케스트레이션(generate_suggestions) — confirmed 불변·쿠팡 앵커·후보0=행없음.
+ N+1 제거(쿼리 수 상수) · bare 스칼라 predict · 사전밖 예측코드 앵커 폐기.
+ 부분일치 오탐(2026-07-23 라이브 'Men' → 도서 'Mentoring & Coaching') — 영문 단어경계·
  한글 짧은 토큰 경계 · 한 마디 경로 제안 금지 · 더는 후보 아닌 옛 제안 정리.
"""
import datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.registration import category_suggest as cs
from lemouton.registration.models import SourceCategory, CategoryMapRow, MarketCategory

_MARKET_LEAVES = [
    {'code': '1', 'name': '여성운동화', 'full_path': '패션잡화>여성신발>여성운동화'},
    {'code': '2', 'name': '운동화', 'full_path': '패션잡화>남성신발>운동화'},
    {'code': '3', 'name': '러닝화', 'full_path': '스포츠>운동화>러닝화'},
    {'code': '4', 'name': '노트북가방', 'full_path': '가방>노트북가방'},
]


def test_정확일치가_1등이고_부분일치가_그_다음이다():
    # 소스 경로에 성별이 없어야 순수 점수 순서를 본다(성별이 있으면 성별 축이 점수보다
    # 앞선다 — 아래 성별 규칙 테스트들이 그 쪽을 담당).
    ranked = cs.rank_candidates('패션>운동화', _MARKET_LEAVES, top=3)
    assert [r['code'] for r in ranked][:2] == ['2', '1']
    assert ranked[0]['score'] > ranked[1]['score']


def test_리프명이_없으면_경로_토큰_겹침으로라도_찾는다():
    ranked = cs.rank_candidates('스포츠>운동화>트레일화', _MARKET_LEAVES, top=3)
    assert ranked and ranked[0]['code'] in ('3', '2')   # '운동화' 토큰 겹침


def test_아무것도_안_겹치면_빈_리스트다():
    assert cs.rank_candidates('식품>과일>사과', _MARKET_LEAVES, top=3) == []


# ── 성별 축 (2026-07-23 사장님 규칙 · 라이브 오제안 회귀) ────────────────────
# 라이브 실측: 소싱처 '슈즈/운동화>여성신발>스니커즈' 에 11번가 '남성신발>스니커즈',
# 스스 '패션잡화>남성신발>스니커즈/운동화', 옥션 '브랜드 잡화>남성화>로퍼' 가 1등으로
# 제안됐다 — 맨 끝 리프명만 비교해 앞마디의 '여성/남성' 을 통째로 무시했기 때문.
# 규칙 ①중립 1순위 ②같은 성별 2순위 ③반대 성별은 제안하지 않는다(후보 0개면 행 없음).

_SHOE_LEAVES = [
    {'code': '1011575', 'name': '스니커즈', 'full_path': '패션의류>남성신발>스니커즈'},
    {'code': 'F1', 'name': '스니커즈', 'full_path': '패션의류>여성신발>스니커즈'},
    {'code': 'N1', 'name': '스니커즈/운동화', 'full_path': '패션잡화>신발>스니커즈/운동화'},
]


def test_여성_소스는_중립후보가_1등이고_남성후보는_아예_빠진다():
    ranked = cs.rank_candidates('슈즈/운동화>여성신발>스니커즈', _SHOE_LEAVES, top=3)
    codes = [r['code'] for r in ranked]
    assert codes[0] == 'N1'                 # 중립이 1순위 — 점수(0.7)가 낮아도 성별이 앞선다
    assert '1011575' not in codes           # 반대 성별(남성)은 후보에서 제거
    assert codes == ['N1', 'F1']
    assert ranked[0]['gender_vs_source'] == 'neutral'
    assert ranked[1]['gender_vs_source'] == 'same'
    assert ranked[0]['score'] < ranked[1]['score']   # 점수는 낮지만 성별 축이 이긴다


def test_중립후보가_없으면_같은_성별이_1등이고_반대성별은_없다():
    leaves = [c for c in _SHOE_LEAVES if c['code'] != 'N1']
    ranked = cs.rank_candidates('슈즈/운동화>여성신발>스니커즈', leaves, top=3)
    assert [r['code'] for r in ranked] == ['F1']
    assert ranked[0]['gender_vs_source'] == 'same'


def test_남성_소스는_남성이_1등이고_여성후보는_없다():
    leaves = [c for c in _SHOE_LEAVES if c['code'] != 'N1']
    ranked = cs.rank_candidates('슈즈/운동화>남성신발>스니커즈', leaves, top=3)
    assert [r['code'] for r in ranked] == ['1011575']
    assert ranked[0]['gender_vs_source'] == 'same'


def test_옥션_여성플랫로퍼가_남성화_로퍼로_가지_않는다():
    """라이브 오제안 회귀 — 소스 '여성신발>플랫/로퍼' → 옥션 '브랜드 잡화>남성화>로퍼'."""
    leaves = [
        {'code': 'A_M', 'name': '로퍼', 'full_path': '브랜드 잡화>남성화>로퍼'},
        {'code': 'A_W', 'name': '로퍼', 'full_path': '브랜드 잡화>여성화>로퍼'},
    ]
    ranked = cs.rank_candidates('슈즈/운동화>여성신발>플랫/로퍼', leaves, top=3)
    assert [r['code'] for r in ranked] == ['A_W']


def test_소스에_성별이_없으면_성별필터가_걸리지_않는다():
    ranked = cs.rank_candidates('신발>스니커즈', _SHOE_LEAVES, top=3)
    codes = [r['code'] for r in ranked]
    assert set(codes) == {'1011575', 'F1', 'N1'}     # 남성·여성 모두 살아 있다
    assert all(r['gender_vs_source'] == 'none' for r in ranked)


def test_소스에_성별이_없으면_중립후보를_깎지도_않는다():
    """규칙 ④ — 성별 없는 소스에서 중립을 굳이 우대(또는 강등)하지 않는다: 점수 순서 그대로."""
    ranked = cs.rank_candidates('신발>스니커즈', _SHOE_LEAVES, top=3)
    assert ranked[0]['score'] == 1.0                  # 정확일치(남성·여성)가 0.7 중립보다 앞
    assert ranked[-1]['code'] == 'N1'


def test_공용_유니섹스는_중립으로_본다():
    leaves = [
        {'code': 'U1', 'name': '스니커즈', 'full_path': '신발>남녀공용>스니커즈'},
        {'code': 'U2', 'name': '스니커즈', 'full_path': '신발>유니섹스>스니커즈'},
        {'code': 'U3', 'name': '스니커즈', 'full_path': '슈즈>UNISEX>스니커즈'},
        {'code': 'M1', 'name': '스니커즈', 'full_path': '신발>남성화>스니커즈'},
    ]
    ranked = cs.rank_candidates('슈즈/운동화>여성신발>스니커즈', leaves, top=4)
    codes = [r['code'] for r in ranked]
    assert 'M1' not in codes                          # 남성은 제외
    assert set(codes) == {'U1', 'U2', 'U3'}
    assert all(r['gender_vs_source'] == 'neutral' for r in ranked)


def test_영문_WOMEN_MEN_도_성별로_읽는다():
    leaves = [
        {'code': 'E_M', 'name': 'SNEAKERS', 'full_path': 'SHOES>MEN>SNEAKERS'},
        {'code': 'E_W', 'name': 'SNEAKERS', 'full_path': 'SHOES>WOMEN>SNEAKERS'},
    ]
    # 'WOMEN' 안에 'MEN' 이 통째로 들어 있다 — 단순 포함검사면 여성 경로가 남성으로도
    # 읽혀 판정이 무너진다. 단어경계(\b)로 봐야 한다.
    ranked = cs.rank_candidates('WOMEN>SHOES>SNEAKERS', leaves, top=3)
    assert [r['code'] for r in ranked] == ['E_W']


def test_맨투맨은_남성으로_오탐하지_않는다():
    """'맨' 포함검사는 '맨투맨'(스스·옥션 실제 카테고리)을 남성으로 잘못 읽는다."""
    assert cs._gender_of('여성의류>맨투맨/후드티') == 'female'
    assert cs._gender_of('의류>맨투맨') is None
    assert cs._gender_of('의류>맨즈>티셔츠') == 'male'


def test_성별표지가_한_경로에_둘_다_있으면_중립으로_본다():
    assert cs._gender_of('신발>남성/여성>스니커즈') is None


# ── 연령 축(유아동) — 성별과 같은 방식으로 반대는 제외 ──────────────────────

def test_성인_소스는_유아동_후보를_제안하지_않는다():
    leaves = [
        {'code': 'K1', 'name': '운동화', 'full_path': '유아동>아동화>운동화'},
        {'code': 'W1', 'name': '운동화', 'full_path': '패션잡화>여성신발>운동화'},
    ]
    ranked = cs.rank_candidates('슈즈/운동화>여성신발>운동화', leaves, top=3)
    assert [r['code'] for r in ranked] == ['W1']


def test_유아동_소스는_유아동_후보가_1등이고_성인_후보는_빠진다():
    leaves = [
        {'code': 'K1', 'name': '운동화', 'full_path': '유아동>키즈신발>운동화'},
        {'code': 'W1', 'name': '운동화', 'full_path': '패션잡화>여성신발>운동화'},
        {'code': 'N1', 'name': '운동화', 'full_path': '패션잡화>신발>운동화'},
    ]
    ranked = cs.rank_candidates('키즈>주니어신발>운동화', leaves, top=3)
    codes = [r['code'] for r in ranked]
    assert codes[0] == 'K1'          # 같은 연령축이 먼저
    assert 'W1' not in codes         # 성인(성별표지) 후보는 제외
    assert codes == ['K1', 'N1']     # 연령 미표기(중립)는 남되 뒤로


# ── generate_suggestions ────────────────────────────────────────────────
# 공유 Supabase 를 안 쓴다 — Task 1(test_category_map_models.py)과 같은 패턴으로
# 매 테스트 완전히 새 sqlite 인메모리 DB 를 쓴다(시드 정리 불필요·격리 완전).

def _mem():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _seed_source(s, source_id='musinsa', path='신발>스니커즈>여성운동화',
                 leaf_name='여성운동화'):
    s.add(SourceCategory(source_id=source_id, path=path, leaf_name=leaf_name,
                         depth=3, first_seen_at=datetime.datetime(2026, 7, 23)))
    s.commit()


def _seed_market_leaves(s, name='여성운동화'):
    """6마켓 전부에 이름이 정확히 같은 리프 카테고리를 1개씩 심는다(정확일치 score=1.0).

    코드는 market[:2]+순번 이라 마켓별로 고유하고 예측 가능하다(smartstore→'sm1' ...).
    """
    harvested = datetime.datetime(2026, 7, 22)
    for i, market in enumerate(cs.MARKETS, start=1):
        s.add(MarketCategory(market=market, code=f'{market[:2]}{i}', name=name,
                             full_path=f'패션잡화>운동화>{name}', depth=3, is_leaf=True,
                             harvested_at=harvested))
    s.commit()


def test_제안생성은_confirmed_행을_건드리지_않고_suggested만_갱신한다():
    s = _mem()
    _seed_source(s)
    _seed_market_leaves(s)
    # lotteon 은 이미 confirmed 로 미리 존재 — generate_suggestions 후에도 절대 불변이어야 한다
    s.add(CategoryMapRow(source_id='musinsa', source_path='신발>스니커즈>여성운동화',
                         market='lotteon', market_cat_code='OLD_CODE',
                         market_cat_path='OLD>PATH', status='confirmed', method='manual',
                         confirmed_at=datetime.datetime(2026, 7, 20)))
    # 쿠팡 예측코드 '777' 이 로컬 사전(market_categories)에 실재해야 앵커가 채택된다
    # (Important 2 — 사전에 없는 예측코드는 폐기되므로, 앵커 성공 시나리오는 미리 심어야 한다).
    s.add(MarketCategory(market='coupang', code='777', name='여성운동화(쿠팡추천)',
                         full_path='패션잡화>여성신발>여성운동화(쿠팡추천)', depth=3, is_leaf=True,
                         harvested_at=datetime.datetime(2026, 7, 22)))
    s.commit()

    result = cs.generate_suggestions(
        s, 'musinsa',
        coupang_predict=lambda name, brand: {'result': 'SUCCESS', 'predictedCategoryId': '777'})

    # [2026-07-23 I3] lotteon 은 이제 아예 순회 대상이 아니다(카테고리 맵핑 대상 제외) —
    # 5마켓만 새로 생성되고, skipped_confirmed 는 0(lotteon 은 순회조차 안 하므로 "건너뜀"
    # 집계 자체가 안 잡힌다 — 그래도 아래에서 confirmed 행이 안 건드려졌음은 그대로 확인한다).
    assert result == {'sources': 1, 'suggested': 5, 'skipped_confirmed': 0, 'cleared': 0,
                      'skipped_shallow': 0}

    lotteon_row = s.query(CategoryMapRow).filter_by(market='lotteon').one()
    assert lotteon_row.status == 'confirmed'
    assert lotteon_row.market_cat_code == 'OLD_CODE'
    assert lotteon_row.market_cat_path == 'OLD>PATH'

    coupang_row = s.query(CategoryMapRow).filter_by(market='coupang').one()
    assert coupang_row.status == 'suggested'
    assert coupang_row.method == 'coupang_reco'
    assert coupang_row.market_cat_code == '777'
    assert coupang_row.confidence == 0.95

    smartstore_row = s.query(CategoryMapRow).filter_by(market='smartstore').one()
    assert smartstore_row.status == 'suggested'
    assert smartstore_row.method == 'name_sim'
    assert smartstore_row.confidence == 1.0
    assert smartstore_row.market_cat_code == 'sm1'

    for market in ('auction', 'gmarket', 'eleven11'):
        assert s.query(CategoryMapRow).filter_by(market=market).count() == 1


def test_쿠팡_predict_FAILURE면_쿠팡_제안을_만들지_않는다():
    s = _mem()
    _seed_source(s)
    _seed_market_leaves(s)

    result = cs.generate_suggestions(
        s, 'musinsa',
        coupang_predict=lambda name, brand: {'result': 'FAILURE'})

    coupang_row = s.query(CategoryMapRow).filter_by(market='coupang').one()
    assert coupang_row.method == 'name_sim'          # coupang_reco 아님
    assert coupang_row.confidence == 1.0              # 0.95(쿠팡 앵커) 아님, 이름유사도 1.0
    assert coupang_row.market_cat_code != '777'
    assert result['suggested'] == 5                   # lotteon 제외 5마켓 이름유사도로 생성됨
    assert result['skipped_confirmed'] == 0


def test_쿠팡_predict_미주입이면_이름유사도만_사용한다():
    s = _mem()
    _seed_source(s)
    _seed_market_leaves(s)

    result = cs.generate_suggestions(s, 'musinsa')  # coupang_predict 생략

    coupang_row = s.query(CategoryMapRow).filter_by(market='coupang').one()
    assert coupang_row.method == 'name_sim'
    assert result['suggested'] == 5
    assert result['skipped_confirmed'] == 0


def test_후보가_0개면_행을_만들지도_기존행을_건드리지도_않는다():
    s = _mem()
    # market_categories 를 아예 안 심는다 — 어떤 마켓도 후보를 못 낸다
    _seed_source(s, path='식품>과일>사과', leaf_name='사과')

    result = cs.generate_suggestions(s, 'musinsa')

    assert s.query(CategoryMapRow).count() == 0
    assert result == {'sources': 1, 'suggested': 0, 'skipped_confirmed': 0, 'cleared': 0,
                      'skipped_shallow': 0}


# ── Critical: N+1 제거 — 쿼리 수가 소스 경로 수와 무관(상수)임을 증명 ──────────
# market_categories 를 아예 비워 두면(후보 0개) generate_suggestions 가 어떤
# CategoryMapRow 도 INSERT 하지 않는다 — SELECT 만 남아 "읽기 쿼리 수" 를 그대로
# 비교할 수 있다(쓰기 건수는 결과 행 수에 비례하는 게 당연하므로 대상이 아니다).

def _mem_engine():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    return eng


def _count_select_queries(engine, n_paths):
    session = sessionmaker(bind=engine)()
    for i in range(n_paths):
        session.add(SourceCategory(source_id='musinsa', path=f'식품>과일>사과{i}',
                                   leaf_name=f'사과{i}', depth=3,
                                   first_seen_at=datetime.datetime(2026, 7, 23)))
    session.commit()

    counter = {'n': 0}

    @event.listens_for(engine, 'before_cursor_execute')
    def _count(conn, cursor, statement, parameters, context, executemany):
        counter['n'] += 1

    result = cs.generate_suggestions(session, 'musinsa')
    event.remove(engine, 'before_cursor_execute', _count)

    assert result['suggested'] == 0   # market_categories 가 비어 있어 후보 0개 — 쓰기 없음
    return counter['n']


def test_제안생성_쿼리수는_소스경로_개수와_무관하게_상수다():
    n_at_10 = _count_select_queries(_mem_engine(), 10)
    n_at_100 = _count_select_queries(_mem_engine(), 100)
    assert n_at_10 == n_at_100
    # 참고: sources(1) + market_categories 마켓별 1회(5, lotteon 제외) + category_map 전체 1회(1) = 7
    assert n_at_10 == 7


# ── Important 1: bare 스칼라 predict(실래퍼 그대로) — int|None 분기 미테스트 보완 ──

def test_쿠팡_predict가_bare_int이지만_사전에_없으면_앵커를_폐기한다():
    s = _mem()
    _seed_source(s)
    _seed_market_leaves(s)

    result = cs.generate_suggestions(s, 'musinsa', coupang_predict=lambda **kw: 12345)

    coupang_row = s.query(CategoryMapRow).filter_by(market='coupang').one()
    assert coupang_row.method == 'name_sim'          # 12345 는 로컬 사전에 없는 코드 — 앵커 폐기
    assert result['suggested'] == 5


def test_쿠팡_predict가_bare_int이고_사전에_있으면_앵커로_쓴다():
    s = _mem()
    _seed_source(s)
    _seed_market_leaves(s)   # coupang 코드는 'co2' 하나뿐 (index 2 = coupang)
    # bare int 예측코드가 로컬 사전에 실재하는 케이스 — int 그대로(문자열 아님) 넘어와도
    # str() 변환 후 정상 매치돼 앵커로 채택돼야 한다(폐기되면 안 된다).
    s.add(MarketCategory(market='coupang', code='555', name='여성운동화(쿠팡추천)',
                         full_path='패션잡화>여성신발>여성운동화(쿠팡추천)', depth=3, is_leaf=True,
                         harvested_at=datetime.datetime(2026, 7, 22)))
    s.commit()

    result = cs.generate_suggestions(s, 'musinsa', coupang_predict=lambda **kw: 555)

    coupang_row = s.query(CategoryMapRow).filter_by(market='coupang').one()
    assert coupang_row.method == 'coupang_reco'
    assert coupang_row.market_cat_code == '555'
    assert coupang_row.confidence == 0.95
    assert result['suggested'] == 5


def test_쿠팡_predict가_bare_None을_돌려주면_이름유사도만_쓴다():
    s = _mem()
    _seed_source(s)
    _seed_market_leaves(s)

    result = cs.generate_suggestions(s, 'musinsa', coupang_predict=lambda **kw: None)

    coupang_row = s.query(CategoryMapRow).filter_by(market='coupang').one()
    assert coupang_row.method == 'name_sim'
    assert result['suggested'] == 5


# ── Important 2: 예측코드가 로컬 사전(market_categories)에 없으면 앵커를 버린다 ──
# (확정 게이트가 400 으로 거부할 코드를 1등 제안으로 주는 게 문제 — bare int 케이스와
#  달리, 여기서는 코드가 실제로 존재하는 마켓 리프 코드 하나를 더 심어 "정확히 그 코드가
#  로컬 사전에 없을 때만" 앵커가 빠진다는 걸 구분해 증명한다)

def test_쿠팡_예측코드가_로컬_market_categories에_없으면_앵커를_버리고_이름유사도만_쓴다():
    s = _mem()
    _seed_source(s)
    _seed_market_leaves(s)   # coupang 코드는 'co2' 하나뿐 (index 2 = coupang)

    result = cs.generate_suggestions(
        s, 'musinsa',
        coupang_predict=lambda **kw: {'result': 'SUCCESS', 'predictedCategoryId': 'NOT_IN_DICT'})

    coupang_row = s.query(CategoryMapRow).filter_by(market='coupang').one()
    assert coupang_row.method == 'name_sim'
    assert coupang_row.market_cat_code != 'NOT_IN_DICT'
    assert coupang_row.market_cat_code == 'co2'       # 이름유사도 1등 후보(정확일치)로 대체
    assert result['suggested'] == 5


# ── I3: 롯데온은 카테고리 맵핑 대상이 아니다(spdNo 로 등록 — 2026-07-23 리뷰 수정) ──

def test_롯데온은_기존_맵핑이_없어도_제안이_생성되지_않는다():
    """I3-1 — confirmed 로 미리 존재하던 이전 테스트와 달리, lotteon 카테고리 리프가
    사전에 있고 confirmed 행조차 없어도(완전 신규) 제안 자체가 만들어지지 않는다 —
    SUGGESTION_MARKETS 에서 아예 빠졌기 때문이다."""
    s = _mem()
    _seed_source(s)
    _seed_market_leaves(s)   # lotteon 리프도 심어지지만(cs.MARKETS 기준) 사용되지 않아야 한다

    result = cs.generate_suggestions(s, 'musinsa')

    assert result['suggested'] == 5
    assert s.query(CategoryMapRow).filter_by(market='lotteon').count() == 0
    assert 'lotteon' not in cs.SUGGESTION_MARKETS
    assert 'lotteon' in cs.MARKETS   # 다른 용도(브랜드제한 market 검증)엔 여전히 6마켓


# ── 성별 규칙이 제안 생성 전체에 걸리는지 (라이브 오제안 정리 포함) ────────────

def _seed_gendered_leaves(s):
    """5마켓 각각에 남성·여성 리프를 하나씩 심는다 — 중립 후보는 없다."""
    harvested = datetime.datetime(2026, 7, 22)
    for market in cs.SUGGESTION_MARKETS:
        s.add(MarketCategory(market=market, code=f'{market}_M', name='스니커즈',
                             full_path='패션의류>남성신발>스니커즈', depth=3, is_leaf=True,
                             harvested_at=harvested))
        s.add(MarketCategory(market=market, code=f'{market}_W', name='스니커즈',
                             full_path='패션의류>여성신발>스니커즈', depth=3, is_leaf=True,
                             harvested_at=harvested))
    s.commit()


def test_제안생성도_반대성별을_1등으로_올리지_않는다():
    s = _mem()
    _seed_source(s, path='슈즈/운동화>여성신발>스니커즈', leaf_name='스니커즈')
    _seed_gendered_leaves(s)

    result = cs.generate_suggestions(s, 'musinsa')

    assert result['suggested'] == 5
    for row in s.query(CategoryMapRow).all():
        assert row.market_cat_code.endswith('_W')
        assert '남성' not in (row.market_cat_path or '')


def test_쿠팡_앵커도_반대성별이면_버린다():
    """쿠팡 추천은 리프명('스니커즈')만 보고 오므로 남성 카테고리를 돌려줄 수 있다."""
    s = _mem()
    _seed_source(s, path='슈즈/운동화>여성신발>스니커즈', leaf_name='스니커즈')
    _seed_gendered_leaves(s)

    result = cs.generate_suggestions(
        s, 'musinsa',
        coupang_predict=lambda **kw: {'result': 'SUCCESS', 'predictedCategoryId': 'coupang_M'})

    coupang_row = s.query(CategoryMapRow).filter_by(market='coupang').one()
    assert coupang_row.method == 'name_sim'          # 앵커 폐기
    assert coupang_row.market_cat_code == 'coupang_W'
    assert result['suggested'] == 5


def test_후보가_0개가_돼도_반대성별로_남은_제안은_걷어낸다():
    """새 규칙으로 후보가 0개면 갱신이 안 걸린다 — 그대로 두면 틀린 제안이 계속 1등이다.

    suggested(제안) 만 지운다. confirmed 는 손대지 않고, re_confirm 은 「다시 골라야 함」
    신호라 남긴다.
    """
    s = _mem()
    _seed_source(s, path='슈즈/운동화>여성신발>스니커즈', leaf_name='스니커즈')
    # 사전에는 남성 리프만 있다 → 여성 소스 기준 후보 0개
    harvested = datetime.datetime(2026, 7, 22)
    for market in cs.SUGGESTION_MARKETS:
        s.add(MarketCategory(market=market, code=f'{market}_M', name='스니커즈',
                             full_path='패션의류>남성신발>스니커즈', depth=3, is_leaf=True,
                             harvested_at=harvested))
    # 예전 규칙이 만들어 둔 반대 성별 제안들
    s.add(CategoryMapRow(source_id='musinsa', source_path='슈즈/운동화>여성신발>스니커즈',
                         market='eleven11', market_cat_code='1011575',
                         market_cat_path='패션의류>남성신발>스니커즈', status='suggested',
                         method='name_sim', confidence=1.0))
    s.add(CategoryMapRow(source_id='musinsa', source_path='슈즈/운동화>여성신발>스니커즈',
                         market='auction', market_cat_code='A_M',
                         market_cat_path='브랜드 잡화>남성화>스니커즈', status='re_confirm',
                         method='name_sim', confidence=1.0))
    s.add(CategoryMapRow(source_id='musinsa', source_path='슈즈/운동화>여성신발>스니커즈',
                         market='gmarket', market_cat_code='G_M',
                         market_cat_path='패션의류>남성신발>스니커즈', status='confirmed',
                         method='manual', confirmed_at=datetime.datetime(2026, 7, 20)))
    s.commit()

    result = cs.generate_suggestions(s, 'musinsa')

    assert result['suggested'] == 0
    assert result['cleared'] == 1
    assert s.query(CategoryMapRow).filter_by(market='eleven11').count() == 0   # 제안=삭제
    assert s.query(CategoryMapRow).filter_by(market='auction').one().status == 're_confirm'
    confirmed = s.query(CategoryMapRow).filter_by(market='gmarket').one()
    assert confirmed.status == 'confirmed' and confirmed.market_cat_code == 'G_M'


# ── 2026-07-23 라이브 오제안 회귀 — 짧은 단어 부분일치 오탐 ('Men' → 도서) ──────
# 라이브 응답 원문(르무통):
#   source_path='Men', market='coupang', confidence=0.7,
#   market_cat_path='도서>외국도서>BUSINESS & ECONOMICS>Mentoring & Coaching',
#   candidates=['Mentoring & Coaching', 'Teacher & Student Mentoring', 'Amish & Mennonite']
# 원인은 부분일치가 맨 포함검사(`leaf in name`)라 'Men' ⊂ 'Mentoring' 이 걸린 것.

_BOOK_LEAVES = [
    {'code': '92762', 'name': 'Mentoring & Coaching',
     'full_path': '도서>외국도서>BUSINESS & ECONOMICS>Mentoring & Coaching'},
    {'code': '92763', 'name': 'Teacher & Student Mentoring',
     'full_path': '도서>외국도서>EDUCATION>Teacher & Student Mentoring'},
    {'code': '92764', 'name': 'Amish & Mennonite',
     'full_path': '도서>외국도서>RELIGION>Amish & Mennonite'},
]


def test_Men은_Mentoring류_도서카테고리와_부분일치하지_않는다():
    assert cs.rank_candidates('Men', _BOOK_LEAVES, top=3) == []
    assert cs.rank_candidates('Men>클래식', _BOOK_LEAVES, top=3) == []


def test_영문_부분일치는_단어경계에서만_성립한다():
    assert cs._partial_match('Men', 'Mentoring & Coaching') is False
    assert cs._partial_match('Men', 'Amish & Mennonite') is False
    assert cs._partial_match('Men', "Men's Shoes") is True      # 따옴표가 경계
    assert cs._partial_match('men', 'MENS SNEAKERS') is True    # 대소문자 무시·복수형
    assert cs._partial_match('Bag', 'Bags') is True             # 복수형 s 만 덤으로 허용
    assert cs._partial_match('Bag', 'Baggage') is False


def test_한글_부분일치는_3자부터_포함만으로_성립하고_2자는_경계를_요구한다():
    # 한글은 붙여쓰기 합성어가 정상이라 3자 이상이면 포함만으로 뜻이 이어진다.
    assert cs._partial_match('운동화', '여성운동화') is True
    assert cs._partial_match('스니커즈', '스니커즈/운동화') is True
    # 2자 이하는 다른 말에 통째로 끼는 일이 흔하다 → 경계가 있어야만 인정.
    assert cs._partial_match('가방', '가방걸이') is False
    assert cs._partial_match('반지', '반지갑') is False
    assert cs._partial_match('로퍼', '플랫/로퍼') is True        # 앞이 '/' 라 경계 있음


def test_정상케이스는_그대로_통과한다_여성신발_스니커즈():
    """회귀 가드 — 오탐을 막느라 멀쩡한 제안까지 죽이지 않았는지."""
    ranked = cs.rank_candidates('여성신발>스니커즈', _SHOE_LEAVES + _BOOK_LEAVES, top=3)
    codes = [r['code'] for r in ranked]
    assert codes == ['N1', 'F1']            # 중립 1순위 · 같은 성별 2순위
    assert '1011575' not in codes           # 반대 성별 제외
    assert not any(c.startswith('927') for c in codes)   # 도서는 아예 안 걸린다


def test_Men은_남성으로_읽히고_후보행에_소스판정이_함께_실린다():
    """B — 성별 규칙은 'Men' 에 **제대로 걸렸다**(male). 라이브 응답의 "gender":"neutral"
    은 소스 판정이 아니라 **도서 후보가 성별 미표기**라는 뜻이었고, 그 이름 때문에 원인
    진단이 한 번 틀어졌다. 그래서 무엇과 견준 값인지 이름에 박고 소스 판정도 같이 싣는다.
    """
    assert cs._gender_of('Men') == 'male'
    assert cs._gender_of('men') == 'male'
    assert cs._gender_of('MENS') == 'male'
    assert cs._axes('Men') == ('male', 'adult')

    # 르무통 빵부스러기가 cate_no 따라 두 마디로 나오는 실제 모양 'Men>클래식'.
    leaves = [{'code': 'N', 'name': '클래식', 'full_path': '패션의류>클래식'}]
    ranked = cs.rank_candidates('Men>클래식', leaves, top=1)
    assert ranked[0]['source_gender'] == 'male'       # 소스 자체 판정 — 오해 불가
    assert ranked[0]['source_age'] == 'adult'
    assert ranked[0]['gender_vs_source'] == 'neutral'  # 후보(패션잡화>Men)가 미표기라는 뜻
    assert 'gender' not in ranked[0] and 'age' not in ranked[0]


def test_한마디_소스경로는_제안을_만들지_않는다():
    """'Men' 처럼 한 마디뿐인 경로(Cafe24 빵부스러기가 cate_no 따라 잘린 것)는
    정보량이 리프 이름 하나뿐이라 억지 제안보다 '없음'이 낫다."""
    s = _mem()
    _seed_source(s, path='Men', leaf_name='Men')
    harvested = datetime.datetime(2026, 7, 22)
    for market in cs.SUGGESTION_MARKETS:
        # 이름이 정확일치라 옛 규칙이면 1.0 으로 제안이 만들어졌을 후보
        s.add(MarketCategory(market=market, code=f'{market}_MEN', name='Men',
                             full_path='패션의류>Men', depth=2, is_leaf=True,
                             harvested_at=harvested))
    s.commit()

    result = cs.generate_suggestions(s, 'musinsa')

    assert result['suggested'] == 0
    assert result['skipped_shallow'] == 1
    assert s.query(CategoryMapRow).count() == 0


def test_한마디_경로의_confirmed_맵핑은_그대로_살아있다():
    """제안을 안 만드는 규칙이지 맵핑을 금지하는 규칙이 아니다 — 확정본은 불변."""
    s = _mem()
    _seed_source(s, path='Men', leaf_name='Men')
    s.add(CategoryMapRow(source_id='musinsa', source_path='Men', market='coupang',
                         market_cat_code='OK', market_cat_path='패션의류>남성의류>티셔츠',
                         status='confirmed', method='manual',
                         confirmed_at=datetime.datetime(2026, 7, 20)))
    s.commit()

    result = cs.generate_suggestions(s, 'musinsa')

    assert result['skipped_shallow'] == 1
    row = s.query(CategoryMapRow).filter_by(market='coupang').one()
    assert row.status == 'confirmed' and row.market_cat_code == 'OK'


def test_한마디_경로에_남은_옛_제안은_정확일치라도_걷어낸다():
    """라이브 정리 — 한 마디 경로의 **제안은 전부** 걷어낸다(2026-07-23 실측으로 판단 뒤집힘).

    처음엔 「지금도 후보로 성립하면 남긴다」로 짰는데, 라이브에 남은 것이
    'Women' → '도서>외국도서>BIOGRAPHY & AUTOBIOGRAPHY>Women' **확신도 1.0** 이었다.
    한 마디 영문은 패션 리프와 도서 리프에 **똑같이 정확일치**해서 고를 근거가 없다.
    남겨 두면 사장님 화면에 100% 짜리 도서 카테고리가 1등으로 뜬다 — 그대로 확정될 수 있다.

    「한 마디는 제안할 근거가 없다」고 정한 이상 이미 있는 제안도 근거가 없기는 같다.
    확정본(confirmed)과 re_confirm 은 사장님 판단이라 손대지 않는다.
    """
    s = _mem()
    _seed_source(s, path='Men', leaf_name='Men')
    s.add(CategoryMapRow(source_id='musinsa', source_path='Men', market='coupang',
                         market_cat_code='92762',
                         market_cat_path='도서>외국도서>BUSINESS & ECONOMICS>Mentoring & Coaching',
                         status='suggested', method='name_sim', confidence=0.7))
    s.add(CategoryMapRow(source_id='musinsa', source_path='Men', market='smartstore',
                         market_cat_code='S_MEN', market_cat_path='패션의류>Men',
                         status='suggested', method='name_sim', confidence=1.0))
    s.add(CategoryMapRow(source_id='musinsa', source_path='Men', market='auction',
                         market_cat_code='92762',
                         market_cat_path='도서>외국도서>BUSINESS & ECONOMICS>Mentoring & Coaching',
                         status='re_confirm', method='name_sim', confidence=0.7))
    s.commit()

    result = cs.generate_suggestions(s, 'musinsa')

    assert result['skipped_shallow'] == 1
    assert result['cleared'] == 2
    assert s.query(CategoryMapRow).filter_by(market='coupang').count() == 0   # 오제안 삭제
    # 정확일치여도 한 마디 경로면 고를 근거가 없다 — 같이 걷어낸다
    assert s.query(CategoryMapRow).filter_by(market='smartstore').count() == 0
    # re_confirm 은 「다시 골라야 함」 신호라 남긴다
    assert s.query(CategoryMapRow).filter_by(market='auction').one().status == 're_confirm'


def test_이름이_말단위로_안맞게_된_옛제안도_걷어낸다():
    """성별이 아니라 **이름 규칙** 때문에 후보가 0개가 된 경우도 정리 대상이다.

    (기존 cleared 는 is_opposite_axis 로 성별·연령 반대만 걷어내서 'Men'→도서 같은
     이름 오탐은 계속 남았다.)"""
    s = _mem()
    _seed_source(s, path='의류>Men', leaf_name='Men')     # 두 마디 — 제안 대상은 맞다
    s.add(CategoryMapRow(source_id='musinsa', source_path='의류>Men', market='coupang',
                         market_cat_code='92762',
                         market_cat_path='도서>외국도서>BUSINESS & ECONOMICS>Mentoring & Coaching',
                         status='suggested', method='name_sim', confidence=0.7))
    s.commit()

    result = cs.generate_suggestions(s, 'musinsa')   # market_categories 비어 후보 0개

    assert result['skipped_shallow'] == 0
    assert result['cleared'] == 1
    assert s.query(CategoryMapRow).count() == 0


def test_쿠팡앵커로_만든_제안은_이름이_안맞아도_걷어내지_않는다():
    """앵커는 쿠팡 API 가 준 외부 신호다 — 우리 이름 규칙으로 틀렸다고 단정할 수 없다.

    다만 성별·연령이 **반대**면 그건 어디서 왔든 틀렸으므로 걷어낸다.
    """
    s = _mem()
    _seed_source(s, path='슈즈>여성신발>스니커즈', leaf_name='스니커즈')
    s.add(CategoryMapRow(source_id='musinsa', source_path='슈즈>여성신발>스니커즈',
                         market='coupang', market_cat_code='C1',
                         market_cat_path='패션잡화>신발>캔버스화',   # 이름은 안 맞는다
                         status='suggested', method='coupang_reco', confidence=0.95))
    s.add(CategoryMapRow(source_id='musinsa', source_path='슈즈>여성신발>스니커즈',
                         market='smartstore', market_cat_code='C2',
                         market_cat_path='패션잡화>남성신발>캔버스화',  # 반대 성별
                         status='suggested', method='coupang_reco', confidence=0.95))
    s.commit()

    result = cs.generate_suggestions(s, 'musinsa')

    assert result['cleared'] == 1
    assert s.query(CategoryMapRow).filter_by(market='coupang').one().market_cat_code == 'C1'
    assert s.query(CategoryMapRow).filter_by(market='smartstore').count() == 0


def test_후보가_0개여도_성별이_맞는_기존제안은_남긴다():
    """사전이 비어 후보가 0개인 경우(수집 전) — 멀쩡한 제안을 지우면 데이터 손실이다."""
    s = _mem()
    _seed_source(s, path='슈즈/운동화>여성신발>스니커즈', leaf_name='스니커즈')
    s.add(CategoryMapRow(source_id='musinsa', source_path='슈즈/운동화>여성신발>스니커즈',
                         market='eleven11', market_cat_code='OK_W',
                         market_cat_path='패션의류>여성신발>스니커즈', status='suggested',
                         method='name_sim', confidence=1.0))
    s.commit()

    result = cs.generate_suggestions(s, 'musinsa')

    assert result['cleared'] == 0
    assert s.query(CategoryMapRow).filter_by(market='eleven11').one().market_cat_code == 'OK_W'
