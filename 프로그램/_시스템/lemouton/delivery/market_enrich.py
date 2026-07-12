"""배송검사 v2 — 더망고 주문을 마켓 API 실주문으로 보강(enrich).

오픈마켓주문번호로 order_export 실주문과 매칭 → 마켓 통일상태·등록송장을 MangoOrder 에 캐시.
마켓 API = 서버(AWS) 전용. 로컬/테스트는 order_export 를 monkeypatch.
"""
from datetime import datetime, timezone

from lemouton.markets import order_export as _oe
from lemouton.delivery.models import MangoOrder

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

    # 미지원 마켓 주문 → 확인불가
    for o in orders:
        if o.mango_uid in skipped_set:
            o.market_check_error = "마켓 API 미지원(주문 조회 불가)"
            o.market_checked_at = _now()

    # 마켓별 실주문 조회 → 오픈마켓주문번호 인덱스
    index = {}
    if grouped:
        try:
            fetched = _oe.combined_order_rows(list(grouped.keys()), use_cache=True,
                                              warnings=warnings)
        except Exception as e:   # noqa: BLE001 — 조회 전체 실패도 확인불가로 표면화
            fetched = []
            warnings.append(f"[배송검사] 마켓 조회 실패: {type(e).__name__}")
        for fr in fetched:
            no = str(fr.get("오픈마켓주문번호") or "").strip()
            if no:
                index[no] = fr

    checked = unmatched = 0
    for o in orders:
        if o.mango_uid in skipped_set:
            continue
        no = (o.market_order_no or "").strip()
        fr = index.get(no)
        if fr is None:
            o.market_check_error = "마켓에서 못 찾음(조회 실패 또는 기간 밖)"
            o.market_checked_at = _now()
            unmatched += 1
            continue
        inv = str(fr.get("송장입력") or "").strip()
        if inv == "송장미입력":
            inv = ""
        o.market_api_status = str(fr.get("주문상태") or "").strip() or None
        o.market_api_invoice = inv
        o.market_shipped_at = str(fr.get("발송처리일") or "").strip() or None
        o.market_check_error = None
        o.market_checked_at = _now()
        checked += 1

    session.commit()
    return {"checked": checked, "unmatched": unmatched, "skipped": len(skipped_uids),
            "warnings": warnings}
