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
    SourceProduct, SourceOption, ModelSourceLink, OptionSourceLink, CrawlDelta,
)
from .change_detection import detect_changes


# ─────────────────────────────────────────────────────────────────────────────
# URL 정규화 (잔여 #2) — 트래킹 파라미터 제거
# ─────────────────────────────────────────────────────────────────────────────
import re as _re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


# ─────────────────────────────────────────────────────────────────────────────
# SourceOption color/size 정규화 — 표기 차이 중복행 방지
# ─────────────────────────────────────────────────────────────────────────────
import re as _re_norm


def _norm_size(s) -> str:
    """size_text 정규화: 숫자+mm 통일, 대소문자·공백 제거.

    '220MM' → '220mm', '220' → '220mm', ' 235 mm ' → '235mm'
    빈 문자열·None → ''
    """
    s = str(s or '').strip()
    if not s:
        return ''
    d = ''.join(c for c in s if c.isdigit())
    return (d + 'mm') if d else s.lower()


def _norm_color(s) -> str:
    """color_text 정규화: 앞뒤 공백 제거. None → ''"""
    return str(s or '').strip()

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
    if existing is None:
        # [2026-06-19 fix] 레거시 행: 2026-06-13 정규화 도입 전 생성된 SourceProduct 는
        #   저장 url 이 raw(utag 등 포함)라 위 정확매칭(저장url==정규화input)이 빗나간다 →
        #   같은 상품인데 새 행을 만들어 중복 누적(SSF 다크네이비 3행). 매트릭스 sp_by_norm
        #   과 동일하게 normalize_url 양쪽 비교로 재탐색해 중복 생성을 막는다(정규화된 행 우선).
        #   url self-heal 은 하지 않는다(기존 중복 정규화행과 uq_source_product_site_url 충돌
        #   회피) — 정규화·병합은 dedupe 마이그레이션에서 일괄 처리.
        cands = [c for c in (session.query(SourceProduct)
                             .filter_by(site=site, deleted_at=None).all())
                 if normalize_url(c.url or '') == url]
        if cands:
            cands.sort(key=lambda c: (
                (c.url or '') == url,                       # 이미 정규화된 행 우선
                getattr(c, 'last_status', None) == 'ok',    # 성공 데이터 보유 우선
                str(getattr(c, 'last_fetched_at', '') or '')),  # 최신 우선
                reverse=True)
            existing = cands[0]
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
    # [2026-06-24 fix] 대소문자·공백·단위 표기 차이로 유니크 제약을 우회하는 중복행 방지.
    #   '220MM' vs '220mm', ' 235 mm ' vs '235mm' 등을 하나로 수렴.
    color_text = _norm_color(color_text) or None
    size_text = _norm_size(size_text) or None
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


# ─────────────────────────────────────────────────────────────────────────────
# 단품 색상 스코프 — 무신사 단품 SP 형제색 병합 폴루션 차단
# ─────────────────────────────────────────────────────────────────────────────

import re as _re_color


def _cnorm_color(x) -> str:
    """색상 비교용 정규화 — 공백·괄호·구분자 제거 + 소문자.

    api_pricing._stk_cnorm 과 동일 로직; 외부 import 부담 없이 service 내 자체 정의.
    """
    return _re_color.sub(r'[\s()（）\[\]·,/\-_:：]', '', str(x or '')).lower()


