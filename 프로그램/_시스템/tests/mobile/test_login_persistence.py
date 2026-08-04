# -*- coding: utf-8 -*-
"""폰에서 앱을 껐다 켤 때마다 비밀번호를 다시 묻지 않게 — 로그인 유지 90일.

flask_login 기본값은 365일이라 90일은 **줄이는** 쪽(보안상 더 낫다).
PC 에도 같이 적용된다 — 사장님께 보고된 사실.
"""
import datetime as _dt
from datetime import timedelta
from email.utils import parsedate_to_datetime

import pytest

# flask_app 픽스처는 tests/mobile/conftest.py 에 있다.


def test_로그인_유지_기간이_90일이다(flask_app):
    assert flask_app.config.get('REMEMBER_COOKIE_DURATION') == timedelta(days=90)


def test_remember_쿠키는_JS_가_못_읽는다(flask_app):
    """HttpOnly 가 아니면 XSS 한 방에 90일짜리 자동로그인 쿠키를 도둑맞는다."""
    assert flask_app.config.get('REMEMBER_COOKIE_HTTPONLY') is True


def test_로그인_유지_체크가_기본으로_켜져있다():
    # LoginForm.remember 는 WTForms UnboundField — 생성 인자를 .kwargs 로 읽는다(실측).
    from webapp.auth.forms import LoginForm
    field = LoginForm.remember
    assert field.kwargs.get('default') is True, '기본이 꺼져 있으면 매번 다시 묻는다'


# ── 기능 시험: 진짜 로그인 → remember_token 쿠키가 정말 90일짜리인가 ──────────

# ★ 이웃 시험들처럼 @test.local 을 쓰면 안 된다 — 걔들은 DB 에 직접 만들 뿐이지만
#   여긴 폼의 Email() 검증기를 지나는데, email_validator 가 .local 같은 특수용도
#   도메인을 거부한다("Invalid email address." 로 200 이 와서 헛짚기 쉽다. 실측).
LOGIN_EMAIL = 'persist-user@example.com'
LOGIN_PASSWORD = 'persist-pw-12345'


@pytest.fixture
def real_login_app(monkeypatch):
    """DISABLE_AUTH **없는** 앱 — 자동로그인이 켜져 있으면 /auth/login 이
    이미 로그인됐다며 redirect 만 하고 login_user() 경로를 안 탄다.

    CSRF 는 이 시험 전용 앱에서만 끈다(공용 conftest 는 다른 세션 소유라 안 건드림).
    FlaskForm 자체 CSRF 는 TESTING 이어도 자동으로 안 꺼진다(실측: 안 끄면
    validate_on_submit() 이 False 라 쿠키가 영영 안 나와 시험이 헛돈다).
    """
    monkeypatch.delenv('DISABLE_AUTH', raising=False)
    # /auth/* 라우트는 ENVIRONMENT 게이트 안에서만 등록된다 (conftest 주석 참조)
    monkeypatch.setenv('ENVIRONMENT', 'team-share-dev')
    import app as appmod
    a = appmod.create_app()
    a.config['TESTING'] = True
    a.config['WTF_CSRF_ENABLED'] = False
    return a


def test_로그인하면_remember_쿠키가_약_90일짜리로_박힌다(real_login_app):
    # 진짜 사용자를 만들어 로그인하는 시험 — 라이브 DB 에선 안 돈다.
    from tests.mobile.conftest import require_sqlite
    require_sqlite()

    from shared.db import SessionLocal
    from webapp.auth.models import User

    s = SessionLocal()
    user_id = None
    try:
        u = s.query(User).filter(User.email == LOGIN_EMAIL).first()
        if u is None:
            u = User(email=LOGIN_EMAIL, name='persist', role='member',
                     is_active=True, password_hash='x')
            s.add(u)
        u.set_password(LOGIN_PASSWORD)
        u.is_active = True
        s.commit()
        user_id = u.id

        c = real_login_app.test_client()
        r = c.post('/auth/login', data={
            'email': LOGIN_EMAIL,
            'password': LOGIN_PASSWORD,
            # 실제 화면에선 default=True 로 체크박스가 켜진 채 렌더돼 브라우저가
            # 같이 보낸다. 체크박스는 '안 오면 무조건 꺼짐'이라 여기선 명시한다.
            'remember': 'y',
        })
        assert r.status_code == 302, f'로그인 실패(={r.status_code}) — 쿠키 검사 이전에 무너짐'

        set_cookies = r.headers.getlist('Set-Cookie')
        remember = [h for h in set_cookies if h.startswith('remember_token=')]
        assert remember, f'remember_token 쿠키가 안 나왔다: {set_cookies}'
        header = remember[0]

        # flask_login 은 Max-Age 없이 Expires 만 박는다 — 날짜를 파싱해 지금과 비교.
        low = header.lower()
        assert 'httponly' in low, f'HttpOnly 가 없다: {header}'
        expires_str = None
        for part in header.split(';'):
            k, _, v = part.strip().partition('=')
            if k.lower() == 'expires':
                expires_str = v
            if k.lower() == 'max-age':          # 있으면 그걸 우선 검사
                assert abs(int(v) - 90 * 86400) < 3600, f'Max-Age 가 90일이 아니다: {v}'
                return
        assert expires_str, f'Expires 도 Max-Age 도 없다(세션 쿠키 = 앱 닫으면 로그아웃): {header}'
        expires = parsedate_to_datetime(expires_str)
        now = _dt.datetime.now(_dt.timezone.utc)
        days = (expires - now).total_seconds() / 86400
        assert 89.9 < days < 90.1, f'쿠키 수명이 {days:.2f}일 — 90일이 아니다'
    finally:
        if user_id is not None:
            # 시험용 사용자를 남기면 DISABLE_AUTH 의 '첫 활성 사용자' 선택이나
            # member_client 의 전원-비활성 복원 같은 이웃 시험이 흔들린다 — 지운다.
            s.query(User).filter(User.id == user_id).delete()
            s.commit()
        s.close()
