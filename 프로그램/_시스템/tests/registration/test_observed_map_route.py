# -*- coding: utf-8 -*-
"""M3 Task 6 Step 3 — POST /bulk/api/catmap/observe (백그라운드 회수) 라우트.

harvest 와 같은 계약: 202(시작)/409(중복) · 결과·사유는 GET status 로 읽는다.
실회수(마켓 호출)는 monkeypatch 로 대체한다 — 라이브 마켓 호출 0.
공유 DB 원칙 — 이 파일이 만든 실행상태 행(`__observe__`)만 정확히 지운다.
"""
import threading

import pytest


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    application = appmod.create_app()
    application.config['TESTING'] = True
    with application.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun
    from webapp.routes.bulk.category_map import OBSERVE_RUN_KEY
    s = SessionLocal()
    try:
        row = s.query(MarketCategoryHarvestRun).filter_by(market=OBSERVE_RUN_KEY).first()
        if row is not None:
            s.delete(row)
            s.commit()
    except Exception:      # noqa: BLE001
        s.rollback()
    finally:
        s.close()


_SUMMARY = {'scanned': 3, 'mapped': 2, 'skipped_no_source_path': 1,
            'skipped_code_unknown': 0, 'skipped_confirmed': 0,
            'errors': 0, 'error_samples': [], 'conflicts': 0}


def test_회수는_백그라운드로_시작되고_결과는_status로_읽는다(client, monkeypatch):
    done = threading.Event()

    def _fake(session, fetch_category, now=None, on_progress=None):
        done.set()
        return dict(_SUMMARY)

    monkeypatch.setattr('lemouton.registration.observed_map.build_observed_map', _fake)

    r = client.post('/bulk/api/catmap/observe')
    assert r.status_code == 202
    assert r.get_json() == {'ok': True, 'started': True}
    assert done.wait(10) is True

    for _ in range(50):        # 스레드 마무리(상태 기록)를 기다린다
        st = client.get('/bulk/api/catmap/observe/status').get_json()
        if not st['running']:
            break
        threading.Event().wait(0.1)
    assert st['ok'] is True and st['running'] is False
    assert st['last_error'] is None
    assert st['last_summary']['mapped'] == 2
    assert st['last_summary']['skipped_no_source_path'] == 1


def test_이미_돌고_있으면_409(client, monkeypatch):
    gate = threading.Event()

    def _slow(session, fetch_category, now=None, on_progress=None):
        gate.wait(5)
        return dict(_SUMMARY)

    monkeypatch.setattr('lemouton.registration.observed_map.build_observed_map', _slow)
    try:
        assert client.post('/bulk/api/catmap/observe').status_code == 202
        second = client.post('/bulk/api/catmap/observe')
        assert second.status_code == 409
        assert second.get_json()['ok'] is False
    finally:
        gate.set()


def test_회수가_터져도_500이_아니라_사유가_상태에_남는다(client, monkeypatch):
    boom = threading.Event()

    def _boom(session, fetch_category, now=None, on_progress=None):
        boom.set()
        raise RuntimeError('자격증명 로드 실패')

    monkeypatch.setattr('lemouton.registration.observed_map.build_observed_map', _boom)
    assert client.post('/bulk/api/catmap/observe').status_code == 202
    assert boom.wait(10) is True

    for _ in range(50):
        st = client.get('/bulk/api/catmap/observe/status').get_json()
        if not st['running']:
            break
        threading.Event().wait(0.1)
    assert st['running'] is False
    assert '자격증명 로드 실패' in (st['last_error'] or '')


def test_설정탭_카테고리맵핑_카드에_회수_버튼이_있다(client):
    """만들어 놓고 화면에 안 붙으면 없는 기능이다 — 버튼·상태 폴링이 실제로 렌더되는지."""
    html = client.get('/bulk/?tab=settings').get_data(as_text=True)
    assert '등록 실적에서 회수' in html
    assert "id=\"cm-observe\"" in html or "id='cm-observe'" in html
    assert '/bulk/api/catmap/observe' in html


def test_계정이_없는_마켓은_전체를_멈추지_않고_사유만_남긴다(monkeypatch):
    """_observe_fetcher: 활성 계정이 없으면 그 마켓만 예외 — 회수 엔진이 건너뛰고 집계한다."""
    from webapp.routes.bulk import category_map as CM
    from lemouton.registration import category_harvest as ch

    notes = []
    monkeypatch.setattr('webapp.routes.bulk.categories._first_env_prefix',
                        lambda s, m: (_ for _ in ()).throw(ch.HarvestError('활성 계정이 없음')))
    fetch = CM._observe_fetcher(notes)
    with pytest.raises(Exception) as e1:
        fetch('smartstore', '777')
    with pytest.raises(Exception):
        fetch('smartstore', '888')
    assert '활성 계정이 없음' in str(e1.value)
    # 사유는 마켓당 한 번만 기록(상품마다 같은 줄을 쌓지 않는다)
    assert len(notes) == 1