def _resolve_reg_color(session: Session, source_product: SourceProduct) -> str | None:
    """단품 SourceProduct 의 등록 색상명 반환.

    우선순위:
      1. OptionSourceUrlLink → Option.color_code (연결옵션 — 권위 있는 원천)
         단일 색상이면 그대로 반환. 0개 또는 2+개(혼재) 면 단계 2로.
      2. BundleSourceUrl.label 파싱 (기존 경로 — 폴백)
         label 형식: '{source_key}_{색상}' (예: 'musinsa_오렌지') 또는 색상만('오렌지').
         라벨이 없거나 파싱 결과가 비어있으면 None 반환.

    반환:
      str  — 등록 색상(예: '오렌지')
      None — 색상을 자신있게 판별할 수 없는 경우 (보수적: 필터 안 함)

    범위: 무신사 단품만. 타 소싱처(롯데온/SSF/SSG/르무통)는 색스코프 미적용(보수적)
      — 동일 URL이 다른 소싱처에 단품 등록돼도 무신사 외엔 None 반환해 데이터 보존.
    """
    # 무신사 단품에만 색스코프 적용 — 타소싱처 부분손실 방지
    if (getattr(source_product, 'site', None) or '') != 'musinsa':
        return None
    try:
        from lemouton.sourcing.models import BundleSourceUrl, OptionSourceUrlLink, Option as SOption
    except ImportError:
        return None

    try:
        sp_url_norm = normalize_url(source_product.url or '')
        # 같은 URL 을 사용하는 BundleSourceUrl 전부 탐색 (normalize_url 양쪽 비교)
        bsu_rows = (session.query(BundleSourceUrl)
                    .filter(BundleSourceUrl.url.isnot(None))
                    .all())
        # url_type='단품' 인 것만 (label 존재 여부 무관)
        matching = [b for b in bsu_rows
                    if normalize_url(b.url or '') == sp_url_norm
                    and (b.url_type or '단품') == '단품']
        if not matching:
            return None
        # 첫 번째 매칭 BundleSourceUrl 사용
        bsu = matching[0]
    except Exception:
        return None  # 보수적: 예외 시 필터 안 함

    # ── 경로 1: 연결옵션(OptionSourceUrlLink → Option.color_code) ──────────────
    # 라벨 없어도 연결옵션에서 색 판별 가능 — 권위 있는 단일 진실 원천
    try:
        links = (session.query(OptionSourceUrlLink)
                 .filter(OptionSourceUrlLink.bundle_source_url_id == bsu.id)
                 .all())
        if links:
            linked_skus = [lnk.option_canonical_sku for lnk in links]
            opt_rows = (session.query(SOption)
                        .filter(SOption.canonical_sku.in_(linked_skus))
                        .all())
            colors = {(o.color_code or '').strip() for o in opt_rows
                      if (o.color_code or '').strip()}
            if len(colors) == 1:
                # 단일 색상 — 권위 있음
                return colors.pop()
            # 0개(매핑된 옵션에 color_code 없음) 또는 2+개(혼재) → 폴백
    except Exception:
        pass  # 연결옵션 조회 실패 → 라벨 경로로 폴백

    # ── 경로 2: label 파싱 (기존 경로 — 폴백) ──────────────────────────────────
    try:
        label = (bsu.label or '').strip()
        if not label:
            return None
        # 'musinsa_오렌지' → '오렌지'; '오렌지' → '오렌지'
        if '_' in label:
            color = label.split('_', 1)[1].strip()
        else:
            color = label
        return color if color else None
    except Exception:
        return None  # 보수적: 예외 시 필터 안 함


def _scope_options_to_color(options: list[dict], reg_color: str | None) -> list[dict]:
    """단품 SP 색상 필터 — 등록색 일치(또는 빈 색) 옵션만 반환하고 color_text 를 정규화.

    Args:
      options:   크롤러가 반환한 옵션 dict 리스트 (원본 수정 안 함)
      reg_color: _resolve_reg_color 가 반환한 등록 색상; None/'' 이면 no-op

    Returns:
      필터·정규화된 새 리스트. 원본 리스트·dict 는 변형하지 않음.

    정책:
      - reg_color 가 없으면 → 전부 반환(모음전·매핑없음 경로와 동일)
      - 통과 조건: _cnorm_color(color_text) == _cnorm_color(reg_color)
                   OR color_text 가 빈 값
      - 통과된 옵션의 color_text 를 reg_color 로 정규화(표기 통일)
      - 탈락 옵션은 조용히 제거 (no log — prune 이 soft-delete 함)
    """
    if not reg_color:
        return list(options)
    rc_norm = _cnorm_color(reg_color)
    result = []
    for o in options:
        ct = o.get('color_text') or ''
        oc_norm = _cnorm_color(ct)
        # 빈 색(단일색 URL 에서 색 미포함) 또는 등록색과 일치
        if not oc_norm or oc_norm == rc_norm or rc_norm in oc_norm or oc_norm in rc_norm:
            new_o = dict(o)
            new_o['color_text'] = reg_color  # 등록색으로 정규화
            result.append(new_o)
    return result


