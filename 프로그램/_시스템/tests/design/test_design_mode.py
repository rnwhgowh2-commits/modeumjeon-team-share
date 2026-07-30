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


def test_로그인화면은_base_html_체인_밖이라_영향없다(client_with_auth):
    """auth/login.html 은 auth/_base_auth.html 을 extends — base.html 을 안 탄다.

    디자인 모드 주입은 전역 context_processor 라 모든 템플릿에 변수는 들어가지만,
    login 화면이 그 변수를 쓰지 않아도(=body_class 를 안 박아도) 렌더가 깨지면 안 된다.
    (기본 client 는 ENVIRONMENT 미설정이라 /auth/login 라우트 자체가 없어 client_with_auth 사용.)
    """
    r = client_with_auth.get('/auth/login')
    assert r.status_code == 200


def test_tokens_css_에_모드_3종이_정의돼_있다():
    import io, os
    p = os.path.join(os.path.dirname(__file__), '..', '..',
                     'webapp', 'static', 'tokens.css')
    css = io.open(os.path.abspath(p), encoding='utf-8').read()
    for sel in ('.ds.ds-mono', '.ds.ds-layer', '.ds.ds-light'):
        assert sel in css, sel + ' 가 tokens.css 에 없다'


def test_tokens_css_에는_그림자를_쓰지_않는다():
    import io, os, re
    p = os.path.join(os.path.dirname(__file__), '..', '..',
                     'webapp', 'static', 'tokens.css')
    css = io.open(os.path.abspath(p), encoding='utf-8').read()
    나쁜것 = [m for m in re.findall(r'box-shadow:\s*([^;}\n]+)', css)
              if m.strip() != 'none' and not m.strip().startswith('var(')]
    assert 나쁜것 == [], 나쁜것


# ─────────────────────────────────────────────────────────────────────────
# T5 — 저장 API + 전환 UI
# ─────────────────────────────────────────────────────────────────────────

def _저장된_사용자_만들기(email='design-save@test.local', **override):
    """임시(격리된) DB 에 사용자 하나를 만들고 id 를 반환한다.

    client_with_auth 픽스처 실행 **이후** 호출해야 한다 — 그래야
    shared.db.SessionLocal 이 임시 SQLite 로 몽키패치된 뒤의 값을 잡는다.
    """
    from shared.db import SessionLocal
    from webapp.auth.models import User

    with SessionLocal() as s:
        u = User(
            email=email, name='디자인모드테스트', password_hash='x',
            role='admin', is_active=True,
        )
        for k, v in override.items():
            setattr(u, k, v)
        s.add(u)
        s.commit()
        return u.id


def _사용자의_design_mode(user_id):
    from shared.db import SessionLocal
    from webapp.auth.models import User

    with SessionLocal() as s:
        u = s.get(User, user_id)
        return u.design_mode if u else None


def test_모드저장_POST가_DB에_반영된다(client_with_auth):
    uid = _저장된_사용자_만들기()

    r = client_with_auth.post('/auth/design-mode', data={'mode': 'layer'})
    assert r.status_code == 302
    assert _사용자의_design_mode(uid) == 'layer'


def test_모드저장_모르는값은_저장안됨(client_with_auth):
    uid = _저장된_사용자_만들기()

    r = client_with_auth.post('/auth/design-mode', data={'mode': '../etc'})
    assert r.status_code == 302
    assert not r.headers['Location'].endswith('etc')
    assert _사용자의_design_mode(uid) == 'current'


def test_모드저장_mode필드_없어도_안전망유지(client_with_auth):
    uid = _저장된_사용자_만들기()

    r = client_with_auth.post('/auth/design-mode', data={})
    assert r.status_code == 302
    assert _사용자의_design_mode(uid) == 'current'


def test_모드저장_외부주소로_리다이렉트_안됨(client_with_auth):
    """next 를 사용자가 조작해도 다른 사이트로 튀면 안 된다(열린 리다이렉트 금지)."""
    _저장된_사용자_만들기()

    r1 = client_with_auth.post(
        '/auth/design-mode', data={'mode': 'mono', 'next': 'http://evil.example/x'})
    loc1 = r1.headers['Location']
    assert 'evil.example' not in loc1

    r2 = client_with_auth.post(
        '/auth/design-mode', data={'mode': 'mono', 'next': '//evil.example/x'})
    loc2 = r2.headers['Location']
    assert 'evil.example' not in loc2


def test_모드저장_같은사이트_상대경로_next는_허용(client_with_auth):
    _저장된_사용자_만들기()

    r = client_with_auth.post(
        '/auth/design-mode', data={'mode': 'mono', 'next': '/auth/me'})
    assert r.headers['Location'].endswith('/auth/me')


def test_모드저장_체인_전체_base_html에_클래스가_박힌다(client_with_auth):
    """저장 → 이후 GET 화면까지 실코드 경로로 끝까지 증명."""
    _저장된_사용자_만들기()

    r = client_with_auth.post('/auth/design-mode', data={'mode': 'layer'})
    assert r.status_code == 302

    r2 = client_with_auth.get('/')
    if r2.status_code == 200:
        html = r2.get_data(as_text=True)
        assert 'class="app ds ds-dark ds-layer"' in html


def test_me_화면에_네가지_모드_이름이_다있다(client_with_auth):
    from webapp.design_mode import MODES

    _저장된_사용자_만들기()

    r = client_with_auth.get('/auth/me')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for 이름, 설명, _어두운가 in MODES.values():
        assert 이름 in html
