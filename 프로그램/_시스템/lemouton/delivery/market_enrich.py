"""배송검사 v2 — 더망고 주문을 마켓 API 실주문으로 보강(enrich).

오픈마켓주문번호로 order_export 실주문과 매칭 → 마켓 통일상태·등록송장을 MangoOrder 에 캐시.
마켓 API = 서버(AWS) 전용. 로컬/테스트는 order_export 를 monkeypatch.
"""
import re
from datetime import datetime, timedelta, timezone

from lemouton.markets import order_export as _oe
from lemouton.delivery.models import MangoOrder

_PAREN = re.compile(r'^(.+?)\((.+?)\)\s*$')


def _match_keys(order_no):
    """더망고 주문번호 → 마켓 오픈마켓주문번호 매칭 후보 키(순서대로).

    더망고는 스마트스토어를 '주문번호(상품주문번호)' 괄호 형식으로 저장하는데,
    order_export 오픈마켓주문번호는 상품주문번호(또는 주문번호)만이라 그대로는 매칭 실패한다.
    → 괄호 안(상품주문번호)·괄호 밖(주문번호)도 후보로 넣는다.
    """
    no = (order_no or "").strip()
    keys = [no] if no else []
    m = _PAREN.match(no)
    if m:
        inner, outer = m.group(2).strip(), m.group(1).strip()
        if inner:
            keys.append(inner)   # 스마트스토어 오픈마켓주문번호 = 상품주문번호(괄호 안)
        if outer:
            keys.append(outer)
    return keys

# 더망고 마켓명(B열) → order_export 슬러그. 공개 안 된 마켓은 None(스킵).
_SLUG = {
    "쿠팡": "coupang",
    "롯데on": "lotteon", "롯데온": "lotteon", "롯데ON": "lotteon",
    "스마트스토어": "smartstore", "스스": "smartstore",
    "11번가": "eleven11",
    # 옥션·G마켓 — 라이브 검증으로 열린 뒤에만 매칭된다(아래 게이트).
    "옥션": "auction", "AUCTION": "auction",
    "G마켓": "gmarket", "지마켓": "gmarket", "GMARKET": "gmarket", "G마켓(구스마일)": "gmarket",
}


def market_slug(market_name):
    if not market_name:
        return None
    slug = _SLUG.get(str(market_name).strip())
    return slug if slug in _oe.supported_markets() else None


def group_by_market(rows):
    """rows(dict, market_name·market_order_no) → ({slug: [주문번호...]}, [스킵된 uid...])."""
    grouped, skipped = {}, []
    for r in rows:
        slug = market_slug(r.get("market_name"))
        if not slug:
            skipped.append(r.get("mango_uid"))
            continue
        no = (r.get("market_order_no") or "").strip()
        if no:
            grouped.setdefault(slug, []).append(no)
    return grouped, skipped


def _now():
    return datetime.now(timezone.utc)


_KST = timezone(timedelta(hours=9))
_DATE_RE = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
# 마켓 조회 최대 소급(일). 해외현지배송중은 보통 2~4주 전 주문 → 넉넉히 두 달.
# 이보다 오래된 주문은 마켓 조회 범위 밖이라 정직하게 '확인 불가'로 남긴다.
_MAX_LOOKBACK_DAYS = 62


def _parse_order_date(s):
    """더망고 주문일자(A열) 문자열 → datetime(KST). 형식 무관(YYYY-MM-DD·YYYY.MM.DD 등). 실패 None."""
    m = _DATE_RE.search(str(s or ""))
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=_KST)
    except ValueError:
        return None


def _query_window(orders):
    """업로드 주문의 주문일 범위 → 마켓 조회 (since, until).

    가장 오래된 주문일까지 소급하되 _MAX_LOOKBACK_DAYS 로 상한(마켓 조회 한계·속도 보호).
    7일 기본창은 '해외현지배송중'처럼 오래된 주문을 놓쳐 매칭 실패(확인불가) 하던 원인.
    """
    until = datetime.now(_KST)
    floor = until - timedelta(days=_MAX_LOOKBACK_DAYS)
    dates = [d for d in (_parse_order_date(o.ordered_at) for o in orders) if d]
    if not dates:
        return floor, until          # 주문일을 못 읽으면 소급 상한까지 넓게(7일보다 안전)
    since = max(min(dates) - timedelta(days=1), floor)   # 하루 버퍼, 상한 클램프
    return since, until


# 슬러그 → 화면 표시 라벨(진행현황 마켓 칩)
_LABEL = {"coupang": "쿠팡", "lotteon": "롯데온",
          "smartstore": "스마트스토어", "eleven11": "11번가"}


def _apply_match(o, fr):
    """조회된 마켓 행(fr)을 주문(o)에 반영. 매칭 성공 처리."""
    inv = str(fr.get("송장입력") or "").strip()
    if inv == "송장미입력":
        inv = ""
    o.market_api_status = str(fr.get("주문상태") or "").strip() or None
    o.market_api_status_raw = str(fr.get("주문상태원본") or "").strip() or None
    o.market_api_invoice = inv
    o.market_shipped_at = str(fr.get("발송처리일") or "").strip() or None
    o.market_check_error = None
    o.market_checked_at = _now()


