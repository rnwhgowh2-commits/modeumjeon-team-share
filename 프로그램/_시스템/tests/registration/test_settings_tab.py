# -*- coding: utf-8 -*-
"""대량등록 ⑧ 설정 탭 — 등급 경계·계수·하한·상한을 화면에서 고친다.

설계서 §4: "모든 수치는 제안값. 최종은 사장님이 화면에서 설정."
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _restore():
    """설정은 전역 1행이라 테스트가 라이브 값을 바꿔놓으면 안 된다 — 끝나면 되돌린다."""
    yield
    from shared.db import SessionLocal
    from lemouton.sources.grade_config_store import reset_grade_config
    s = SessionLocal()
    try:
        reset_grade_config(s)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()


# ── 탭 등록 ─────────────────────────────────────────────────────

def test_설정_탭이_등록되어_있다():
    from webapp.routes.bulk import SUBTABS
    assert 'settings' in [t['key'] for t in SUBTABS]


def test_설정_페이지가_200(client):
    r = client.get('/bulk/?tab=settings')
    assert r.status_code == 200
    assert 'st-root' in r.get_data(as_text=True)


def test_app이_설정_모델을_import_한다():
    """create_all 은 import 된 모델만 만든다 — 빠뜨리면 저장이 조용히 안 된다."""
    import io
    import os
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = io.open(os.path.join(here, "app.py"), encoding="utf-8").read()
    assert "lemouton.sources.grade_config_store" in src


# ── 읽기 ────────────────────────────────────────────────────────

def test_기본값을_돌려준다(client):
    j = client.get('/bulk/api/settings/grade').get_json()
    assert j['ceiling_per_day'] == pytest.approx(2.0)   # 사장님 결정 4-A
    assert len(j['grades']) == 6
    assert j['customized'] is False


def test_등급마다_실제_적용값이_같이_온다(client):
    """제안 3회가 상한 2회로 깎이는 걸 화면이 보여줘야 한다."""
    g0 = client.get('/bulk/api/settings/grade').get_json()['grades'][0]
    assert g0['raw_per_day'] == pytest.approx(3.0)
    assert g0['effective_per_day'] == pytest.approx(2.0)
    assert g0['capped'] is True


# ── 저장 ────────────────────────────────────────────────────────

def test_상한을_바꾸면_저장된다(client):
    r = client.post('/bulk/api/settings/grade', json={"ceiling_per_day": 6.0})
    assert r.status_code == 200 and r.get_json()['ok'] is True
    assert client.get('/bulk/api/settings/grade').get_json()['ceiling_per_day'] == pytest.approx(6.0)


def test_상한을_올리면_깎임_표시가_사라진다(client):
    client.post('/bulk/api/settings/grade', json={"ceiling_per_day": 6.0})
    g0 = client.get('/bulk/api/settings/grade').get_json()['grades'][0]
    assert g0['capped'] is False
    assert g0['effective_per_day'] == pytest.approx(3.0)


def test_고치면_customized가_True(client):
    client.post('/bulk/api/settings/grade', json={"ceiling_per_day": 5.0})
    assert client.get('/bulk/api/settings/grade').get_json()['customized'] is True


# ── 🔴 잘못된 값은 400 과 사유 ──────────────────────────────────

def test_하한이_상한보다_크면_400(client):
    r = client.post('/bulk/api/settings/grade',
                    json={"ceiling_per_day": 0.5, "floor_per_day": 2.0})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False
    assert r.get_json()['error']


def test_경계가_내림차순이_아니면_400(client):
    r = client.post('/bulk/api/settings/grade',
                    json={"boundaries": [100, 200, 33, 14, 3]})
    assert r.status_code == 400


def test_거부돼도_기존_값이_안_바뀐다(client):
    client.post('/bulk/api/settings/grade', json={"ceiling_per_day": 6.0})
    client.post('/bulk/api/settings/grade', json={"boundaries": [1, 2, 3, 4, 5]})
    assert client.get('/bulk/api/settings/grade').get_json()['ceiling_per_day'] == pytest.approx(6.0)


# ── 되돌리기 ────────────────────────────────────────────────────

def test_기본값으로_되돌린다(client):
    client.post('/bulk/api/settings/grade', json={"ceiling_per_day": 9.0})
    r = client.post('/bulk/api/settings/grade/reset')
    assert r.status_code == 200
    j = client.get('/bulk/api/settings/grade').get_json()
    assert j['ceiling_per_day'] == pytest.approx(2.0)
    assert j['customized'] is False


# ── 기존 탭이 안 깨진다 ─────────────────────────────────────────

def test_다섯_탭이_모두_열린다(client):
    for t in ('collect', 'process', 'send', 'manual', 'settings'):
        assert client.get(f'/bulk/?tab={t}').status_code == 200, f"{t} 탭이 안 열린다"
