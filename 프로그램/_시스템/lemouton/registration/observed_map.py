# -*- coding: utf-8 -*-
"""등록 실적에서 카테고리를 되받아 맵핑 제안을 만든다 (M3 Task 6 · 스펙 §C `method='observed'`).

사장님 지적("URL은 마켓별로 다 있다")의 핵심 — 우리는 이미 이 상품들을 마켓에 올렸고,
그때 카테고리를 **사람이 골랐다**. 그 코드를 되받아오면 이름 유사도 추측(name_sim)보다
훨씬 정확한 맵핑 근거가 된다. 그래서 confidence 는 0.99(추측 계열 중 최상)로 둔다.

원칙(전부 데이터 정합성 3대 원칙·M2 게이트와 같은 기준):
  · 짝이 둘 다 있어야 맵핑 1건 — 소싱처 카테고리 경로(SourceProduct.category_path)와
    마켓 상품ID 둘 중 하나라도 없으면 건너뛰고 사유를 집계한다(추측 금지).
  · 회수한 코드는 우리 카테고리 사전(market_categories)에 **현존할 때만** 채택한다.
    없거나 removed 면 버린다 — confirm 라우트가 400 으로 거부할 코드를 제안으로 박아 넣으면
    다음 등록이 조용히 실패한다.
  · `status='confirmed'` 행은 절대 불변(M2 원칙). `re_confirm` 은 코드·근거만 갱신하고
    상태를 suggested 로 되돌리지 않는다 — 되돌리면 「재확정 필요」 표시가 조용히 지워진다.
  · 자동 확정 없음 — 아무리 정확해도 승격은 사장님 클릭(confirm)으로만.

마켓 호출은 주입식 콜러블 `fetch_category(market, product_id)` 로 받는다 — 실배선(계정별
클라이언트·속도정책)은 라우트(webapp/routes/bulk/category_map.py)가 담당하고, 여기서는
테스트가 fixture 로 대체할 수 있게 순수 오케스트레이션만 한다.
"""
from __future__ import annotations

import datetime

from lemouton.registration.models import CategoryMapRow, MarketCategory
from lemouton.registration.source_category_ingest import normalize_path

# 우리 마켓 슬러그 → `models` 테이블의 마켓 상품ID 컬럼.
#   ★ 롯데온 없음 — 롯데온 등록은 카테고리 코드가 아니라 '본보기 상품번호(spdNo)' 방식이라
#     맵핑 대상 자체가 아니다(webapp/routes/bulk/category_map.py::catmap_confirm 도 400 거부).
#   ★ eleven11 은 아직 `models` 에 상품ID 컬럼이 없다(orchestrator.py 주석: 신설=나중).
#     getattr 폴백이라 컬럼이 생기는 날 자동으로 회수 대상에 들어온다 — 지금은 늘 None.
MARKET_ID_FIELDS = {
    'smartstore': 'naver_product_id',            # originProductNo
    'coupang': 'coupang_seller_product_id',      # sellerProductId
    'auction': 'auction_product_id',             # ESM goodsNo
    'gmarket': 'gmarket_product_id',             # ESM goodsNo
    'eleven11': 'eleven11_product_id',           # prdNo (컬럼 신설 전까지 항상 None)
}

# `models` 의 레거시 단일 소싱처 URL 컬럼 → 크롤 소싱처 키(SourceProduct.site).
#   다중 URL 은 BundleSourceUrl(source_key, url) 이 정본이라 그쪽도 함께 본다.
LEGACY_URL_FIELDS = {
    'url_lemouton': 'lemouton',
    'url_musinsa': 'musinsa',
    'url_ssf': 'ssf',
    'url_lotteon': 'lotteon',
    'url_ss_lemouton': 'ss_lemouton',
}

OBSERVED_CONFIDENCE = 0.99   # 실적 회수 — 추측(name_sim 0.4~1.0·coupang_reco 0.95)보다 위
ERROR_SAMPLE_LIMIT = 5


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _source_path_index(session):
    """(site, url) → 정규화된 카테고리 경로. 경로가 빈 상품은 아예 담지 않는다."""
    from lemouton.sources.models import SourceProduct

    out = {}
    rows = (session.query(SourceProduct)
            .filter(SourceProduct.category_path.isnot(None))
            .all())
    for sp in rows:
        path = normalize_path(sp.category_path)
        if not path or not sp.site or not sp.url:
            continue
        out[(str(sp.site).strip(), str(sp.url).strip())] = path
    return out


def _extra_urls_by_model(session):
    """model_code → [(site, url)] — 다중 소싱처 URL(BundleSourceUrl)."""
    from lemouton.sourcing.models import BundleSourceUrl

    out = {}
    for row in session.query(BundleSourceUrl).all():
        if not row.url or not row.source_key:
            continue
        out.setdefault(row.model_code, []).append(
            (str(row.source_key).strip(), str(row.url).strip()))
    return out


def _model_source_paths(model, extra_urls, path_index):
    """이 모델이 걸린 (소싱처 키, 카테고리 경로) 목록 — 중복 제거, 입력 순서 유지."""
    pairs = []
    for field, site in LEGACY_URL_FIELDS.items():
        url = (getattr(model, field, None) or '').strip()
        if url:
            pairs.append((site, url))
    pairs.extend(extra_urls.get(model.model_code, []))

    out = []
    seen = set()
    for site, url in pairs:
        path = path_index.get((site, url))
        if not path or (site, path) in seen:
            continue
        seen.add((site, path))
        out.append((site, path))
    return out