# ── 동적 혜택 키 화이트리스트 (단일 진실 원천) ──────────────────────────────
#   서버사이드 _ingest(save_crawl_result)·확장 경로(persist_crawled_options) 공용.
#   compute_breakdown 이 dynamic_benefits_json 에서 이 키들을 lookup 해 매입가 산식에 반영.
#   OPTION = 옵션 레벨(auto_card_discount·lotteon_coupons 포함) / PRODUCT = 상품 레벨.
OPTION_DYNAMIC_KEYS = (
    'point_rate', 'point_amount',           # SSF 멤버십포인트 (변동)
    'gift_point_amount',                    # SSF 기프트포인트 (변동)
    'auto_card_discount',                   # 르무통/롯데/SSF 사이트 자동 카드
    'ssg_money_rate', 'ssg_money_amount',   # SSG MONEY
    'ssg_money_already_applied', 'ssg_money_text',
    'card_benefit_price', 'card_benefit_condition',  # SSG 카드혜택가
    'product_coupon_rate', 'product_coupon_amount',  # SSG 상품쿠폰
    'product_coupon_min_order', 'product_coupon_max_discount',
    'product_coupon_label',
    'product_coupon_list',                  # 무신사 상품쿠폰 전량(키워드 필터용 원본 리스트)
    'point_rewards',                        # 롯데홈쇼핑 L.POINT
    'hmall_point_amount',                   # 현대H몰 H.Point 적립(정액)
    'hmall_card_label', 'hmall_card_discount',  # 현대H몰 카드 즉시할인(조건부)
    # [2026-07-23 · 2차 T1] 현대H몰 카드 즉시할인 **목록** — item-prmo-lst API 수집.
    #   [{label, rate(퍼센트), amount(원), min_order, promo, valid_until}] · 일자별 로테이션이라
    #   크롤 당일 값을 쓴다(사장님 확정 2026-07-23). hmall_pay_promos = 결제수단 프로모션(정보용).
    'hmall_card_discounts', 'hmall_pay_promos',
    # 롯데아이몰 카드 청구할인(조건부) — 2026-07-18 표면가에서 분리 보관
    'lotteimall_card_label', 'lotteimall_card_discount',
    'lotteon_coupons',                      # 롯데온 쿠폰 리스트
    'review_point_max',                     # 스스 르무통 리뷰 적립
    'lotte_member_discount_rate', 'lotte_member_discount_label',  # 롯데온 회원할인
    'store_jjim_coupon_amount', 'store_jjim_coupon_label',
    'member_price', 'is_member_price', 'login_marker_present',    # 무신사 회원가
    # ★ 2026-07-23 롯데온 카드혜택 3종 — 확장 T6(v0.7.55, 0384fe55)이 item 레벨로 전송.
    #   lotteon_card_discounts = **리스트**(dict {label, amount, rate}) — rate 는 퍼센트 단위
    #   (7 = 7%). T8 계산식에서 반드시 /100 해서 쓸 것. 상품 레벨 혜택이므로
    #   PRODUCT_DYNAMIC_KEYS 제외 튜플에 넣지 않는다(상품·옵션 양쪽 허용).
    'lotteon_max_price',                    # 롯데온 최대혜택가(표면)
    'lotteon_card_discounts',               # 롯데온 카드 즉시할인 리스트
    'lotteon_store_discount',               # 롯데온 스토어(판매자) 할인 금액
)
# 상품 레벨은 옵션 전용(auto_card_discount·lotteon_coupons) 두 키만 제외.
PRODUCT_DYNAMIC_KEYS = tuple(
    k for k in OPTION_DYNAMIC_KEYS if k not in ('auto_card_discount', 'lotteon_coupons')
)


