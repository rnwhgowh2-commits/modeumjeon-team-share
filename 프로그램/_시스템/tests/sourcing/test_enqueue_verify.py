import pytest
from lemouton.sourcing.crawl_queue import enqueue_verify, get_job
from lemouton.sourcing.models import CrawlJob
from shared.db import SessionLocal, Base, engine

# [포팅 2026-06-26] 'no such table: crawl_jobs' 픽스처 문제.
# SessionLocal 은 실제 SQLite DB(data/lemouton.db) 를 가리킨다.
# 테스트 실행 환경에서는 app.py init_db() 가 먼저 호출되지 않아 crawl_jobs 테이블이
# 없을 수 있다. 모든 모델을 등록하고 Base.metadata.create_all 로 테이블을 생성한다.
for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass


@pytest.fixture(scope="module", autouse=True)
def ensure_crawl_jobs_table():
    """SessionLocal 이 가리키는 엔진에 crawl_jobs 테이블이 없으면 생성."""
    Base.metadata.create_all(engine)
    yield


FAKE_URL = "https://example.test/__pytest_verify__/4112020"


def _cleanup():
    s = SessionLocal()
    try:
        for j in s.query(CrawlJob).filter(CrawlJob.verify_url == FAKE_URL).all():
            s.delete(j)
        s.commit()
    finally:
        s.close()


def test_enqueue_verify_creates_job():
    _cleanup()
    try:
        out = enqueue_verify(FAKE_URL, required_login="musinsa", triggered_by="guide_verify")
        assert out["status"] == "pending"
        assert out["created"] is True
        s = SessionLocal()
        try:
            job = s.query(CrawlJob).get(out["id"])
            assert job.phase == "verify"
            assert job.verify_url == FAKE_URL
            assert job.triggered_by == "guide_verify"
        finally:
            s.close()
        # get_job 폴링
        info = get_job(out["id"])
        assert info["status"] == "pending"
        assert info["verify_url"] == FAKE_URL
        assert info["result"] is None
        # dedup: 같은 URL 재등록 시 기존 잡 재사용
        again = enqueue_verify(FAKE_URL)
        assert again["created"] is False
        assert again["id"] == out["id"]
    finally:
        _cleanup()


def test_enqueue_verify_rejects_bad_url():
    import pytest
    with pytest.raises(ValueError):
        enqueue_verify("not-a-url")