def iter_enrich(session, uploaded_uids, warnings=None):
    """업로드 주문을 마켓 API 로 보강하며 진행 이벤트를 마켓마다 순차 yield(스트리밍용).

    이벤트: start(markets[{slug,label,total}], skipped) → 마켓마다 market(state=fetching→done,
    matched/total) → done(checked,unmatched,skipped). DB 갱신은 부수효과(마지막에 commit).
    마켓을 하나씩 조회해 '어느 마켓 몇 건'을 실시간으로 흘려준다(폴링 없이 업로드 응답 스트림).
    """
    if warnings is None:
        warnings = []
    orders = (session.query(MangoOrder)
              .filter(MangoOrder.mango_uid.in_(list(uploaded_uids))).all())
    rows = [{"mango_uid": o.mango_uid, "market_name": o.market_name,
             "market_order_no": o.market_order_no} for o in orders]
    grouped, skipped_uids = group_by_market(rows)
    skipped_set = set(skipped_uids)

    # 미지원 마켓 주문 → 확인불가 (옥션·G마켓 등)
    for o in orders:
        if o.mango_uid in skipped_set:
            o.market_check_error = "옥션·G마켓은 주문 조회 미지원"
            o.market_checked_at = _now()

    orders_by_slug = {}
    for o in orders:
        if o.mango_uid in skipped_set:
            continue
        sl = market_slug(o.market_name)
        if sl:
            orders_by_slug.setdefault(sl, []).append(o)

    market_slugs = list(grouped.keys())
    yield {"phase": "start", "skipped": len(skipped_uids),
           "markets": [{"slug": sl, "label": _LABEL.get(sl, sl),
                        "total": len(orders_by_slug.get(sl, []))} for sl in market_slugs]}

    since, until = _query_window(orders) if market_slugs else (None, None)
    checked = unmatched = 0

    # 모든 마켓을 '조회 중'으로 먼저 표시 → 한번에(병렬) 조회 시작. 각 마켓은 끝나는 대로 완료.
    # (마켓 4개 동시, 한 마켓 안의 계정만 순차 = 주문내역과 동일한 병렬 방식·429 방지)
    for sl in market_slugs:
        yield {"phase": "market", "slug": sl, "label": _LABEL.get(sl, sl),
               "total": len(orders_by_slug.get(sl, [])), "matched": 0, "state": "fetching"}

    if market_slugs:
        import queue as _queue
        from concurrent.futures import ThreadPoolExecutor

        q = _queue.Queue()

        def _fetch(sl):   # 워커: 조회만(DB 안 건드림 — 세션은 메인 스레드 전용)
            try:
                rows = _oe.combined_order_rows([sl], use_cache=True, since=since, until=until,
                                               include_settlement=False, warnings=warnings)
            except Exception as e:   # noqa: BLE001
                rows = None
                warnings.append(f"[배송검사] {_LABEL.get(sl, sl)} 조회 실패: {type(e).__name__}")
            q.put((sl, rows))

        ex = ThreadPoolExecutor(max_workers=min(4, len(market_slugs)))
        try:
            for sl in market_slugs:
                ex.submit(_fetch, sl)
            for _ in market_slugs:
                sl, fetched = q.get()          # 끝나는 대로(완료 순서)
                if fetched is None:
                    fetched = []
                index, responded = {}, False
                for fr in fetched:
                    no = str(fr.get("오픈마켓주문번호") or "").strip()
                    if no:
                        index[no] = fr
                    if market_slug(fr.get("판매처")) == sl:
                        responded = True
                m_checked = 0
                for o in orders_by_slug.get(sl, []):   # 매칭·DB 갱신은 메인 스레드에서만
                    fr = None
                    for k in _match_keys(o.market_order_no):   # 괄호형(스스 상품주문번호) 포함
                        if k in index:
                            fr = index[k]
                            break
                    if fr is None:
                        if not responded:
                            o.market_check_error = f"{o.market_name} 계정 조회 실패 · 「판매처 관리」에서 서버 IP·키 확인"
                        else:
                            o.market_check_error = "마켓에서 주문 못 찾음 · 조회 기간 밖이거나 취소된 주문"
                        o.market_checked_at = _now()
                        unmatched += 1
                        continue
                    _apply_match(o, fr)
                    checked += 1
                    m_checked += 1
                yield {"phase": "market", "slug": sl, "label": _LABEL.get(sl, sl),
                       "total": len(orders_by_slug.get(sl, [])), "matched": m_checked, "state": "done"}
        finally:
            ex.shutdown(wait=False)

    session.commit()
    yield {"phase": "done", "checked": checked, "unmatched": unmatched,
           "skipped": len(skipped_uids), "warnings": list(warnings)}


def enrich_from_market_api(session, uploaded_uids, warnings=None) -> dict:
    """iter_enrich 를 소비해 요약 반환(비스트리밍 호출·테스트용). {checked,unmatched,skipped}."""
    if warnings is None:
        warnings = []
    done = {"checked": 0, "unmatched": 0, "skipped": 0}
    for ev in iter_enrich(session, uploaded_uids, warnings):
        if ev.get("phase") == "done":
            done = ev
    return {"checked": done.get("checked", 0), "unmatched": done.get("unmatched", 0),
            "skipped": done.get("skipped", 0), "warnings": warnings}