def _record_crawl_delta(session, source_product, old_snapshot, scoped):
    """직전 크롤(old_snapshot) 대비 이번 저장될 값 비교 → CrawlDelta 1행 + no_change_streak 갱신.

    ★ 핵심: 비교 대상은 '들어온 raw 값'이 아니라 '실제로 DB에 저장되는 값'이어야 한다.
      upsert_source_option 은 price·stock 둘 다 들어온 값이 None 이면 그 필드를
      **덮어쓰지 않고 기존값을 보존**한다(§upsert_source_option:191-194). 따라서 크롤이
      stock=None(확인 불가)을 반환해도 DB 는 안 바뀌므로 '변동'이 아니다 — new_snapshot 에서
      None 필드를 old 값으로 대체해 저장 상태를 그대로 반영한다(streak 오리셋 방지).
      단, 기존 키가 없는 신규 옵션은 old 값이 없으니 None 그대로 → 신규 등장은
      기존 로직대로 변동으로 잡힌다(정상).
    """
    old_map = {(o['color_text'], o['size_text']): o for o in old_snapshot}
    new_snapshot = []
    for o in scoped:
        _c = _norm_color(o.get('color_text'))
        _s = _norm_size(o.get('size_text'))
        _prev = old_map.get((_c, _s))
        _price = o.get('price')
        _stock = o.get('stock')
        # None 가드 있는 필드(price·stock): 들어온 값 None → 저장은 기존값 보존 → old 값으로 비교.
        if _price is None and _prev is not None:
            _price = _prev.get('price')
        if _stock is None and _prev is not None:
            _stock = _prev.get('stock')
        new_snapshot.append({'color_text': _c, 'size_text': _s,
                             'price': _price, 'stock': _stock})
    _chg = detect_changes(old_snapshot, new_snapshot)
    session.add(CrawlDelta(
        source_product_id=source_product.id,
        stock_changed=_chg['stock_changed'],
        price_changed=_chg['price_changed'],
        detail=(_chg['detail'][:1000] if _chg['detail'] else None),
    ))
    if _chg['stock_changed'] or _chg['price_changed']:
        source_product.no_change_streak = 0
    else:
        source_product.no_change_streak = (source_product.no_change_streak or 0) + 1
    # ── [M5] 변동 통계 적립 — 계수를 정할 근거 ────────────────────────────────
    #   ★기준선은 소싱처다. 방금 만든 이 CrawlDelta 를 그대로 세기 때문에
    #     실전송 잠금(MOUM_LIVE_UPLOAD OFF)과 무관하게 숫자가 나온다.
    #     여기서 diff 를 다시 계산하지 않는다 — 위 _chg 를 그대로 넘긴다.
    #   통계 실패가 크롤 저장을 막을 이유는 없으므로 삼키되, 조용히 넘기지 않고 남긴다.
    try:
        from lemouton.sources.crawl_change_stats import record_crawl_observation
        record_crawl_observation(session, source_product=source_product,
                                 detail=_chg['detail'])
    except Exception:   # noqa: BLE001
        _log.warning("[sources] 변동 통계 적립 실패 sp=%s (크롤 저장은 정상)",
                     getattr(source_product, 'id', None), exc_info=True)


def changed_product_ids_since(session, *, only_latest: bool = True) -> set[int]:
    """변동(재고 또는 가격)이 있는 source_product_id 집합.

    only_latest=True 면 각 URL의 '가장 최근 CrawlDelta' 만 보고 판단
    (업로드 게이트용 — 지금 보낼지 말지). False 면 하나라도 변동이면 포함.
    """
    rows = (session.query(CrawlDelta)
            .order_by(CrawlDelta.source_product_id, CrawlDelta.id.desc())
            .all())
    result: set[int] = set()
    seen: set[int] = set()
    for r in rows:
        if only_latest:
            if r.source_product_id in seen:
                continue
            seen.add(r.source_product_id)
        if r.stock_changed or r.price_changed:
            result.add(r.source_product_id)
    return result


