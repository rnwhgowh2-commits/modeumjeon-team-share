"""연속 배수 큐 — '지금 크롤할 URL'을 오래된 순 + 계수로 선정 (두뇌).

유효 간격 = 기준주기 ÷ 계수 × 완화배수.
- 계수(crawl_weight) 1~5: 클수록 자주(간격 나눔).
- 완화배수 = min(1 + 무변동연속 × RELAX_STEP, RELAX_CAP): 계속 안 변하면 덜 긁음.
실제 크롤 실행은 P3(워커). 여기는 순서만 정한다.
"""
from datetime import datetime, timezone

RELAX_STEP = 0.5   # 무변동 1회당 간격 +0.5배
RELAX_CAP = 4.0    # 완화 상한(최대 4배)


def _as_naive_utc(dt: datetime | None) -> datetime | None:
    """aware→naive-UTC, naive는 그대로. SQLite naive/aware 섞임 방지."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def effective_interval_seconds(base_interval_seconds: float,
                               crawl_weight, no_change_streak) -> float:
    weight = max(1, int(crawl_weight or 1))
    streak = max(0, int(no_change_streak or 0))
    base = base_interval_seconds / weight
    relax = min(1.0 + streak * RELAX_STEP, RELAX_CAP)
    return base * relax


def overdue_seconds(now: datetime, last_fetched_at,
                    base_interval_seconds: float,
                    crawl_weight, no_change_streak) -> float:
    """연체 초. 클수록 더 오래 밀림. 한 번도 안 긁음 = 무한대(최우선)."""
    if last_fetched_at is None:
        return float("inf")
    n = _as_naive_utc(now)
    lf = _as_naive_utc(last_fetched_at)
    age = (n - lf).total_seconds()
    return age - effective_interval_seconds(base_interval_seconds,
                                            crawl_weight, no_change_streak)


def is_due(now, last_fetched_at, base_interval_seconds,
           crawl_weight, no_change_streak) -> bool:
    return overdue_seconds(now, last_fetched_at, base_interval_seconds,
                           crawl_weight, no_change_streak) >= 0


def due_products(session, *, base_interval_seconds: float, now: datetime) -> list:
    """지금 크롤할 때가 된 활성 SourceProduct 를 '가장 오래 밀린 순'으로 반환.

    실제 크롤 실행(P3 워커)이 이 순서대로 소비한다.
    """
    from lemouton.sources.models import SourceProduct
    products = (session.query(SourceProduct)
                .filter(SourceProduct.deleted_at.is_(None))
                .all())
    scored = []
    for p in products:
        od = overdue_seconds(now, p.last_fetched_at, base_interval_seconds,
                             p.crawl_weight, p.no_change_streak)
        if od >= 0:
            scored.append((od, p))
    scored.sort(key=lambda t: t[0], reverse=True)   # 연체 큰 순
    return [p for _, p in scored]


def set_crawl_weight(session, source_product_id: int, weight) -> int:
    """URL(SourceProduct)의 계수(1~5) 저장. 1~5로 클램프. 호출자가 commit."""
    from lemouton.sources.models import SourceProduct
    sp = session.get(SourceProduct, source_product_id)
    if sp is None:
        raise ValueError(f"source_product {source_product_id} 없음")
    sp.crawl_weight = max(1, min(5, int(weight)))
    session.flush()
    return sp.crawl_weight


_SCOPE_TYPES = ("source", "brand", "model", "url")


def set_crawl_weight_rule(session, scope_type: str, scope_key: str, weight):
    """범위 계수 규칙 설정. weight None = 해제(삭제→상속). 1~5 클램프. 호출자 commit."""
    from lemouton.sources.models import CrawlWeightRule
    if scope_type not in _SCOPE_TYPES:
        raise ValueError(f"scope_type: {scope_type}")
    r = (session.query(CrawlWeightRule)
         .filter_by(scope_type=scope_type, scope_key=scope_key).first())
    if weight is None:
        if r is not None:
            session.delete(r)
        session.flush()
        return None
    w = max(1, min(5, int(weight)))
    if r is not None:
        r.weight = w
    else:
        session.add(CrawlWeightRule(scope_type=scope_type, scope_key=scope_key, weight=w))
    session.flush()
    return w


def base_crawl_interval_seconds(session) -> float:
    """자동화 설정의 기준 주기(시·분)를 초로. 0이면 '항상 마감'(연속)."""
    from lemouton.pricing.settings import get_or_init
    s = get_or_init(session)
    return (s.crawl_interval_hours or 0) * 3600 + (s.crawl_interval_minutes or 0) * 60


def select_due_products(session, *, now: datetime) -> list:
    """설정 주기를 읽어 due URL을 연체 순으로 반환 (P3 워커 진입점)."""
    base = base_crawl_interval_seconds(session)
    return due_products(session, base_interval_seconds=base, now=now)


def due_bundle_codes(session, *, now) -> list:
    """마감난 URL이 걸린 모음전(번들) 코드 목록(중복 제거). 확장이 이걸 크롤한다.

    실행/정지(crawl_auto_enabled)가 꺼져 있으면 빈 목록.

    [조용한 누락 방지] due SourceProduct.url 과 BundleSourceUrl.url 을 **둘 다**
    파이프라인과 동일한 normalize_url 로 정규화해 비교한다. BundleSourceUrl.url 은
    등록 원본(트래킹 파라미터 포함 가능)이라 raw 비교하면 due URL이 어떤 번들에도
    안 걸려 영원히 안 긁히고 에러도 없다(이 프로젝트 조용한실패 클래스).
    SourceProduct.url 은 이미 정규화 저장이라 normalize_url 재적용은 멱등이다.
    """
    from lemouton.pricing.settings import get_or_init
    from lemouton.sourcing.models import BundleSourceUrl
    from lemouton.sources.service import normalize_url as _norm_url
    if not bool(get_or_init(session).crawl_auto_enabled):
        return []
    base = base_crawl_interval_seconds(session)
    due = due_products(session, base_interval_seconds=base, now=now)
    due_urls = {_norm_url(p.url) for p in due}
    if not due_urls:
        return []
    codes = []
    seen = set()
    for bsu in session.query(BundleSourceUrl).all():
        if _norm_url(bsu.url) in due_urls and bsu.model_code not in seen:
            seen.add(bsu.model_code)
            codes.append(bsu.model_code)
    return codes


def due_crawl_payload(session, *, now) -> dict:
    """로컬 크롤러(확장)가 폴링할 페이로드. 서버는 목록만 알려줄 뿐 크롤 안 함.

    실행/정지(crawl_auto_enabled)가 꺼져 있으면 빈 목록 + enabled=False.
    """
    from lemouton.pricing.settings import get_or_init
    s = get_or_init(session)
    base = base_crawl_interval_seconds(session)
    if not bool(s.crawl_auto_enabled):
        return {"enabled": False, "base_interval_seconds": base,
                "count": 0, "items": []}
    products = due_products(session, base_interval_seconds=base, now=now)
    items = [{
        "source_product_id": p.id,
        "site": p.site,
        "url": p.url,
        "crawl_weight": p.crawl_weight,
        "no_change_streak": p.no_change_streak,
        "last_fetched_at": p.last_fetched_at.isoformat() if p.last_fetched_at else None,
    } for p in products]
    return {"enabled": True, "base_interval_seconds": base,
            "count": len(items), "items": items}
