"""[v2] 소싱 정규화 서비스 — 단일 진실 원천 보장.

핵심 의도:
  - 같은 URL 을 N 모음전이 입력해도 SourceProduct 1행만 존재 (글로벌 단일)
  - 크롤러는 SourceProduct 단위로 1번만 fetch (네트워크 dedup)
  - 모음전·옵션은 SourceProduct/SourceOption 을 참조 (M:N)

설계 문서: docs/architecture_v2.md §3.1
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger(__name__)

from sqlalchemy.orm import Session

from .models import (
    SourceProduct, SourceOption, ModelSourceLink, OptionSourceLink,
)


# ─────────────────────────────────────────────────────────────────────────────
# URL 정규화 (잔여 #2) — 트래킹 파라미터 제거
# ─────────────────────────────────────────────────────────────────────────────
import re as _re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# 제거 대상 트래킹 파라미터 (네이버 / 일반 광고·검색 트래킹).
_TRACKING_PARAM_PATTERNS = [
    _re.compile(r'^nl[-_]ts'),       # NAVER 광고 추적 (nl-ts-pid, nl-ts-id 등)
    _re.compile(r'^NaPm$'),           # NAVER 검색 광고 메타
    _re.compile(r'^utm_'),            # Google Analytics utm_*
    _re.compile(r'^utag$'),           # SSF / SSG utag
    _re.compile(r'^fbclid$'),         # Facebook click ID
    _re.compile(r'^gclid$'),          # Google click ID
    _re.compile(r'^_trk'),            # 일반 트래킹
]


from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=8192)
def normalize_url(url: str) -> str:
    """트래킹 파라미터를 제거한 정규화 URL 반환. 비교·매칭 용도.

    예:
      ``brand.naver.com/lemouton/products/9496367527?nl-ts-pid=xxx&NaPm=yyy``
      → ``brand.naver.com/lemouton/products/9496367527``

    [perf 2026-06-12] 순수 함수(url→정규화url) 이며 매트릭스/breakdown 빌드 중 동일 URL 에
      수백~수천 번 호출되므로 lru_cache 로 메모이즈. 입력 URL 집합은 유한(상품 URL)이라 안전.
    """
    if not url:
        return url
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    kept_qs = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(p.match(k) for p in _TRACKING_PARAM_PATTERNS)
    ]
    new_query = urlencode(kept_qs)
    return urlunparse(parsed._replace(query=new_query))


def _utcnow():
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Upsert helpers — 멱등 보장
# ─────────────────────────────────────────────────────────────────────────────

def upsert_source_product(
    session: Session,
    *,
    site: str,
    url: str,
    external_product_id: str | None = None,
    product_name: str | None = None,
) -> SourceProduct:
    """site + url 조합으로 SourceProduct 가져오거나 생성.

    같은 URL을 N 번 호출해도 1 행만 만들어짐 (uq_source_product_site_url).

    [INV-2 2026-06-13] url 을 normalize_url 로 정규화 후 조회·저장한다. utag/NaPm
    같은 트래킹 파라미터만 다른 같은 상품이 2행으로 분열(매트릭스 stale 픽 위험)
    되던 것을 차단. ckwhere 등 가격에 영향 주는 파라미터는 normalize 가 보존하므로
    별도 상품으로 유지된다(쿠폰가/비쿠폰가 혼선 방지).
    """
    url = normalize_url(url)
    existing = (session.query(SourceProduct)
                .filter_by(site=site, url=url, deleted_at=None)
                .first())
    if existing is not None:
        # 메타 정보 보강 (옵션)
        if external_product_id and not existing.external_product_id:
            existing.external_product_id = external_product_id
        if product_name and not existing.product_name:
            existing.product_name = product_name
        return existing
    sp = SourceProduct(
        site=site, url=url,
        external_product_id=external_product_id,
        product_name=product_name,
    )
    session.add(sp)
    session.flush()  # id 즉시 할당
    return sp


def upsert_source_option(
    session: Session,
    *,
    source_product_id: int,
    color_text: str | None = None,
    size_text: str | None = None,
    external_option_id: str | None = None,
    current_price: int | None = None,
    current_stock: int | None = None,
    dynamic_benefits_json: str | None = None,
) -> SourceOption:
    """SourceProduct + (color, size) 조합으로 SourceOption upsert."""
    # [2026-06-19 fix] deleted_at 필터 제거 — 유니크 제약
    #   uq_source_option_product_color_size 는 (source_product_id, color_text, size_text)
    #   만 보고 deleted_at 을 무시한다. prune 으로 soft-delete 된 (색,사이즈) 행이 남아 있는데
    #   deleted_at=None 으로만 조회하면 '없음'으로 보여 새 INSERT → 중복키 충돌(UniqueViolation)
    #   → 크롤 저장 전체가 IntegrityError 로 실패하던 '조용한 실패'(예: SSF 오렌지). 매치되면
    #   soft-delete 여부와 무관히 같은 행을 되살려(revive) 갱신한다.
    existing = (session.query(SourceOption)
                .filter_by(source_product_id=source_product_id,
                           color_text=color_text, size_text=size_text)
                .first())
    if existing is not None:
        if getattr(existing, 'deleted_at', None) is not None:
            existing.deleted_at = None   # soft-delete 행 되살림
        if external_option_id and not existing.external_option_id:
            existing.external_option_id = external_option_id
        if current_price is not None:
            existing.current_price = current_price
        if current_stock is not None:
            existing.current_stock = current_stock
        if dynamic_benefits_json is not None:
            existing.dynamic_benefits_json = dynamic_benefits_json
        existing.last_fetched_at = _utcnow()
        return existing
    so = SourceOption(
        source_product_id=source_product_id,
        color_text=color_text, size_text=size_text,
        external_option_id=external_option_id,
        current_price=current_price, current_stock=current_stock,
        dynamic_benefits_json=dynamic_benefits_json,
        last_fetched_at=_utcnow(),
    )
    session.add(so)
    session.flush()
    return so


def link_model_to_source(
    session: Session,
    *,
    model_code: str,
    source_product_id: int,
) -> ModelSourceLink:
    """모음전 ↔ SourceProduct M:N 링크 멱등 생성."""
    existing = (session.query(ModelSourceLink)
                .filter_by(model_code=model_code,
                           source_product_id=source_product_id)
                .first())
    if existing is not None:
        return existing
    link = ModelSourceLink(model_code=model_code,
                           source_product_id=source_product_id)
    session.add(link)
    session.flush()
    return link


def link_option_to_source(
    session: Session,
    *,
    canonical_sku: str,
    source_option_id: int,
) -> OptionSourceLink:
    """옵션 ↔ SourceOption M:N 링크 멱등 생성."""
    existing = (session.query(OptionSourceLink)
                .filter_by(canonical_sku=canonical_sku,
                           source_option_id=source_option_id)
                .first())
    if existing is not None:
        return existing
    link = OptionSourceLink(canonical_sku=canonical_sku,
                            source_option_id=source_option_id)
    session.add(link)
    session.flush()
    return link


# ─────────────────────────────────────────────────────────────────────────────
# Fetch dedup — 같은 URL 한 번만 호출
# ─────────────────────────────────────────────────────────────────────────────

def _is_missing_browser_error(exc: Exception) -> bool:
    """Playwright 브라우저(chrome-headless-shell 등) 미설치로 인한 launch 실패인지 판별.

    배경(Plan A): Playwright 가 필요한 소싱처(lotteon.com 등)는 크롬이 깔린 사용자
    PC 가 크롤해 Supabase 에 채운다. 크롬 없는 서버(AWS 1GB)가 같은 소싱처를 크롤하면
    'BrowserType.launch: Executable doesn't exist ...' 로 실패하는데, 이때 last_status
    를 'error' 로 덮어쓰면 사용자 PC 가 채운 정상 데이터(가격/재고)가 사라진다.
    → 이 에러는 '실패'가 아니라 '이 호스트는 담당 아님'으로 보고 기존 데이터를 보존한다.
    """
    msg = str(exc or '')
    low = msg.lower()
    return ("executable doesn't exist" in low
            or ("playwright" in low and "launch" in low))


def fetch_one_source(
    session: Session,
    *,
    source_product_id: int,
    crawlers: dict[str, Any],
) -> dict:
    """단일 SourceProduct 만 fetch — `/sources/<id>/refetch` 사용.

    Returns:
      {'status': 'ok'|'error'|'no_crawler'|'not_found',
       'crawl_result': CrawlResult|None, 'error': str|None}
    """
    sp = session.get(SourceProduct, source_product_id)
    if sp is None or sp.deleted_at is not None:
        return {'status': 'not_found', 'crawl_result': None,
                'error': 'SourceProduct 없음 또는 삭제됨'}
    crawler = crawlers.get(sp.site)
    if crawler is None:
        sp.last_status = 'no_crawler'
        return {'status': 'no_crawler', 'crawl_result': None, 'error': None}
    try:
        cr = crawler.fetch(sp.url)
    except Exception as e:
        if _is_missing_browser_error(e):
            # 크롬 미설치 호스트(서버) — 기존 데이터 보존, 상태 손대지 않음.
            _log.warning("Playwright 브라우저 미설치 — %s 크롤 건너뜀(기존 데이터 유지)", sp.url)
            return {'status': 'skipped_no_browser', 'crawl_result': None, 'error': None}
        sp.last_status = 'error'
        sp.last_error_msg = str(e)[:500]
        sp.last_fetched_at = _utcnow()
        return {'status': 'error', 'crawl_result': None, 'error': str(e)}
    save_crawl_result(session, source_product=sp, crawl_result=cr)
    return {'status': 'ok', 'crawl_result': cr, 'error': None}


def fetch_unique_sources(
    session: Session,
    *,
    crawlers: dict[str, Any],
    progress_cb: Any = None,
) -> dict[int, dict]:
    """모든 활성 SourceProduct 를 사이트별로 dedup 호출.

    Args:
      crawlers: {source_name: AbstractCrawler}
      progress_cb: 선택. 상품 1개 크롤할 때마다 호출 — 소싱처별 실시간 진행 표시용.
        ``progress_cb(done, total, site, src_totals, src_done)``. 콜백 예외는 무시.

    Returns:
      {source_product_id: {'status': 'ok'|'error'|'no_crawler',
                           'crawl_result': CrawlResult|None,
                           'error': str|None}}

    핵심 가치:
      v1 pipeline.py 에서는 모델 N개 × URL 5개 = 같은 URL 중복 호출 가능.
      v2 service 는 unique URL 수만큼만 호출.
    """
    results: dict[int, dict] = {}

    products = (session.query(SourceProduct)
                .filter_by(deleted_at=None)
                .all())

    # 소싱처(site)별 총개수 — 진행 표시용
    src_totals: dict[str, int] = {}
    for sp in products:
        src_totals[sp.site] = src_totals.get(sp.site, 0) + 1
    src_done: dict[str, int] = {k: 0 for k in src_totals}
    total = len(products)

    def _emit(done: int, site) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(done, total, site, dict(src_totals), dict(src_done))
        except Exception:
            pass

    _emit(0, None)  # 시작 — 전부 대기중으로 즉시 표시
    done = 0
    for sp in products:
        crawler = crawlers.get(sp.site)
        if crawler is None:
            results[sp.id] = {'status': 'no_crawler',
                              'crawl_result': None, 'error': None}
            sp.last_status = 'no_crawler'
        else:
            try:
                cr = crawler.fetch(sp.url)
                results[sp.id] = {'status': 'ok',
                                  'crawl_result': cr, 'error': None}
                save_crawl_result(session, source_product=sp, crawl_result=cr)
            except Exception as e:
                if _is_missing_browser_error(e):
                    # 크롬 미설치 호스트(서버) — 사용자 PC 가 채운 데이터 보존, 덮어쓰지 않음.
                    _log.warning("Playwright 브라우저 미설치 — %s 크롤 건너뜀(기존 데이터 유지)", sp.url)
                    results[sp.id] = {'status': 'skipped_no_browser',
                                      'crawl_result': None, 'error': None}
                else:
                    results[sp.id] = {'status': 'error',
                                      'crawl_result': None, 'error': str(e)}
                    sp.last_status = 'error'
                    sp.last_error_msg = str(e)[:500]
                    sp.last_fetched_at = _utcnow()
        src_done[sp.site] = src_done.get(sp.site, 0) + 1
        done += 1
        _emit(done, sp.site)  # 상품 1개 완료 — 소싱처별 진행 갱신

    return results


def crawl_bundle_registered_urls(
    session: Session,
    *,
    model_code: str,
    crawlers: dict[str, Any],
    progress_cb: Any = None,
) -> dict:
    """[2026-06-03] 모음전에 등록된 소싱처 URL(bundle_source_urls)을 SourceProduct 로
    보장(get-or-create)한 뒤 크롤 → last_price 저장.

    배경: 등록 UI(bundle_source_urls/links)와 크롤 저장소(SourceProduct)가 분리돼,
    등록만 하고는 매트릭스에 가격이 안 뜨던 문제. 이 함수가 둘을 잇는다 —
    등록 URL → upsert SourceProduct(site=source_key) → fetch → save_crawl_result.
    SourceProduct.url 이 등록 URL 과 동일하므로 매트릭스(normalize_url 매칭)가 가격 표시.

    progress_cb: 선택. URL 1개 크롤할 때마다 호출 — 실시간 진행 표시용.
        시그니처 ``progress_cb(done:int, total:int, source_key:str|None,
                              src_totals:dict[str,int], src_done:dict[str,int])``.
        루프 시작 전 1회(done=0, source_key=None) + 각 URL 완료 후 1회 호출.
        콜백 예외는 크롤을 막지 않도록 무시한다.

    Returns: {total, ok, error, no_crawler, per_source:{key:{ok,error,no_crawler}}}.
    """
    from lemouton.sourcing.models import BundleSourceUrl
    rows = (session.query(BundleSourceUrl)
            .filter_by(model_code=model_code)
            .order_by(BundleSourceUrl.sort_order, BundleSourceUrl.id).all())
    valid = [b for b in rows if b.url]
    # [2026-06-12] SSG 딜(dealItemView) = 색상별 단품 URL 로 가격·재고가 커버되는 허브.
    #   uitemObj 인라인 JS 가 없어 fetch 시 "[SSG] 옵션 추출 실패"로 잡힘(거짓 실패).
    #   bundle_url_crawl.crawl_registered_urls 와 동일 정책으로 크롤 대상에서 제외한다.
    #   (가격·재고는 등록된 개별 색상 itemView URL 이 제공.)
    valid = [b for b in valid
             if not (b.source_key == 'ssg' and 'dealitemview' in b.url.lower())]
    # 소싱처별 크롤할 URL 총개수 (등록 순서 보존)
    src_totals: dict[str, int] = {}
    for b in valid:
        src_totals[b.source_key] = src_totals.get(b.source_key, 0) + 1
    src_done: dict[str, int] = {k: 0 for k in src_totals}
    total = len(valid)

    def _emit(done: int, key: str | None) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(done, total, key, dict(src_totals), dict(src_done))
        except Exception:
            pass

    # [2026-06-03] '보면서 크롤'(WATCH_CRAWL=1): HTTP(curl) 방식 소싱처는 자체 브라우저가
    #   없으므로 보기 전용 브라우저로 URL 을 띄워 보여준다. (Playwright 크롤러는 자체 headful.)
    from lemouton.sources.watch_browser import watch_enabled as _watch_on, show_url as _watch_show
    _HTTP_SHOW_SOURCES = {'ssf', 'ssg', 'ss_lemouton'}
    _watch = _watch_on()

    out = {'total': 0, 'ok': 0, 'error': 0, 'no_crawler': 0, 'per_source': {}}
    _emit(0, None)  # 시작 — 위젯 즉시 표시 (소싱처별 0/N)
    # [2026-06-13] 크롤 시작 하드 리셋 — 옛 가격/재고/혜택 비우고 옵션 pessimistic block.
    #   크롤/마무리 실패 시 차단 유지(fail-safe) → 옛값으로 잘못 판매되는 사고 방지.
    try:
        from webapp.routes.api_pricing import _reset_bundle_crawl_state
        _reset_bundle_crawl_state(session, model_code)
    except Exception:
        pass
    done = 0
    for bsu in valid:
        out['total'] += 1
        sp = upsert_source_product(session, site=bsu.source_key, url=bsu.url)
        try:
            link_model_to_source(session, model_code=model_code, source_product_id=sp.id)
        except Exception:
            pass
        # 보면서 크롤 — HTTP 소싱처 URL 을 보이는 브라우저로 잠깐 표시 (fetch 전)
        if _watch and bsu.source_key in _HTTP_SHOW_SOURCES:
            _watch_show(bsu.url)
        r = fetch_one_source(session, source_product_id=sp.id, crawlers=crawlers)
        st = r.get('status')
        if st == 'skipped_no_browser':
            st = 'no_crawler'  # 이 호스트는 담당 아님(사용자 PC 크롤) — error 로 집계하지 않음
        bucket = st if st in ('ok', 'no_crawler') else 'error'
        out['ok' if bucket == 'ok' else ('no_crawler' if bucket == 'no_crawler' else 'error')] += 1
        ps = out['per_source'].setdefault(bsu.source_key, {'ok': 0, 'error': 0, 'no_crawler': 0})
        ps[bucket] += 1
        src_done[bsu.source_key] += 1
        done += 1
        _emit(done, bsu.source_key)  # URL 1개 완료 — 실시간 진행 갱신
    session.commit()
    # [2026-06-13] 크롤 종료 마무리 — 유효 소싱가 없는 옵션 crawl_blocked 확정(성공=해제).
    try:
        from webapp.routes.api_pricing import _finalize_bundle_crawl_block
        _finalize_bundle_crawl_block(session, model_code)
    except Exception:
        pass
    return out


def save_crawl_result(
    session: Session,
    *,
    source_product: SourceProduct,
    crawl_result: Any,  # CrawlResult
) -> dict:
    """CrawlResult → SourceProduct 메타 갱신 + 옵션 row 들 upsert."""
    # 모음전 단위 메타
    if crawl_result.product_name_raw and not source_product.product_name:
        source_product.product_name = crawl_result.product_name_raw

    source_product.last_fetched_at = _utcnow()
    source_product.last_status = 'ok'
    source_product.last_error_msg = None

    # ★ 2026-05-13 — 사이트 자동 적용 카드 할인 정보 저장.
    #   크롤러가 options[i].auto_card_discount 에 dict 또는 None 으로 전달.
    #   같은 사이트·상품 내 모든 옵션이 동일하다고 가정하므로 첫 non-null 값을 채택.
    import json as _json
    _acd = None
    for _o in (crawl_result.options or []):
        _v = _o.get('auto_card_discount')
        if _v:
            _acd = _v
            break
    source_product.auto_card_discount_json = _json.dumps(_acd, ensure_ascii=False) if _acd else None

    # ★ 2026-05-15 — 옵션 dict 의 동적 혜택 키를 SourceProduct.dynamic_benefits_json 에 저장.
    #   compute_breakdown 이 lookup 해서 매트릭스 매입가 산식에 추가 차감으로 자동 반영.
    #   상품 단위로 동일 값 가정 → 첫 옵션의 동적 키들만 추출.
    PRODUCT_DYNAMIC_KEYS = (
        'point_rate', 'point_amount',                 # SSF 멤버십포인트
        'gift_point_amount',                          # SSF 기프트포인트 (변동)
        'ssg_money_rate', 'ssg_money_amount',         # SSG MONEY
        'ssg_money_already_applied', 'ssg_money_text',
        'card_benefit_price', 'card_benefit_condition',  # SSG 카드혜택가
        # SSG 상품쿠폰 (2026-05-15 — X% 또는 정액 + 최소 구매금액 조건)
        'product_coupon_rate', 'product_coupon_amount',
        'product_coupon_min_order', 'product_coupon_max_discount',
        'product_coupon_label',
        'point_rewards',                              # 롯데홈쇼핑 L.POINT
        'review_point_max',                           # 스스 르무통 리뷰 적립
        # ★ 2026-05-15 — 롯데온 (lotteon.com) 사용자 스크린샷 명세 동적 혜택
        'lotte_member_discount_rate',                 # 롯데오너스 X% 회원할인 (자동 활성)
        'lotte_member_discount_label',
        'store_jjim_coupon_amount',                   # 스토어찜 쿠폰 정액 (비활성 기본)
        'store_jjim_coupon_label',
        # ★ Phase 8.8.3 (2026-05-17) — 무신사 회원가 추출 (사고 방지 핵심)
        'member_price',                               # 무신사 "나의 할인가" 회원가
        'is_member_price',                            # 회원가 추출 성공 여부 (False = 비회원가 사고)
        'login_marker_present',                       # 로그인 페이지 마커 노출 여부 (Gate 1)
    )
    _dyn = {}
    for _o in (crawl_result.options or []):
        for _k in PRODUCT_DYNAMIC_KEYS:
            if _k in _o and _o[_k] not in (None, 0, '', False):
                _dyn[_k] = _o[_k]
        # breakdown (무신사) 안의 일부 플래그도 추출
        _bd = _o.get('breakdown') if isinstance(_o.get('breakdown'), dict) else None
        if _bd:
            if 'money_active' in _bd:
                _dyn['money_active'] = bool(_bd['money_active'])
            if 'is_no_benefit_product' in _bd:
                _dyn['is_no_benefit_product'] = bool(_bd['is_no_benefit_product'])
            # 2026-05-15 — 무신사 동적 LV % + 쿠폰 정보
            for _k in ('grade_discount_rate', 'grade_reward_rate', 'money_reward_rate',
                       'coupon', 'cart_coupons', 'purchase_extra_reward'):
                if _k in _bd and _bd[_k] not in (None, 0, '', False, []):
                    _dyn[_k] = _bd[_k]
            # ★ 2026-06-05 — 무신사 시안 v3: 표면가 + 등급적립/무신사머니 '금액'을 SourceProduct 레벨에
            #   영속 저장 (relogin 등 옵션레벨 덮어쓰기에 안전). compute_breakdown 이 항목으로 차감.
            _surface = _o.get('sale_price')
            if _surface:
                _dyn['surface_price'] = int(_surface)
                _dyn['grade_reward_amount'] = int(_bd.get('grade_reward_amount') or 0)
                _dyn['money_reward_amount'] = int(_bd.get('money_reward_amount') or 0)
                _dyn['grade_discount_amount'] = int(_bd.get('grade_discount') or 0)
                _dyn['coupon_amount'] = int(_bd.get('coupon') or 0)
                _dyn['review_amount'] = 500 if _bd.get('review_reward_active') else 0
        if _dyn:
            break  # 첫 non-empty 옵션만 (상품 단위 가정)
    source_product.dynamic_benefits_json = _json.dumps(_dyn, ensure_ascii=False) if _dyn else None

    # 모음전 단위 가격·재고 = 옵션 평균/합 (UI 표시용)
    # ★ 2026-05-14 — 매입가 단일 진실 원천 통합: 옵션 'price' 와 'sale_price' 가
    #   사이트 판매가로 일치됨 (매입가는 api_benefits.compute_breakdown 으로 별도 계산).
    #   sale_price 우선 + price 폴백 (모든 크롤러 둘 다 박지만 안전 폴백 유지).
    def _display_price(o: dict):
        return o.get('sale_price') or o.get('price')
    if crawl_result.options:
        prices = [_display_price(o) for o in crawl_result.options if _display_price(o)]
        stocks = [o.get('stock') for o in crawl_result.options
                  if o.get('stock') is not None]
        source_product.last_price = (sum(prices) // len(prices)
                                     if prices else None)
        source_product.last_stock = sum(stocks) if stocks else None

    # ★ 잔여 #1 — 같은 URL (정규화 비교) 의 OptionSourceUrl.price_cached 동기화.
    #   기존: legacy 자동 수집만 채움 → 새 크롤러 결과와 stale 차이.
    #   변경: SourceProduct 갱신 시 동일 URL 의 모든 OptionSourceUrl.price_cached 도
    #         sp.last_price 로 일괄 update (옵션 단위 가격 차이 없는 사이트 가정).
    if source_product.last_price:
        try:
            from lemouton.sourcing.models_pricing import OptionSourceUrl
            sp_url_norm = normalize_url(source_product.url)
            osu_rows = (session.query(OptionSourceUrl)
                        .filter(OptionSourceUrl.product_url.isnot(None))
                        .all())
            for osu in osu_rows:
                if normalize_url(osu.product_url) == sp_url_norm:
                    osu.price_cached = source_product.last_price
        except Exception:
            # 기존 데이터에 OptionSourceUrl 미존재 환경 등 — 무시 (선택적 동기화)
            pass

    # 옵션 단위 upsert
    # ★ 2026-05-15 — 옵션 dict 의 동적 혜택 키 (point_rate / gift_point_amount /
    #   auto_card_discount / ssg_money_* / card_benefit_* / lotteon_coupons 등)
    #   을 SourceOption.dynamic_benefits_json 에 저장. compute_breakdown 이 lookup.
    import json as _json
    DYNAMIC_KEYS = (
        'point_rate', 'point_amount',           # SSF 멤버십포인트 (변동)
        'gift_point_amount',                    # SSF 기프트포인트 (변동)
        'auto_card_discount',                   # 르무통/롯데/SSF 사이트 자동 카드
        'ssg_money_rate', 'ssg_money_amount',   # SSG MONEY
        'ssg_money_already_applied', 'ssg_money_text',
        'card_benefit_price', 'card_benefit_condition',  # SSG 카드혜택가
        # SSG 상품쿠폰 (2026-05-15 — X% 또는 정액 + 최소 구매금액 조건)
        'product_coupon_rate', 'product_coupon_amount',
        'product_coupon_min_order', 'product_coupon_max_discount',
        'product_coupon_label',
        'point_rewards',                        # 롯데홈쇼핑 L.POINT
        'lotteon_coupons',                      # 롯데온 쿠폰 리스트
        'review_point_max',                     # 스스 르무통 리뷰 적립
        # ★ 2026-05-15 — 롯데온 (lotteon.com) 사용자 스크린샷 명세 동적 혜택
        'lotte_member_discount_rate', 'lotte_member_discount_label',
        'store_jjim_coupon_amount', 'store_jjim_coupon_label',
        # ★ Phase 8.8.3 (2026-05-17) — 무신사 회원가 / 로그인 마커 (옵션 단위)
        'member_price', 'is_member_price', 'login_marker_present',
    )
    counts = {'options_inserted': 0, 'options_updated': 0}
    for opt_data in crawl_result.options:
        existed = (session.query(SourceOption)
                   .filter_by(source_product_id=source_product.id,
                              color_text=opt_data.get('color_text'),
                              size_text=opt_data.get('size_text'),
                              deleted_at=None)
                   .first())
        # 동적 혜택 키 추출 → JSON
        dynamic = {k: opt_data[k] for k in DYNAMIC_KEYS if k in opt_data}
        dynamic_json = _json.dumps(dynamic, ensure_ascii=False) if dynamic else None
        upsert_source_option(
            session,
            source_product_id=source_product.id,
            color_text=opt_data.get('color_text'),
            size_text=opt_data.get('size_text'),
            external_option_id=opt_data.get('option_id'),
            current_price=_display_price(opt_data),
            current_stock=opt_data.get('stock'),
            dynamic_benefits_json=dynamic_json,
        )
        if existed is None:
            counts['options_inserted'] += 1
        else:
            counts['options_updated'] += 1

    # ★ [동시·무결성 1단계] 재크롤 리셋 — 이번 크롤에 없는 옛 옵션 조합은 soft-delete.
    #   기존엔 upsert 만 해서, 한 번 긁힌 (색·사이즈) 조합이 다음 크롤에서 사라져도
    #   옛 가격·재고가 그대로 남아 그 값으로 판매되는 오발주(치명적 손실)가 가능했다.
    #   성공 크롤(옵션 ≥1)에서만 prune — 빈 결과(크롤 실패 추정)면 옛 데이터 보존.
    #   (crawl_guide 체크리스트 integrity_recrawl_reset 의 코드 구현.)
    counts['options_pruned'] = 0
    if crawl_result.options:
        new_keys = {(o.get('color_text'), o.get('size_text'))
                    for o in crawl_result.options}
        stale_opts = (session.query(SourceOption)
                      .filter_by(source_product_id=source_product.id,
                                 deleted_at=None)
                      .all())
        for so in stale_opts:
            if (so.color_text, so.size_text) not in new_keys:
                so.deleted_at = _utcnow()
                counts['options_pruned'] += 1
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 조회 헬퍼 — 가격결정·매처가 사용
# ─────────────────────────────────────────────────────────────────────────────

def get_source_data_for_sku(
    session: Session,
    canonical_sku: str,
) -> list[dict]:
    """canonical_sku 가 매핑된 모든 SourceOption 의 가격·재고 반환.

    가격 결정 단계가 사용 — 한 SKU 가 N 사이트(르무통/무신사/SSF/...) 가격을
    가지므로 list 로 반환.

    Returns:
      [{'site': str, 'price': int|None, 'stock': int|None,
        'fetched_at': datetime|None}, ...]
    """
    rows = (session.query(OptionSourceLink, SourceOption, SourceProduct)
            .join(SourceOption,
                  OptionSourceLink.source_option_id == SourceOption.id)
            .join(SourceProduct,
                  SourceOption.source_product_id == SourceProduct.id)
            .filter(OptionSourceLink.canonical_sku == canonical_sku)
            .filter(SourceOption.deleted_at.is_(None))
            .filter(SourceProduct.deleted_at.is_(None))
            .all())
    return [{
        'site': sp.site,
        'price': so.current_price,
        'stock': so.current_stock,
        'fetched_at': so.last_fetched_at,
    } for _, so, sp in rows]


def get_models_sharing_source(
    session: Session,
    source_product_id: int,
) -> list[str]:
    """이 SourceProduct 를 공유하는 모음전 코드 목록.

    /sources 페이지에서 "이 URL 사용 모음전 N 개" 표시에 사용.
    """
    links = (session.query(ModelSourceLink)
             .filter_by(source_product_id=source_product_id)
             .all())
    return [l.model_code for l in links]


def list_source_products_grouped(session: Session) -> dict[str, list[dict]]:
    """모든 활성 SourceProduct 를 사이트별로 그룹화.

    /sources 페이지 메인 그리드에서 사용.

    Returns:
      {site: [{'id': int, 'url': str, 'product_name': str|None,
               'last_fetched_at': datetime|None, 'last_status': str|None,
               'last_price': int|None, 'last_stock': int|None,
               'shared_with': int}, ...]}
    """
    products = (session.query(SourceProduct)
                .filter_by(deleted_at=None)
                .order_by(SourceProduct.site, SourceProduct.url)
                .all())
    # 한 번에 모든 ModelSourceLink 카운트
    link_counts = defaultdict(int)
    for l in session.query(ModelSourceLink).all():
        link_counts[l.source_product_id] += 1

    grouped: dict[str, list[dict]] = defaultdict(list)
    for sp in products:
        grouped[sp.site].append({
            'id': sp.id, 'url': sp.url,
            'product_name': sp.product_name,
            'last_fetched_at': sp.last_fetched_at,
            'last_status': sp.last_status,
            'last_price': sp.last_price, 'last_stock': sp.last_stock,
            'shared_with': link_counts.get(sp.id, 0),
        })
    return dict(grouped)


def record_price_history(
    session: Session,
    *,
    source_option_id: int,
    canonical_sku: str | None = None,
) -> int:
    """SourceOption 의 현재 가격·재고를 PriceTrackHistory 에 시점 기록.

    v2 정규화: source_option_id 단위 시계열.
    canonical_sku 는 백워드 호환 — 매핑이 있으면 함께 채움 (없으면 빈 문자열).

    Returns:
      생성된 PriceTrackHistory.id
    """
    from lemouton.templates.models import PriceTrackHistory

    so = session.get(SourceOption, source_option_id)
    if so is None:
        raise ValueError(f"SourceOption id={source_option_id} 없음")
    sp = session.get(SourceProduct, so.source_product_id)

    sku = canonical_sku
    if sku is None:
        # 첫 번째 매핑 SKU (없으면 placeholder)
        link = (session.query(OptionSourceLink)
                .filter_by(source_option_id=source_option_id)
                .first())
        sku = link.canonical_sku if link else f"_unmapped_so_{source_option_id}"

    h = PriceTrackHistory(
        canonical_sku=sku,
        source=sp.site if sp else 'unknown',
        price=so.current_price,
        stock=so.current_stock,
        source_option_id=source_option_id,
    )
    session.add(h)
    session.flush()
    return h.id


def get_price_history_for_sku(
    session: Session,
    canonical_sku: str,
    limit: int = 100,
) -> list[dict]:
    """canonical_sku 의 시계열 — v2 정규화 통해 source_option 까지 join.

    한 SKU 에 N 사이트(매핑된 SourceOption N개) 가 있으면 모두 반환.
    """
    from lemouton.templates.models import PriceTrackHistory

    # v2: OptionSourceLink 통해 SKU 의 모든 source_option 식별 → 그 시계열 조회
    link_ids = [l.source_option_id for l in
                session.query(OptionSourceLink)
                .filter_by(canonical_sku=canonical_sku).all()]
    if not link_ids:
        # v1 백워드: canonical_sku 직접 시계열
        rows = (session.query(PriceTrackHistory)
                .filter_by(canonical_sku=canonical_sku)
                .order_by(PriceTrackHistory.captured_at.desc())
                .limit(limit).all())
    else:
        rows = (session.query(PriceTrackHistory)
                .filter(PriceTrackHistory.source_option_id.in_(link_ids))
                .order_by(PriceTrackHistory.captured_at.desc())
                .limit(limit).all())
    return [{
        'captured_at': r.captured_at, 'source': r.source,
        'price': r.price, 'stock': r.stock,
        'source_option_id': r.source_option_id,
    } for r in rows]


def get_share_count_by_url(session: Session, site: str, url: str) -> int:
    """동일 (site, url) 의 ModelSourceLink 수.

    모음전 §2 URL 입력 옆에 "공유 N 모음전" 배지 표시용.
    """
    sp = (session.query(SourceProduct)
          .filter_by(site=site, url=url, deleted_at=None)
          .first())
    if sp is None:
        return 0
    return (session.query(ModelSourceLink)
            .filter_by(source_product_id=sp.id)
            .count())


def get_share_counts_batch(session: Session, site_url_pairs) -> dict:
    """[(site, url), ...] → {(site, url): share_count}. get_share_count_by_url 의 배치판.

    [perf 2026-06-12] bundle_edit 페이지가 소싱처마다 get_share_count_by_url(2쿼리)을
      호출하던 N+1(5소싱처=10쿼리)을 2쿼리로 축소. 값은 동일(같은 필터·count).
    """
    from sqlalchemy import tuple_, func
    pairs = [(s, u) for s, u in site_url_pairs if s and u]
    if not pairs:
        return {}
    out = {p: 0 for p in pairs}
    try:
        sps = (session.query(SourceProduct.id, SourceProduct.site, SourceProduct.url)
               .filter(SourceProduct.deleted_at.is_(None),
                       tuple_(SourceProduct.site, SourceProduct.url).in_(pairs)).all())
        id_to_key = {sp_id: (site, url) for sp_id, site, url in sps}
        if id_to_key:
            counts = dict(session.query(ModelSourceLink.source_product_id, func.count())
                          .filter(ModelSourceLink.source_product_id.in_(list(id_to_key)))
                          .group_by(ModelSourceLink.source_product_id).all())
            for sp_id, key in id_to_key.items():
                out[key] = counts.get(sp_id, 0)
    except Exception:
        # 실패 시 전부 0 (배지 표시 전용 — 페이지 렌더는 절대 막지 않음)
        pass
    return out


def kpi_summary(session: Session) -> dict:
    """소싱처 운영센터 KPI."""
    base = session.query(SourceProduct).filter_by(deleted_at=None)
    total = base.count()
    ok = base.filter(SourceProduct.last_status == 'ok').count()
    error = base.filter(SourceProduct.last_status.in_(['error', 'timeout'])).count()
    no_crawler = base.filter(SourceProduct.last_status == 'no_crawler').count()
    pending = total - ok - error - no_crawler  # 한 번도 fetch 안 한 것
    return {
        'total': total, 'ok': ok, 'error': error,
        'no_crawler': no_crawler, 'pending': pending,
    }
