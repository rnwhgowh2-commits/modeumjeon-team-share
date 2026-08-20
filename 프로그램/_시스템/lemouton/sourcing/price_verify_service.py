"""소싱처별 최종매입가 검증 — DB 조회 계층 (② 수집 데이터 · ③ 계산 결과 채움).

판정 로직은 price_verify.py (순수), 여기는 DB 에서 ②③ 을 긁어오는 역할만 한다.

★ 라이브 사이트에 절대 접속하지 않는다. 크롤 트리거 없음. 우리 DB 값만 읽는다.
★ ③ 계산은 기존 엔진 webapp.routes.api_benefits.compute_breakdown 을 그대로 호출한다.
   재구현 금지 — 재구현하면 '검증기가 검증 대상과 같은 버그를 갖는' 상태가 된다.
★ 값이 없으면 폴백·추정 없이 None 을 돌려준다. 판정 단계에서 '확인불가' 가 된다.
"""
import json

# source_key → SourceRegistry.main_url 도메인 (레지스트리 정수 id 매핑용).
# api_pricing.py 의 _key_domain 과 같은 표 — 거기서 매트릭스가 쓰는 매핑 그대로.
_KEY_DOMAIN = {
    "lemouton": "lemouton.co.kr",
    "ss_lemouton": "smartstore.naver.com",
    "musinsa": "musinsa.com",
    "ssf": "ssfshop.com",
    "lotteon": "lotteon.com",
    "ssg": "ssg.com",
}


def _norm(url):
    from lemouton.sources.service import normalize_url
    return normalize_url(url or "")


def resolve_source_id(session, source_key):
    """소싱처 key → compute_breakdown 이 받는 source_id.

    SourceRegistry 에 행이 있으면 정수 id, 없으면(카탈로그 소싱처 — 롯데아이몰·현대H몰)
    합성 문자열 'key:<source_key>'. compute_breakdown._resolve_site_key 가 둘 다 받는다.
    """
    dom = _KEY_DOMAIN.get(source_key)
    if dom:
        try:
            from lemouton.sourcing.models_pricing import SourceRegistry
            for r in session.query(SourceRegistry).all():
                if dom in (r.main_url or ""):
                    return r.id
        except Exception:
            pass
    return "key:" + str(source_key)


def find_source_product(session, source_key, url):
    """(site, url) → SourceProduct. 없으면 None (= 크롤 데이터 없음 → 확인불가)."""
    from lemouton.sources.models import SourceProduct
    target = _norm(url)
    if not target:
        return None
    base = (url or "").split("?", 1)[0]
    q = (session.query(SourceProduct)
         .filter(SourceProduct.site == source_key,
                 SourceProduct.deleted_at.is_(None)))
    if base:
        q = q.filter(SourceProduct.url.startswith(base, autoescape=True))
    for sp in q.all():
        if _norm(sp.url) == target:
            return sp
    return None


def find_sku(session, source_key, url):
    """URL → canonical_sku. 못 찾으면 None (③ 계산 불가 → 확인불가).

    두 경로를 다 본다:
      (a) legacy  option_source_urls.product_url
      (b) 현행    bundle_source_urls.url → option_source_url_links.option_canonical_sku
    URL 저장소가 분열돼 있어(등록·크롤·표시 따로) 한 곳만 보면 놓친다.
    """
    target = _norm(url)
    if not target:
        return None
    try:
        from lemouton.sourcing.models_pricing import OptionSourceUrl
        for r in session.query(OptionSourceUrl).all():
            if _norm(r.product_url) == target:
                return r.canonical_sku
    except Exception:
        pass
    try:
        from lemouton.sourcing.models import BundleSourceUrl, OptionSourceUrlLink
        rows = (session.query(OptionSourceUrlLink, BundleSourceUrl)
                .join(BundleSourceUrl,
                      OptionSourceUrlLink.bundle_source_url_id == BundleSourceUrl.id)
                .filter(BundleSourceUrl.source_key == source_key)
                .all())
        for lk, bsu in rows:
            if _norm(bsu.url) == target:
                return lk.option_canonical_sku
    except Exception:
        pass
    return None


def _parse_json(raw):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def collect(session, source_key, url):
    """② 우리가 수집한 데이터 + ③ 우리 계산 결과를 한 번에 채운다.

    반환 dict (없는 값은 전부 None — 폴백 없음):
      ours_surface_price   ② 표면가 (SourceProduct.last_price)
      ours_benefits        ② 혜택 항목 목록 (엔진이 실제로 쥔 items_used)
      dynamic_benefits     ② 크롤이 담아온 사이트 동적 혜택 원문
      computed_final_price ③ 최종매입가
      computed_steps       ③ fx영수증 steps (None = 계산 실패/불가)
      compute_error        ③ 실패 사유
      canonical_sku / source_product_id / last_fetched_at / last_status
    """
    out = {
        "ours_surface_price": None, "ours_benefits": None, "dynamic_benefits": None,
        "computed_final_price": None, "computed_steps": None, "compute_error": None,
        "canonical_sku": None, "source_product_id": None,
        "last_fetched_at": None, "last_status": None, "product_name": None,
    }

    sp = find_source_product(session, source_key, url)
    if sp is None:
        out["compute_error"] = ("이 URL 의 크롤 데이터가 우리 DB 에 없습니다. "
                                "(크롤을 먼저 돌려야 합니다 — 이 화면은 크롤을 실행하지 않습니다.)")
        return out

    out["source_product_id"] = sp.id
    out["ours_surface_price"] = sp.last_price
    out["dynamic_benefits"] = _parse_json(sp.dynamic_benefits_json)
    out["last_status"] = sp.last_status
    out["product_name"] = sp.product_name
    out["last_fetched_at"] = sp.last_fetched_at.isoformat() if sp.last_fetched_at else None

    if sp.last_price is None:
        out["compute_error"] = "수집된 표면가가 없습니다(크롤 실패 또는 파싱 실패)."
        return out

    sku = find_sku(session, source_key, url)
    out["canonical_sku"] = sku
    if not sku:
        out["compute_error"] = ("이 URL 에 연결된 옵션(SKU)을 찾지 못해 최종매입가를 "
                                "계산할 수 없습니다. URL 등록·옵션 연결을 확인해 주세요.")
        return out

    source_id = resolve_source_id(session, source_key)
    try:
        # ★ 기존 엔진 그대로 호출 — 여기서 계산을 재구현하지 않는다.
        from webapp.routes.api_benefits import compute_breakdown
        bd = compute_breakdown(
            session, sku=sku, source_id=source_id,
            sale_price=float(sp.last_price), source_product_id=sp.id)
    except Exception as e:  # noqa: BLE001
        out["compute_error"] = f"최종매입가 계산 중 오류: {e}"
        return out

    if not isinstance(bd, dict) or bd.get("error"):
        out["compute_error"] = (bd or {}).get("error") or "계산 결과를 받지 못했습니다."
        return out

    out["computed_final_price"] = bd.get("final_price")
    out["computed_steps"] = bd.get("steps")
    out["ours_benefits"] = bd.get("items_used")
    return out
