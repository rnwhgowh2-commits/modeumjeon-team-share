from lemouton.sources.failure_classify import list_crawl_failures
from lemouton.sources.models import SourceProduct


def _sp(db, url, status, err):
    sp = SourceProduct(site="musinsa", url=url, last_status=status, last_error_msg=err)
    db.add(sp); db.flush(); return sp


def test_only_error_status_included(db):
    _sp(db, "u/ok", "ok", None)
    _sp(db, "u/nc", "no_crawler", None)
    _sp(db, "u/err", "error", "403 차단")
    groups = list_crawl_failures(db)
    urls = [it["url"] for g in groups for it in g["items"]]
    assert "u/err" in urls
    assert "u/ok" not in urls and "u/nc" not in urls


def test_grouped_by_type_with_counts(db):
    _sp(db, "u/1", "error", "403 차단")
    _sp(db, "u/2", "error", "WAF blocked")
    _sp(db, "u/3", "error", "로그인 필요")
    _sp(db, "u/4", "error", "이상한 오류 zzz")   # 유형 외
    groups = {g["type"]: g for g in list_crawl_failures(db)}
    assert groups["block"]["count"] == 2
    assert groups["login"]["count"] == 1
    assert groups["etc"]["count"] == 1
    assert groups["block"]["label"] == "차단" and groups["block"]["emoji"] == "🚫"


def test_item_carries_url_and_error(db):
    _sp(db, "u/x", "error", "옵션 파싱 실패")
    g = list_crawl_failures(db)[0]
    it = g["items"][0]
    assert it["url"] == "u/x" and it["error"] == "옵션 파싱 실패"
    assert "source_product_id" in it and it["site"] == "musinsa"


def test_soft_deleted_excluded(db):
    from datetime import datetime, timezone
    sp = _sp(db, "u/del", "error", "403 차단")
    sp.deleted_at = datetime.now(timezone.utc); db.flush()
    assert list_crawl_failures(db) == []
