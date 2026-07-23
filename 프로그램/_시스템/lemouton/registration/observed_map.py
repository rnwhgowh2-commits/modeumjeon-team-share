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
import json

from lemouton.registration.models import CategoryMapRow, MarketCategory
from lemouton.registration.source_category_ingest import normalize_path
from lemouton.sources.service import normalize_url

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
CONFLICT_SAMPLE_LIMIT = 5

# [2026-07-23 리뷰 I3] 전량 1회 커밋 금지 — 수백 콜×sleep 이라 러닝타임이 harvest 급인데
#   끝에서 한 번만 커밋하면 중간에 죽을 때 0건이 남는다(이 저장소가 이미 당한 사고).
COMMIT_EVERY_MODELS = 20


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _source_paths(session):
    """소싱처 상품 → 카테고리 경로 인덱스 2종.

    ① by_url : (site, **정규화** URL) → 경로
    ② by_id  : SourceProduct.id → (site, 경로)  — ModelSourceLink 정본 조인용

    [2026-07-23 리뷰 C1] URL 은 반드시 `normalize_url` 로 맞춰서 비교한다.
      SourceProduct.url 은 정규화 저장(sources/service.py::upsert_source_product)인데
      Model.url_* · BundleSourceUrl.url 은 사장님이 붙여넣은 **원문**(NaPm·utm 포함)이다.
      문자열 완전일치로 조인하면 짝이 조용히 사라지고 그 상품이 'skipped_no_source_path
      (소싱처 카테고리 없음)'로 집계돼 **조인 버그가 크롤 미수집으로 위장**된다.
    [리뷰 M1] deleted_at 이 찍힌 행은 담지 않는다 — 지워진 상품의 옛 카테고리로 맵핑 금지.
    [리뷰 M2] 필요한 컬럼만 select (전 행 ORM 로딩 금지 — 소싱처 상품 수천 건).
    """
    from lemouton.sources.models import SourceProduct

    by_url, by_id = {}, {}
    rows = (session.query(SourceProduct.id, SourceProduct.site,
                          SourceProduct.url, SourceProduct.category_path)
            .filter(SourceProduct.category_path.isnot(None),
                    SourceProduct.deleted_at.is_(None))
            .all())
    for sp_id, site, url, category_path in rows:
        path = normalize_path(category_path)
        site = str(site).strip() if site else ''
        if not path or not site:
            continue
        by_id[sp_id] = (site, path)
        if url:
            by_url[(site, normalize_url(str(url).strip()))] = path
    return by_url, by_id


def _links_by_model(session, paths_by_sp_id):
    """model_code → [(site, 경로)] — 크롤이 남긴 **정본 링크**(ModelSourceLink) 기준.

    이 링크는 실제로 채워진다(크롤 시 `sources/service.py::link_model_to_source`,
    `sources/bundle_url_crawl.py`). 다만 **아직 한 번도 크롤하지 않은 모델**에는 없고
    레거시 단일 URL 컬럼(Model.url_*)은 링크를 만들지 않는 경로도 있어, 이것만으로는
    반쪽이다 → 정규화 URL 조인과 **둘 다** 쓴다(합집합·중복 제거).
    """
    from lemouton.sources.models import ModelSourceLink

    out = {}
    for model_code, sp_id in session.query(ModelSourceLink.model_code,
                                           ModelSourceLink.source_product_id).all():
        pair = paths_by_sp_id.get(sp_id)
        if pair is None:
            continue
        out.setdefault(model_code, []).append(pair)
    return out


def _extra_urls_by_model(session):
    """model_code → [(site, url)] — 다중 소싱처 URL(BundleSourceUrl). 원문 그대로 담는다
    (정규화는 조인 직전 한 곳에서만 — 규칙이 두 군데로 갈라지면 또 어긋난다)."""
    from lemouton.sourcing.models import BundleSourceUrl

    out = {}
    for model_code, source_key, url in session.query(
            BundleSourceUrl.model_code, BundleSourceUrl.source_key, BundleSourceUrl.url).all():
        if not url or not source_key:
            continue
        out.setdefault(model_code, []).append((str(source_key).strip(), str(url).strip()))
    return out


def _model_source_paths(model, extra_urls, path_index, link_pairs):
    """이 모델이 걸린 (소싱처 키, 카테고리 경로) 목록과, **못 붙은 URL** 목록.

    Returns: (pairs, unmatched) — pairs 는 중복 제거·입력 순서 유지,
             unmatched 는 정규화 후에도 SourceProduct 를 못 찾은 (site, url).
             같은 소싱처를 정본 링크로 이미 붙였다면 그 URL 은 손실이 아니라 세지 않는다.
    """
    out, seen, linked_sites = [], set(), set()
    for site, path in link_pairs:
        if (site, path) in seen:
            continue
        seen.add((site, path))
        out.append((site, path))
        linked_sites.add(site)

    urls = []
    for field, site in LEGACY_URL_FIELDS.items():
        url = (getattr(model, field, None) or '').strip()
        if url:
            urls.append((site, url))
    urls.extend(extra_urls.get(model.model_code, []))

    unmatched = []
    for site, url in urls:
        path = path_index.get((site, normalize_url(url)))
        if not path:
            if site not in linked_sites:
                unmatched.append((site, url))
            continue
        if (site, path) in seen:
            continue
        seen.add((site, path))
        out.append((site, path))
    return out, unmatched


