"""회차(한 바퀴)별 크롤 보고서 — 그 바퀴에 무엇이 바뀌었나.

회차 경계 = 연속한 CrawlLapRun.completed_at 두 개 사이 (N회차 = N번째 완료 시각까지).
그 구간의 CrawlDelta 를 모아 ①요약 ②변동(가격/재고) ③성공 을 만든다.

★정직성: CrawlDelta 는 **저장에 성공한 크롤**마다 1행이다. 실패는 회차별로 남지 않는다
  → 회차 실패 건수를 지어내지 않는다. 대신 '지금 실패 중'(last_status='error')만 별도 표기.
"""
import re
from datetime import datetime, timedelta

# CrawlDelta.detail 예: "[블랙/265] 가격 115000→119900 · [블랙/265] 재고 3→0 · [화이트/270] 옵션 생김"
_PRICE_RE = re.compile(r"\[([^\]]*)\]\s*가격\s*(\S+?)→(\S+)")
_STOCK_RE = re.compile(r"\[([^\]]*)\]\s*재고\s*(\S+?)→(\S+)")
_OPT_RE = re.compile(r"\[([^\]]*)\]\s*옵션\s*(생김|사라짐)")


def parse_detail(detail: str) -> list[dict]:
    """변동 문장 → [{kind:'price'|'stock'|'option', option, from, to}] (순서 보존 아님)."""
    out: list[dict] = []
    if not detail:
        return out
    for m in _PRICE_RE.finditer(detail):
        out.append({"kind": "price", "option": m.group(1),
                    "from": m.group(2), "to": m.group(3)})
    for m in _STOCK_RE.finditer(detail):
        out.append({"kind": "stock", "option": m.group(1),
                    "from": m.group(2), "to": m.group(3)})
    for m in _OPT_RE.finditer(detail):
        out.append({"kind": "option", "option": m.group(1),
                    "from": "", "to": m.group(2)})
    return out


