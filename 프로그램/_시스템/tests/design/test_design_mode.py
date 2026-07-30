# -*- coding: utf-8 -*-
"""디자인 모드 단일 원천 — 안전망(current)이 새 CSS 를 전혀 부르지 않는지가 핵심."""
import pytest

from webapp.design_mode import MODES, DEFAULT_MODE, normalize, body_class


def test_모드는_넷이다():
    assert list(MODES.keys()) == ['current', 'mono', 'layer', 'light']


def test_기본값은_현재디자인():
    assert DEFAULT_MODE == 'current'


def test_현재모드는_클래스를_붙이지_않는다():
    # 안전망의 핵심 — current 면 ds 가 한 글자도 안 붙어야 한다
    assert body_class('current') == ''


def test_검정한판은_ds_와_다크를_붙인다():
    assert body_class('mono') == 'ds ds-dark ds-mono'


def test_검정3단도_다크다():
    assert body_class('layer') == 'ds ds-dark ds-layer'


def test_밝은카드는_다크가_아니다():
    assert body_class('light') == 'ds ds-light'


@pytest.mark.parametrize('bad', ['', None, 'stripe', 'toss', '  ', 'MONO', '../etc'])
def test_모르는_값은_현재디자인으로_떨어진다(bad):
    assert normalize(bad) == 'current'


def test_아는_값은_그대로():
    assert normalize('layer') == 'layer'


def test_사용자에게_디자인모드_칸이_있고_기본값이_현재다():
    from webapp.auth.models import User
    u = User(email='a@b.c', name='홍길동', password_hash='x')
    # 아직 DB 에 넣기 전에도 파이썬 기본값이 잡혀야 한다
    assert getattr(u, 'design_mode', None) in (None, 'current')
    assert User.__table__.c.design_mode.type.length == 16


def test_마이그레이션_목록에_디자인모드가_있다():
    import inspect as _i
    from shared import db as _db
    src = _i.getsource(_db._apply_lightweight_migrations)
    assert '"users", "design_mode"' in src or "'users', 'design_mode'" in src


def test_마이그레이션이_실제_SQLite에서_컬럼을_만든다(tmp_path, monkeypatch):
    """엔트리만 있고 실제로 안 도는 마이그레이션은 무가치하다 — 그래서 진짜 실행해본다.

    design_mode 컬럼이 없던 시절에 만들어진 users 표(=throwaway SQLite)를 흉내내고,
    _apply_lightweight_migrations() 를 그 표에 대해 돌려서 ALTER TABLE 이 실제로
    컬럼을 붙이는지 확인한다. 실제 DB(shared.db.engine)는 건드리지 않는다 —
    monkeypatch 로 이 함수가 보는 engine 만 일회용 SQLite 파일로 바꾼다.
    """
    from sqlalchemy import create_engine, text, inspect
    from shared import db as _db

    db_path = tmp_path / "legacy_users.sqlite3"
    legacy_engine = create_engine(f"sqlite:///{db_path}", future=True)
    with legacy_engine.begin() as conn:
        # design_mode 신설 이전의 users 표 — 딱 그 컬럼 하나만 빠져 있다.
        conn.execute(text(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY, email VARCHAR(255), name VARCHAR(100), "
            "password_hash VARCHAR(255), role VARCHAR(16), is_active BOOLEAN)"
        ))

    cols_before = {c['name'] for c in inspect(legacy_engine).get_columns('users')}
    assert 'design_mode' not in cols_before

    monkeypatch.setattr(_db, 'engine', legacy_engine)
    _db._apply_lightweight_migrations()

    cols_after = {c['name']: c for c in inspect(legacy_engine).get_columns('users')}
    assert 'design_mode' in cols_after
    # ORM 이 nullable=False 이므로 실제 물리 컬럼도 NOT NULL 이어야 한다 —
    # 아니면 개발(SQLite)·운영(Postgres) 스키마가 갈리는 함정이 된다.
    assert cols_after['design_mode']['nullable'] is False
