# -*- coding: utf-8 -*-
"""디자인 모드 테스트용 앱 — 팩토리는 프로그램/_시스템/app.py 의 create_app.

★ DB 격리 (필수, 코드리뷰 지적 반영) — 이 프로젝트는 라이브(Fly.io)와 로컬 개발이
  **같은 Supabase Postgres** 를 공유한다(CLAUDE.md 데이터 정합성 원칙). config.py 의
  ``Config.DB_URL`` 은 ``DATABASE_URL`` 환경변수를 최초 import 시점에 한 번만 읽고,
  shared/db.py 의 ``engine``/``SessionLocal`` 도 그 시점에 한 번만 만들어진다.

  그런데 ``tests/conftest.py``(루트, 이 파일보다 먼저 로드됨)가 수집 단계에서
  ``webapp.auth.models`` 등 모델 모듈을 강제로 import 한다 — 그 cascade 로
  ``config``/``shared.db`` 가 이 파일이 로드되기 **전에 이미 import 완료**된다.
  즉 여기서 ``os.environ['DATABASE_URL']`` 을 바꿔봐야 이미 늦다(``Config.DB_URL`` 은
  변하지 않는다) — 그래서 환경변수가 아니라 ``shared.db`` 의 engine/SessionLocal
  **객체 자체**를 임시 SQLite 로 몽키패치한다. ``create_app()`` 이 처음으로
  ``from shared.db import SessionLocal`` 하는 라우트 모듈들(webapp/routes/*)은 이
  패치 **이후**에 처음 import 되므로(이 테스트 파일 스코프에서는 그 전에 아무도
  라우트 모듈을 안 건드림) 패치된 값을 그대로 물고 간다.

  아래서 실제로 임시 파일을 들여다봐서(엔진 URL 확인 + users 표 존재 확인) 격리가
  됐는지 "주장"이 아니라 "증명"한다 — 조용히 통과시키지 않고 격리가 깨지면 매 테스트
  fixture 단계에서 즉시 실패한다.
"""
import os
import pytest

os.environ.setdefault('DISABLE_AUTH', '1')   # 로그인 벽 우회(솔로 개발용 플래그)


def _build_isolated_app(tmp_path, monkeypatch, extra_env=None):
    """임시 SQLite 로 격리된 Flask 앱을 만든다 — client/client_with_auth 가 공유."""
    import shared.db as _db
    from config import Config
    from sqlalchemy import create_engine, inspect as sa_inspect
    from sqlalchemy.orm import sessionmaker

    for k, v in (extra_env or {}).items():
        monkeypatch.setenv(k, v)

    temp_db_path = tmp_path / 'design_mode_test.sqlite3'
    temp_url = f"sqlite:///{temp_db_path.as_posix()}"
    assert not temp_url.lower().startswith(('postgres', 'postgresql')), \
        f"임시 DB URL 이 postgres 로 잡혔다(자기점검 실패): {temp_url!r}"

    # ★ 패치하기 전에 원본을 붙잡아 둔다. 정리 시점엔 monkeypatch 가 아직
    #   살아 있어서 shared.db 를 읽으면 임시값이 나온다.
    원본_engine, 원본_Session = _db.engine, _db.SessionLocal

    temp_engine = create_engine(temp_url, future=True)
    temp_session_factory = sessionmaker(
        bind=temp_engine, autoflush=False, autocommit=False,
        future=True, expire_on_commit=False,
    )

    # shared.db 모듈 전역을 통째로 교체 — init_db()/_apply_lightweight_migrations()/
    # 아직 import 안 된 라우트 모듈들이 이 이후 처음 물어가는 engine·SessionLocal 이
    # 전부 이 임시 엔진을 보게 만든다.
    monkeypatch.setattr(_db, 'engine', temp_engine)
    monkeypatch.setattr(_db, 'SessionLocal', temp_session_factory)
    monkeypatch.setattr(Config, 'DB_URL', temp_url)

    from app import create_app                # 프로그램/_시스템/app.py:18
    flask_app = create_app()
    flask_app.config.update(TESTING=True)

    # ★ 격리 증명 (댓글이 아니라 실행되는 검사) ─────────────────────────────
    # 1) shared.db.engine 이 여전히(누가 재할당하지 않고) 임시 URL을 가리키는지.
    assert str(_db.engine.url) == temp_url, (
        f"design 테스트용 client 가 실DB 를 볼 뻔했다: {_db.engine.url!r} "
        f"(기대: {temp_url!r}) — shared.db.engine 이 create_app() 도중 재할당됐다."
    )
    # 2) init_db() 가 실제로 이 임시 파일에 대해 돌았는지 — users 표가 임시 SQLite
    #    파일 안에 생겼어야 한다. 라이브 Postgres 를 봤다면 이 파일은 빈 채로 남는다.
    tables_in_temp_file = set(sa_inspect(temp_engine).get_table_names())
    assert 'users' in tables_in_temp_file, (
        "임시 SQLite 파일에 users 표가 없다 — init_db() 가 이 임시 DB 가 아니라 "
        "다른(실) DB 에 대해 돌았을 가능성이 있다. DB 격리가 깨졌다."
    )
    assert temp_db_path.exists()

    return flask_app, temp_engine, temp_session_factory, 원본_engine, 원본_Session


def _원래대로_되돌리기(temp_engine, temp_session_factory, 원본_engine, 원본_Session):
    """다른 테스트를 오염시키지 않게 임시 연결을 붙잡은 모듈을 되돌린다.

    ★ 왜 필요한가 (2026-07-31 실측으로 확인한 사고)
      create_app() 이 처음 import 하는 라우트 모듈들은 모듈 최상단에서
      ``from shared.db import SessionLocal`` 을 한다. 파이썬은 모듈을 한 번만
      import 하므로, 그 이름은 **그때 물어간 임시 SQLite 를 영원히 붙잡는다.**
      monkeypatch 는 ``shared.db`` 자체만 되돌리지 그 사본들은 못 되돌린다.
      그래서 이 테스트가 먼저 돌면 뒤따르는 테스트가 이미 지워진 임시 파일을
      보게 되어 무더기로 깨졌다(등록 테스트 30개 실패를 실측).

      전체 스위트: 작업 전 22 실패 → 이 정리 없이는 188 실패.
    """
    import sys as _sys
    원본 = {'engine': 원본_engine, 'SessionLocal': 원본_Session}
    임시 = {'engine': temp_engine, 'SessionLocal': temp_session_factory}
    for mod in list(_sys.modules.values()):
        if mod is None:
            continue
        for 이름, 임시객체 in 임시.items():
            try:
                if getattr(mod, 이름, None) is 임시객체:
                    setattr(mod, 이름, 원본[이름])
            except Exception:
                pass          # __getattr__ 이 있는 특수 모듈 — 건너뛴다


@pytest.fixture()
def client(tmp_path, monkeypatch):
    flask_app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(tmp_path, monkeypatch)
    with flask_app.test_client() as c:
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()


@pytest.fixture()
def client_with_auth(tmp_path, monkeypatch):
    """ENVIRONMENT=team-share-dev — webapp.auth 블루프린트(/auth/login 등)까지 등록된 앱.

    기본 ``client`` 는 ENVIRONMENT 미설정이라 app.py:337 의 조건부 import 가 안 걸려
    /auth/login 라우트 자체가 없다(404). base.html 체인 밖 템플릿(§Issue 3) 검증에는
    이 fixture 를 쓴다.
    """
    flask_app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(
        tmp_path, monkeypatch, extra_env={'ENVIRONMENT': 'team-share-dev'})
    with flask_app.test_client() as c:
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()
