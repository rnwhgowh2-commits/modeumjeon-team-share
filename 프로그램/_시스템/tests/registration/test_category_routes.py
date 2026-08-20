# -*- coding: utf-8 -*-
"""카테고리 사전 라우트 — status·harvest·검색.

[2026-07-22 코드리뷰 수정] harvest 는 백그라운드 스레드로 돈다(Critical: gunicorn sync
워커 60초 타임아웃 회피). POST 는 202+started 만 확인해 주고, 실제 성공/실패는
GET status 의 running/last_error/last_summary 로 폴링해서 읽는다 — 아래 테스트들은
`_run_harvest` 를 monkeypatch 한 뒤 `_wait_until()` 로 백그라운드 스레드가 끝나기를
기다리는 패턴을 공유한다.

[2026-07-22 코드리뷰 수정 #2] 실행 상태가 모듈 전역 dict 에서 DB 테이블
(MarketCategoryHarvestRun)로 옮겨갔다 — 라이브가 gunicorn 3워커라 dict 는 워커 로컬이었다.
아래 테스트들은 `cat_routes._harvest_state` 대신 `_run_row(market).running` 로 폴링한다.
"""
import datetime
import threading
import time

import pytest


def _run_row(market):
    """실행 상태 행을 DB 에서 읽는다 — 폴링용 헬퍼(매번 새 세션으로 커밋된 값을 본다)."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun
    s = SessionLocal()
    try:
        return s.query(MarketCategoryHarvestRun).filter_by(market=market).first()
    finally:
        s.close()


def _running(market):
    row = _run_row(market)
    return bool(row.running) if row else False


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    application = appmod.create_app()
    application.config['TESTING'] = True
    with application.test_client() as c:
        yield c


_SEEDED = []   # [(market, code), ...] — 이번 테스트에서 심은 행. 끝나면 정확히 이것만 지운다.


def _seed(code='1003', market='eleven11', name='여성운동화',
          path='패션잡화>운동화>여성운동화', leaf=True):
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    s.add(MarketCategory(market=market, code=code, name=name, full_path=path,
                         depth=3, is_leaf=leaf, harvested_at=datetime.datetime(2026, 7, 22)))
    s.commit(); s.close()
    _SEEDED.append((market, code))


def _wait_until(cond, timeout=2.0, step=0.05):
    """조건이 참이 될 때까지 최대 timeout 초 폴링한다 — 백그라운드 harvest 스레드 join 대체."""
    waited = 0.0
    while not cond() and waited < timeout:
        time.sleep(step)
        waited += step
    return cond()


@pytest.fixture(autouse=True)
def _cleanup_categories():
    """market_categories 는 공유 DB(개발기=SQLite, 라이브=Supabase 동일 규약) — 재실행 시
    unique(market,code) 충돌을 막기 위해 이 파일이 심은 행만 정확히 지운다.

    category_harvest_runs 는 market 이 PK(마켓당 최대 1행)라 이 파일이 건드리는 마켓
    (eleven11 이 전부) 행을 매 테스트 후 지운다 — 다음 테스트·다음 실행이 이전 테스트가
    남긴 running/started_at 을 물려받지 않게(예: 스테일 테스트가 심은 running=True 행이
    다른 409 테스트를 오염시키는 것 방지)."""
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory, MarketCategoryHarvestRun
    s = SessionLocal()
    try:
        for market, code in _SEEDED:
            row = s.query(MarketCategory).filter_by(market=market, code=code).first()
            if row is not None:
                s.delete(row)
        for run in s.query(MarketCategoryHarvestRun).filter_by(market='eleven11').all():
            s.delete(run)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _SEEDED.clear()


def test_status가_마켓별_건수와_수집시각을_준다(client):
    _seed()
    r = client.get('/bulk/api/categories/status')
    assert r.status_code == 200
    data = r.get_json()
    m = {row['market']: row for row in data['rows']}
    assert m['eleven11']['total'] >= 1
    assert m['eleven11']['last_harvested'] is not None
    assert set(m) == {'smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon'}
    # 백그라운드 수집 상태 필드도 항상 실린다 — 진행 중인 게 없으면 running=False, 에러 없음.
    assert 'running' in m['eleven11']
    assert 'last_error' in m['eleven11']
    assert 'last_summary' in m['eleven11']


def test_status에_progress_count_progress_at_started_at이_실린다(client):
    """[2026-07-23 M1 실측 후속] 수 시간 걸리는 수집이 "돌고 있는지 멈췄는지" 화면에서
    구분되도록 진행률 3필드가 status 응답에 실린다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun
    started = datetime.datetime(2026, 7, 23, 10, 0, 0)
    progressed = datetime.datetime(2026, 7, 23, 10, 5, 0)
    s = SessionLocal()
    try:
        s.add(MarketCategoryHarvestRun(market='eleven11', running=True, started_at=started,
                                        finished_at=None, summary_json=None, error=None,
                                        progress_count=42, progress_at=progressed))
        s.commit()
    finally:
        s.close()

    r = client.get('/bulk/api/categories/status')
    row = {x['market']: x for x in r.get_json()['rows']}['eleven11']
    assert row['progress_count'] == 42
    assert row['progress_at'] is not None
    assert row['started_at'] is not None


