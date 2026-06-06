from lemouton.sourcing.crawl_queue import enqueue_verify, get_job
from lemouton.sourcing.models import CrawlJob
from shared.db import SessionLocal

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