def _to_int(v):
    try:
        return int(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _stock_word(v):
    """재고 숫자 → 사람 말. 0=품절 / 999·10=있음 / -1=확인불가 / None=미크롤."""
    n = _to_int(v)
    if v in (None, "None", ""):
        return "미크롤"
    if n is None:
        return str(v)
    if n < 0:
        return "확인불가"
    if n == 0:
        return "품절"
    if n >= 999:
        return "있음"
    return f"{n}개"


def _price_word(v):
    n = _to_int(v)
    return f"{n:,}" if n is not None else "없음"


def lap_bounds(session, *, lap_no: int, now: datetime) -> tuple | None:
    """N회차(오늘 N번째 완료)의 (시작, 끝). 없으면 None.

    ★lap_stats()['today_laps'] 는 화면용으로 **최근 50개만** 잘라 보낸다(`[-50:]`).
      거기 순번으로 찾으면 오늘 151회차 같은 번호를 못 찾아 404 가 난다(라이브 실측).
      → 오늘의 CrawlLapRun 을 직접 시간순으로 세어 N번째를 잡는다.
    """
    from lemouton.sources.models import CrawlLapRun
    from lemouton.sources.crawl_schedule import _as_naive_utc, _KST_OFFSET_H

    kst = _as_naive_utc(now) + timedelta(hours=_KST_OFFSET_H)
    midnight_utc = (kst.replace(hour=0, minute=0, second=0, microsecond=0)
                    - timedelta(hours=_KST_OFFSET_H))
    runs = (session.query(CrawlLapRun)
            .filter(CrawlLapRun.completed_at >= midnight_utc)
            .order_by(CrawlLapRun.completed_at.asc()).all())
    if not (1 <= lap_no <= len(runs)):
        return None
    end = _as_naive_utc(runs[lap_no - 1].completed_at)
    if lap_no >= 2:
        start = _as_naive_utc(runs[lap_no - 2].completed_at)
    else:
        prev = (session.query(CrawlLapRun)
                .filter(CrawlLapRun.completed_at < end)
                .order_by(CrawlLapRun.completed_at.desc()).first())
        start = _as_naive_utc(prev.completed_at) if prev else (end - timedelta(hours=24))
    return start, end


def site_labels() -> dict:
    """소싱처 키 → 사람이 읽는 이름(hmall → 현대H몰). 실패해도 빈 dict."""
    try:
        from lemouton.sourcing.source_registry import get_labels
        return get_labels() or {}
    except Exception:
        return {}


def excluded_sites(session) -> list[str]:
    """계수 0 = 이번 바퀴에서 아예 제외된 소싱처 (사람이 읽는 이름)."""
    from lemouton.sources.crawl_schedule import list_weight_rules
    src = list_weight_rules(session).get("source", {})
    lab = site_labels()
    return sorted(lab.get(k, k) for k, w in src.items() if (w or 0) <= 0)


# source_key → SourceRegistry.id (main_url 도메인 매칭). 매트릭스(api_pricing)와 같은 규칙.
_KEY_DOMAIN = {
    "lemouton": "lemouton.co.kr", "ss_lemouton": "smartstore.naver.com",
    "musinsa": "musinsa.com", "ssf": "ssfshop.com",
    "lotteon": "lotteon.com", "ssg": "ssg.com",
}


def _key_to_regid(session) -> dict:
    from lemouton.sourcing.models_pricing import SourceRegistry
    rows = session.query(SourceRegistry).all()
    out = {}
    for k, dom in _KEY_DOMAIN.items():
        for r in rows:
            if dom in (r.main_url or ""):
                out[k] = r.id
                break
    return out


def _link_by_product(session, prods) -> dict:
    """SourceProduct.id → (canonical_sku, source_id) — 최종매입가 계산의 두 열쇠.

    ★열쇠의 출처는 '옵션 ↔ 등록 URL' 매핑(OptionSourceUrlLink ⨝ BundleSourceUrl)이다.
      매트릭스가 믿는 바로 그 경로. 소싱처 이름으로 짐작하면(레지스트리엔 id 가 없다)
      늘 None 이 되고, 레거시 OptionSourceUrl 은 라이브에서 비어 있다 — 둘 다 겪었다.
    레거시 표는 폴백으로만 본다. 못 찾으면 None → 화면은 「확인불가」로 정직하게.
    """
    from lemouton.sources.service import normalize_url as _nu

    by_url = {}
    try:                                    # ① 정본 — 옵션 ↔ 등록 URL
        from lemouton.sourcing.models import BundleSourceUrl, OptionSourceUrlLink
        regid = _key_to_regid(session)
        rows = (session.query(OptionSourceUrlLink, BundleSourceUrl)
                .join(BundleSourceUrl,
                      OptionSourceUrlLink.bundle_source_url_id == BundleSourceUrl.id)
                .all())
        for lk, bsu in rows:
            sid = regid.get(bsu.source_key)
            if not bsu.url or sid is None:
                continue                    # 레지스트리에 없는 소싱처 = 혜택 계산 불가
            by_url.setdefault(_nu(bsu.url), (lk.option_canonical_sku, sid))
    except Exception:
        pass
    try:                                    # ② 레거시 폴백
        from lemouton.sourcing.models_pricing import OptionSourceUrl
        for l in session.query(OptionSourceUrl).all():
            if l.product_url and l.source_id is not None:
                by_url.setdefault(_nu(l.product_url), (l.canonical_sku, l.source_id))
    except Exception:
        pass

    out = {}
    for pr in prods:
        out[pr.id] = by_url.get(_nu(pr.url)) if pr.url else None
    return out


def _stock_cells(session, source_product_id: int, limit: int = 200) -> tuple:
    from lemouton.sources.models import SourceOption
    opts = (session.query(SourceOption)
            .filter(SourceOption.source_product_id == source_product_id,
                    SourceOption.deleted_at.is_(None))
            .limit(limit).all())
    grid = [{"color": o.color_text, "size": o.size_text, "stock": o.current_stock}
            for o in opts]
    summ = {"ample": 0, "limited": 0, "soldout": 0, "unknown": 0}
    for g in grid:
        q = g["stock"]
        if q is None or q < 0:
            summ["unknown"] += 1
        elif q == 0:
            summ["soldout"] += 1
        elif q >= 999:
            summ["ample"] += 1
        else:
            summ["limited"] += 1
    return grid, summ


def keep_sources(session, *, crawled_sites: set, changed_sites: set) -> list[dict]:
    """이번 바퀴에 '변동 없던' 소싱처의 지금 값 — ★상품(URL) 단위.

    한 소싱처에 상품 URL이 여러 개다(르무통 공홈 9개). 소싱처 한 줄로 뭉치면
      · 표면노출가 = 최저가 폴백 (CLAUDE.md 가 금지)
      · 색×사이즈가 서로 덮어써 격자(154칸)와 요약(400개)이 모순
    둘 다 필연이다. 그래서 값은 상품마다 따로 낸다. 폴백 없음, 합산 없음.
    """
    from lemouton.sources.models import SourceProduct

    lab = site_labels()
    out = []
    for site in sorted(crawled_sites - changed_sites):
        prods = (session.query(SourceProduct)
                 .filter(SourceProduct.site == site,
                         SourceProduct.deleted_at.is_(None))
                 .order_by(SourceProduct.id).all())
        if not prods:
            continue
        link_by = _link_by_product(session, prods)
        items = []
        for p in prods:
            grid, summ = _stock_cells(session, p.id)
            key = link_by.get(p.id) or (None, None)
            items.append({
                "source_product_id": p.id,
                "url": p.url,
                "name": p.product_name or p.url,
                "surface_price": p.last_price,          # 그 상품의 값. 대표가·최저가 폴백 없음
                "sku": key[0],
                "source_id": key[1],
                "stock_summary": summ,
                "stock_grid": grid,
            })
        out.append({
            "site": site, "site_label": lab.get(site, site),
            "product_count": len(items),
            "products": items,
        })
    return out


def failing_now(session) -> list[dict]:
    """'지금 실패 중'(★회차별 아님 — 현재 last_status='error') 사유별 묶음."""
    try:
        from lemouton.sources.failure_classify import list_crawl_failures
        groups = list_crawl_failures(session)
    except Exception:
        return []
    out = []
    for g in groups or []:
        if not g.get("count"):
            continue
        sites = sorted({i.get("site_label") or i.get("site") for i in g.get("items", [])})
        out.append({"reason": g.get("label"), "emoji": g.get("emoji"),
                    "count": g["count"], "sites": sites})
    return out


def lap_report(session, *, lap_no: int, now: datetime) -> dict | None:
    """N회차 보고서. 없으면 None."""
    from lemouton.sources.models import CrawlDelta, SourceProduct
    from lemouton.sources.crawl_schedule import lap_stats, _as_naive_utc

    b = lap_bounds(session, lap_no=lap_no, now=now)
    if b is None:
        return None
    start, end = b

    deltas = (session.query(CrawlDelta)
              .filter(CrawlDelta.crawled_at > start, CrawlDelta.crawled_at <= end)
              .all())
    spids = {d.source_product_id for d in deltas}
    sp_map = {}
    if spids:
        for sp in session.query(SourceProduct).filter(SourceProduct.id.in_(spids)).all():
            sp_map[sp.id] = sp

    # ★[2026-07-10] '처음 수집'(이전 값 없음 → 값이 처음 잡힘)은 변동이 아니다.
    #   그냥 세면 첫 크롤 때 수백~수천 건이 '가격 변동'으로 둔갑해 사용자를 속인다(라이브 실측).
    #   → 변동 목록에서 빼고 first_seen 으로 따로 센다.
    price_rows, stock_rows = [], []
    first_seen = {"price": 0, "stock": 0}
    _lab = site_labels()          # hmall → 현대H몰 (화면 표기용)
    for d in deltas:
        if not (d.price_changed or d.stock_changed):
            continue
        sp = sp_map.get(d.source_product_id)
        site = (sp.site if sp else "?")
        site_label = _lab.get(site, site)
        for it in parse_detail(d.detail or ""):
            if it["kind"] == "price":
                fw, tw = _price_word(it["from"]), _price_word(it["to"])
                if fw == "없음":                 # 처음 가격이 잡힘 = 변동 아님
                    first_seen["price"] += 1
                    continue
                f, t = _to_int(it["from"]), _to_int(it["to"])
                delta = (t - f) if (f is not None and t is not None) else None
                if delta == 0:
                    continue
                price_rows.append({
                    "site": site, "site_label": site_label,
                    "option": it["option"], "from": fw, "to": tw,
                    "delta": delta,
                    "dir": ("up" if (delta or 0) > 0 else "dn" if (delta or 0) < 0 else "unk"),
                })
            elif it["kind"] == "stock":
                fw, tw = _stock_word(it["from"]), _stock_word(it["to"])
                if fw == "미크롤":               # 처음 재고가 잡힘 = 변동 아님
                    first_seen["stock"] += 1
                    continue
                if fw == tw:
                    continue
                stock_rows.append({
                    "site": site, "site_label": site_label,
                    "option": it["option"], "from": fw, "to": tw,
                    "dir": ("so" if tw == "품절" else "re" if fw == "품절"
                            else "unk" if tw == "확인불가" else "chg"),
                })
            else:  # 옵션 생김 = 신규(변동 아님) / 사라짐 = 옵션 소멸(중요 변동)
                if it["to"] == "생김":
                    first_seen["stock"] += 1
                    continue
                stock_rows.append({
                    "site": site, "site_label": site_label,
                    "option": it["option"], "from": "있음", "to": "옵션 사라짐",
                    "dir": "so",
                })

    minutes = max(1, round((end - start).total_seconds() / 60))
    stats = lap_stats(session, now=now)
    _crawled = {sp_map[i].site for i in spids if i in sp_map}
    _changed = {r["site"] for r in price_rows} | {r["site"] for r in stock_rows}
    try:
        _keep = keep_sources(session, crawled_sites=_crawled, changed_sites=_changed)
    except Exception:
        _keep = []            # 요약 실패해도 변동 보고서는 살린다
    return {
        "lap": {
            "no": lap_no,
            "started_at": start.isoformat(),
            "ended_at": end.isoformat(),
            "minutes": minutes,
            "avg_minutes": stats.get("avg_lap_minutes"),
        },
        "summary": {
            "urls": len(spids),
            "sites": len({(sp_map[i].site) for i in spids if i in sp_map}),
            "excluded_sites": excluded_sites(session),
            # 처음 수집(이전 값 없음 → 값이 처음 잡힘). 변동 아님 — 따로 표기.
            "first_seen": first_seen["price"] + first_seen["stock"],
        },
        "changes": {"price": price_rows, "stock": stock_rows},
        # 변동 없던 소싱처의 지금 값 (표면가 + 최종매입가 열쇠 + 재고 격자)
        "keep_sources": _keep,
        "result": {
            "saved": len(deltas),          # 이번 바퀴 저장된(=성공) 크롤 수
            "failing_now": failing_now(session),   # ★현재 기준(회차별 아님)
        },
    }
