# -*- coding: utf-8 -*-
"""폰 크롤 리모컨의 'PC 연결됨' 판정.

생존 신호는 **확장이 실제로 부르는 곳**에만 실린다 = /api/crawl/due-bundles.
/api/crawl/queue 는 확장이 아니라 PC 자동화 화면 JS 가 1.5초마다 부르는 곳이라,
거기에 붙이면 확장이 꺼져 있어도 '🟢 PC 연결됨'이 뜬다 — 사장님이 '눌러도 아무 일
없는 버튼'을 누르게 된다. 그게 이 설계에서 가장 나쁜 결과다.
"""
from datetime import datetime, timedelta, timezone

import pytest

# 시험용 고정 시각 — 시계는 now= 로 주입한다(DB 행을 직접 고치지 않는다).
T0 = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)

PC_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36'
PHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile/15E148'


@pytest.fixture
def db():
    from shared.db import SessionLocal, Base, engine
    Base.metadata.create_all(engine)
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_touch_throttle():
    """프로세스 로컬 문지기(_last_touch_monotonic)는 모듈 전역이라 시험 간에 샌다.

    풀어 두지 않으면 앞 시험이 잠가 둔 30초 때문에 뒷 시험의 첫 기록이 조용히 건너뛰어진다.
    """
    from lemouton.sourcing import crawl_queue as q
    q._last_touch_monotonic = 0.0
    yield
    q._last_touch_monotonic = 0.0


def _clear(s):
    """우리 센티널 행만 지운다.

    ★ crawl_workers 를 통째로 비우지 않는다 — DATABASE_URL 이 환경에 이미 있으면
      conftest 의 임시 DB 격리가 꺼져서 실제 워커 등록부가 날아간다.
    """
    from lemouton.sourcing.models import CrawlWorker
    from lemouton.sourcing import crawl_queue as q
    s.query(CrawlWorker).filter(CrawlWorker.name == q.CRAWL_PC_NAME).delete()
    s.commit()


def test_아무도_안_왔으면_PC는_꺼진_것으로_본다(db):
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    got = q.worker_presence()
    assert got["online"] is False
    assert got["last_seen_at"] is None
    assert got["seconds_ago"] is None


def test_한_번_다녀가면_PC가_켜진_것으로_본다(db):
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4", now=T0)
    got = q.worker_presence(now=T0 + timedelta(seconds=5))
    assert got["online"] is True
    assert got["seconds_ago"] == 5


def test_확장_폴링_주기_1분은_여유롭게_온라인이다(db):
    """확장은 1분에 한 번 부른다. 90초 창이면 한 번만 늦어도 깜빡였다."""
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4", now=T0)
    assert q.worker_presence(now=T0 + timedelta(seconds=90))["online"] is True
    assert q.worker_presence(now=T0 + timedelta(seconds=179))["online"] is True


def test_180초를_넘기면_꺼진_것으로_본다(db):
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4", now=T0)
    assert q.worker_presence(now=T0 + timedelta(seconds=181))["online"] is False
    assert q.worker_presence(now=T0 + timedelta(seconds=600))["online"] is False


def test_30초_안에_다시_오면_DB를_안_고친다(db):
    """확장이 자주 불러도 매번 쓰지 않는다."""
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4", now=T0)
    assert q.worker_presence(now=T0)["last_seen_at"] == T0.isoformat()

    q.touch_worker_heartbeat(ip_address="1.2.3.4", now=T0 + timedelta(seconds=10))
    assert q.worker_presence(now=T0)["last_seen_at"] == T0.isoformat(), "30초 안에 두 번 썼다"

    later = T0 + timedelta(seconds=31)
    q.touch_worker_heartbeat(ip_address="1.2.3.4", now=later)
    assert q.worker_presence(now=later)["last_seen_at"] == later.isoformat(), "30초 지나면 갱신돼야 한다"


def test_30초_안에는_DB_세션을_열지도_않는다(db, monkeypatch):
    """폴링마다 SELECT 왕복을 하면 Supabase 무료 티어에 불필요한 부하다."""
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4")      # 실시계 — 문지기가 잠긴다

    def _boom():
        raise AssertionError("DB 세션을 열었다 — 프로세스 로컬 문지기가 안 걸렸다")

    monkeypatch.setattr(q, "SessionLocal", _boom)
    q.touch_worker_heartbeat(ip_address="1.2.3.4")      # 세션을 열지 않고 즉시 반환해야 함