def _alive_codes(session, market, cache):
    """market → {코드: 표시용 전체경로} — 현존(removed_at 없음)만. 마켓당 1회 로딩."""
    if market not in cache:
        rows = (session.query(MarketCategory.code, MarketCategory.full_path)
                .filter(MarketCategory.market == market,
                        MarketCategory.removed_at.is_(None))
                .all())
        cache[market] = {str(code): full_path for code, full_path in rows}
    return cache[market]


def _flush(session, keys, ctx, now):
    """모아 둔 표(votes)로 맵핑 행을 확정 기록한다 — 같은 키를 다시 불러도 결과가 같다(멱등).

    [2026-07-23 리뷰 I1] 승자를 '먼저 본 것'으로 조용히 정하지 않는다. 키별로 관측된 코드가
      **2종 이상이면 아무 것도 채택하지 않는다**(금전 손해 경로 — 틀린 카테고리로 등록되면
      손해다. 애매하면 제안하지 않고 사람이 고르게 남긴다):
        · 이번 실행이 만든 행이면 지운다(먼저 본 것이 이겨서 남는 일 방지)
        · 원래 있던 행이면 **건드리기 전 상태로 되돌리고** 후보만 candidates_json 에 남긴다
      충돌 키는 요약에 샘플(source_path·market·codes)로 최대 5건 올라간다.
    """
    votes, market_paths = ctx['votes'], ctx['market_paths']
    decided, created, snapshots = ctx['decided'], ctx['created'], ctx['snapshots']

    for key in keys:
        site, path, market = key
        codes = votes.get(key) or {}
        if not codes:
            continue
        row = (session.query(CategoryMapRow)
               .filter_by(source_id=site, source_path=path, market=market)
               .first())
        if row is not None and row.status == 'confirmed':
            # 확정 행은 절대 불변(M2 원칙) — 충돌 판정도 하지 않는다.
            decided[key] = 'confirmed'
            continue

        if len(codes) > 1:
            decided[key] = 'conflict'
            candidates = [{'code': c, 'path': market_paths.get((market, c)), 'votes': n}
                          for c, n in sorted(codes.items(), key=lambda kv: (-kv[1], kv[0]))]
            if key in created:
                if row is not None:
                    session.delete(row)
                created.discard(key)
                snapshots.pop(key, None)
            elif row is not None:
                snap = snapshots.pop(key, None)
                if snap is not None:
                    (row.market_cat_code, row.market_cat_path,
                     row.method, row.confidence, row.updated_at) = snap
                row.candidates_json = json.dumps(candidates, ensure_ascii=False)
            if key not in ctx['sampled'] and len(ctx['conflict_samples']) < CONFLICT_SAMPLE_LIMIT:
                ctx['sampled'].add(key)
                ctx['conflict_samples'].append(
                    {'source_id': site, 'source_path': path, 'market': market,
                     'codes': [c['code'] for c in candidates]})
            continue

        code = next(iter(codes))
        if row is None:
            row = CategoryMapRow(source_id=site, source_path=path, market=market,
                                 status='suggested')
            session.add(row)
            created.add(key)
        elif key not in snapshots:
            # 되돌릴 수 있게 손대기 전 상태를 남긴다(뒤늦게 충돌이 드러날 때 복원용).
            snapshots[key] = (row.market_cat_code, row.market_cat_path,
                              row.method, row.confidence, row.updated_at)
        # status 는 새 행에서만 정한다 — 기존 re_confirm 을 suggested 로 내리지 않는다.
        row.market_cat_code = code
        row.market_cat_path = market_paths.get((market, code))
        row.method = 'observed'
        row.confidence = OBSERVED_CONFIDENCE
        row.updated_at = now
        decided[key] = 'mapped'


