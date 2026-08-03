# -*- coding: utf-8 -*-
"""폰 크롤 리모컨의 'PC 연결됨' 판정.

확장은 고치지 않는다 — 확장이 /api/crawl/due-bundles 를 부를 때 서버가 시각을 남긴다.
이 표시가 틀리면 사장님이 '눌러도 아무 일 없는 버튼'을 누르게 된다.
"""
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def db():
    from shared.db import SessionLocal, Base, engine
    Base.metadata.create_all(engine)
    s = SessionLocal()
    yield s
    s.close()


def _clear(s):
    from lemouton.sourcing.models import CrawlWorker
    s.query(CrawlWorker).delete()
    s.commit()


def test_아무도_안_왔으면_PC는_꺼진_것으로_본다(db):
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    got = q.worker_presence()
    assert got["online"] is False
    assert got["last_seen_at"] is None


def test_한_번_다녀가면_PC가_켜진_것으로_본다(db):
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4")
    got = q.worker_presence()
    assert got["online"] is True
    assert got["seconds_ago"] is not None and got["seconds_ago"] < 10


def test_90초를_넘기면_꺼진_것으로_본다(db):
    from lemouton.sourcing import crawl_queue as q
    from lemouton.sourcing.models import CrawlWorker
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4")
    w = db.query(CrawlWorker).filter(CrawlWorker.name == q.CRAWL_PC_NAME).first()
    w.last_heartbeat_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=200)
    db.commit()
    assert q.worker_presence()["online"] is False


def test_폴링이_잦아도_30초_안에는_다시_안_쓴다(db):
    """확장은 1~2초마다 부른다. 매번 DB 를 쓰면 낭비다."""
    from lemouton.sourcing import crawl_queue as q
    from lemouton.sourcing.models import CrawlWorker
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4")
    w = db.query(CrawlWorker).filter(CrawlWorker.name == q.CRAWL_PC_NAME).first()
    first = w.last_heartbeat_at
    q.touch_worker_heartbeat(ip_address="1.2.3.4")
    db.expire_all()
    w2 = db.query(CrawlWorker).filter(CrawlWorker.name == q.CRAWL_PC_NAME).first()
    assert w2.last_heartbeat_at == first, "30초 안에 두 번 썼다"


def test_폰에서_연_화면은_PC로_치지_않는다(db):
    """사장님이 폰으로 PC용 자동화 화면을 열어도 'PC 연결됨'이 되면 안 된다."""
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4", user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile/15E148")
    assert q.worker_presence()["online"] is False


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
    r = client.get('/api/crawl/due-bundles',
                   headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126'})
    assert r.status_code == 200
    assert q.worker_presence()["online"] is True