def _alive_codes(session, market, cache):
    """market → {코드: 표시용 전체경로} — 현존(removed_at 없음)만. 마켓당 1회 로딩."""
    if market not in cache:
        rows = (session.query(MarketCategory.code, MarketCategory.full_path)
                .filter(MarketCategory.market == market,
                        MarketCategory.removed_at.is_(None))
                .all())
        cache[market] = {str(code): full_path for code, full_path in rows}
    return cache[market]


def build_observed_map(session, fetch_category, now=None, on_progress=None):
    """등록 상품에서 카테고리를 회수해 `category_map` 에 observed 제안을 채운다.

    Args:
      session: SQLAlchemy 세션
      fetch_category: `f(market, product_id) -> 코드(str) | None`. 예외를 던지면 그 상품만
        건너뛰고 사유를 집계한다(전체 중단 금지 — 계정 하나가 죽어도 나머지는 계속 간다).
      now: 기록 시각(미지정 시 UTC 현재)
      on_progress: 선택. 마켓 조회 1건이 끝날 때마다 `f(누적 조회 수)` 로 불린다(진행률용).

    Returns:
      {'scanned': 마켓 조회 대상(모델×마켓) 수, 'mapped': 만들거나 갱신한 맵핑 행 수,
       'skipped_no_source_path': 소싱처 카테고리 경로가 없어 건너뛴 수,
       'skipped_code_unknown': 코드를 못 받았거나 사전에 없어 건너뛴 수,
       'skipped_confirmed': 확정 행이라 건드리지 않은 수,
       'errors': 조회 실패 수, 'error_samples': 사유 원문 최대 5건,
       'conflicts': 같은 실행 안에서 다른 코드가 또 관측돼 무시한 수}
    """
    from lemouton.sourcing.models import Model

    now = now or _utcnow()
    path_index = _source_path_index(session)
    extra_urls = _extra_urls_by_model(session)

    code_cache = {}      # (market, product_id) → 코드 | None
    dict_cache = {}      # market → {코드: 경로}
    written = {}         # (source_id, path, market) → 이번 실행에서 채택한 코드
    stats = {'scanned': 0, 'mapped': 0, 'skipped_no_source_path': 0,
             'skipped_code_unknown': 0, 'skipped_confirmed': 0,
             'errors': 0, 'conflicts': 0}
    error_samples = []
    fetched = 0

    for model in session.query(Model).all():
        pairs = _model_source_paths(model, extra_urls, path_index)

        for market, field in MARKET_ID_FIELDS.items():
            product_id = getattr(model, field, None)
            product_id = str(product_id).strip() if product_id else ''
            if not product_id:
                continue
            stats['scanned'] += 1

            if not pairs:
                # 마켓 코드를 회수해봤자 붙일 소싱처 경로가 없다 — 호출 자체를 아낀다.
                stats['skipped_no_source_path'] += 1
                continue

            key = (market, product_id)
            if key in code_cache:
                code = code_cache[key]
            else:
                try:
                    code = fetch_category(market, product_id)
                except Exception as e:   # noqa: BLE001 — 개별 실패는 집계하고 계속 간다
                    stats['errors'] += 1
                    if len(error_samples) < ERROR_SAMPLE_LIMIT:
                        error_samples.append(f'{market} {product_id}: {e}')
                    code_cache[key] = None
                    continue
                code = str(code).strip() if code not in (None, '') else None
                code_cache[key] = code
                fetched += 1
                if on_progress is not None:
                    try:
                        on_progress(fetched)
                    except Exception:   # noqa: BLE001 — 진행률 기록이 회수를 죽이면 안 된다
                        pass

            if not code:
                stats['skipped_code_unknown'] += 1
                continue

            alive = _alive_codes(session, market, dict_cache)
            if code not in alive:
                # 사전에 없거나 재수집에서 사라진 코드 — 확정 게이트가 거부할 값이라 버린다.
                stats['skipped_code_unknown'] += 1
                continue
            market_path = alive[code]

            for site, path in pairs:
                map_key = (site, path, market)
                prev = written.get(map_key)
                if prev is not None:
                    # 같은 소싱처 경로를 쓰는 다른 모델이 **다른** 마켓 카테고리로 올라가
                    # 있었다 — 조용히 덮어쓰면 먼저 본 실적이 사라진다. 먼저 본 것을 남기고
                    # 충돌만 센다(사장님이 확정 화면에서 최종 결정).
                    if prev != code:
                        stats['conflicts'] += 1
                    continue

                row = (session.query(CategoryMapRow)
                       .filter_by(source_id=site, source_path=path, market=market)
                       .first())
                if row is not None and row.status == 'confirmed':
                    stats['skipped_confirmed'] += 1
                    written[map_key] = row.market_cat_code
                    continue

                if row is None:
                    row = CategoryMapRow(source_id=site, source_path=path, market=market,
                                         status='suggested')
                    session.add(row)
                # status 는 새 행에서만 정한다 — 기존 re_confirm 을 suggested 로 내리지 않는다.
                row.market_cat_code = code
                row.market_cat_path = market_path
                row.method = 'observed'
                row.confidence = OBSERVED_CONFIDENCE
                row.updated_at = now
                written[map_key] = code
                stats['mapped'] += 1

    session.commit()
    stats['error_samples'] = error_samples
    return stats
