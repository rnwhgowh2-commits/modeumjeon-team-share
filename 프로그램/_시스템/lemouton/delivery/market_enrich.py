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

# 더망고 마켓명(B열) → order_export 슬러그. SUPPORTED 밖은 None(스킵).
_SLUG = {
    "쿠팡": "coupang",
    "롯데on": "lotteon", "롯데온": "lotteon", "롯데ON": "lotteon",
    "스마트스토어": "smartstore", "스스": "smartstore",
    "11번가": "eleven11",
}


def market_slug(market_name):
    if not market_name:
        return None
    slug = _SLUG.get(str(market_name).strip())
    return slug if slug in _oe.SUPPORTED else None


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


def enrich_from_market_api(session, uploaded_uids, warnings=None) -> dict:
    """업로드된 주문을 마켓 API 실주문으로 보강. 반환 {checked, unmatched, skipped}."""
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

    # 마켓별 실주문 조회 → 오픈마켓주문번호 인덱스 + 실제 응답 온 마켓(슬러그) 추적
    index = {}
    fetched_slugs = set()
    if grouped:
        since, until = _query_window(orders)   # 주문일까지 소급(7일 기본창 밖 주문 매칭)
        try:
            # include_settlement=False — 배송검사는 주문상태·송장만 필요. 정산 하루씩 루프는
            # 넓은 창에서 타임아웃 유발이라 끈다.
            fetched = _oe.combined_order_rows(list(grouped.keys()), use_cache=True,
                                              since=since, until=until,
                                              include_settlement=False,
                                              warnings=warnings)
        except Exception as e:   # noqa: BLE001 — 조회 전체 실패도 확인불가로 표면화
            fetched = []
            warnings.append(f"[배송검사] 마켓 조회 실패: {type(e).__name__}")
        for fr in fetched:
            no = str(fr.get("오픈마켓주문번호") or "").strip()
            if no:
                index[no] = fr
            sl = market_slug(fr.get("판매처"))
            if sl:
                fetched_slugs.add(sl)

    checked = unmatched = 0
    for o in orders:
        if o.mango_uid in skipped_set:
            continue
        fr = None
        for k in _match_keys(o.market_order_no):   # 괄호형(스스 상품주문번호) 포함 후보로 매칭
            if k in index:
                fr = index[k]
                break
        if fr is None:
            # 왜 못 찾았나 구분: 그 마켓 응답이 아예 없으면=조회 실패(IP/키), 있으면=기간 밖/취소
            slug = market_slug(o.market_name)
            if slug and slug not in fetched_slugs:
                o.market_check_error = f"{o.market_name} 계정 조회 실패 · 「판매처 관리」에서 서버 IP·키 확인"
            else:
                o.market_check_error = "마켓에서 주문 못 찾음 · 조회 기간 밖이거나 취소된 주문"
            o.market_checked_at = _now()
            unmatched += 1
            continue
        inv = str(fr.get("송장입력") or "").strip()
        if inv == "송장미입력":
            inv = ""
        o.market_api_status = str(fr.get("주문상태") or "").strip() or None
        o.market_api_status_raw = str(fr.get("주문상태원본") or "").strip() or None
        o.market_api_invoice = inv
        o.market_shipped_at = str(fr.get("발송처리일") or "").strip() or None
        o.market_check_error = None
        o.market_checked_at = _now()
        checked += 1

    session.commit()
    return {"checked": checked, "unmatched": unmatched, "skipped": len(skipped_uids),
            "warnings": warnings}
