# -*- coding: utf-8 -*-
"""쿠팡 브랜드 조회 클라이언트 + 캐시 (6단계-A).

🔴 이 시험이 못박는 핵심 두 가지 (나머지 항목은 전부 이 둘의 변주다)
  ① **정확일치만 matched=True.** brand-search 는 키워드 검색이라 엉뚱한 브랜드가 딸려 온다
     (삼바 실측: 해칭룸→해피룸, 모이에토이파리스→아미파리스). items[0] 을 그냥 채택하면
     **남의 brandId 로 등록**된다.
  ② **「모른다」와 「아니다」를 가른다.** uid_required=None 은 판정 불가이지
     「소명 필요 없음(False)」이 아니다. 예외를 삼켜 「자유판매」로 만들면 소명 대상
     브랜드가 그대로 올라가 계정이 정지된다.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from shared.platforms.coupang.client import CoupangAPIError
from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy.models import BrandRegistryCache

from shared.platforms.coupang import brands as BR
from lemouton.registration import brand_registry as REG


# ──────────────────────────────────────────────────────────────
# 가짜 클라이언트 — 이 저장소 관례(tests/platforms/test_confirm_calls.py) 그대로.
#   진짜 CoupangClient 를 흉내내는 건 request() 하나뿐이고, 무엇을 보냈는지는
#   calls 에 쌓아 두고 그대로 못박는다.
# ──────────────────────────────────────────────────────────────
class FakeClient:
    def __init__(self, response=None, error=None):
        self.calls = []
        self._response = response
        self._error = error

    def request(self, method=None, path=None, body=None, query=None):
        self.calls.append({'method': method, 'path': path, 'body': body, 'query': query})
        if self._error is not None:
            raise self._error
        return self._response


def _ok(items):
    return {
        'code': 'SUCCESS',
        'message': '',
        'data': {'page': 1, 'countPerPage': 10, 'totalCount': len(items), 'items': items},
    }


def _item(name, brand_id='KR-5', uid=None, types=None):
    it = {'brandId': brand_id, 'brandName': name, 'brandLogoUrl': ''}
    if uid is not None:
        it['isUIDRequired'] = uid
    if types is not None:
        it['allowedUIDTypes'] = types
    return it


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _utcnow():
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────
# 1층 — shared/platforms/coupang/brands.py
# ──────────────────────────────────────────────────────────────

def test_정확일치면_brandId_와_소명여부를_담아_돌려준다():
    c = FakeClient(_ok([_item('NIKE', 'KR-5', uid=True, types=['GTIN', 'MPN'])]))
    got = BR.search_brand('NIKE', client=c)

    assert got['matched'] is True
    assert got['brand_id'] == 'KR-5'
    assert got['uid_required'] is True
    assert got['allowed_uid_types'] == ['GTIN', 'MPN']

    call = c.calls[0]
    assert call['method'] == 'POST'
    assert call['path'].endswith('/marketplace/brands/search')
    assert call['body']['brandName'] == 'NIKE'


def test_부분일치는_matched_False_이고_소명여부는_모름이다():
    """🔴 삼바 실측 — 해칭룸으로 물으면 해피룸이 딸려 온다. 채택하면 남의 brandId."""
    c = FakeClient(_ok([_item('해피룸', 'KR-9', uid=True, types=['GTIN'])]))
    got = BR.search_brand('해칭룸', client=c)

    assert got['matched'] is False
    assert got['brand_id'] is None
    assert got['uid_required'] is None
    assert got['uid_required'] is not False   # 「모름」을 「아니다」로 읽으면 안 된다


def test_대소문자_공백_차이는_같은_브랜드로_본다():
    c = FakeClient(_ok([_item('해피 룸', 'KR-9', uid=False)]))
    got = BR.search_brand('해피룸', client=c)
    assert got['matched'] is True
    assert got['brand_id'] == 'KR-9'
    assert got['uid_required'] is False       # 이건 쿠팡이 준 판정이다


def test_code_가_ERROR_면_판정하지_않는다():
    c = FakeClient({'code': 'ERROR', 'message': 'something', 'data': None})
    got = BR.search_brand('NIKE', client=c)

    assert got['matched'] is False
    assert got['uid_required'] is None
    assert got['uid_required'] is not False


def test_items_가_비면_판정하지_않는다():
    c = FakeClient(_ok([]))
    got = BR.search_brand('듣보브랜드', client=c)

    assert got['matched'] is False
    assert got['brand_id'] is None
    assert got['uid_required'] is None


def test_예외를_삼켜_자유판매로_만들지_않는다():
    c = FakeClient(error=CoupangAPIError(401, 'Authentication failed'))
    got = BR.search_brand('NIKE', client=c)

    assert got['matched'] is False
    assert got['uid_required'] is None
    assert got['uid_required'] is not False
    assert got['answered'] is False          # 쿠팡이 답을 준 적이 없다


def test_isUIDRequired_가_없으면_모름이다():
    """🔴 키가 없다고 False(소명 필요 없음)로 읽으면 안 된다."""
    c = FakeClient(_ok([_item('NIKE', 'KR-5')]))
    got = BR.search_brand('NIKE', client=c)

    assert got['matched'] is True
    assert got['uid_required'] is None
    assert got['uid_required'] is not False


def test_정확일치가_둘이면_판정하지_않는다():
    """🔴 어느 쪽이 우리 브랜드인지 모른다 — 첫 번째를 고르면 남의 brandId 로 등록된다."""
    c = FakeClient(_ok([_item('NIKE', 'KR-5', uid=True),
                        _item('나이키', 'KR-8', uid=False)]))
    got = BR.search_brand('나이키', client=c)   # 둘 다 비교 키가 다르므로 1건만 일치
    assert got['brand_id'] == 'KR-8'

    c2 = FakeClient(_ok([_item('해피 룸', 'KR-5', uid=True),
                         _item('해피룸', 'KR-8', uid=False)]))
    got2 = BR.search_brand('해피룸', client=c2)  # 정규화하면 둘 다 정확일치가 된다
    assert got2['matched'] is False
    assert got2['brand_id'] is None
    assert got2['uid_required'] is None


def test_비교_키가_비면_판정하지_않는다():
    """🔴 브랜드가 특수문자뿐이면 비교 키가 빈다 — 이름 없는 항목과 우연히 같아진다."""
    c = FakeClient(_ok([{'brandId': 'KR-5'}]))   # brandName 자체가 없는 항목
    got = BR.search_brand('···', client=c)

    assert got['matched'] is False
    assert got['brand_id'] is None
    assert got['uid_required'] is None


def test_countPerPage_는_10_을_넘겨_보내지_않는다():
    """지도: 기본 10 · 최대 10. 20 을 보내면 400 이다."""
    c = FakeClient(_ok([]))
    BR.search_brand('NIKE', count_per_page=20, client=c)
    assert c.calls[0]['body']['countPerPage'] == 10


def test_브랜드가_비면_API_를_부르지_않는다():
    """지도 errors: 400 'brandName is required' — 부를 필요가 없다."""
    c = FakeClient(_ok([]))
    got = BR.search_brand('   ', client=c)

    assert c.calls == []
    assert got['matched'] is False
    assert got['uid_required'] is None


# ──────────────────────────────────────────────────────────────
# 2층 — lemouton/registration/brand_registry.py (캐시를 낀 창구)
# ──────────────────────────────────────────────────────────────

def test_처음_조회하면_API_를_부르고_캐시에_남긴다(db):
    c = FakeClient(_ok([_item('NIKE', 'KR-5', uid=True, types=['GTIN'])]))
    got = REG.lookup(db, 'NIKE', client=c)

    assert got['matched'] is True
    assert got['brand_id'] == 'KR-5'
    assert got['uid_required'] is True
    assert got['from_cache'] is False

    row = db.query(BrandRegistryCache).filter_by(brand='NIKE').one()
    assert row.coupang_brand_id == 'KR-5'
    assert row.uid_required is True
    assert row.matched is True


def test_캐시에_신선한_행이_있으면_API_를_안_부른다(db):
    db.add(BrandRegistryCache(brand='NIKE', coupang_brand_id='KR-5',
                              uid_required=True, matched=True,
                              checked_at=_utcnow() - timedelta(days=3)))
    db.commit()

    c = FakeClient(_ok([_item('NIKE', 'KR-999', uid=False)]))
    got = REG.lookup(db, 'NIKE', client=c, max_age_days=30)

    assert c.calls == []                      # 호출 0회
    assert got['from_cache'] is True
    assert got['brand_id'] == 'KR-5'          # 캐시 값이 그대로 나온다
    assert got['uid_required'] is True


def test_캐시가_오래되면_다시_부른다(db):
    db.add(BrandRegistryCache(brand='NIKE', coupang_brand_id='KR-5',
                              uid_required=True, matched=True,
                              checked_at=_utcnow() - timedelta(days=40)))
    db.commit()

    c = FakeClient(_ok([_item('NIKE', 'KR-7', uid=False, types=[])]))
    got = REG.lookup(db, 'NIKE', client=c, max_age_days=30)

    assert len(c.calls) == 1
    assert got['from_cache'] is False
    assert got['brand_id'] == 'KR-7'
    assert got['uid_required'] is False

    row = db.query(BrandRegistryCache).filter_by(brand='NIKE').one()
    assert row.coupang_brand_id == 'KR-7'     # 캐시가 갱신된다


def test_client_가_없으면_API_를_안_부르고_캐시만_본다(db):
    db.add(BrandRegistryCache(brand='NIKE', coupang_brand_id='KR-5',
                              uid_required=True, matched=True))
    db.commit()

    got = REG.lookup(db, 'NIKE')              # client 미주입
    assert got['from_cache'] is True
    assert got['brand_id'] == 'KR-5'

    # 캐시에 없으면 지어내지 않는다 — None
    assert REG.lookup(db, '듣보브랜드') is None


def test_캐시의_모름을_아니다로_바꿔_읽지_않는다(db):
    """🔴 판정 못 한 브랜드는 uid_required 가 정확히 None 이다."""
    db.add(BrandRegistryCache(brand='듣보브랜드', matched=False))
    db.commit()

    got = REG.lookup(db, '듣보브랜드')
    assert got['matched'] is False
    assert got['uid_required'] is None
    assert got['uid_required'] is not False


def test_API_가_답을_못_주면_캐시를_덮지_않는다(db):
    """🔴 일시적 401·네트워크 오류를 matched=False 로 굳히면 그 브랜드가
    max_age_days 동안 「판정 불가」로 얼어붙는다."""
    db.add(BrandRegistryCache(brand='NIKE', coupang_brand_id='KR-5',
                              uid_required=True, matched=True,
                              checked_at=_utcnow() - timedelta(days=40)))
    db.commit()

    c = FakeClient(error=CoupangAPIError(401, 'Authentication failed'))
    got = REG.lookup(db, 'NIKE', client=c, max_age_days=30)

    assert len(c.calls) == 1
    assert got['stale'] is True               # 오래됐다는 사실을 숨기지 않는다
    assert got['brand_id'] == 'KR-5'

    row = db.query(BrandRegistryCache).filter_by(brand='NIKE').one()
    assert row.coupang_brand_id == 'KR-5'     # 덮이지 않았다
    assert row.matched is True


def test_판정_불가도_캐시에_남긴다(db):
    """쿠팡이 「그런 브랜드 없다」고 답한 것은 판정이다 — 매번 다시 묻지 않는다."""
    c = FakeClient(_ok([]))
    got = REG.lookup(db, '듣보브랜드', client=c)

    assert got['matched'] is False
    assert got['uid_required'] is None

    row = db.query(BrandRegistryCache).filter_by(brand='듣보브랜드').one()
    assert row.matched is False
    assert row.uid_required is None


def test_같은_브랜드가_동시에_들어와도_터지지_않는다(db):
    """🔴 brand 는 UNIQUE 인데 등록은 배경 스레드로 돈다 — 두 스레드가 같은 브랜드를
    처음 조회하면 나중 쪽 flush 가 UNIQUE 로 터져 그 상품 등록이 통째로 죽는다.
    (먼저 들어온 행이 있는데 row=None 으로 들어온 상황 = 그 경합의 재현)"""
    db.add(BrandRegistryCache(brand='NIKE', coupang_brand_id='KR-1', matched=True))
    db.commit()

    row = REG._upsert(db, None, 'NIKE',
                      {'brand_id': 'KR-5', 'uid_required': True, 'matched': True})

    assert row.coupang_brand_id == 'KR-5'
    assert db.query(BrandRegistryCache).filter_by(brand='NIKE').count() == 1


def test_브랜드가_비면_캐시도_API_도_안_본다(db):
    c = FakeClient(_ok([]))
    assert REG.lookup(db, '', client=c) is None
    assert REG.lookup(db, None, client=c) is None
    assert c.calls == []
    assert db.query(BrandRegistryCache).count() == 0


# ── [2026-08-24 실측으로 잡은 결함] 예외가 밖으로 새면 등록 전체가 터진다 ──────
#   예전 코드는 `except CoupangAPIError` 만 잡았다. 그런데 client.request 는 재시도를
#   다 쓰면 `raise last_error` 로 **원본 예외**(대개 requests.RequestException)를
#   그대로 낸다. 쿠팡이 잠깐 죽었을 때 브랜드 조회 하나 때문에 등록이 통째로 죽었다.
#   브랜드 조회는 등록을 돕는 곁가지지 등록의 전제가 아니다.

class _RaisingClient:
    """request() 가 정해진 예외를 던지는 가짜 클라이언트."""

    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def request(self, *a, **k):
        self.calls += 1
        raise self._exc


@pytest.mark.parametrize('exc', [
    Exception('network down'),
    TimeoutError('read timeout'),
    ConnectionError('connection reset'),
    ValueError('unexpected payload'),
])
def test_어떤_예외가_나도_밖으로_새지_않는다(exc):
    """🔴 좁게 잡으면 쿠팡이 잠깐 죽었을 때 등록이 통째로 터진다."""
    from shared.platforms.coupang import brands

    got = brands.search_brand('나이키', client=_RaisingClient(exc))

    assert got['matched'] is False
    assert got['uid_required'] is None       # 🔴 못 물어본 것 — False(자유판매) 아님
    assert got['brand_id'] is None


def test_예외가_나도_소명필요없음으로_바꾸지_않는다():
    """「모른다」를 「아니다」로 바꾸는 게 이 프로젝트의 반복 사고다."""
    from shared.platforms.coupang import brands

    got = brands.search_brand('나이키', client=_RaisingClient(Exception('boom')))

    assert got['uid_required'] is not False   # None 이어야 한다
    assert got['uid_required'] is None
