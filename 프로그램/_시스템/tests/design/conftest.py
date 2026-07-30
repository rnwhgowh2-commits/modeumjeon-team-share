# -*- coding: utf-8 -*-
"""디자인 모드 테스트용 앱 — 팩토리는 프로그램/_시스템/app.py 의 create_app."""
import os
import pytest

os.environ.setdefault('DISABLE_AUTH', '1')   # 로그인 벽 우회(솔로 개발용 플래그)


@pytest.fixture()
def client():
    from app import create_app                # 프로그램/_시스템/app.py:18
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as c:
        yield c
