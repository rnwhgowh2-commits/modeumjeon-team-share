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


def test_회수_요약에_조인실패와_충돌이_화면에_드러난다(client):
    """[리뷰 C1·I1] 못 붙은 URL 수·충돌 후보가 화면에 안 나오면 또 조용한 실패가 된다."""
    html = client.get('/bulk/?tab=settings').get_data(as_text=True)
    for field in ('unmatched_urls', 'unmatched_url_samples',
                  'conflict_samples', 'skipped_no_dict'):
        assert field in html, field


def test_계정이_없는_마켓은_전체를_멈추지_않고_사유만_남긴다(monkeypatch):
    """_observe_fetcher: 활성 계정이 없으면 그 마켓만 예외 — 회수 엔진이 건너뛰고 집계한다."""
    from webapp.routes.bulk import category_map as CM

    notes = []
    monkeypatch.setattr(CM, '_active_env_prefixes', lambda s, m: [])
    fetch = CM._observe_fetcher(notes)
    with pytest.raises(Exception) as e1:
        fetch('smartstore', '777')
    with pytest.raises(Exception):
        fetch('smartstore', '888')
    assert '활성 계정이 없음' in str(e1.value)
    # 사유는 마켓당 한 번만 기록(상품마다 같은 줄을 쌓지 않는다)
    assert len(notes) == 1


# ── [2026-07-23 리뷰 I2] 마켓별 계정 순차 시도 ──────────────────────────
#   상품 조회는 계정에 매인다(ESM 6계정·쿠팡 vendor). 첫 계정 하나만 쓰면 2번 계정 상품이
#   전부 errors 로 뭉개져 원인 판별이 불가능하고, 이 저장소는 '기본 계정 폴백 금지'를 이미
#   못 박았다(send_more._env_prefix).
@pytest.fixture()
def _no_sleep(monkeypatch):
    from webapp.routes.bulk import category_map as CM
    for m in list(CM.OBSERVE_SLEEP):
        monkeypatch.setitem(CM.OBSERVE_SLEEP, m, 0)


def _stub_calls(monkeypatch, results):
    """(env_prefix → 결과 or 예외) 로 마켓 호출을 대체하고 호출 순서를 돌려준다."""
    from webapp.routes.bulk import category_map as CM

    calls = []
    monkeypatch.setattr(CM, '_active_env_prefixes', lambda s, m: list(results))
    monkeypatch.setattr(CM, '_observe_client', lambda market, env_prefix: env_prefix)

    def _call(market, product_id, client):
        calls.append((client, product_id))
        r = results[client]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(CM, '_observe_call', _call)
    return calls


def test_첫_계정이_실패하면_다음_계정으로_이어서_시도한다(monkeypatch, _no_sleep):
    from webapp.routes.bulk import category_map as CM

    calls = _stub_calls(monkeypatch, {'ESM_A': RuntimeError('상품 없음'), 'ESM_B': 'A1'})
    notes = []
    fetch = CM._observe_fetcher(notes)
    assert fetch('auction', '777') == 'A1'
    assert [c for c, _ in calls] == ['ESM_A', 'ESM_B']
    # 다음 상품은 마지막에 성공한 계정부터 — 매번 죽은 계정을 먼저 두드리지 않는다
    fetch('auction', '888')
    assert calls[-1][0] == 'ESM_B'


def test_계정_전부_실패하면_사유에_계정_식별자가_모두_들어간다(monkeypatch, _no_sleep):
    from webapp.routes.bulk import category_map as CM

    _stub_calls(monkeypatch, {'ESM_A': RuntimeError('401 인증'),
                              'ESM_B': RuntimeError('404 없음')})
    fetch = CM._observe_fetcher([])
    with pytest.raises(Exception) as e:
        fetch('auction', '777')
    msg = str(e.value)
    assert 'ESM_A' in msg and 'ESM_B' in msg
    assert '401 인증' in msg and '404 없음' in msg


def test_시도한_계정_수를_market_notes에_남긴다(monkeypatch, _no_sleep):
    from webapp.routes.bulk import category_map as CM

    _stub_calls(monkeypatch, {'ESM_A': 'A1', 'ESM_B': 'A2'})
    notes = []
    CM._observe_fetcher(notes)('auction', '777')
    assert any('auction' in n and '2' in n for n in notes)


def test_코드를_못_준_계정_다음에_다른_계정을_더_본다(monkeypatch, _no_sleep):
    """None(카테고리 확인불가)도 '이 계정 상품이 아닐 수 있다' — 다음 계정을 더 본다."""
    from webapp.routes.bulk import category_map as CM

    calls = _stub_calls(monkeypatch, {'ESM_A': None, 'ESM_B': 'A1'})
    assert CM._observe_fetcher([])('auction', '777') == 'A1'
    assert [c for c, _ in calls] == ['ESM_A', 'ESM_B']


def test_전부_코드가_없으면_예외가_아니라_확인불가_None(monkeypatch, _no_sleep):
    from webapp.routes.bulk import category_map as CM

    _stub_calls(monkeypatch, {'ESM_A': None, 'ESM_B': None})
    assert CM._observe_fetcher([])('auction', '777') is None


# ── [리뷰 I5] 호출 간격은 실측 이상으로 보수적 ──────────────────────────
def test_마켓_호출간격이_저장소_실측보다_공격적이지_않다():
    from webapp.routes.bulk.category_map import OBSERVE_SLEEP

    # ESM 실 상품경로 실측 = 상품당 순차 0.68건/s → 최소 1.47초. 0.35초(2.9콜/s)는 과속.
    assert OBSERVE_SLEEP['auction'] >= 1.5
    assert OBSERVE_SLEEP['gmarket'] >= 1.5
    assert OBSERVE_SLEEP['smartstore'] >= 0.5      # 계정별 ~2.0콜/s 실측
    assert OBSERVE_SLEEP['coupang'] >= 0.2         # 문서 토큰버킷 5req/s (실측 9.7콜/s)
    assert OBSERVE_SLEEP['eleven11'] >= 0.2        # 이 경로는 미측정 — 보수적으로


# ── [리뷰 I6] 엔진이 남긴 마켓 사유를 계정 사유가 덮어쓰지 않는다 ────────
def test_엔진_사유와_계정_사유가_모두_요약에_남는다(client, monkeypatch):
    from webapp.routes.bulk import category_map as CM

    done = threading.Event()

    def _fake_fetcher(notes):
        notes.append('auction: 활성 계정이 없음')
        return lambda market, product_id: None

    def _fake(session, fetch_category, now=None, on_progress=None):
        done.set()
        out = dict(_SUMMARY)
        out['market_notes'] = ['coupang: 카테고리 사전이 비어 있음 — 먼저 수집']
        return out

    monkeypatch.setattr(CM, '_observe_fetcher', _fake_fetcher)
    monkeypatch.setattr('lemouton.registration.observed_map.build_observed_map', _fake)

    assert client.post('/bulk/api/catmap/observe').status_code == 202
    assert done.wait(10) is True
    for _ in range(50):
        st = client.get('/bulk/api/catmap/observe/status').get_json()
        if not st['running']:
            break
        threading.Event().wait(0.1)
    notes = st['last_summary']['market_notes']
    assert any('사전이 비어' in n for n in notes)
    assert any('활성 계정이 없음' in n for n in notes)