def persist_crawled_options(session: Session, *, source_product, options) -> dict:
    """크롤 옵션(색·사이즈·재고·가격) → SourceOption upsert(생성+갱신) + 단품 색스코프 + stale prune.

    ★ parse(navGrab)·crawl-result(확장추출) 양쪽이 공유하는 **단일 옵션 영속 루틴**.
      매트릭스가 읽는 바로 그 SourceOption 을 만든다(_match_option_so 와 같은 행).
      옵션행이 없으면 매트릭스가 상품 last_stock(전 사이즈 합계)을 균일 폴백 → 품절 둔갑.
      서버사이드 _ingest 와 동일 규칙으로 통일.

    옵션 dict 키는 두 표기를 모두 허용:
      - parse 파서 출력: color_text / size_text / option_id / price·sale_price / stock
      - 확장 추출(무신사 등): color / size / stock / price (size 는 'mm' 제거됨)

    무결성: 폴백·추정 금지 — 파서가 준 값(품절 0 포함)만 영속. stock=None 이면
      upsert 가 current_stock 을 건드리지 않음(하드리셋 NULL 보존).
    커밋은 호출자 책임(트랜잭션 일관성).

    Returns: {'upserted': N, 'pruned': M}
    """
    if not isinstance(options, list) or not options:
        return {'upserted': 0, 'pruned': 0}
    # 키 정규화 — color_text|color, size_text|size, price|sale_price
    norm = []
    for o in options:
        if not isinstance(o, dict):
            continue
        # 동적 혜택 키(ssg_money_rate 등) 추출 — 서버사이드 _ingest 와 동일 화이트리스트.
        #   확장이 옵션 dict 에 실어 보내면 여기서 SourceOption.dynamic_benefits_json 으로 영속.
        _dyn = {k: o[k] for k in OPTION_DYNAMIC_KEYS if k in o}
        norm.append({
            'color_text': o.get('color_text') or o.get('color'),
            'size_text': o.get('size_text') or o.get('size'),
            'option_id': o.get('option_id') or o.get('external_option_id'),
            'price': o.get('sale_price') or o.get('price'),
            'stock': o.get('stock'),
            '_dynamic': _dyn or None,
        })
    scoped = _scope_options_to_color(norm, _resolve_reg_color(session, source_product))
    if not scoped:
        return {'upserted': 0, 'pruned': 0}
    # ★ 2026-07-04 변동 감지 — upsert 전 기존 옵션값 스냅샷(직전 크롤 결과).
    #   detect_changes 가 이 old_snapshot vs 새 옵션(new_snapshot) 을 비교해
    #   CrawlDelta 1행 기록 + no_change_streak(무변동 연속) 갱신.
    #   키((color,size))는 저장 시 정규화(_norm_*)와 동일하게 맞춰 표기차 오탐 방지.
    #   ⚠️ 즉시(eager) 스칼라 복사로 리스트를 만든다 — 아래 upsert 루프가 같은
    #   identity-map SourceOption 행을 in-place mutate 하므로, 제너레이터·lazy
    #   참조로 바꾸면 비교 시점엔 이미 새 값으로 오염돼 old 스냅샷이 무의미해진다.
    old_snapshot = [
        {'color_text': _norm_color(so.color_text), 'size_text': _norm_size(so.size_text),
         'price': so.current_price, 'stock': so.current_stock}
        for so in (session.query(SourceOption)
                   .filter_by(source_product_id=source_product.id, deleted_at=None).all())
    ]
    upserted = 0
    failed = 0
    err_sample = None
    for o in scoped:
        # [2026-06-29] 옵션별 savepoint 격리 — 한 옵션이 throw(데이터 이상·제약 등)해도
        #   savepoint 만 롤백하고 나머지를 살린다. 기존엔 한 옵션 예외가 세션을 abort 시켜
        #   persist 전체가 죽고(호출부 except:pass 가 삼킴) 확장이 보낸 152개가 통째 유실됐다
        #   (현대H몰 색상모음전 사이즈별 미저장). begin_nested = SAVEPOINT(이전 upsert 보존).
        try:
            _dj = None
            if o.get('_dynamic'):
                import json as _json
                _dj = _json.dumps(o['_dynamic'], ensure_ascii=False)
            with session.begin_nested():
                upsert_source_option(
                    session, source_product_id=source_product.id,
                    color_text=o.get('color_text'), size_text=o.get('size_text'),
                    external_option_id=o.get('option_id'),
                    current_price=o.get('price'), current_stock=o.get('stock'),
                    dynamic_benefits_json=_dj)
            upserted += 1
        except Exception as _e:
            failed += 1
            if err_sample is None:
                err_sample = (str(_e)[:90] + ' | opt=' +
                              repr({'c': o.get('color_text'), 's': o.get('size_text')})[:60])
    # stale prune — 이번 크롤에 없는 (색,사이즈) 조합 soft-delete (옛 가격·재고 잔존 차단).
    new_keys = {(_norm_color(o.get('color_text')), _norm_size(o.get('size_text')))
                for o in scoped}
    pruned = 0
    for so in (session.query(SourceOption)
               .filter_by(source_product_id=source_product.id, deleted_at=None).all()):
        if (_norm_color(so.color_text), _norm_size(so.size_text)) not in new_keys:
            so.deleted_at = _utcnow()
            pruned += 1
    # ★ 2026-07-04 변동 기록 — old_snapshot vs 저장될 값 비교 후 CrawlDelta 1행 + streak 갱신.
    _record_crawl_delta(session, source_product, old_snapshot, scoped)
    return {'upserted': upserted, 'pruned': pruned, 'failed': failed, 'err': err_sample}


# 상품명으로 잘못 저장되는 내비/섹션 텍스트. 빈값 포함 = '채워야 할 상태'.
_NAME_JUNK = {"", "메인메뉴", "메뉴"}