def test_동시_폴링_두_건이_같은_행을_만들려_해도_안_터진다(db, monkeypatch):
    """둘 다 '행 없음'을 보면 name 유니크에 걸린다 — 진 쪽은 UPDATE 로 승계해야 한다."""
    from lemouton.sourcing import crawl_queue as q
    from lemouton.sourcing.models import CrawlWorker
    _clear(db)
    # 경쟁자가 방금 만들어 둔 행(60초 전 신호)
    db.add(CrawlWorker(name=q.CRAWL_PC_NAME,
                       last_heartbeat_at=(T0 - timedelta(seconds=60)).replace(tzinfo=None)))
    db.commit()

    real_session_local = q.SessionLocal
    seen = {"n": 0}

    class _Blind:
        """첫 조회만 '행 없음'으로 속인다 — 두 폴링이 겹친 그 순간의 재현."""
        def filter(self, *a, **kw):
            return self

        def first(self):
            return None

    class _RaceSession:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def query(self, *a, **kw):
            if seen["n"] == 0:
                seen["n"] = 1
                return _Blind()
            return self._inner.query(*a, **kw)

    monkeypatch.setattr(q, "SessionLocal", lambda: _RaceSession(real_session_local()))
    q.touch_worker_heartbeat(ip_address="9.9.9.9", now=T0)   # INSERT 실패 → 승계

    monkeypatch.undo()
    assert q.worker_presence(now=T0)["last_seen_at"] == T0.isoformat(), "승계 UPDATE 가 안 됨"


def test_폰에서_연_화면은_PC로_치지_않는다(db):
    """사장님이 폰으로 PC용 자동화 화면을 열어도 'PC 연결됨'이 되면 안 된다."""
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4", user_agent=PHONE_UA, now=T0)
    assert q.worker_presence(now=T0)["online"] is False


def test_온라인_판정은_워커목록과_리모컨이_같은_규칙을_쓴다(db):
    """규칙이 두 벌이면 화면마다 다른 답을 낸다.

    워커 목록(online_workers)이 쓰는 _is_online 과 리모컨(worker_presence)의 답을
    직접 맞대 본다 — 목록에 우리 센티널이 섞여 있는지와는 무관하게 성립해야 한다.
    """
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4", now=T0)
    stamp = T0.replace(tzinfo=None)          # DB 에 저장되는 모양(naive UTC)

    fresh = T0 + timedelta(seconds=5)
    stale = T0 + timedelta(seconds=600)
    assert q._is_online(stamp, fresh) is True
    assert q.worker_presence(now=fresh)["online"] is True
    assert q._is_online(stamp, stale) is False
    assert q.worker_presence(now=stale)["online"] is False


def test_센티널은_워커_목록에_안_섞인다(db):
    """__crawl_poll__ 은 사람이 등록한 PC 가 아니라 '폴링이 다녀갔다'는 표식이다.

    '크롤 PC 목록' 화면이 생기면 사장님 눈에 정체불명 워커로 뜬다.
    같이 확인: 진짜 워커는 그대로 보인다(naive/aware TypeError 재발 방지).
    """
    from lemouton.sourcing import crawl_queue as q
    from lemouton.sourcing.models import CrawlWorker
    _clear(db)
    사람PC = "영빈 PC"
    db.query(CrawlWorker).filter(CrawlWorker.name == 사람PC).delete()
    db.add(CrawlWorker(name=사람PC, last_heartbeat_at=T0.replace(tzinfo=None)))
    db.commit()
    try:
        q.touch_worker_heartbeat(ip_address="1.2.3.4", now=T0)
        rows = q.online_workers(now=T0 + timedelta(seconds=5))
        names = [w["name"] for w in rows]
        assert q.CRAWL_PC_NAME not in names, "센티널이 워커 목록에 샜다"
        assert 사람PC in names
        assert next(w for w in rows if w["name"] == 사람PC)["online"] is True
    finally:
        db.query(CrawlWorker).filter(CrawlWorker.name == 사람PC).delete()
        db.commit()


# ── 라우트 배선 ────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_확장이_일감을_물어보면_PC가_켜진_것으로_바뀐다(client, db):
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    assert q.worker_presence()["online"] is False
    r = client.get('/api/crawl/due-bundles', headers={'User-Agent': PC_UA})
    assert r.status_code == 200
    assert q.worker_presence()["online"] is True


def test_PC화면_폴링만으로는_PC가_켜진_것으로_안_바뀐다(client, db):
    """/api/crawl/queue 는 확장이 아니라 자동화 화면 JS(1.5초)가 부른다.

    여기에 생존 신호를 붙이면 확장이 꺼져 있어도 🟢 가 떠서 리모컨이 거짓말을 한다.
    """
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    r = client.get('/api/crawl/queue', headers={'User-Agent': PC_UA})
    assert r.status_code == 200
    assert q.worker_presence()["online"] is False, "queue 폴링이 생존 신호를 남겼다"


def test_생존신호_기록이_터져도_크롤_폴링은_계속된다(client, db, monkeypatch):
    """기록은 곁다리다 — 그것 때문에 확장이 일감을 못 받으면 본말전도다."""
    from lemouton.sourcing import crawl_queue as q
    _clear(db)

    def _boom(**kw):
        raise RuntimeError("DB 접속 실패(가정)")

    monkeypatch.setattr(q, "touch_worker_heartbeat", _boom)
    r = client.get('/api/crawl/due-bundles', headers={'User-Agent': PC_UA})
    assert r.status_code == 200
    assert 'codes' in r.get_json()
