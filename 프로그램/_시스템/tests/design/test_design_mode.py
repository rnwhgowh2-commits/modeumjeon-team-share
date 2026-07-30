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


def test_화면에_모드가_주입된다(client):
    """로그인 없이도(DISABLE_AUTH) 화면이 뜨고 data-design 이 박혀 있어야 한다."""
    r = client.get('/')
    assert r.status_code in (200, 302)
    if r.status_code == 200:
        html = r.get_data(as_text=True)
        assert 'data-design="' in html


def test_현재모드에서는_ds_클래스가_없다(client):
    r = client.get('/')
    if r.status_code != 200:
        return
    html = r.get_data(as_text=True)
    # 안전망 — app 상자에 ds 가 붙으면 안 된다
    assert 'class="app ds' not in html


def _run_design_mode_processor(app):
    """앱에 등록된 context processor 들 중 우리 것(design_mode 키)을 찾아 실행한다.

    실제 webapp/routes/__init__.py 의 inject_design_mode 클로저를 그대로 호출한다 —
    로직을 테스트에서 재구현하지 않고 실코드를 태운다.
    """
    ctx = {}
    for fn in app.template_context_processors[None]:
        ctx.update(fn())
    assert 'design_mode' in ctx, 'inject_design_mode 컨텍스트 프로세서를 못 찾음'
    return ctx


def test_로그인사용자_현재모드는_ds가_안붙는다(client, monkeypatch):
    """실코드 경로(진짜 context processor)로 안전망을 증명 — DB 연결 없이 가짜 사용자만 세운다."""
    import flask_login

    class _FakeUser:
        is_authenticated = True
        design_mode = 'current'

    monkeypatch.setattr(flask_login, 'current_user', _FakeUser())

    app = client.application
    with app.test_request_context('/'):
        ctx = _run_design_mode_processor(app)

    assert ctx['design_mode'] == 'current'
    assert ctx['design_body_class'] == ''

    # base.html 의 실제 두 표현식을 그대로 렌더해 최종 HTML 문자열까지 확인
    import flask
    with app.test_request_context('/'):
        html = flask.render_template_string(
            '<html lang="ko" data-design="{{ design_mode|default(\'current\') }}">'
            '<div class="app {{ design_body_class|default(\'\') }}"></div></html>',
            **ctx,
        )
    assert 'data-design="current"' in html
    assert 'class="app "' in html
    assert 'ds' not in html


def test_로그인사용자_레이어모드는_ds_ds_dark_ds_layer가_붙는다(client, monkeypatch):
    """실코드 경로로 전환도 증명 — design_mode='layer' 인 사용자는 세 클래스가 그대로 박힌다."""
    import flask_login

    class _FakeUser:
        is_authenticated = True
        design_mode = 'layer'

    monkeypatch.setattr(flask_login, 'current_user', _FakeUser())

    app = client.application
    with app.test_request_context('/'):
        ctx = _run_design_mode_processor(app)

    assert ctx['design_mode'] == 'layer'
    assert ctx['design_body_class'] == 'ds ds-dark ds-layer'

    import flask
    with app.test_request_context('/'):
        html = flask.render_template_string(
            '<html lang="ko" data-design="{{ design_mode|default(\'current\') }}">'
            '<div class="app {{ design_body_class|default(\'\') }}"></div></html>',
            **ctx,
        )
    assert 'data-design="layer"' in html
    assert 'class="app ds ds-dark ds-layer"' in html
