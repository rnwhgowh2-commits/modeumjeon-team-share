"""연속 배수 큐 — '지금 크롤할 URL'을 오래된 순 + 계수로 선정 (두뇌).

유효 간격 = 기준주기 ÷ 계수 × 완화배수.
- 계수(crawl_weight) 1~5: 클수록 자주(간격 나눔).
- 완화배수 = min(1 + 무변동연속 × RELAX_STEP, RELAX_CAP): 계속 안 변하면 덜 긁음.
실제 크롤 실행은 P3(워커). 여기는 순서만 정한다.
"""
from datetime import datetime, timezone, timedelta

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

    기준주기 0 이하 = 연속 모드 → 벽시계 간격이 아닌 '가중 라운드로빈 랩'으로 위임
    (각 URL을 계수만큼/랩, 절대 안 쉼). 기준주기>0 = 기존 벽시계 간격 로직.
    """
    if (base_interval_seconds or 0) <= 0:
        return next_lap_products(session)
    from lemouton.sources.models import SourceProduct
    products = (session.query(SourceProduct)
                .filter(SourceProduct.deleted_at.is_(None))
                .all())
    scored = []
    for p in products:
        od = overdue_seconds(now, p.last_fetched_at, base_interval_seconds,
                             resolve_crawl_weight(session, p), p.no_change_streak)
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


def list_weight_rules(session) -> dict:
    """범위종류별 {scope_key: weight} (화면 트리가 유효계수 표시에 사용)."""
    from lemouton.sources.models import CrawlWeightRule
    out = {t: {} for t in _SCOPE_TYPES}
    for r in session.query(CrawlWeightRule).all():
        out.setdefault(r.scope_type, {})[r.scope_key] = r.weight
    return out


def resolve_crawl_weight(session, source_product) -> int:
    """URL의 최종 계수: URL→모음전(최고)→브랜드(최고)→소싱처→기본1."""
    from lemouton.sources.models import CrawlWeightRule
    from lemouton.sources.service import normalize_url
    from lemouton.sourcing.models import BundleSourceUrl, Model

    def _rule(stype, skey):
        return (session.query(CrawlWeightRule)
                .filter_by(scope_type=stype, scope_key=skey).first())

    nurl = normalize_url(source_product.url)
    r = _rule("url", nurl)
    if r:
        return r.weight

    model_codes = {b.model_code for b in session.query(BundleSourceUrl).all()
                   if normalize_url(b.url) == nurl}
    if model_codes:
        mr = (session.query(CrawlWeightRule)
              .filter(CrawlWeightRule.scope_type == "model",
                      CrawlWeightRule.scope_key.in_(model_codes)).all())
        if mr:
            return max(x.weight for x in mr)
        brands = {m.brand for m in session.query(Model)
                  .filter(Model.model_code.in_(model_codes)).all() if m.brand}
        if brands:
            br = (session.query(CrawlWeightRule)
                  .filter(CrawlWeightRule.scope_type == "brand",
                          CrawlWeightRule.scope_key.in_(brands)).all())
            if br:
                return max(x.weight for x in br)

    sr = _rule("source", source_product.site)
    if sr:
        return sr.weight
    return 1


# ════════════════════════════════════════════════════════════════════
#  가중 라운드로빈 랩 (연속 모드 = 기준주기 0)
#  ─ 시간 기준 없이 최대한 자주 크롤하되, 계수만큼 빈도 배수.
#    한 랩 = 각 URL을 유효계수만큼 크롤(×1=1번, ×2=2번, ×3=3번).
#    벽시계 간격은 랩 시간이 유동적이라 배수를 못 만든다 → 카운터 기반.
#  ─ crawl_lap_count = 이번 랩에 이 URL을 크롤한 횟수. save_crawl_result 가 URL 저장
#    시마다 record_crawl_served 로 +1. quota(=계수) 채우면 이번 랩 소진.
#  ─ 전부 채우면 랩 완료 → start_new_lap 로 리셋(다음 랩 즉시 시작 = 절대 안 쉼).
# ════════════════════════════════════════════════════════════════════

def lap_quota(session, source_product) -> int:
    """이번 랩에 이 URL을 몇 번 크롤해야 하나 = 유효계수(1~5)."""
    return max(1, min(5, resolve_crawl_weight(session, source_product)))


def record_crawl_served(source_product) -> int:
    """URL 1회 크롤 완료 = 이번 랩 served +1. 호출자가 commit."""
    source_product.crawl_lap_count = int(source_product.crawl_lap_count or 0) + 1
    return source_product.crawl_lap_count


def _active_products(session) -> list:
    from lemouton.sources.models import SourceProduct
    return (session.query(SourceProduct)
            .filter(SourceProduct.deleted_at.is_(None))
            .all())


def _lap_products(session) -> list:
    """가중 랩 대상 = 확장에 실제 보낼 수 있는(모음전에 걸린) 활성 URL만.

    orphan/미연결 URL(어떤 BundleSourceUrl 에도 없음)은 due_bundle_codes 가 코드로
    못 바꿔 확장이 영영 못 긁는다 → 랩에 넣으면 served 가 quota 에 못 닿아 '한 바퀴'가
    영영 안 끝나고 링이 멈춘다(라이브 확인된 89% 정지·오늘 바퀴 0 고정의 뿌리).
    그래서 랩은 dispatchable URL 로만 센다.
    """
    from lemouton.sourcing.models import BundleSourceUrl
    from lemouton.sources.service import normalize_url
    disp = {normalize_url(b.url) for b in session.query(BundleSourceUrl).all()}
    return [p for p in _active_products(session) if normalize_url(p.url) in disp]


def _lap_view(session) -> list:
    """이번 랩에 '실제로 셀' URL만 (p, quota, served). straggler 제외.

    계속 실패(last_status='error')하고 아직 못 채운 URL만 랩 계산에서 제외한다(크롤 불가 →
    랩을 막지 않게. 크롤은 계속 시도되고 「크롤 실패」 패널엔 그대로 표면화 — 숨기지 않음).

    ★[2026-07-06 버그수정] 이전엔 'maxc>q(다른 URL이 quota 초과)' 도 제외조건에 넣었으나,
    재시도·중복저장으로 크롤 중간에 한 URL만 2번 긁혀도 참이 돼 → 아직 안 긁힌 URL을
    몽땅 제외 → **패스 중간에 가짜 완료**(오늘 바퀴 우르르 증가·링 0% 튐). 이 조건 제거.
    '한 패스 끝' 판정은 서버 추측이 아니라 확장의 pass-done 신호로 한다(due_bundle_codes).
    """
    prods = _lap_products(session)
    live = []
    for p in prods:
        q = lap_quota(session, p)
        s = int(p.crawl_lap_count or 0)
        if s == 0 and (p.last_status or "") == "error":
            continue
        live.append((p, q, s))
    return live


def weighted_due_products(session) -> list:
    """이번 가중 랩에 아직 덜 채운(계수 미달) URL을 '적게 채운 순'으로 반환.

    정렬 = 채움비(served/quota) 오름차순 → 계수 큰 URL이 랩 뒷부분까지 남아 더 자주 나옴.
    동률은 오래된(last_fetched) 순 → id 순. 랩 다 채웠으면 [] (호출자가 리셋 판단).
    """
    from datetime import datetime as _dt
    _MIN = _dt.min
    remaining = []
    for p, quota, served in _lap_view(session):
        if served < quota:
            remaining.append((served / quota, _as_naive_utc(p.last_fetched_at) or _MIN, p.id, p))
    remaining.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in remaining]


def start_new_lap(session, now=None, record=True) -> int:
    """이번 랩 카운터 전부 0으로 리셋(다음 가중 랩 시작) + (record 시) 완료 1건 기록.

    가중 한 바퀴가 끝나 새 랩을 시작하는 순간 = 랩 1개 완료 → CrawlLapRun append
    (자정 이후 개수 = '오늘 몇 바퀴', 간격 = '1바퀴 시간'). record=False 면 리셋만(전부
    실패해 실제 크롤 0인 경우 spurious 바퀴 방지). 호출자가 commit. 리셋 개수 반환.
    """
    from datetime import datetime as _dt
    from lemouton.sources.models import CrawlLapRun
    n = 0
    for p in _lap_products(session):
        if int(p.crawl_lap_count or 0) != 0:
            p.crawl_lap_count = 0
        n += 1
    if record:
        session.add(CrawlLapRun(completed_at=now or _dt.utcnow()))
    session.flush()
    return n


#  ── 회차(CrawlLapRun) 전수 중복 감사·청소 ─────────────────────────────
#   진짜 한 바퀴는 수 분 간격(라이브 실측 평균 8분·최소 8분)인데, 신고자 중복으로 같은
#   바퀴가 0~수십 초 간격의 클러스터로 여러 행 박혔다. 연속 두 행의 간격이 window_seconds
#   이하면 같은 바퀴(중복)로 본다. 이 값은 중복 간격(<30초)보다 크고 진짜 간격(수 분)보다
#   작아 안전하다.
_DEDUP_WINDOW_SECONDS = 90


def audit_lap_runs(session, window_seconds: int = _DEDUP_WINDOW_SECONDS) -> dict:
    """CrawlLapRun 전수 조사. 연속 간격이 window 이하인 행 = 같은 바퀴 중복.

    반환 {total, real_laps(=중복 제거 후 진짜 바퀴 수), duplicates, max_cluster,
    dup_ids}. 삭제는 안 함(dry-run). dup_ids = 지울 대상(각 클러스터 첫 행만 남김).
    """
    from lemouton.sources.models import CrawlLapRun
    runs = (session.query(CrawlLapRun)
            .order_by(CrawlLapRun.completed_at.asc(), CrawlLapRun.id.asc()).all())
    prev_t = None
    real = 0
    dup_ids = []
    cluster = 0
    max_cluster = 0
    for r in runs:
        t = _as_naive_utc(r.completed_at)
        if prev_t is None or (t - prev_t).total_seconds() > window_seconds:
            real += 1                       # 새 바퀴(경계) — 이 행 유지
            max_cluster = max(max_cluster, cluster)
            cluster = 1
        else:
            dup_ids.append(r.id)            # 직전 행과 가까움 = 같은 바퀴 중복
            cluster += 1
        prev_t = t
    max_cluster = max(max_cluster, cluster)
    return {"total": len(runs), "real_laps": real, "duplicates": len(dup_ids),
            "max_cluster": max_cluster, "dup_ids": dup_ids,
            "window_seconds": window_seconds}


def dedupe_lap_runs(session, window_seconds: int = _DEDUP_WINDOW_SECONDS) -> dict:
    """중복 회차 삭제 — 각 클러스터의 첫 행만 남기고 제거. 호출자가 commit. audit dict 반환."""
    from lemouton.sources.models import CrawlLapRun
    a = audit_lap_runs(session, window_seconds)
    if a["dup_ids"]:
        (session.query(CrawlLapRun)
         .filter(CrawlLapRun.id.in_(a["dup_ids"]))
         .delete(synchronize_session=False))
        session.flush()
    return a


_KST_OFFSET_H = 9   # 자정 기준 = 한국시간(UTC+9)


def lap_stats(session, *, now, tz_offset_hours: int = _KST_OFFSET_H) -> dict:
    """자정(KST) 이후 '오늘 몇 바퀴' + 평균/최근 1바퀴 시간(분). 링 박스가 읽음.

    laps_today = 자정 이후 완료 개수. current_lap_no = 지금 몇 바퀴째(오늘+1).
    recent_lap_minutes = 연속 완료 간격(분) 최근 12개. avg = 그 평균(없으면 None).
    """
    from lemouton.sources.models import CrawlLapRun
    kst = _as_naive_utc(now) + timedelta(hours=tz_offset_hours)
    kst_midnight = kst.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = kst_midnight - timedelta(hours=tz_offset_hours)
    runs = (session.query(CrawlLapRun)
            .filter(CrawlLapRun.completed_at >= midnight_utc)
            .order_by(CrawlLapRun.completed_at.asc()).all())
    times = [_as_naive_utc(r.completed_at) for r in runs]
    diffs = [round((times[i] - times[i - 1]).total_seconds() / 60)
             for i in range(1, len(times))]
    avg = round(sum(diffs) / len(diffs)) if diffs else None
    # 차수별 완료 시각(회차 no=오늘 n번째 + ISO naive UTC). 최근 50 (화면은 접기/펼치기).
    today_laps = [{"no": i + 1, "at": t.isoformat()} for i, t in enumerate(times)][-50:]
    return {
        "laps_today": len(times),
        "current_lap_no": len(times) + 1,
        "avg_lap_minutes": avg,
        "recent_lap_minutes": diffs[-12:],
        "today_laps": today_laps,
    }


def next_lap_products(session) -> list:
    """연속모드 진입점 — 절대 안 쉼: 남은 게 있으면 그걸, 랩 다 채웠으면 리셋 후 새 랩 전부.

    활성 URL이 하나도 없으면 [] (크롤할 게 없는 정상 상태).
    """
    due = weighted_due_products(session)
    if due:
        return due
    if not _lap_products(session):
        return []
    # ★[2026-07-06] 서버 자동리셋은 '리셋만'(record=False) — 한 바퀴 '기록'(오늘 바퀴+1)은
    #   확장의 pass-done 신호(POST /api/crawl/pass-done)만 한다. 서버가 완료를 추측해 기록하면
    #   가짜 바퀴가 생김(over-serve 버그의 교훈). 여기선 안 쉬게 카운터만 리셋.
    start_new_lap(session, record=False)
    # 랩 리셋은 반드시 영속 — 이 함수는 읽기 라우트(/crawl/queue·due-bundles)에서
    #   호출되는데 그 라우트들은 commit 하지 않는다. flush 만 하면 close()에서 롤백돼
    #   served 가 quota 에 붙박이고 매 폴링이 전체 랩 = 계수 배수가 무력화된다.
    try:
        session.commit()
    except Exception:
        session.rollback()
    return weighted_due_products(session)


def lap_progress(session) -> dict:
    """링 표시용 — 이번 가중 랩 진행률. served/total(가중 합) + pct(0~100)."""
    served_sum = 0
    total = 0
    for p, quota, served in _lap_view(session):
        total += quota
        served_sum += min(served, quota)
    pct = round(served_sum / total * 100) if total else 0
    return {"served": served_sum, "total": total, "pct": pct}


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
    prog = lap_progress(session)   # 링('이번 한 바퀴')용 — 정지 상태여도 항상 노출
    stats = lap_stats(session, now=now)   # 오늘 몇 바퀴·평균·막대 (항목4)
    if not bool(s.crawl_auto_enabled):
        return {"enabled": False, "base_interval_seconds": base,
                "count": 0, "items": [], "lap_progress": prog, "lap_stats": stats}
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
            "count": len(items), "items": items,
            "lap_progress": prog, "lap_stats": stats}
