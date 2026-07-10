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
    """N회차(오늘 기준)의 (시작, 끝). 없으면 None."""
    from lemouton.sources.models import CrawlLapRun
    from lemouton.sources.crawl_schedule import lap_stats, _as_naive_utc

    laps = lap_stats(session, now=now)["today_laps"]
    if not (1 <= lap_no <= len(laps)):
        return None
    end = datetime.fromisoformat(laps[lap_no - 1]["at"])
    if lap_no >= 2:
        start = datetime.fromisoformat(laps[lap_no - 2]["at"])
    else:
        prev = (session.query(CrawlLapRun)
                .filter(CrawlLapRun.completed_at < end)
                .order_by(CrawlLapRun.completed_at.desc()).first())
        start = _as_naive_utc(prev.completed_at) if prev else (end - timedelta(hours=24))
    return start, end


def excluded_sites(session) -> list[str]:
    """계수 0 = 이번 바퀴에서 아예 제외된 소싱처."""
    from lemouton.sources.crawl_schedule import list_weight_rules
    src = list_weight_rules(session).get("source", {})
    return sorted(k for k, w in src.items() if (w or 0) <= 0)


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

    price_rows, stock_rows = [], []
    for d in deltas:
        if not (d.price_changed or d.stock_changed):
            continue
        sp = sp_map.get(d.source_product_id)
        site = (sp.site if sp else "?")
        for it in parse_detail(d.detail or ""):
            if it["kind"] == "price":
                f, t = _to_int(it["from"]), _to_int(it["to"])
                delta = (t - f) if (f is not None and t is not None) else None
                price_rows.append({
                    "site": site, "option": it["option"],
                    "from": _price_word(it["from"]), "to": _price_word(it["to"]),
                    "delta": delta,
                    "dir": ("up" if (delta or 0) > 0 else "dn" if (delta or 0) < 0 else "flat"),
                })
            elif it["kind"] == "stock":
                fw, tw = _stock_word(it["from"]), _stock_word(it["to"])
                stock_rows.append({
                    "site": site, "option": it["option"], "from": fw, "to": tw,
                    "dir": ("so" if tw == "품절" else "re" if fw == "품절" else "chg"),
                })
            else:  # 옵션 생김/사라짐
                stock_rows.append({
                    "site": site, "option": it["option"], "from": "-", "to": it["to"],
                    "dir": ("so" if it["to"] == "사라짐" else "re"),
                })

    minutes = max(1, round((end - start).total_seconds() / 60))
    stats = lap_stats(session, now=now)
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
        },
        "changes": {"price": price_rows, "stock": stock_rows},
        "result": {
            "saved": len(deltas),          # 이번 바퀴 저장된(=성공) 크롤 수
            "failing_now": failing_now(session),   # ★현재 기준(회차별 아님)
        },
    }