def apply_name_heal(source_product, new_name) -> bool:
    """상품명 치유 — 현재가 비었거나 내비 쓰레기(「메인메뉴」)면 새 이름으로 갱신.

    [2026-07-11] 옛 파서(og:title 도입 전)가 PC 첫 h2 '메인메뉴'(내비)를 상품명으로
      저장했고, fill-if-blank 가드 때문에 파서를 고쳐도 stale '메인메뉴'가 영원히 남았다.
      확장 저장 경로(api_sources_parse)·서버 저장 경로(save_crawl_result) 둘 다 이 함수를
      부른다. 정상 저장된 좋은 이름은 덮지 않는다(파서 폴백이 더 나쁜 값을 줄 때 보호).
    반환 True = 갱신함.
    """
    _new = (new_name or "").strip()
    _cur = (getattr(source_product, "product_name", None) or "").strip()
    if _new and _new not in _NAME_JUNK and _cur in _NAME_JUNK:
        source_product.product_name = _new
        return True
    return False


def save_crawl_result(
    session: Session,
    *,
    source_product: SourceProduct,
    crawl_result: Any,  # CrawlResult
) -> dict:
    """CrawlResult → SourceProduct 메타 갱신 + 옵션 row 들 upsert."""
    # 모음전 단위 메타 — 상품명 치유([2026-07-11]). 아래 apply_name_heal 참조.
    apply_name_heal(source_product, crawl_result.product_name_raw)

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
    # PRODUCT_DYNAMIC_KEYS 는 모듈 상수(단일 진실 원천) 사용 — persist_crawled_options 와 공유.
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
                # ★ 무신사 상품쿠폰 전량(product_coupon_list) — 개별 키워드 필터링용 원본 보존.
                #   coupon_amount(합계)는 기존 경로 그대로 유지, 리스트는 별도 키에 추가 저장.
                _pcl = _o.get('product_coupon_list')
                if isinstance(_pcl, list) and _pcl:
                    _dyn['product_coupon_list'] = _pcl
                else:
                    # [2026-07-20] 명시적으로 지운다 — api_pricing.py:1758~1762 의 같은
                    #   블록과 규칙을 맞춘다. 이 함수의 _dyn 은 매 호출 새로 만들어(849행
                    #   `_dyn = {}`) 그대로 dynamic_benefits_json 전체를 덮어쓰므로(883행),
                    #   지금 이 시점엔 else 유무가 결과에 차이를 안 만든다(빈 리스트면 애초에
                    #   키가 안 생겨 pop 과 동일한 최종 JSON). 하지만 두 저장 경로가 같은
                    #   블록을 '다르게' 쓰면 다음에 한쪽만 옛값-머지 방식으로 리팩터될 때
                    #   조용히 갈라진다 — 그게 실제로 무신사 옛 쿠폰(12,980원)이 사라진
                    #   페이지에서도 계속 차감되던 사고의 형태였다. 두 경로를 항상 동일하게.
                    _dyn.pop('product_coupon_list', None)
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
    DYNAMIC_KEYS = OPTION_DYNAMIC_KEYS  # 모듈 상수(단일 진실 원천) — persist_crawled_options 와 공유.
    # ★ [2026-06-24] 단품 색상 스코프 — 무신사 단품 SP 형제색 병합 폴루션 차단.
    #   _discover_color_variants 가 모든 색 변형(오렌지+블랙+아이보리...)을 합쳐 반환하면
    #   필터 없이 upsert 할 때 오렌지 SP 에 블랙·아이보리 행이 섞인다(pollution).
    #   BundleSourceUrl.url_type='단품' 인 경우에만 등록색 외 옵션을 차단한다.
    #   모음전(색상모음전/모델모음전) SP 와 BundleSourceUrl 미등록 SP 는 동작 변경 없음.
    _reg_color = _resolve_reg_color(session, source_product)
    _scoped_options = _scope_options_to_color(crawl_result.options or [], _reg_color)

    counts = {'options_inserted': 0, 'options_updated': 0}
    for opt_data in _scoped_options:
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
    #   prune 기준도 scoped_options — 단품 SP 에서 형제색 기존 행을 soft-delete.
    #   (crawl_guide 체크리스트 integrity_recrawl_reset 의 코드 구현.)
    counts['options_pruned'] = 0
    if _scoped_options:
        new_keys = {(_norm_color(o.get('color_text')), _norm_size(o.get('size_text')))
                    for o in _scoped_options}
        stale_opts = (session.query(SourceOption)
                      .filter_by(source_product_id=source_product.id,
                                 deleted_at=None)
                      .all())
        for so in stale_opts:
            if (_norm_color(so.color_text), _norm_size(so.size_text)) not in new_keys:
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
