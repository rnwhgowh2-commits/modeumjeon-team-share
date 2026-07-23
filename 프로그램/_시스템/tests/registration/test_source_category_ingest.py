"""소싱처 카테고리 사전 적재 — 처음 보면 추가, 다시 보면 카운트만."""
import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.registration.models import SourceCategory
from lemouton.registration import source_category_ingest as ing


def _mem():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_처음_본_경로는_추가되고_깊이와_리프이름이_채워진다():
    s = _mem()
    now = datetime.datetime(2026, 7, 23, 10, 0, 0)
    assert ing.ingest_path(s, 'musinsa', '신발>스니커즈>여성운동화', now=now) is True
    row = s.query(SourceCategory).one()
    assert (row.leaf_name, row.depth, row.product_count) == ('여성운동화', 3, 1)


def test_같은_경로를_또_보면_행은_그대로고_카운트만_오른다():
    s = _mem()
    t1 = datetime.datetime(2026, 7, 23, 10, 0, 0)
    t2 = datetime.datetime(2026, 7, 23, 11, 0, 0)
    ing.ingest_path(s, 'musinsa', '신발>스니커즈>여성운동화', now=t1)
    assert ing.ingest_path(s, 'musinsa', '신발>스니커즈>여성운동화', now=t2) is False
    row = s.query(SourceCategory).one()
    assert row.product_count == 2 and row.last_seen_at == t2
    assert s.query(SourceCategory).count() == 1


def test_빈_경로는_저장하지_않는다():
    s = _mem()
    for bad in ('', '   ', None, '>>'):
        assert ing.ingest_path(s, 'musinsa', bad, now=datetime.datetime(2026, 7, 23)) is False
    assert s.query(SourceCategory).count() == 0
    # 이유: 파싱 실패를 '카테고리 없음'이라는 사실로 둔갑시키지 않는다(추측 금지)


def test_경로_조각의_앞뒤_공백은_정리되고_구분자는_통일된다():
    s = _mem()
    ing.ingest_path(s, 'ssf', ' 신발 > 스니커즈 ', now=datetime.datetime(2026, 7, 23))
    assert s.query(SourceCategory).one().path == '신발>스니커즈'
