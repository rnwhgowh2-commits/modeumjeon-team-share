# -*- coding: utf-8 -*-
"""자동완성 창구 — 28만 건에서도 글자를 칠 수 있어야 한다.

실측 2026-08-04: 마켓에 약 28만 건이 있다(롯데온만 136,510 · 스마트스토어 7,055).
그런데 찾기는 `ILIKE '%낱말%'` 라 **앞이 열려 있어 보통 색인을 못 탄다** —
글자마다 표 전체를 훑는다.

그래서 두 가지를 지킨다.
  ① 자동완성은 **전체 건수를 세지 않는다** (search 는 센다 — 글자마다 28만 건 세면 멈춤)
  ② **두 글자 미만은 안 찾는다** — 한 글자면 거의 전부가 걸려 색인이 소용없다
"""
import pytest

from lemouton.catalog.search import SUGGEST_LIMIT, index_status, suggest


class FakeQuery:
    """세는 것과 집는 것을 갈라 기록하는 가짜 질의."""

    def __init__(self, log, rows):
        self.log, self.rows = log, rows

    def filter(self, *a, **k):
        return self

    def order_by(self, *a):
        return self

    def offset(self, n):
        return self

    def limit(self, n):
        self.log.append(('limit', n))
        return self

    def count(self):
        self.log.append(('count', None))
        return len(self.rows)

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows=()):
        self.log = []
        self.rows = list(rows)
        self.bind = None

    def query(self, *a):
        return FakeQuery(self.log, self.rows)


def test_자동완성은_전체_건수를_세지_않는다():
    """🔴 이 검사가 이 파일의 존재 이유.

    글자를 칠 때마다 28만 건을 세면 화면이 멈춘다.
    """
    s = FakeSession()
    suggest(s, '르무통')
    assert ('count', None) not in s.log, (
        '자동완성이 전체 건수를 세고 있다 — 28만 건에서 글자마다 멈춘다')


def test_자동완성은_몇_개만_집어온다():
    s = FakeSession()
    suggest(s, '르무통')
    limits = [n for k, n in s.log if k == 'limit']
    assert limits and limits[0] == SUGGEST_LIMIT


@pytest.mark.parametrize('q', ['', ' ', '르', 'a'])
def test_두_글자_미만은_안_찾는다(q):
    """한 글자로 찾으면 거의 전부가 걸려 색인이 소용없다."""
    s = FakeSession()
    r = suggest(s, q)
    assert r['rows'] == []
    assert r['reason'], '왜 안 찾았는지 이유를 돌려줘야 한다'
    assert s.log == [], '아예 질의하지 않아야 한다'


def test_상한을_넘겨도_25개를_안_넘는다():
    s = FakeSession()
    suggest(s, '르무통', limit=999)
    assert [n for k, n in s.log if k == 'limit'][0] == 25


def test_색인_상태창구는_sqlite_를_해당없음으로_답한다():
    """로컬은 SQLite 라 이 색인이 없는 게 정상 — 「고장」으로 보이면 안 된다."""
    s = FakeSession()
    r = index_status(s)
    assert r['applicable'] is False
    assert 'PostgreSQL' in r['note']


def test_색인_생성이_마이그레이션에_있다():
    """🔴 색인 생성은 실패해도 프로그램이 돈다(느려질 뿐) — 조용한 실패를 막는다."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / 'shared' / 'db.py').read_text(encoding='utf-8')
    assert 'pg_trgm' in src, '세글자 색인 생성이 없다 — 28만 건에서 찾기가 표 전체를 훑는다'
    assert 'ix_mp_name_trgm' in src
    assert '_log.warning' in src, '실패를 조용히 삼키면 「빠른 줄 알았는데」가 생긴다'