def test_harvest_모르는_마켓은_400(client):
    r = client.post('/bulk/api/categories/harvest/nosuch')
    assert r.status_code == 400


def test_harvest_시작하면_202와_started를_주고_status는_따로_폴링한다(client, monkeypatch):
    """① POST 는 결과를 기다리지 않고 즉시 202+started 만 준다(60초 타임아웃 회피 핵심)."""
    from webapp.routes.bulk import categories as cat_routes
    release = threading.Event()

    def fake_run(market, on_progress=None, on_chunk=None, progress_state=None):
        release.wait(timeout=2)   # 라우트가 이미 202 를 응답한 뒤에야 실제로 진행되게 지연
        return [{'code': 'zzh1', 'name': '테스트A', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '테스트A', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r = client.post('/bulk/api/categories/harvest/eleven11')
        assert r.status_code == 202
        assert r.get_json() == {'ok': True, 'started': True, 'market': 'eleven11'}
        # 응답이 이미 돌아왔다는 것 자체가 동기 대기가 아니었다는 증거 — 그 다음에 풀어준다.
        release.set()
        assert _wait_until(lambda: not _running('eleven11'))
    finally:
        release.set()
        _SEEDED.append(('eleven11', 'zzh1'))


def test_harvest_완료후_status에_summary가_반영된다(client, monkeypatch):
    """② 백그라운드 수집이 끝나면 GET status 의 last_summary 에 결과가 실린다."""
    from webapp.routes.bulk import categories as cat_routes

    def fake_run(market, on_progress=None, on_chunk=None, progress_state=None):
        return [{'code': 'zzh2', 'name': '테스트B', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '테스트B', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r = client.post('/bulk/api/categories/harvest/eleven11')
        assert r.status_code == 202
        assert _wait_until(lambda: not _running('eleven11'))
        r2 = client.get('/bulk/api/categories/status')
        row = {x['market']: x for x in r2.get_json()['rows']}['eleven11']
        assert row['running'] is False
        assert row['last_error'] is None
        assert row['last_summary'] == {'added': 1, 'updated': 0, 'removed': 0, 'total': 1}
    finally:
        _SEEDED.append(('eleven11', 'zzh2'))


def test_harvest_on_chunk이_오면_완주전에도_부분저장된다(client, monkeypatch):
    """[2026-07-23 체크포인트 배선] `_run_harvest` 가 완주 전에 on_chunk 를 호출하면
    `_harvest_and_save` 가 그 즉시 별도 세션으로 partial=True 저장을 실행한다 — 아직
    수집 스레드가 안 끝났는데도(release 이전) DB 에 청크 코드가 먼저 보여야 한다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    from webapp.routes.bulk import categories as cat_routes
    release = threading.Event()
    chunk_seen = threading.Event()

    def fake_run(market, on_progress=None, on_chunk=None, progress_state=None):
        on_chunk([{'code': 'zzchunk1', 'name': '청크A', 'parent_code': None, 'depth': 1,
                   'is_leaf': True, 'full_path': '청크A', 'raw': '{}'}])
        chunk_seen.set()
        release.wait(timeout=2)   # 최종 저장은 아직 — 청크 저장이 먼저 보여야 한다
        return [{'code': 'zzchunk1', 'name': '청크A', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '청크A', 'raw': '{}'},
                {'code': 'zzchunk2', 'name': '청크B', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '청크B', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r = client.post('/bulk/api/categories/harvest/eleven11')
        assert r.status_code == 202
        assert chunk_seen.wait(timeout=2)

        def _chunk_row_exists():
            s = SessionLocal()
            try:
                return s.query(MarketCategory).filter_by(market='eleven11', code='zzchunk1').first() is not None
            finally:
                s.close()
        assert _wait_until(_chunk_row_exists)         # 최종 저장 전인데 이미 DB 에 있다
        assert _running('eleven11')                    # 아직 진행 중(최종 저장 전)

        release.set()
        assert _wait_until(lambda: not _running('eleven11'))
        s = SessionLocal()
        try:
            row2 = s.query(MarketCategory).filter_by(market='eleven11', code='zzchunk2').one()
            assert row2.removed_at is None
        finally:
            s.close()
    finally:
        release.set()
        _SEEDED.append(('eleven11', 'zzchunk1'))
        _SEEDED.append(('eleven11', 'zzchunk2'))


def test_harvest_진행중이면_중복_POST는_409(client, monkeypatch):
    """③ 같은 마켓이 이미 수집 중이면 두 번째 POST 는 409(레이스 방지)."""
    from webapp.routes.bulk import categories as cat_routes
    hold = threading.Event()

    def fake_run(market, on_progress=None, on_chunk=None, progress_state=None):
        hold.wait(timeout=2)
        return [{'code': 'zzh3', 'name': '테스트C', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '테스트C', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r1 = client.post('/bulk/api/categories/harvest/eleven11')
        assert r1.status_code == 202
        r2 = client.post('/bulk/api/categories/harvest/eleven11')
        assert r2.status_code == 409
        assert r2.get_json() == {'ok': False, 'error': 'eleven11: 이미 수집이 진행 중입니다'}
    finally:
        hold.set()
        assert _wait_until(lambda: not _running('eleven11'))
        _SEEDED.append(('eleven11', 'zzh3'))


def test_harvest_progress_at없이_started_at만_오래됐으면_회수해서_202(client, monkeypatch):
    """③-2 [멀티워커 대비] progress_at 이 아예 없는(구 실행·단발 마켓 등) running=True 행은
    started_at 으로 스테일을 판정한다 — 10분보다 오래됐으면 죽은 실행으로 보고 새 POST 가
    회수한다(409 아님). 워커 재시작으로 데몬 스레드가 죽으면 running=True 가 영영 안
    지워지는 케이스를 이걸로 구제한다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun
    stale_started = datetime.datetime.utcnow() - datetime.timedelta(minutes=11)
    s = SessionLocal()
    try:
        s.add(MarketCategoryHarvestRun(market='eleven11', running=True,
                                        started_at=stale_started, finished_at=None,
                                        summary_json=None, error=None))
        s.commit()
    finally:
        s.close()

    from webapp.routes.bulk import categories as cat_routes
    hold = threading.Event()

    def fake_run(market, on_progress=None, on_chunk=None, progress_state=None):
        hold.wait(timeout=2)
        return [{'code': 'zzh4', 'name': '테스트D', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '테스트D', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r = client.post('/bulk/api/categories/harvest/eleven11')
        assert r.status_code == 202
        assert r.get_json() == {'ok': True, 'started': True, 'market': 'eleven11'}
    finally:
        hold.set()
        assert _wait_until(lambda: not _running('eleven11'))
        _SEEDED.append(('eleven11', 'zzh4'))


def test_harvest_progress_at가_10분_넘게_안_움직이면_회수해서_202(client, monkeypatch):
    """[2026-07-23 실측 사고 대응] 쿠팡처럼 수 시간 걸리는 수집이 죽었는지 판정하는 핵심
    시나리오 — started_at 은 방금(살아있는 척)인데 progress_at 이 10분 넘게 안 움직였으면
    (실측: 1,534건에서 22분 정지) 죽은 실행으로 보고 새 POST 가 회수한다. progress_at 이
    있으면 started_at 이 아무리 최근이어도 progress_at 을 기준으로 판정한다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun
    now = datetime.datetime.utcnow()
    s = SessionLocal()
    try:
        s.add(MarketCategoryHarvestRun(market='eleven11', running=True,
                                        started_at=now - datetime.timedelta(minutes=1),
                                        progress_at=now - datetime.timedelta(minutes=11),
                                        progress_count=1534, finished_at=None,
                                        summary_json=None, error=None))
        s.commit()
    finally:
        s.close()

    from webapp.routes.bulk import categories as cat_routes
    hold = threading.Event()

    def fake_run(market, on_progress=None, on_chunk=None, progress_state=None):
        hold.wait(timeout=2)
        return [{'code': 'zzh4b', 'name': '테스트D2', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '테스트D2', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r = client.post('/bulk/api/categories/harvest/eleven11')
        assert r.status_code == 202
        assert r.get_json() == {'ok': True, 'started': True, 'market': 'eleven11'}
    finally:
        hold.set()
        assert _wait_until(lambda: not _running('eleven11'))
        _SEEDED.append(('eleven11', 'zzh4b'))


def test_harvest_progress_at가_최근이면_10분_안됐어도_409(client, monkeypatch):
    """progress_at 이 방금 갱신됐으면(=살아있는 진짜 실행) 10분 문턱과 무관하게 새 POST 는
    409 — 진행 중인 실행을 뺏지 않는다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun
    now = datetime.datetime.utcnow()
    s = SessionLocal()
    try:
        s.add(MarketCategoryHarvestRun(market='eleven11', running=True,
                                        started_at=now - datetime.timedelta(hours=1),
                                        progress_at=now - datetime.timedelta(seconds=5),
                                        progress_count=999, finished_at=None,
                                        summary_json=None, error=None))
        s.commit()
    finally:
        s.close()

    r = client.post('/bulk/api/categories/harvest/eleven11')
    assert r.status_code == 409
    assert r.get_json() == {'ok': False, 'error': 'eleven11: 이미 수집이 진행 중입니다'}


def test_harvest_새_실행_클레임시_이전_진행률이_리셋된다(client, monkeypatch):
    """I7 — 지난 실행이 남긴 progress_count/progress_at 이 새 실행 시작 직후(202 응답
    시점)에 바로 비워진다. 안 비우면 재시작 직후에도 "3120건째 · 400분 전"이 화면에
    남아 "지금 이 실행"의 진행률이라는 착시를 준다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun
    stale_progress_at = datetime.datetime(2026, 7, 20, 0, 0, 0)
    s = SessionLocal()
    try:
        s.add(MarketCategoryHarvestRun(market='eleven11', running=False, started_at=None,
                                        finished_at=datetime.datetime(2026, 7, 20, 0, 5, 0),
                                        summary_json=None, error=None,
                                        progress_count=3120, progress_at=stale_progress_at))
        s.commit()
    finally:
        s.close()

    from webapp.routes.bulk import categories as cat_routes
    hold = threading.Event()

    def fake_run(market, on_progress=None, on_chunk=None, progress_state=None):
        hold.wait(timeout=2)
        return [{'code': 'zzh5', 'name': '테스트E', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '테스트E', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        r = client.post('/bulk/api/categories/harvest/eleven11')
        assert r.status_code == 202
        # 백그라운드 스레드가 아직 진행률을 쓰지 않았을(hold 로 붙잡아 둔) 시점에도
        # 클레임 자체가 이전 값을 지워야 한다.
        row = _run_row('eleven11')
        assert row.progress_count is None
        assert row.progress_at is None
    finally:
        hold.set()
        assert _wait_until(lambda: not _running('eleven11'))
        _SEEDED.append(('eleven11', 'zzh5'))


def test_harvest_HarvestError는_state_error에_원문으로_노출된다(client, monkeypatch):
    """④ _run_harvest 가 HarvestError 를 던지면 조용히 삼키지 않고 status.last_error 에 원문 사유."""
    from lemouton.registration import category_harvest as ch
    from webapp.routes.bulk import categories as cat_routes

    def boom(market, on_progress=None, on_chunk=None, progress_state=None):
        raise ch.HarvestError('IP 미등록 403: 원문사유')

    monkeypatch.setattr(cat_routes, '_run_harvest', boom)
    r = client.post('/bulk/api/categories/harvest/eleven11')
    assert r.status_code == 202
    assert _wait_until(lambda: not _running('eleven11'))
    r2 = client.get('/bulk/api/categories/status')
    row = {x['market']: x for x in r2.get_json()['rows']}['eleven11']
    assert row['running'] is False
    assert '원문사유' in row['last_error']


def test_harvest_저장단계_실패도_state_error에_원문으로_노출된다(client, monkeypatch):
    """save_snapshot 이 배치 내 중복코드로 HarvestError 를 던지는 경우도 500 이 아니라
    status.last_error 로 사유가 노출된다(조용한 500 금지)."""
    from webapp.routes.bulk import categories as cat_routes

    def fake_rows(market, on_progress=None, on_chunk=None, progress_state=None):
        return [{'code': 'zzdup', 'name': '가', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '가', 'raw': '{}'},
                {'code': 'zzdup', 'name': '가또', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '가또', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_rows)
    r = client.post('/bulk/api/categories/harvest/eleven11')
    assert r.status_code == 202
    assert _wait_until(lambda: not _running('eleven11'))
    r2 = client.get('/bulk/api/categories/status')
    row = {x['market']: x for x in r2.get_json()['rows']}['eleven11']
    assert row['running'] is False
    assert '중복' in row['last_error']


# ── [2026-07-23 사고 #5] 콜 예산 자기종료 — "미완이면 partial 저장" 이 최우선 안전장치 ──
def _cat_row(market, code):
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    try:
        return s.query(MarketCategory).filter_by(market=market, code=code).first()
    finally:
        s.close()


def test_harvest_미완이면_partial저장이라_아직_안훑은_카테고리가_removed되지_않는다(client, monkeypatch):
    """★ 이 수정에서 가장 중요한 안전장치. 콜 예산을 다 써서 큐가 남은 채 끝난 실행의
    rows 는 "지금 존재하는 카테고리 전체"가 아니라 "이번에 훑은 일부"다. 이걸 partial=False
    로 저장하면 아직 안 훑은 카테고리가 전부 removed_at 으로 마킹되고 그걸 가리키던
    맵핑까지 re_confirm 으로 강등되는 대참사가 난다 — 미완이면 반드시 partial=True."""
    from webapp.routes.bulk import categories as cat_routes
    _seed(code='zzkeep1', name='아직안훑음', path='아직안훑음')

    def fake_run(market, on_progress=None, on_chunk=None, progress_state=None):
        if progress_state is not None:
            progress_state['incomplete'] = True     # 예산 소진 = 미완
            progress_state['calls'] = 150
            progress_state['pending'] = 812
        return [{'code': 'zzpart1', 'name': '이번에훑음', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '이번에훑음', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        assert client.post('/bulk/api/categories/harvest/eleven11').status_code == 202
        assert _wait_until(lambda: not _running('eleven11'))
        assert _cat_row('eleven11', 'zzpart1') is not None      # 이번 몫은 남았고
        assert _cat_row('eleven11', 'zzkeep1').removed_at is None   # ★ 사라졌다고 마킹 안 됨
    finally:
        _SEEDED.append(('eleven11', 'zzpart1'))


def test_harvest_완주하면_사라진_코드를_removed로_마킹한다(client, monkeypatch):
    """반대편 — 완주(incomplete 없음)했을 때만 전량 기준 removed 마킹이 돈다. 이걸 안 하면
    실제로 없어진 카테고리가 confirmed 로 방치돼 존재하지 않는 코드로 등록이 나간다."""
    from webapp.routes.bulk import categories as cat_routes
    _seed(code='zzgone1', name='진짜사라짐', path='진짜사라짐')

    def fake_run(market, on_progress=None, on_chunk=None, progress_state=None):
        if progress_state is not None:
            progress_state['incomplete'] = False    # 완주
        return [{'code': 'zzfull1', 'name': '전량', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '전량', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        assert client.post('/bulk/api/categories/harvest/eleven11').status_code == 202
        assert _wait_until(lambda: not _running('eleven11'))
        assert _cat_row('eleven11', 'zzgone1').removed_at is not None
    finally:
        _SEEDED.append(('eleven11', 'zzfull1'))


def test_harvest_미완이면_status_incomplete가_True고_완주해야만_False(client, monkeypatch):
    """미완을 「완료」로 칠하지 않는다 — 화면(설정 탭 카드)이 "이어받는 중" 으로 보여줄 근거."""
    from webapp.routes.bulk import categories as cat_routes
    flag = {'incomplete': True}

    def fake_run(market, on_progress=None, on_chunk=None, progress_state=None):
        if progress_state is not None:
            progress_state['incomplete'] = flag['incomplete']
        return [{'code': 'zzinc1', 'name': '조금', 'parent_code': None, 'depth': 1,
                 'is_leaf': True, 'full_path': '조금', 'raw': '{}'}]

    monkeypatch.setattr(cat_routes, '_run_harvest', fake_run)
    try:
        assert client.post('/bulk/api/categories/harvest/eleven11').status_code == 202
        assert _wait_until(lambda: not _running('eleven11'))
        row = {x['market']: x for x in client.get(
            '/bulk/api/categories/status').get_json()['rows']}['eleven11']
        assert row['incomplete'] is True
        assert row['last_error'] is None            # 실패가 아니다 — 정상 종료다

        flag['incomplete'] = False                  # 이어받아 완주한 다음 실행
        assert client.post('/bulk/api/categories/harvest/eleven11').status_code == 202
        assert _wait_until(lambda: not _running('eleven11'))
        row2 = {x['market']: x for x in client.get(
            '/bulk/api/categories/status').get_json()['rows']}['eleven11']
        assert row2['incomplete'] is False
    finally:
        _SEEDED.append(('eleven11', 'zzinc1'))


def test_status는_실행행이_없어도_incomplete를_False로_준다(client):
    """수집 전 마켓도 필드가 빠지지 않는다(카드 JS 가 undefined 로 분기하지 않게)."""
    row = {x['market']: x for x in client.get(
        '/bulk/api/categories/status').get_json()['rows']}['smartstore']
    assert row['incomplete'] is False


def test__run_harvest가_쿠팡에만_콜예산과_progress_state를_넘긴다(client, monkeypatch):
    """실행당 콜 예산은 쿠팡 분기에서만 준다(상수 근거는 categories.py 주석). 다른 마켓은
    단발 호출이거나 완주 시간이 짧아 예산이 필요 없다."""
    from lemouton.registration import category_harvest as ch
    from webapp.routes.bulk import categories as cat_routes
    import lemouton.uploader.market_fetch as MF

    # 예산은 **유한**해야 한다 — 무한이면 「스스로 끝낸다」는 설계가 무너지고 다시
    # 죽어서 끝나는(=최종 저장 유실) 옛 사고로 돌아간다.
    # 상한 근거: 콜 1개 ≈ 0.4~0.7s 이므로 1000콜 ≈ 7~12분. gunicorn 워커 재활용
    # (`--max-requests 1000`)을 감안하면 그보다 길게 잡는 건 「완주 기대」이지 예산이 아니다.
    # [2026-07-23] 옛 상한 300 은 「스왑 없는 2GB 램에서 2~3분 만에 죽는다」는 실측에
    # 묶여 있었는데, 그 원인(OOM)이 제거돼 근거가 사라졌다 — 상한의 근거를 바꿔 단다.
    assert 0 < cat_routes.COUPANG_MAX_CALLS_PER_RUN <= 1000
    monkeypatch.setattr(cat_routes, '_first_env_prefix', lambda s, m: 'COUPANG')
    monkeypatch.setattr(MF, '_coupang_client', lambda prefix: object())
    monkeypatch.setattr(cat_routes, '_build_coupang_known', lambda s: {})
    got = {}

    def fake_harvest(fetch, sleep, **kw):
        got.update(kw)
        kw['progress_state']['incomplete'] = True
        return []

    monkeypatch.setattr(ch, 'harvest_coupang', fake_harvest)
    state = {}
    assert cat_routes._run_harvest('coupang', progress_state=state) == []
    assert got['max_calls'] == cat_routes.COUPANG_MAX_CALLS_PER_RUN
    assert got['progress_state'] is state
    assert state['incomplete'] is True


def test__build_coupang_known이_DB에서_리프_비리프_children을_구성한다(client):
    """[2026-07-23 이어받기] `_build_coupang_known` 이 market_categories(coupang)를 읽어
    harvest_coupang(known=...) 형태로 조립한다 — 리프는 children=[], 비-리프는 실제 자식
    코드 목록이 채워진다."""
    from shared.db import SessionLocal
    from webapp.routes.bulk import categories as cat_routes
    _seed(code='c10', market='coupang', name='패션잡화', path='패션잡화', leaf=False)
    _seed(code='c101', market='coupang', name='여성운동화', path='패션잡화>여성운동화', leaf=True)
    _seed(code='c102', market='coupang', name='남성운동화', path='패션잡화>남성운동화', leaf=True)
    # DB 에 parent_code 를 직접 채운다(_seed 헬퍼는 parent_code 인자를 안 받음).
    s = SessionLocal()
    try:
        from lemouton.registration.models import MarketCategory
        (s.query(MarketCategory).filter_by(market='coupang', code='c101')
         .update({'parent_code': 'c10'}))
        (s.query(MarketCategory).filter_by(market='coupang', code='c102')
         .update({'parent_code': 'c10'}))
        s.commit()

        known = cat_routes._build_coupang_known(s)
        assert known['c10']['is_leaf'] is False
        assert sorted(known['c10']['children']) == ['c101', 'c102']
        assert known['c101']['is_leaf'] is True
        assert known['c101']['children'] == []
        assert known['c102']['is_leaf'] is True
    finally:
        s.close()


def test__build_coupang_known이_비어있으면_빈_dict(client):
    """첫 수집(테이블에 coupang 행이 아예 없음)이면 known 이 비어 — 기존 전체 탐색과 동일."""
    from shared.db import SessionLocal
    from webapp.routes.bulk import categories as cat_routes
    s = SessionLocal()
    try:
        known = cat_routes._build_coupang_known(s)
        assert known == {}
    finally:
        s.close()


def test_검색이_사전에서_리프만_경로포함으로_돌려준다(client):
    _seed()   # eleven11 여성운동화 리프
    _seed(code='1002', name='운동화', path='패션잡화>운동화', leaf=False)
    r = client.get('/bulk/api/category-search?market=eleven11&q=운동화')
    data = r.get_json()
    assert data['ok'] is True
    assert [row['code'] for row in data['rows']] == ['1003']       # 리프만
    assert data['rows'][0]['path'] == '패션잡화>운동화>여성운동화'  # 경로 동봉


def test_검색어에_퍼센트가_있으면_LIKE_와일드카드가_아닌_리터럴로_매치한다(client):
    """Minor 4 — q 의 %/_/\\ 를 이스케이프하지 않으면 '90%' 검색이 '90 뒤에 아무거나'로
    번져 무관한 카테고리까지 걸린다. 이스케이프 후에는 리터럴 '90%' 를 포함한 것만 걸린다."""
    _seed(code='zzpct', name='90% 할인 운동화', path='패션잡화>운동화>90% 할인 운동화')
    _seed(code='zzpctx', name='90XYZ 할인 운동화', path='패션잡화>운동화>90XYZ 할인 운동화')
    r = client.get('/bulk/api/category-search', query_string={'market': 'eleven11', 'q': '90%'})
    data = r.get_json()
    assert data['ok'] is True
    assert [row['code'] for row in data['rows']] == ['zzpct']


def test_설정탭에_카테고리사전_카드가_뜬다(client):
    r = client.get('/bulk/?tab=settings')
    assert r.status_code == 200
    assert 'cat-dict-root' in r.get_data(as_text=True)


def test_검색은_사전이_비면_수집안내를_준다(client):
    # 실존하지 않는(영원히 수집될 일 없는) 마켓명 — 실제 마켓명(coupang 등)을 쓰면 Task 12
    # 라이브 수집 이후 사전이 채워져 이 테스트가 영구히 깨진다(시한폭탄, 리뷰 지적).
    r = client.get('/bulk/api/category-search?market=zz-never-harvested&q=운동화')
    data = r.get_json()
    assert data['ok'] is False
    assert '수집' in data['error']       # "설정 탭에서 카테고리 수집 먼저" 안내


def test_진행이_멈춘_수집은_status가_멈췄다고_말한다(client):
    """[2026-07-23 라이브 사고] 배포로 백그라운드 스레드가 죽었는데 카드는 116분째
    「수집 중…」을 띄우고 있었다 — 하지도 않는 일을 하고 있다고 말한 것이다.

    회수 기준(STALE_AFTER)과 화면 표시가 갈리면 「멈췄다는데 재수집이 409」 같은
    모순이 생기므로, 판정은 **서버가 회수와 같은 기준으로** 내려서 내려보낸다.
    """
    import webapp.routes.bulk.categories as cat_routes
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun

    s = SessionLocal()
    try:
        row = s.query(MarketCategoryHarvestRun).filter_by(market='coupang').first()
        if row is None:
            row = MarketCategoryHarvestRun(market='coupang')
            s.add(row)
        row.running = True
        row.error = None
        row.progress_count = 42
        row.progress_at = (datetime.datetime.utcnow()
                           - cat_routes.STALE_AFTER - datetime.timedelta(minutes=1))
        row.started_at = row.progress_at
        s.commit()
    finally:
        s.close()

    r = client.get('/bulk/api/categories/status')
    got = {x['market']: x for x in r.get_json()['rows']}['coupang']
    assert got['running'] is True        # 상태 행은 그대로 둔다(회수는 새 POST 의 몫)
    assert got['stalled'] is True        # 화면엔 「멈춘 것 같습니다」로 뜬다


def test_방금_진행한_수집은_멈춘_것으로_치지_않는다(client):
    """살아 있는 수집을 「멈췄다」고 하면 사장님이 멀쩡한 작업을 다시 눌러 뺏는다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun

    s = SessionLocal()
    try:
        row = s.query(MarketCategoryHarvestRun).filter_by(market='coupang').first()
        if row is None:
            row = MarketCategoryHarvestRun(market='coupang')
            s.add(row)
        row.running = True
        row.error = None
        row.progress_count = 7
        row.progress_at = datetime.datetime.utcnow()
        row.started_at = row.progress_at
        s.commit()
    finally:
        s.close()

    r = client.get('/bulk/api/categories/status')
    got = {x['market']: x for x in r.get_json()['rows']}['coupang']
    assert got['stalled'] is False


def test_안_돌고_있으면_멈춘_것도_아니다(client):
    """끝난 수집(running=False)은 「멈춤」이 아니라 그냥 완료/이어받는 중이다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategoryHarvestRun

    s = SessionLocal()
    try:
        row = s.query(MarketCategoryHarvestRun).filter_by(market='coupang').first()
        if row is None:
            row = MarketCategoryHarvestRun(market='coupang')
            s.add(row)
        row.running = False
        row.progress_at = (datetime.datetime.utcnow() - datetime.timedelta(days=1))
        s.commit()
    finally:
        s.close()

    r = client.get('/bulk/api/categories/status')
    got = {x['market']: x for x in r.get_json()['rows']}['coupang']
    assert got['stalled'] is False


def _seed_search_rank(client):
    """검색 순서 회귀용 씨앗 — 가나다순으로는 「식품/생활」이 「패션」보다 앞선다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    try:
        s.query(MarketCategory).filter_by(market='zz-rank').delete()
        rows = [
            # (code, name, full_path)
            ('C1', '초코바/스니커즈', '식품>스낵>초콜릿>초코바/스니커즈'),
            ('C2', '운동화크리너/세제', '생활용품>세제>세탁세제>운동화크리너/세제'),
            ('C3', '남성스니커즈', '패션의류잡화>남성패션>남성화>남성스니커즈'),
            ('C4', '스니커즈', '패션의류잡화>여성패션>여성화>스니커즈'),
            ('C5', '스니커즈양말', '패션의류잡화>남성패션>양말>스니커즈양말'),
        ]
        for code, name, path in rows:
            s.add(MarketCategory(market='zz-rank', code=code, name=name,
                                 full_path=path, depth=path.count('>') + 1,
                                 is_leaf=True,
                                 harvested_at=datetime.datetime(2026, 7, 24)))
        s.commit()
    finally:
        s.close()


def test_검색은_이름이_정확히_같은_카테고리를_맨_위에_둔다(client):
    """[2026-07-24 라이브 실측] 「스니커즈」를 찾으면 초코바(스니커즈 초콜릿)가 1등이었다.

    경로 가나다순 정렬이라 「식품」이 「패션」보다 앞섰기 때문이다. 사장님이 맨 위를
    고르면 신발이 과자 카테고리로 올라간다 — 화면이 잘못된 선택을 유도하면 안 된다.
    """
    _seed_search_rank(client)
    r = client.get('/bulk/api/category-search',
                   query_string={'market': 'zz-rank', 'q': '스니커즈'})
    data = r.get_json()
    assert data['ok'] is True
    paths = [x['path'] for x in data['rows']]
    assert paths[0].endswith('>스니커즈')        # 이름이 정확히 같은 것
    assert '초코바' not in paths[0]


def test_검색_상한은_관련도_정렬_뒤에_적용된다(client):
    """상한을 먼저 자르면 관련 없는 카테고리로 자리가 다 차서 진짜 후보가 사라진다.

    [실측] 쿠팡 「티셔츠」 30건이 반려동물 옷·야구복으로 채워지고 의류는 안 보였다.
    """
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    try:
        s.query(MarketCategory).filter_by(market='zz-cut').delete()
        # 가나다순으로 앞서는 무관한 리프를 상한(30)보다 많이 깔아 둔다.
        for i in range(40):
            s.add(MarketCategory(market='zz-cut', code=f'A{i:03d}',
                                 name=f'가공품{i:03d}티셔츠포장',
                                 full_path=f'가공식품>포장재>가공품{i:03d}티셔츠포장',
                                 depth=3, is_leaf=True,
                                 harvested_at=datetime.datetime(2026, 7, 24)))
        s.add(MarketCategory(market='zz-cut', code='Z1', name='티셔츠',
                             full_path='패션의류>남성의류>티셔츠', depth=3,
                             is_leaf=True,
                             harvested_at=datetime.datetime(2026, 7, 24)))
        s.commit()
    finally:
        s.close()

    r = client.get('/bulk/api/category-search',
                   query_string={'market': 'zz-cut', 'q': '티셔츠'})
    data = r.get_json()
    paths = [x['path'] for x in data['rows']]
    assert '패션의류>남성의류>티셔츠' in paths          # 잘려 나가면 안 된다
    assert paths[0] == '패션의류>남성의류>티셔츠'       # 정확히 같은 이름이 1등


def test_검색은_전체_몇건인지_알려준다(client):
    """상한에 걸렸는지 사장님이 알아야 「더 좁혀 검색」할 수 있다."""
    _seed_search_rank(client)
    r = client.get('/bulk/api/category-search',
                   query_string={'market': 'zz-rank', 'q': '스니커즈'})
    data = r.get_json()
    assert data['total'] == 4          # 세제(운동화크리너)는 '스니커즈' 를 안 가짐
    assert data['count'] == len(data['rows'])


def test_검색은_뒷말이_같은_것을_앞말이_같은_것보다_위에_둔다(client):
    """한국어·영어 합성어는 **뒤에 오는 말이 진짜 정체**다.

    「운동화크리너」는 크리너이지 운동화가 아니고, 「남성운동화」는 운동화다.
    [2026-07-24 라이브] 첫 수정 뒤에도 「운동화」 1위가 `세탁세제>운동화크리너/세제`
    였다 — 「~로 시작」을 「~로 끝남」보다 위에 뒀기 때문이다.
    """
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    try:
        s.query(MarketCategory).filter_by(market='zz-head').delete()
        for code, name, path in [
            ('H1', '운동화크리너/세제', '생활용품>세제>세탁세제>운동화크리너/세제'),
            ('H2', '남성운동화', '패션의류>남성패션>신발>남성운동화'),
        ]:
            s.add(MarketCategory(market='zz-head', code=code, name=name, full_path=path,
                                 depth=path.count('>') + 1, is_leaf=True,
                                 harvested_at=datetime.datetime(2026, 7, 24)))
        s.commit()
    finally:
        s.close()

    r = client.get('/bulk/api/category-search',
                   query_string={'market': 'zz-head', 'q': '운동화'})
    paths = [x['path'] for x in r.get_json()['rows']]
    assert paths[0].endswith('>남성운동화')
    assert '크리너' not in paths[0]


def test_검색어를_두_단어로_좁힐_수_있다(client):
    """[2026-07-24 라이브] 화면이 「검색어를 좁혀 주세요」라고 안내하는데, 정작
    「남성의류 티셔츠」로 좁히면 **0건**이었다 — 경로 전체를 한 덩어리로만 훑어서
    두 단어가 붙어 있는 경로가 없으면 아무것도 못 찾았다. 우리가 준 안내가 작동하지
    않는 상태였다. 이제 띄어쓴 말은 **각각** 경로 어딘가에 있으면 된다(그리고 조건).
    """
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    try:
        s.query(MarketCategory).filter_by(market='zz-multi').delete()
        for code, name, path in [
            ('M1', '티셔츠', '반려/애완용품>강아지/고양이>의류>티셔츠'),
            ('M2', '남성 카라티셔츠', '패션의류잡화>남성패션>남성의류>티셔츠>남성 카라티셔츠'),
            ('M3', '여아 카라티셔츠', '패션의류잡화>주니어의류>여아의류>티셔츠>여아 카라티셔츠'),
        ]:
            s.add(MarketCategory(market='zz-multi', code=code, name=name, full_path=path,
                                 depth=path.count('>') + 1, is_leaf=True,
                                 harvested_at=datetime.datetime(2026, 7, 24)))
        s.commit()
    finally:
        s.close()

    r = client.get('/bulk/api/category-search',
                   query_string={'market': 'zz-multi', 'q': '남성의류 티셔츠'})
    data = r.get_json()
    paths = [x['path'] for x in data['rows']]
    assert len(paths) == 1
    assert '남성의류' in paths[0] and '티셔츠' in paths[0]


def test_두_단어_검색도_뒷말_기준으로_줄_세운다(client):
    """여러 단어를 넣으면 **마지막 말**이 찾는 물건이다(우리말은 뒤가 정체).

    「패션 티셔츠」면 이름이 「티셔츠」인 것이 「티셔츠수납함」보다 위여야 한다.
    """
    from shared.db import SessionLocal
    from lemouton.registration.models import MarketCategory
    s = SessionLocal()
    try:
        s.query(MarketCategory).filter_by(market='zz-multi2').delete()
        for code, name, path in [
            ('N1', '티셔츠수납함', '패션잡화>정리용품>티셔츠수납함'),
            ('N2', '티셔츠', '패션잡화>남성의류>티셔츠'),
        ]:
            s.add(MarketCategory(market='zz-multi2', code=code, name=name, full_path=path,
                                 depth=path.count('>') + 1, is_leaf=True,
                                 harvested_at=datetime.datetime(2026, 7, 24)))
        s.commit()
    finally:
        s.close()

    r = client.get('/bulk/api/category-search',
                   query_string={'market': 'zz-multi2', 'q': '패션잡화 티셔츠'})
    paths = [x['path'] for x in r.get_json()['rows']]
    assert paths[0].endswith('>티셔츠')