def build_observed_map(session, fetch_category, now=None, on_progress=None,
                       commit_every=COMMIT_EVERY_MODELS):
    """등록 상품에서 카테고리를 회수해 `category_map` 에 observed 제안을 채운다.

    Args:
      session: SQLAlchemy 세션
      fetch_category: `f(market, product_id) -> 코드(str) | None`. 예외를 던지면 그 상품만
        건너뛰고 사유를 집계한다(전체 중단 금지 — 계정 하나가 죽어도 나머지는 계속 간다).
      now: 기록 시각(미지정 시 UTC 현재)
      on_progress: 선택. **시도 1건마다**(성공·실패·스킵 전부) `f(누적 시도 수)` 로 불린다.
        [리뷰 I4] 성공 fetch 에서만 부르면 실패·스킵이 많은 실행은 진행률이 멈춘 채 살아
        있고, 10분 뒤 새 POST 가 스테일로 오판해 두 번째 스레드를 띄운다(마켓 이중 호출).
      commit_every: 모델 N건마다 커밋(리뷰 I3). 0/None 이면 끝에서 한 번만.

    Returns:
      {'scanned': 마켓 조회 대상(모델×마켓) 수, 'mapped': 만들거나 갱신한 맵핑 행 수,
       'skipped_no_source_path': 소싱처 카테고리 경로가 없어 건너뛴 수,
       'skipped_code_unknown': 코드를 못 받았거나 사전에 없어 건너뛴 수,
       'skipped_confirmed': 확정 행이라 건드리지 않은 수,
       'skipped_no_dict': 카테고리 사전이 비어 조회 자체를 건너뛴 수,
       'errors': 조회 실패 수, 'error_samples': 사유 원문 최대 5건,
       'conflicts': 코드가 갈려 채택하지 않은 키 수, 'conflict_samples': 그 샘플 최대 5건,
       'unmatched_urls': 정규화 후에도 소싱처 상품에 못 붙은 URL 수,
       'unmatched_url_samples': 그 샘플 최대 5건,
       'market_notes': 마켓 단위 사유(사전 비어 있음 등)}
    """
    from lemouton.sourcing.models import Model

    now = now or _utcnow()
    path_index, paths_by_sp_id = _source_paths(session)
    extra_urls = _extra_urls_by_model(session)
    links = _links_by_model(session, paths_by_sp_id)

    code_cache = {}      # (market, product_id) → 코드 | None
    dict_cache = {}      # market → {코드: 경로}
    ctx = {
        'votes': {},           # (site, path, market) → {코드: 표수}
        'market_paths': {},    # (market, 코드) → 표시용 전체경로
        'decided': {},         # 키 → 'mapped' | 'conflict' | 'confirmed'
        'created': set(),      # 이번 실행이 만든 키(충돌 시 회수 대상)
        'snapshots': {},       # 키 → 손대기 전 값(충돌 시 복원용)
        'conflict_samples': [], 'sampled': set(),
    }
    stats = {'scanned': 0, 'mapped': 0, 'skipped_no_source_path': 0,
             'skipped_code_unknown': 0, 'skipped_confirmed': 0,
             'skipped_no_dict': 0, 'errors': 0, 'conflicts': 0,
             'unmatched_urls': 0}
    error_samples, unmatched_samples, market_notes = [], [], []
    dict_empty_noted = set()
    dirty = set()
    progress = 0

    def _tick():
        """진행률 — 시도 단위(성공/실패/스킵 전부). 기록 실패가 회수를 죽이면 안 된다."""
        nonlocal progress
        progress += 1
        if on_progress is not None:
            try:
                on_progress(progress)
            except Exception:   # noqa: BLE001
                pass

    for idx, model in enumerate(session.query(Model).all(), 1):
        pairs, unmatched = _model_source_paths(
            model, extra_urls, path_index, links.get(model.model_code, []))
        for site, url in unmatched:
            stats['unmatched_urls'] += 1
            if len(unmatched_samples) < ERROR_SAMPLE_LIMIT:
                unmatched_samples.append(f'{model.model_code} {site} {url}')

        for market, field in MARKET_ID_FIELDS.items():
            product_id = getattr(model, field, None)
            product_id = str(product_id).strip() if product_id else ''
            if not product_id:
                continue
            stats['scanned'] += 1
            _tick()

            alive = _alive_codes(session, market, dict_cache)
            if not alive:
                # [리뷰 I6] 사전이 비면 회수한 코드를 어차피 한 건도 채택 못 한다
                # (확정 게이트가 400 으로 거부) — 콜을 태우지 말고 사유를 드러낸다.
                stats['skipped_no_dict'] += 1
                if market not in dict_empty_noted:
                    dict_empty_noted.add(market)
                    market_notes.append(
                        f'{market}: 카테고리 사전이 비어 있음 — 먼저 수집(카테고리 전수수집) 후 재실행')
                continue

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

            if not code:
                stats['skipped_code_unknown'] += 1
                continue
            if code not in alive:
                # 사전에 없거나 재수집에서 사라진 코드 — 확정 게이트가 거부할 값이라 버린다.
                stats['skipped_code_unknown'] += 1
                continue
            ctx['market_paths'][(market, code)] = alive[code]

            for site, path in pairs:
                map_key = (site, path, market)
                v = ctx['votes'].setdefault(map_key, {})
                v[code] = v.get(code, 0) + 1
                dirty.add(map_key)

        _tick()   # 모델 1건 완료 — 상품ID 가 하나도 없는 모델도 진행률을 움직인다
        if commit_every and idx % commit_every == 0 and dirty:
            _flush(session, dirty, ctx, now)
            session.commit()
            dirty.clear()

    if dirty:
        _flush(session, dirty, ctx, now)
    session.commit()

    decided = ctx['decided'].values()
    stats['mapped'] = sum(1 for v in decided if v == 'mapped')
    stats['conflicts'] = sum(1 for v in decided if v == 'conflict')
    stats['skipped_confirmed'] = sum(1 for v in decided if v == 'confirmed')
    stats['error_samples'] = error_samples
    stats['unmatched_url_samples'] = unmatched_samples
    stats['conflict_samples'] = ctx['conflict_samples']
    stats['market_notes'] = market_notes
    return stats
