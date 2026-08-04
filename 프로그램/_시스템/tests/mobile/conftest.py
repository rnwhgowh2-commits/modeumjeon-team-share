# -*- coding: utf-8 -*-
"""폰(모바일) 시험 공용 준비물.

여기 모은 이유: `flask_app` 픽스처가 test_crawl_remote_api.py 와
test_shell_pages.py 에 주석까지 똑같이 복붙돼 있었고, Task 5(설치 안내 화면)에서
세 번째 사본이 생길 참이었다. 게이트(ENVIRONMENT)를 하나 고치면 세 곳을 다 고쳐야
하는 구조라 한 곳으로 올린다.
"""
import json
import re

import pytest


def shell_blob_of(html: str) -> dict:
    """base.html 이 심는 껍데기 JSON(ms-tabs-data) — {tabs, ready} 한 덩어리.

    여기 둔 이유(배치1 검토 잔여 정리): 같은 파서가 test_shell_pages.tabs_json_of 와
    test_stage3_ready._blob_of 두 벌로 복붙돼 있었다 — JSON 블록 모양이 바뀌면
    한쪽만 고쳐져 어긋난다. 원문 그대로 꺼낸다(공백을 눕히면 JSON 비교가 헛돈다).
    """
    m = re.search(r'<script type="application/json" id="ms-tabs-data">(.*?)</script>',
                  html, re.S)
    assert m, '탭 JSON 블록(ms-tabs-data)이 화면에 없다'
    return json.loads(m.group(1))


def require_sqlite():
    """진짜 DB(PostgreSQL) 면 시험을 건너뛴다.

    🔴 왜 필요한가 — 폰 시험들은 사용자를 **만들고**(client) 심지어 전부
      **비활성으로 돌렸다 되돌린다**(member_client). 도중에 Ctrl-C 나 크래시가 나면
      되돌리는 코드가 못 돌아 사장님과 팀원이 **영구히 로그인 불가**가 된다.

      이 워크트리는 .env 가 없어 tests/conftest.py 의 임시 SQLite 가 먹지만,
      config.py:10 이 `load_dotenv(..., override=True)` 라 **.env 가 있는 체크아웃**
      에서는 그 .env 의 DATABASE_URL=postgresql://... 가 conftest 가 심어 둔 임시값을
      **덮어쓴다**(실측 확인). 그러면 이 시험들이 라이브 팀 DB 를 친다.
      그래서 엔진을 직접 보고 막는다.
    """
    from shared.db import engine
    if engine.url.get_backend_name() != "sqlite":
        pytest.skip("사용자를 건드리는 시험이라 진짜 DB 에선 안 돈다")


@pytest.fixture
def flask_app(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    # 🔴 /mobile/* 라우트는 app.py 의 ENVIRONMENT 게이트 안에서만 등록된다.
    #   pytest 에선 이 값이 없어 라우트가 0개 → 안 넣으면 전부 404 로 실패한다.
    #   라이브가 이 값이다.
    monkeypatch.setenv('ENVIRONMENT', 'team-share-dev')
    import app as appmod
    a = appmod.create_app()
    a.config['TESTING'] = True
    return a
