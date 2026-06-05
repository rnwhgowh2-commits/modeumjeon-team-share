"""[v3] 옵션 매트릭스 API — 다중 소싱처 + 가격 자동/수기 + 일괄.

엔드포인트:
  GET    /api/bundles/<code>/option-matrix
         → 옵션 트리 + 소싱처 매핑 + 가격 설정 일괄 조회
  POST   /api/options/sources/bulk
         → 선택 옵션들에 소싱처 URL 일괄 추가/수정
  DELETE /api/options/<sku>/sources/<src_id>
         → 옵션의 특정 소싱처 매핑 삭제
  POST   /api/options/<sku>/source-url
         → 단일 옵션의 단일 소싱처 URL 수정
  POST   /api/options/price-config/bulk
         → 선택 옵션들의 가격 설정 (자동/수기 + 마진/수수료) 일괄
  GET    /api/options/<sku>/price-calc
         → 단일 옵션 자동계산 산출과정 (breakdown)
"""
import logging

from flask import Blueprint, jsonify, request

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, Option
from lemouton.sourcing.models_pricing import (
    SourceRegistry, OptionSourceUrl, OptionPriceConfig, calc_auto_price,
)
from lemouton.pricing.unified import compute_market_price, is_crawl_valid
from lemouton.templates.models import PriceTemplate
from lemouton.sources.models import SourceProduct

bp = Blueprint('api_pricing', __name__, url_prefix='/api')


# ─── 팀공유 모드: admin 전용 (가격 정책 = 매출 영향, 회색지대 → admin). 기존 모드 통과. ───
# v34.4: 색상/아이콘 설정 (/api/icon/*, /api/progress*) 는 매출 영향 X → admin 검사 우회.
#         로그인은 여전히 필요 (login_required_smart). 가격 정책 (그 외 모든 /api/*) 은 admin.
@bp.before_request
def _admin_only():
    import os
    from flask import request
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    # 색상/아이콘·진행 widget API 는 모든 로그인 사용자 허용
    if request.path.startswith('/api/icon') or request.path.startswith('/api/progress'):
        try:
            from flask_login import current_user
            if not current_user.is_authenticated:
                return jsonify(error="unauthorized", message="로그인 필요"), 401
        except Exception:
            pass
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


def _ok(**kw):
    return jsonify({'ok': True, **kw})


def _err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


# ════════════════════════════════════════════
#  재고 매칭·의미 확정 (2026-06-03 전면 재작성)
#  배경: 기존 매칭은 (상품, 사이즈숫자) 키라 ① 1URL=여러색(르무통/SSF) 일 때
#        색을 무시해 엉뚱한 색 재고를 가져오고 ② size 가 color_text 에 들어간
#        사이트(롯데온/SSG)는 매칭 자체가 깨져 상품합계(999 센티넬 합)로 fallback.
#        → 화면 "재고 10"(가짜)·"품절"(오류) 의 근본 원인.
#  정책(사용자 확정): 정확한 수량 있으면 표기, 없으면 '재고있음', 0=품절.
# ════════════════════════════════════════════
import re as _re

# config.SOURCING_AUTH['stock_cap'] 와 동일 — 무신사는 '충분'을 이 값으로 저장(센티넬).
_STOCK_CAP = 10


def _stk_digits(x):
    return ''.join(c for c in str(x or '') if c.isdigit())


def _stk_cnorm(x):
    """색상 비교용 정규화 — 공백·괄호·구분자 제거 + 소문자."""
    return _re.sub(r'[\s()（）\[\]·,/\-_:：]', '', str(x or '')).lower()


def _build_so_index(source_options):
    """source_product_id -> [SourceOption] (deleted 제외 리스트 입력 가정)."""
    from collections import defaultdict
    idx = defaultdict(list)
    for so in source_options:
        idx[so.source_product_id].append(so)
    return idx


def _match_option_so(so_index, sp_id, opt_color, opt_size):
    """옵션(색상+사이즈) ↔ SourceOption 매칭 → 매칭된 SourceOption 객체. 실패 시 None.

    재고·가격 모두 이 단일 매칭을 통해 파생한다(둘이 따로 매칭돼 어긋나는 것 방지).

    - size: SourceOption.size_text 우선, 없으면 color_text 의 숫자(롯데온/SSG).
    - color: size_text 가 있을 때만 color_text 를 진짜 색으로 간주(르무통/SSF 등
             1URL=여러색). color_text 가 비었거나 size 를 담은 단일색 URL
             (롯데온/SSG/무신사)은 사이즈만으로 매칭(상품=단일색이라 안전).
    """
    cands = so_index.get(sp_id)
    if not cands:
        return None
    osz = _stk_digits(opt_size)
    if not osz:
        return None
    oc = _stk_cnorm(opt_color)
    size_only = None
    for so in cands:
        st = (so.size_text or '').strip()
        s_size = _stk_digits(st) or _stk_digits(so.color_text)
        if not s_size or s_size != osz:
            continue
        has_color = bool(st) and bool((so.color_text or '').strip())
        if has_color:
            sc = _stk_cnorm(so.color_text)
            if oc and sc and (oc == sc or oc in sc or sc in oc):
                return so                         # 색+사이즈 정확 매칭
            continue                              # 색 불일치 → 계속 탐색
        if size_only is None:
            size_only = so                        # 단일색 URL — 사이즈만으로 매칭
    return size_only


def _match_option_stock(so_index, sp_id, opt_color, opt_size):
    """옵션(색+사이즈) 매칭 SourceOption.current_stock. 실패 시 None."""
    so = _match_option_so(so_index, sp_id, opt_color, opt_size)
    return so.current_stock if so is not None else None


def _match_option_price(so_index, sp_id, opt_color, opt_size):
    """옵션(색+사이즈) 매칭 SourceOption.current_price. 실패 시 None.
       매트릭스 가격을 재고와 동일한 옵션단위로 맞추기 위함(상품단위 대표가 오염 방지)."""
    so = _match_option_so(so_index, sp_id, opt_color, opt_size)
    return so.current_price if so is not None else None


def _resolve_stock(site, raw):
    """site + raw → (qty:int|None, label:str, is_out:bool). 화면 표시 단일 진실 원천.

      raw == 0          → 품절
      raw is None       → 재고있음 (크롤됐으나 수량 미상)
      raw >= 900        → 재고있음 (999 센티넬 · 상품합계 더미)
      무신사 raw >= CAP → 재고있음 (stock_cap=10 이 '충분' 센티넬)
      그 외 1~899       → 실수량 'N개'
    """
    if raw == 0:
        return (0, '품절', True)
    if raw is None or raw >= 900:
        return (None, '재고있음', False)
    if (site or '') == 'musinsa' and raw >= _STOCK_CAP:
        return (None, '재고있음', False)
    return (int(raw), f'{int(raw)}개', False)


def _pick_cheapest_buyable(sources):
    """옵션의 소싱처들 중 "재고존재(품절X) + 크롤성공(error X) + 가격>0" 최저가.
       없으면 크롤성공+가격있는 것 중 최저(품절은 허용 — 실가격은 유효).
       그것도 없으면 None.
       winner(★최저)·원가의 단일 정의 — 품절/stale 소싱처가 원가로 잡히는 것 방지.

    [2026-06-05] 폴백도 is_crawl_valid 게이트를 통과해야 한다. 기존엔 폴백이
       `crawled_price` 만 봐서, 모든 소싱처가 크롤 실패(error)면 옛 가격(stale)이
       원가로 잡혀 잘못된 판매가가 계산되던 누수가 있었음. 품절(stock_out)은
       '실가격은 받았으나 재고 0'이라 폴백 후보로 허용하되, error 는 끝까지 배제.
    """
    buyable = [s for s in sources
               if is_crawl_valid(s.get('crawled_price'), s.get('last_status'))
               and not s.get('stock_out')]
    priced = buyable or [s for s in sources
                         if is_crawl_valid(s.get('crawled_price'), s.get('last_status'))]
    if not priced:
        return None
    return min(priced, key=lambda x: x.get('crawled_price') or 9e15)


# ════════════════════════════════════════════
#  v27 시안 ③ — 전역 progress widget API
# ════════════════════════════════════════════
_SEED_SRC_LABELS = {'lemouton': '르무통 공홈', 'ss_lemouton': '스마트스토어',
                    'musinsa': '무신사', 'ssf': 'SSF', 'lotteon': '롯데온', 'ssg': 'SSG'}
_SEED_ORDER = ['lemouton', 'ss_lemouton', 'musinsa', 'ssf', 'lotteon', 'ssg']


def _build_last_seed_from_db():
    """DB 의 소싱처별 마지막 크롤 상태 → '마지막 크롤 결과' 스냅샷 (콜드스타트 시드용)."""
    try:
        from datetime import timezone
        import time as _t
        from sqlalchemy import func
        from shared.db import SessionLocal
        from lemouton.sources.models import SourceProduct
        s = SessionLocal()
        try:
            rows = (s.query(SourceProduct.site,
                            func.count(SourceProduct.id),
                            func.max(SourceProduct.last_fetched_at))
                    .filter(SourceProduct.deleted_at.is_(None))
                    .group_by(SourceProduct.site).all())
        finally:
            s.close()
        by_site = {site: (cnt, maxf) for site, cnt, maxf in rows}
        breakdown, latest = [], 0.0
        for key in _SEED_ORDER:
            cnt, maxf = by_site.get(key, (0, None))
            if not cnt:
                continue
            breakdown.append({'key': key, 'label': _SEED_SRC_LABELS.get(key, key),
                              'total': cnt, 'done': cnt, 'status': 'done'})
            if maxf is not None:
                ts = maxf.replace(tzinfo=timezone.utc).timestamp()  # naive UTC → epoch
                latest = max(latest, ts)
        if not breakdown:
            return None
        return {'breakdown': breakdown,
                'total': sum(b['total'] for b in breakdown),
                'done': sum(b['done'] for b in breakdown),
                'finished_at': latest or _t.time(),
                'label': '마지막 크롤 (저장됨)'}
    except Exception:
        return None


@bp.get('/progress')
def api_get_progress():
    """전역 진행 상태 (크롤·업로드) 조회 — base.html widget 폴링용."""
    from webapp.progress_state import progress_get, progress_seed_last
    data = progress_get()
    if data.get('last') is None:   # 콜드스타트 — DB 로 '마지막 크롤 결과' 시드
        snap = _build_last_seed_from_db()
        if snap:
            progress_seed_last(snap)
            data = progress_get()
    return jsonify(data)


# ════════════════════════════════════════════
#  v32 — 아이콘 picker API (스텁)
# ════════════════════════════════════════════
@bp.post('/icon/set')
def api_set_icon():
    """아이콘 + 색상 저장.
    body: {context, target_id, icon|null, color|null, bg_color?, fg_color?}
      - bg_color/fg_color: v34 — 바탕색/글자색 hex (예: '#FF5500')
      - context='brand': 브랜드 단위 동기화 (target_id 가 'musinsa', 'lemouton' 등 브랜드 키)
    """
    body = request.get_json(silent=True) or {}
    ctx = (body.get('context') or '').strip()
    tid = body.get('target_id')
    icon = body.get('icon')
    color = body.get('color')
    bg_color = body.get('bg_color') or None
    fg_color = body.get('fg_color') or None
    letter = body.get('letter') or None
    if not ctx:
        return _err('context required', 400)
    try:
        from webapp.icon_store import set_icon
        set_icon(ctx, str(tid or ''), icon, color,
                 bg_color=bg_color, fg_color=fg_color, letter=letter)
    except Exception as e:
        logging.getLogger(__name__).warning("icon set failed: %s", e)
    return _ok(context=ctx, target_id=tid, icon=icon, color=color,
               bg_color=bg_color, fg_color=fg_color, letter=letter)


@bp.get('/icon/list')
def api_list_icons():
    """저장된 아이콘 일괄 조회 (페이지 로드 시 적용용)."""
    try:
        from webapp.icon_store import list_icons
        return jsonify({'ok': True, 'icons': list_icons()})
    except Exception:
        return jsonify({'ok': True, 'icons': []})


@bp.post('/progress/<kind>')
def api_set_progress(kind):
    """JS 에서 작업 진행 보고 (start/tick/finish)."""
    from webapp.progress_state import progress_set, progress_tick, progress_finish
    if kind not in ('crawl', 'upload'):
        return _err('kind must be crawl|upload', 400)
    body = request.get_json(silent=True) or {}
    op = (body.get('op') or '').lower()
    bd = body.get('breakdown') if isinstance(body.get('breakdown'), list) else None
    if op == 'start':
        progress_set(kind, total=int(body.get('total') or 0),
                     label=body.get('label') or '', current=body.get('current') or '',
                     breakdown=bd)
    elif op == 'tick':
        progress_tick(kind, done=body.get('done'),
                      current=body.get('current') or '',
                      delta=int(body.get('delta') or 0),
                      breakdown=bd)
    elif op == 'finish':
        progress_finish(kind)
    else:
        return _err('op must be start|tick|finish', 400)
    return _ok()


# ════════════════════════════════════════════
#  GET /api/bundles/<code>/option-matrix
# ════════════════════════════════════════════
def _option_matrix_data(code: str):
    """옵션 트리 + 소싱처 + 가격설정 + 자동계산 가격 일괄 조회 (데이터 dict 반환).

    [2026-06-05] 라우트(get_option_matrix)와 분리 — 업로드 드라이런(preview)이
    이 함수를 직접 호출해 '표시가=업로드가' 단일 진실 원천(parity)을 공유한다.
    반환: 성공 {'ok':True, ...}, 실패 {'ok':False,'error','status'}.

    옵션 트리 + 소싱처 + 가격설정 + 자동계산 가격 일괄 조회.

    [v3 시나리오 C] code 가 model_code 또는 bundle_groups.group_code 둘 다 인식.
    group 일 경우 그 group 의 모든 Model 의 옵션을 통합 반환.
    """
    from lemouton.sourcing.models import BundleGroup
    s = SessionLocal()
    try:
        # 1순위: model_code 직접 매칭 (기존 호환)
        m = s.query(Model).filter_by(model_code=code).first()
        models_in_group = [m] if m else []
        bundle_group = None
        if not m:
            # 2순위: group_code 매칭 → 그룹의 모든 Model
            bundle_group = s.query(BundleGroup).filter_by(group_code=code).first()
            if bundle_group:
                models_in_group = list(bundle_group.models)
                m = models_in_group[0] if models_in_group else None
        if not m:
            return {'ok': False, 'error': '모음전을 찾을 수 없어요.', 'status': 404}
        # 1 모음전 1 모델 (기존) → 그 모델의 그룹 통해 형제 모델들 조회
        if not bundle_group and m.bundle_group_id:
            bundle_group = s.query(BundleGroup).filter_by(id=m.bundle_group_id).first()
            if bundle_group:
                models_in_group = list(bundle_group.models)

        # 그룹의 모든 Model 의 옵션 통합
        model_codes = [mm.model_code for mm in models_in_group]
        opts = (
            s.query(Option)
            .filter(Option.model_code.in_(model_codes))
            .order_by(Option.model_code, Option.sort_order, Option.color_code, Option.size_code)
            .all()
        )
        sku_list = [o.canonical_sku for o in opts]

        # 소싱처 사전
        sources = (
            s.query(SourceRegistry)
            .order_by(SourceRegistry.sort_order, SourceRegistry.id)
            .all()
        )
        source_dict = {src.id: {'id': src.id, 'name': src.name,
                                'main_url': src.main_url or ''} for src in sources}

        # 옵션 × 소싱처 매핑
        url_links = (
            s.query(OptionSourceUrl)
            .filter(OptionSourceUrl.canonical_sku.in_(sku_list))
            .all() if sku_list else []
        )

        # URL → SourceProduct 조인 (크롤링 가격 가져오기 위해)
        # ★ 잔여 #2 — 트래킹 파라미터 stripping 후 정규화 매칭. legacy 입력 URL 의
        #   ``NaPm`` / ``nl-ts-pid`` 같은 광고 트래킹이 매칭 실패 원인이라 매트릭스
        #   가 빈칸으로 표시되던 문제 해결.
        from lemouton.sources.service import normalize_url as _norm_url
        url_set = {link.product_url for link in url_links if link.product_url}
        sp_by_norm = {}  # normalized URL → SourceProduct
        if url_set:
            sps = (s.query(SourceProduct)
                   .filter(SourceProduct.deleted_at.is_(None))
                   .all())
            for sp in sps:
                sp_by_norm[_norm_url(sp.url)] = sp

        sku_to_sources = {}  # sku -> [{source_id, source_name, product_url, ...}]
        for link in url_links:
            sp = sp_by_norm.get(_norm_url(link.product_url)) if link.product_url else None
            # ★ 2026-05-13 — 매트릭스 표시 가격 우선순위 변경.
            #   기존: OptionSourceUrl.price_cached (legacy 자동 수집 캐시) 우선.
            #   변경: SourceProduct.last_price (실시간 어댑터 결과) 우선.
            #   사유: 어댑터는 매번 새 가격 추출하지만 price_cached 갱신 코드는 미사용 →
            #         매트릭스가 stale 가격을 보여주는 데이터 무결성 문제. 사용자 정책
            #         "할인가 (크롤링 기준) 이 사이트 표시와 일치해야 함" 충족.
            #   stock 은 옵션 단위 차이 가능성 있어 기존 우선순위 유지.
            crawled_price = (sp.last_price if sp and sp.last_price
                             else link.price_cached)
            crawled_stock = (link.stock_cached
                             if link.stock_cached is not None
                             else (sp.last_stock if sp else None))
            last_fetched = None
            if link.last_checked_at:
                last_fetched = link.last_checked_at.isoformat()
            elif sp and sp.last_fetched_at:
                last_fetched = sp.last_fetched_at.isoformat()
            # ★ 2026-05-13 — 사이트 자동 적용 카드 할인 정보 (시안 B: 팝업 보조 텍스트)
            _acd = None
            if sp and sp.auto_card_discount_json:
                try:
                    import json as _json
                    _acd = _json.loads(sp.auto_card_discount_json)
                except (ValueError, TypeError):
                    _acd = None

            # ★ 2026-05-13 시안 A1 — 카드 미반영 토글 우선순위 (option > bundle > global)
            #   _bundle_code 는 매트릭스 페이지 전체에 동일 → 상위에서 1회 결정.
            _card_enabled = True
            if _acd:
                from webapp.routes.api_benefits import resolve_card_enabled
                _card_enabled = resolve_card_enabled(
                    s,
                    canonical_sku=link.canonical_sku,
                    source_id=link.source_id,
                    bundle_code=code,  # group_code 또는 model_code (URL path)
                )
            # 카드 OFF + sale_price 에 카드가 반영된 경우 (롯데) → 가격 환원
            _display_price_with_card = crawled_price
            if _acd and not _card_enabled and _acd.get('included_in_sale_price') and crawled_price:
                rate = float(_acd.get('rate') or 0) / 100.0
                if rate > 0 and rate < 1:
                    # 카드 차감 전 가격 = 현재 가격 / (1 - rate)
                    _display_price_with_card = round(crawled_price / (1 - rate))

            sku_to_sources.setdefault(link.canonical_sku, []).append({
                'source_id': link.source_id,
                'site': (sp.site if sp else None),
                'source_name': source_dict.get(link.source_id, {}).get('name', '?'),
                'product_url': link.product_url,
                # 캐시(legacy 호환)
                'price_cached': link.price_cached,
                'stock_cached': link.stock_cached,
                # 옵션 단위 우선 + SourceProduct fallback
                'source_product_id': sp.id if sp else None,
                'crawled_price': _display_price_with_card,
                'crawled_price_raw': crawled_price,  # 카드 적용된 원본 (참고용)
                'crawled_stock': crawled_stock,
                'last_fetched_at': last_fetched,
                'last_status': sp.last_status if sp else None,
                # 시안 B: 팝업 판매가 라인 옆 inline 보조 텍스트
                'auto_card_discount': _acd,
                # 시안 A1: 카드 enabled 상태 (UI 가 체크박스 ON/OFF 표시용)
                'card_enabled': _card_enabled,
            })

        # [2026-06-03] 신규 URL 모델 통합 — bundle_source_urls + option_source_url_links.
        #   배경: 등록 UI 는 이 테이블에 쓰는데 매트릭스는 legacy option_source_urls(빈 테이블)만
        #   읽어 "0 URLs · 크롤링 미실시" 로 보이던 문제. 등록된 URL 을 옵션별로 노출하고,
        #   이미 크롤된 SourceProduct 가 있으면 가격/재고 연결. (additive + 안전 try)
        try:
            from lemouton.sourcing.models import BundleSourceUrl, OptionSourceUrlLink
            from lemouton.sourcing.source_registry import get_labels as _src_labels
            _labels = _src_labels()
            if sku_list:
                # [2026-06-03] 크롤가 매칭 — legacy url_set 이 비어 sp_by_norm 이 미생성되는
                #   경우(신규 URL 모델만 쓰는 번들)를 대비해 SourceProduct 전체로 보강 매핑.
                _sp_by_norm2 = dict(sp_by_norm)
                try:
                    for _sp in (s.query(SourceProduct)
                                .filter(SourceProduct.deleted_at.is_(None)).all()):
                        if _sp.url:
                            _sp_by_norm2.setdefault(_norm_url(_sp.url), _sp)
                except Exception:
                    pass
                # [2026-06-03] source_key → SourceRegistry id 매핑 (main_url 도메인 매칭).
                #   매트릭스 사이트 칼럼은 o.sources 를 source_id===site.id(레지스트리 id)로
                #   매칭하므로, 등록 URL 의 source_id 를 레지스트리 id 로 줘야 칼럼에 가격/재고 노출.
                _key_domain = {
                    'lemouton': 'lemouton.co.kr', 'ss_lemouton': 'smartstore.naver.com',
                    'musinsa': 'musinsa.com', 'ssf': 'ssfshop.com', 'lotteon': 'lotteon.com',
                    # [2026-06-03] SSG 컬럼 추가 — SourceRegistry 에 SSG(main_url=ssg.com) 행 필요.
                    #   ssg.com 은 다른 소싱처 도메인과 겹치지 않음(ssfshop.com 에 'ssg.com' 미포함).
                    'ssg': 'ssg.com',
                }
                _key_to_regid = {}
                for _k, _dom in _key_domain.items():
                    for _rid, _rv in source_dict.items():
                        if _dom in (_rv.get('main_url') or ''):
                            _key_to_regid[_k] = _rid
                            break
                # [2026-06-03 재작성] 옵션별 실재고 — 색상+사이즈 매칭(_match_option_stock).
                #   기존 (상품,사이즈숫자) 키는 ① 1URL=여러색이면 색 무시로 오매칭
                #   ② size 가 color_text 에 든 사이트(롯데온/SSG)는 매칭 자체 실패.
                #   → SourceOption 객체 그대로 인덱싱 후 색·사이즈로 정확 매칭.
                _so_index = {}
                try:
                    from lemouton.sources.models import SourceOption as _SO
                    _spids = list({_v.id for _v in _sp_by_norm2.values() if _v})
                    if _spids:
                        _so_index = _build_so_index(
                            s.query(_SO)
                            .filter(_SO.source_product_id.in_(_spids),
                                    _SO.deleted_at.is_(None)).all())
                except Exception:
                    pass
                _sku_size = {o.canonical_sku: o.size_code for o in opts}
                _sku_color = {o.canonical_sku: o.color_code for o in opts}
                _link_rows = (
                    s.query(OptionSourceUrlLink, BundleSourceUrl)
                    .join(BundleSourceUrl,
                          OptionSourceUrlLink.bundle_source_url_id == BundleSourceUrl.id)
                    .filter(OptionSourceUrlLink.option_canonical_sku.in_(sku_list))
                    .all()
                )
                for lk, bsu in _link_rows:
                    existing = sku_to_sources.setdefault(lk.option_canonical_sku, [])
                    if any(e.get('product_url') == bsu.url for e in existing):
                        continue  # legacy 로 이미 추가된 동일 URL 중복 방지
                    sp = _sp_by_norm2.get(_norm_url(bsu.url)) if bsu.url else None
                    _reg_id = _key_to_regid.get(bsu.source_key)  # 칼럼 매칭용 레지스트리 id
                    # 옵션별 실재고·실가격 — 색상+사이즈로 매칭된 동일 SourceOption 에서 파생.
                    #   실패 시에만 상품단위(last_stock/last_price)로 fallback.
                    #   [2026-06-03] 가격도 옵션단위 우선 — 기존엔 가격만 상품 last_price 라
                    #   SSF 처럼 옵션가(119,900)≠상품대표가(122,376) 일 때 틀린 값 표시되던 버그.
                    _opt_stock = None
                    _opt_price = None
                    if sp:
                        _so_m = _match_option_so(
                            _so_index, sp.id,
                            _sku_color.get(lk.option_canonical_sku),
                            _sku_size.get(lk.option_canonical_sku))
                        if _so_m is not None:
                            _opt_stock = _so_m.current_stock
                            _opt_price = _so_m.current_price
                    # 옵션 크롤가(>0) 우선, 없으면 상품 last_price fallback
                    _disp_price = (_opt_price if (_opt_price and _opt_price > 0)
                                   else (sp.last_price if sp else None))
                    existing.append({
                        # 칼럼 매칭 = 레지스트리 id (없으면 SSG 등 — 칼럼 없음). refetch 도 동일.
                        'source_id': _reg_id,
                        'source_key': bsu.source_key,
                        'site': (sp.site if sp else bsu.source_key),
                        'source_name': _labels.get(bsu.source_key, bsu.source_key),
                        'product_url': bsu.url,
                        'label': bsu.label or '',
                        'price_cached': None,
                        'stock_cached': None,
                        'source_product_id': sp.id if sp else None,
                        'crawled_price': _disp_price,
                        'crawled_price_raw': _disp_price,
                        'crawled_stock': (_opt_stock if _opt_stock is not None
                                          else (sp.last_stock if sp else None)),
                        'last_fetched_at': (sp.last_fetched_at.isoformat()
                                            if sp and sp.last_fetched_at else None),
                        'last_status': (sp.last_status if sp else None),
                        'auto_card_discount': None,
                        'card_enabled': True,
                        'crawled': bool(sp),
                    })
        except Exception:
            pass

        # [2026-06-03] 재고 의미 확정 — 화면 표시 단일 진실 원천.
        #   사이트별 센티넬(999·무신사 cap 10·상품합계 더미)을 백엔드에서 해석해
        #   stock_qty(실수량|None)·stock_label('품절'|'재고있음'|'N개')·stock_out 로 확정.
        #   프론트는 이 값만 렌더(가짜 '재고 10' 제거). 정책: 수량 있으면 표기, 없으면 '재고있음'.
        for _srcs in sku_to_sources.values():
            for _d in _srcs:
                _q, _lbl, _out = _resolve_stock(_d.get('site'), _d.get('crawled_stock'))
                _d['stock_qty'] = _q
                _d['stock_label'] = _lbl
                _d['stock_out'] = _out

        # 가격 설정
        configs = (
            s.query(OptionPriceConfig)
            .filter(OptionPriceConfig.canonical_sku.in_(sku_list))
            .all() if sku_list else []
        )
        cfg_dict = {c.canonical_sku: c for c in configs}

        # v17 Phase 5 — InventoryProduct 매핑 (재고관리 추가 옵션만)
        try:
            from lemouton.inventory.models import InventoryProduct
            inv_products = (s.query(InventoryProduct)
                            .filter(InventoryProduct.canonical_sku.in_(
                                [o.canonical_sku for o in opts]))
                            .all())
            inv_dict = {p.canonical_sku: p for p in inv_products}
        except Exception:
            inv_dict = {}

        # ④ 옵션 재고연결 — OptionProductLink 로 연결된 재고제품 (옵션 SKU 와 다를 수 있음)
        linked_product_dict: dict[str, dict] = {}
        try:
            from lemouton.inventory.models import (
                InventoryProduct as _IP, OptionProductLink as _OPL,
            )
            from shared.inventory_stock import get_stock_batch as _gsb
            links = (s.query(_OPL)
                     .filter(_OPL.option_canonical_sku.in_(sku_list))
                     .all() if sku_list else [])
            # 옵션 SKU 와 동일한 product 를 가리키는 self-link 는 표시 안 함
            #   (1:1 시딩 링크 = 기존 +재고관리 흐름과 동일 의미 → inv_product_id 로 충분)
            ext_links = {lk.option_canonical_sku: lk.product_canonical_sku
                         for lk in links
                         if lk.product_canonical_sku != lk.option_canonical_sku}
            if ext_links:
                prod_skus = list(set(ext_links.values()))
                lp_rows = (s.query(_IP)
                           .filter(_IP.canonical_sku.in_(prod_skus)).all())
                lp_by_sku = {p.canonical_sku: p for p in lp_rows}
                lp_stock = _gsb(s, prod_skus)
                for opt_sku_v, prod_sku_v in ext_links.items():
                    p = lp_by_sku.get(prod_sku_v)
                    if not p:
                        continue
                    linked_product_dict[opt_sku_v] = {
                        'product_sku': p.canonical_sku,
                        'name': p.option_name or p.canonical_sku,
                        'color': p.color_code or '',
                        'size': p.size_code or '',
                        'brand': p.brand or '',
                        'barcode': p.barcode or '',
                        'stock': lp_stock.get(p.canonical_sku, 0),
                    }
        except Exception:
            linked_product_dict = {}

        # [2026-05-25 D-1 리팩터링] 재고 단일 진실 원천 = shared/inventory_stock.get_stock_batch
        #   기존: 옵션 sku 직접 InventoryTx 매칭만 → OptionProductLink 거친 product 재고 누락
        #         (르무통 메이트 89 옵션 중 ext-link 89 = 전체 재고 0 으로 잘못 표시되던 버그)
        #   신: get_stock_batch 가 OptionProductLink 자동 해석 + in/out/adjust/move 모두 합산
        #       N+1 회피 (1 쿼리), self-link·ext-link·no-link 일관 처리
        inv_stock_dict: dict[str, int] = {}
        try:
            from shared.inventory_stock import get_stock_batch
            inv_stock_dict = get_stock_batch(s, [o.canonical_sku for o in opts])
        except Exception:
            inv_stock_dict = {}

        # 가격 템플릿 (자동계산 디폴트값)
        tpl = None
        if m.price_template_id:
            tpl = s.query(PriceTemplate).filter_by(id=m.price_template_id).first()

        # 옵션마다 자동계산 산출 (auto_enabled 일 때만)
        opt_rows = []
        color_groups = {}  # color_code -> [size_code, ...]
        for o in opts:
            cfg = cfg_dict.get(o.canonical_sku)
            auto = cfg.auto_enabled if cfg else True
            margin = (cfg.margin_rate if cfg and cfg.margin_rate is not None
                      else (tpl.ss_margin_rate if tpl else 0.10))
            ss_fee = (cfg.ss_fee_rate if cfg and cfg.ss_fee_rate is not None
                      else (tpl.ss_fee_rate if tpl else 0.06))
            cp_fee = (cfg.cp_fee_rate if cfg and cfg.cp_fee_rate is not None
                      else (tpl.coupang_fee_rate if tpl else 0.1155))
            ss_ship = (tpl.ss_delivery_fee if tpl else 0) or 0
            cp_ship = (tpl.coupang_delivery_fee if tpl else 0) or 0
            rounding = (tpl.rounding_unit if tpl else 100) or 100

            # [2026-06-03 핵심 로직] 원가 = "재고 존재 + 크롤 성공" 소싱처 중 최저 크롤가.
            #   (기존: 첫 번째 가격있는 소싱처 — 품절·크롤실패 stale 가격도 원가로 잡히던 버그.
            #    또 source_id=='lemouton' 비교는 source_id 가 레지스트리 int 라 항상 미스 = dead code.)
            #   사입처는 '재고 있고 가장 싼 곳'에서 산다 → 그 가격이 원가. 없으면 템플릿 매입가 → 95000.
            sources_for_opt = sku_to_sources.get(o.canonical_sku, [])
            _cost_src = _pick_cheapest_buyable(sources_for_opt)
            purchase = ((_cost_src or {}).get('crawled_price')
                        or (tpl.boxhero_purchase_price if tpl else None)
                        or 95000)

            # [2026-06-02] 소싱 카드 가격 — 단일 진실 원천(compute_market_price)로 통일.
            #   모달 마켓별·소싱 정책(rate/amount/지정가)을 그대로 반영. 화면=업로드 보장.
            #   기존 calc_auto_price(ss_margin_rate 를 쿠팡에도 쓰던 버그) 대체.
            _src_ss_res = compute_market_price(tpl, 'ss', 'sourcing', purchase)
            _src_cp_res = compute_market_price(tpl, 'coupang', 'sourcing', purchase)
            ss_price, ss_break = _src_ss_res.final_price, _src_ss_res.breakdown
            cp_price, cp_break = _src_cp_res.final_price, _src_cp_res.breakdown

            display_ss = (cfg.manual_ss_price if cfg and not auto and cfg.manual_ss_price
                          else ss_price)
            display_cp = (cfg.manual_cp_price if cfg and not auto and cfg.manual_cp_price
                          else cp_price)
            color_groups.setdefault(o.color_code, []).append({
                'sku': o.canonical_sku, 'size': o.size_code,
                'src_count': len(sources_for_opt),
                'sort_order': o.sort_order,  # [순서 v33] 사용자 배치 순서
            })
            # [2026-05-25 UI-3] 재고 = SSOT (inv_stock_dict = get_stock_batch 결과)만 사용
            #   배경: 박스히어로 import 가 boxhero_stock_total snapshot 갱신 + InventoryTx 생성
            #   → 두 source 합산하면 ×2 중복. SSOT 하나로 통일.
            _stock = inv_stock_dict.get(o.canonical_sku, 0)
            _avg = o.boxhero_avg_purchase_price or 0
            _mode = o.option_boxhero_margin_mode or 'rate'
            _val = o.option_boxhero_margin_value or 0
            _enabled = bool(o.use_purchase_inventory)
            _pri = (o.purchase_priority or 'auto').lower()

            # [2026-05-25 V5] 매입가 산정 우선순위 (PriceTemplate.price_source_priority)
            #   'template' (기본) — 템플릿 boxhero_purchase_price → 0이면 옵션 _avg 폴백
            #   'avg'             — 옵션 _avg → 0이면 템플릿값 폴백
            #   둘 다 0이면 사입 카드 차단 (UI 빨간 🚫)
            _tpl_purchase = (tpl.boxhero_purchase_price if tpl else 0) or 0
            _src_pri = (tpl.price_source_priority if tpl else 'template') or 'template'
            if _src_pri == 'avg':
                _resolved_avg = _avg or _tpl_purchase
            else:
                _resolved_avg = _tpl_purchase or _avg
            _purchase_blocked = (_resolved_avg == 0)

            # [2026-05-25 M] 마켓별 지정가 활성화 (소싱·사입 × 스마트·쿠팡 = 4개)
            _src_fix_ss_on = bool(o.src_fixed_ss_active)
            _src_fix_cp_on = bool(o.src_fixed_cp_active)
            _src_fix_ss = o.src_fixed_ss_price or 0
            _src_fix_cp = o.src_fixed_cp_price or 0
            _pur_fix_ss_on = bool(o.pur_fixed_ss_active)
            _pur_fix_cp_on = bool(o.pur_fixed_cp_active)
            _pur_fix_ss = o.pur_fixed_ss_price or 0
            _pur_fix_cp = o.pur_fixed_cp_price or 0
            # 역마진 경고 — 사입 마켓 active+값+매입가 있을 때 값 < 매입가
            _pur_loss_ss = bool(_pur_fix_ss_on and _pur_fix_ss and _resolved_avg and _pur_fix_ss < _resolved_avg)
            _pur_loss_cp = bool(_pur_fix_cp_on and _pur_fix_cp and _resolved_avg and _pur_fix_cp < _resolved_avg)

            # [2026-05-25 A1] 소싱 카드 재고 = 재고 ≥1 인 소싱처 중 최저가의 재고
            #   [2026-06-03] 표시 라벨도 백엔드 확정값(stock_label/qty) 사용 → '재고 10' 가짜 제거.
            _src_stock = 0
            _src_stock_label = None   # '품절'|'재고있음'|'N개' (None = 재고 있는 소싱처 없음)
            _src_stock_qty = None     # 실수량 (없으면 None → '재고있음')
            _src_stock_url = None     # [2026-06-03] 최저가 winner 소싱처의 상품 URL (재고 칩 클릭 → 그 페이지)
            # 재고 존재(품절 아님) + 크롤 성공 + 가격 있음 → 그 중 최저가의 재고. (winner 와 동일 정의)
            _src_with_stock = [_s for _s in sources_for_opt
                               if not _s.get('stock_out')
                               and _s.get('last_status') != 'error'
                               and (_s.get('crawled_price') or 0) > 0]
            if _src_with_stock:
                _cheapest_src = min(_src_with_stock, key=lambda x: x.get('crawled_price') or 9999999)
                _src_stock = _cheapest_src.get('crawled_stock') or 0
                _src_stock_label = _cheapest_src.get('stock_label')
                _src_stock_qty = _cheapest_src.get('stock_qty')
                _src_stock_url = _cheapest_src.get('product_url') or None

            # 우선순위 결정 — 재고 ≥1 = 무조건 사입 / 재고 0 = priority 따름
            if _stock >= 1:
                _resolved_pri = 'purchase'
            elif _pri == 'purchase':
                _resolved_pri = 'purchase'
            else:
                _resolved_pri = 'source'

            # [2026-06-02] 소싱 카드 — 옵션별 지정가 토글(최우선) > 템플릿 정책(위에서 산출)
            #   소싱/사입 카드는 항상 각자 가격을 표시하므로 카드별로 분리 산출(기존 conflation 제거).
            src_ss_price = _src_fix_ss if (_src_fix_ss_on and _src_fix_ss) else display_ss
            src_cp_price = _src_fix_cp if (_src_fix_cp_on and _src_fix_cp) else display_cp

            # [2026-06-02] 사입 카드 — 마켓별 매입 정책(rate/amount/지정가) 단일 진실 원천 산출.
            #   원가 = 매입가(_resolved_avg). 옵션별 지정가 토글 ON 이면 그 값 최우선.
            pur_ss_price = None
            pur_cp_price = None
            if _stock >= 1 and not _purchase_blocked:
                _pur_ss_res = compute_market_price(tpl, 'ss', 'purchase', _resolved_avg)
                _pur_cp_res = compute_market_price(tpl, 'coupang', 'purchase', _resolved_avg)
                pur_ss_price = _pur_ss_res.final_price
                pur_cp_price = _pur_cp_res.final_price
                if _pur_fix_ss_on and _pur_fix_ss: pur_ss_price = _pur_fix_ss
                if _pur_fix_cp_on and _pur_fix_cp: pur_cp_price = _pur_fix_cp

            # 사입 판매가(레거시 단일값) — 백워드 호환 유지 (FE 카드 가격은 pur_ss/cp_price 사용)
            _purchase_price = None
            if _stock >= 1 and not _purchase_blocked:
                if _mode == 'manual':
                    _purchase_price = o.purchase_manual_price
                elif _mode == 'rate':
                    _purchase_price = int(_resolved_avg * (1 + _val / 10000.0))
                elif _mode == 'amount':
                    _purchase_price = int(_resolved_avg + _val)
            opt_rows.append({
                'sku': o.canonical_sku,
                'model_code': o.model_code,  # [v3 시나리오 C] 그룹 안 모델 식별
                'color_code': o.color_code,
                'color_display': o.color_display or o.color_code,
                'size_code': o.size_code,
                'size_display': o.size_display or o.size_code,
                'auto_enabled': auto,
                'margin_rate': margin,
                'ss_fee_rate': ss_fee,
                'cp_fee_rate': cp_fee,
                'ss_price': src_ss_price,
                'cp_price': src_cp_price,
                # [2026-06-02] 사입 카드 마켓별 가격 (정책 기반, FE 재계산 제거용)
                'pur_ss_price': pur_ss_price,
                'pur_cp_price': pur_cp_price,
                'ss_breakdown': ss_break,
                'cp_breakdown': cp_break,
                'manual_stock': cfg.manual_stock if cfg else None,
                # v17 Phase 5 — InventoryProduct 매핑 (재고관리 연동 여부)
                'inv_product_id': inv_dict.get(o.canonical_sku).id if inv_dict.get(o.canonical_sku) else None,
                'inv_product_status': inv_dict.get(o.canonical_sku).status if inv_dict.get(o.canonical_sku) else None,
                # ④ 옵션 재고연결 — OptionProductLink 로 연결된 재고제품 (없으면 null)
                'linked_product': linked_product_dict.get(o.canonical_sku),
                'sources': sources_for_opt,
                'src_count': len(sources_for_opt),
                # M4/P3 사입 데이터
                'purchase_stock': _stock,
                'purchase_enabled': _enabled,
                'purchase_priority': _pri,
                'purchase_priority_resolved': _resolved_pri,
                'purchase_avg_cost': _avg,
                'purchase_margin_mode': _mode,
                'purchase_margin_value': _val,
                'purchase_manual_price': o.purchase_manual_price,
                'purchase_final_price': _purchase_price,
                # [2026-05-25 V5] 매입가 우선순위 + 차단 플래그
                'purchase_resolved_avg': _resolved_avg,
                'purchase_blocked': _purchase_blocked,
                'price_source_priority': _src_pri,
                'template_purchase_price': _tpl_purchase,
                # [2026-05-25 M] 마켓별 지정가 active + 가격 + 소싱 재고 + 원가 (JS 마진 계산용)
                'src_stock': _src_stock,
                'src_stock_label': _src_stock_label,
                'src_stock_qty': _src_stock_qty,
                'src_stock_url': _src_stock_url,
                'src_cost': purchase,
                'src_fixed_ss_active': _src_fix_ss_on,
                'src_fixed_cp_active': _src_fix_cp_on,
                'src_fixed_ss_price': _src_fix_ss or None,
                'src_fixed_cp_price': _src_fix_cp or None,
                'pur_fixed_ss_active': _pur_fix_ss_on,
                'pur_fixed_cp_active': _pur_fix_cp_on,
                'pur_fixed_ss_price': _pur_fix_ss or None,
                'pur_fixed_cp_price': _pur_fix_cp or None,
                'pur_loss_ss': _pur_loss_ss,
                'pur_loss_cp': _pur_loss_cp,
            })

        # [순서 v33] 트리 구조화 (color → sizes) — sort_order 우선 (사용자가 매트릭스에서 배치한 순서).
        #   sort_order 미설정(모두 0/None) 시엔 기존처럼 이름·사이즈 순으로 자연 폴백.
        def _so(v):
            return v if isinstance(v, int) else 9999
        tree = []
        _color_order = sorted(
            color_groups.keys(),
            key=lambda cc: (min(_so(r.get('sort_order')) for r in color_groups[cc]), cc),
        )
        for color_code in _color_order:
            sizes = sorted(color_groups[color_code], key=lambda x: (_so(x.get('sort_order')), x['size']))
            tree.append({
                'color_code': color_code,
                'sizes': sizes,
                'count': len(sizes),
            })

        # [v3] cluster 정보 (시나리오 C — 1 그룹 N 모델)
        bundle_group_payload = None
        if bundle_group:
            import json as _json
            opt_cfg = {}
            if bundle_group.option_config_json:
                try:
                    opt_cfg = _json.loads(bundle_group.option_config_json)
                except Exception:
                    opt_cfg = {}
            bundle_group_payload = {
                'id': bundle_group.id,
                'group_code': bundle_group.group_code,
                'group_name': bundle_group.group_name,
                'cluster_size': len(models_in_group),
                'option_config': opt_cfg,
                'models': [
                    {'model_code': mm.model_code,
                     'model_name_display': getattr(mm, 'model_name_display', mm.model_code) or mm.model_code}
                    for mm in models_in_group
                ],
            }

        # [2026-06-05] 소싱처별 URL·매핑 집계 — 듀얼 미니바 카드 + 실패 모달 공용 단일 진실 원천.
        #   url_try/url_done : 소싱처에 등록된 고유 URL 수 / 그중 크롤 성공(last_price>0) URL 수
        #   map_try/map_done : 옵션-URL 매핑 건수(중복 미제거 = 모달 N열 총합) / 그중 크롤 성공 건수
        #   fail_urls        : 크롤 실패 URL 목록(label·url·영향 매핑수·status) — 모달 빨강/재크롤용
        #   ※ 매트릭스 프론트가 o.sources 로 세던 값(URL 중복 제거되어 부정확)을 대체.
        source_stats = {}
        try:
            from lemouton.sourcing.models import (
                BundleSourceUrl as _BSU, OptionSourceUrlLink as _OSL)
            from lemouton.sourcing.source_registry import get_labels as _lbls
            from sqlalchemy import func as _func
            _label_map = _lbls()
            _key_dom = {
                'lemouton': 'lemouton.co.kr', 'ss_lemouton': 'smartstore.naver.com',
                'musinsa': 'musinsa.com', 'ssf': 'ssfshop.com',
                'lotteon': 'lotteon.com', 'ssg': 'ssg.com',
            }
            _k2reg = {}
            for _k, _dom in _key_dom.items():
                for _rid, _rv in source_dict.items():
                    if _dom in (_rv.get('main_url') or ''):
                        _k2reg[_k] = _rid
                        break
            # 크롤 성공 판정용 — url(정규화) → (last_price, last_status)
            _crawl_idx = {}
            for _sp in (s.query(SourceProduct)
                        .filter(SourceProduct.deleted_at.is_(None)).all()):
                if _sp.url:
                    _crawl_idx[_norm_url(_sp.url)] = (_sp.last_price, _sp.last_status)
            _bsus = (s.query(_BSU)
                     .filter(_BSU.model_code.in_(model_codes)).all())
            _bids = [b.id for b in _bsus]
            _lcnt = {}
            if _bids:
                for _bid, _c in (s.query(_OSL.bundle_source_url_id, _func.count())
                                 .filter(_OSL.bundle_source_url_id.in_(_bids))
                                 .group_by(_OSL.bundle_source_url_id).all()):
                    _lcnt[_bid] = _c
            for _b in _bsus:
                _sk = _b.source_key
                _rid = _k2reg.get(_sk)
                _key = _rid if _rid is not None else 'key:' + str(_sk)
                _st = source_stats.setdefault(str(_key), {
                    'source_id': _rid, 'source_key': _sk,
                    'source_name': _label_map.get(_sk, _sk),
                    'url_try': 0, 'url_done': 0, 'map_try': 0, 'map_done': 0,
                    'fail_urls': [],
                })
                _rec = _crawl_idx.get(_norm_url(_b.url)) if _b.url else None
                # [2026-06-05] 성공 판정 = is_crawl_valid(가격>0 AND status!=error) 단일 게이트.
                #   매트릭스 셀(renderSiteCell)은 last_status=='error' 면 '크롤 실패'로 표시하는데,
                #   여기서 가격만 보면 옛 가격(stale)이 남은 실패 URL을 '성공(100%)'으로 집계해
                #   상단 카드와 셀이 모순됨(거짓 100%). 셀·원가·업로드와 동일 기준으로 통일.
                _ok_url = bool(_rec) and is_crawl_valid(_rec[0], _rec[1])
                _links = _lcnt.get(_b.id, 0)
                _st['url_try'] += 1
                _st['map_try'] += _links
                if _ok_url:
                    _st['url_done'] += 1
                    _st['map_done'] += _links
                else:
                    _st['fail_urls'].append({
                        'id': _b.id, 'label': _b.label or '', 'url': _b.url,
                        'affected': _links,
                        'status': (_rec[1] if _rec else 'not_crawled'),
                    })
        except Exception:
            source_stats = {}

        return dict(
            ok=True,
            sources=list(source_dict.values()),
            source_stats=source_stats,
            tree=tree,
            options=opt_rows,
            bundle_group=bundle_group_payload,
            template={
                'id': tpl.id if tpl else None,
                'name': tpl.name if tpl else None,
                'purchase_price': (tpl.boxhero_purchase_price if tpl else None),
                'margin_rate': (tpl.ss_margin_rate if tpl else None),
                'ss_fee_rate': (tpl.ss_fee_rate if tpl else None),
                'cp_fee_rate': (tpl.coupang_fee_rate if tpl else None),
                'ss_delivery_fee': (tpl.ss_delivery_fee if tpl else None),
                'cp_delivery_fee': (tpl.coupang_delivery_fee if tpl else None),
                'rounding_unit': (tpl.rounding_unit if tpl else None),
            } if tpl else None,
        )
    finally:
        s.close()


@bp.get('/bundles/<code>/option-matrix')
def get_option_matrix(code: str):
    """라우트 래퍼 — 데이터는 _option_matrix_data(단일 진실 원천), 여기선 응답 직렬화만."""
    d = _option_matrix_data(code)
    if not d.get('ok'):
        return _err(d.get('error', '오류'), d.get('status', 400))
    return _ok(**{k: v for k, v in d.items() if k != 'ok'})


# ════════════════════════════════════════════
#  POST /api/options/sources/bulk
# ════════════════════════════════════════════
#  URL 저장 후 자동 크롤 헬퍼 (대표 계정 프로필로)
# ════════════════════════════════════════════
def _auto_crawl_after_url_save(session, sku: str, src_id: int) -> dict:
    """URL 저장 직후 자동 크롤 — 대표 계정 있으면 Playwright + 로그인 세션 사용.

    best-effort: 실패해도 예외 안 던짐 (URL 저장은 이미 완료됨).
    Returns: {ok, crawler_used, login_used, crawled_price, crawled_stock, error?}
    """
    try:
        link = (session.query(OptionSourceUrl)
                .filter_by(canonical_sku=sku, source_id=src_id)
                .first())
        if not link or not link.product_url:
            return {'ok': False, 'error': 'URL 없음 (저장 직후 조회 실패)'}
        site = _detect_site_from_url(link.product_url)
        if not site:
            return {'ok': False, 'error': '크롤러 미지원 사이트',
                    'site': None, 'crawler_used': None, 'login_used': False}

        # 대표 계정 프로필 + 크롤러 선택
        profile_dir = _get_default_crawl_profile(session, site)
        login_used = False
        crawler_used = 'requests'
        crawler_for_site = None

        from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
        from lemouton.sourcing.crawlers.musinsa import MusinsaCrawler
        from lemouton.sourcing.crawlers.ssf import SsfCrawler
        from lemouton.sourcing.crawlers.lotteon import LotteCrawler
        from lemouton.sourcing.crawlers.ss_lemouton import SsLemoutonCrawler

        if profile_dir and site == 'musinsa':
            try:
                from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
                crawler_for_site = MusinsaPlaywrightCrawler(profile_dir=profile_dir)
                login_used = True
                crawler_used = 'playwright'
            except (ImportError, TypeError):
                crawler_for_site = MusinsaCrawler()
        elif profile_dir and site == 'lemouton':
            try:
                from lemouton.sourcing.crawlers.lemouton_playwright import PlaywrightLemoutonCrawler
                crawler_for_site = PlaywrightLemoutonCrawler(profile_dir=profile_dir)
                login_used = True
                crawler_used = 'playwright'
            except (ImportError, TypeError):
                crawler_for_site = LemoutonCrawler()

        crawlers = {
            'lemouton': crawler_for_site if site == 'lemouton' and crawler_for_site else LemoutonCrawler(),
            'musinsa': crawler_for_site if site == 'musinsa' and crawler_for_site else MusinsaCrawler(),
            'ssf': SsfCrawler(),
            'lotteon': LotteCrawler(),
            'ss_lemouton': SsLemoutonCrawler(),
        }

        from lemouton.sources.service import upsert_source_product, fetch_one_source
        sp = upsert_source_product(session, site=site, url=link.product_url)
        session.flush()
        result = fetch_one_source(session, source_product_id=sp.id, crawlers=crawlers)
        sp2 = session.get(SourceProduct, sp.id)
        return {
            'ok': result['status'] == 'ok',
            'status': result['status'],
            'site': site,
            'crawler_used': crawler_used,
            'login_used': login_used,
            'crawled_price': sp2.last_price if sp2 else None,
            'crawled_stock': sp2.last_stock if sp2 else None,
            'error': result.get('error'),
        }
    except Exception as e:
        return {'ok': False, 'error': f'자동 크롤 예외: {e}',
                'crawler_used': None, 'login_used': False}


# ════════════════════════════════════════════
@bp.post('/options/sources/bulk')
def bulk_set_source_urls():
    """선택 옵션들에 소싱처 URL 일괄 추가·수정.

    Body: {skus: [...], source_id: int, product_url: str, auto_crawl?: bool=True}
    """
    data = request.get_json(silent=True) or {}
    skus = data.get('skus') or []
    src_id = data.get('source_id')
    url = (data.get('product_url') or '').strip()
    auto_crawl = bool(data.get('auto_crawl', True))  # 기본 True
    if not skus or not isinstance(skus, list):
        return _err('skus 리스트가 비었어요.')
    if not src_id:
        return _err('source_id 필요.')
    if not url:
        return _err('product_url 필요.')
    s = SessionLocal()
    try:
        src = s.query(SourceRegistry).filter_by(id=src_id).first()
        if not src:
            return _err('소싱처를 찾을 수 없어요.', 404)
        upserted = 0
        for sku in skus:
            existing = s.query(OptionSourceUrl).filter_by(
                canonical_sku=sku, source_id=src_id).first()
            if existing:
                existing.product_url = url
            else:
                s.add(OptionSourceUrl(canonical_sku=sku, source_id=src_id,
                                       product_url=url))
            upserted += 1
        s.commit()

        # ★ 자동 크롤 (대표 계정 프로필 사용 — best effort)
        crawl_results = []
        if auto_crawl:
            for sku in skus:
                cr = _auto_crawl_after_url_save(s, sku, src_id)
                crawl_results.append({'sku': sku, **cr})
            s.commit()

        return _ok(upserted=upserted, source_name=src.name,
                   auto_crawl=auto_crawl,
                   crawl_results=crawl_results,
                   crawl_summary={
                       'attempted': len(crawl_results),
                       'ok': sum(1 for r in crawl_results if r.get('ok')),
                       'login_used': sum(1 for r in crawl_results if r.get('login_used')),
                   } if auto_crawl else None)
    finally:
        s.close()


# ════════════════════════════════════════════
#  POST /api/options/<sku>/source-url
# ════════════════════════════════════════════
@bp.post('/options/<sku>/source-url')
def set_single_source_url(sku: str):
    """단일 옵션 × 단일 소싱처 URL 인라인 수정 (단일 모드).

    Body: {source_id: int, product_url: str, auto_crawl?: bool=True}
    """
    data = request.get_json(silent=True) or {}
    src_id = data.get('source_id')
    url = (data.get('product_url') or '').strip()
    auto_crawl = bool(data.get('auto_crawl', True))  # 기본 True
    if not src_id:
        return _err('source_id 필요.')
    s = SessionLocal()
    try:
        existing = s.query(OptionSourceUrl).filter_by(
            canonical_sku=sku, source_id=src_id).first()
        if not url:
            # 빈 URL = 삭제
            if existing:
                s.delete(existing)
                s.commit()
                return _ok(deleted=True)
            return _ok(noop=True)
        if existing:
            existing.product_url = url
        else:
            s.add(OptionSourceUrl(canonical_sku=sku, source_id=src_id,
                                   product_url=url))
        s.commit()

        # ★ 자동 크롤 (대표 계정 프로필 사용 — best effort)
        crawl_result = None
        if auto_crawl:
            crawl_result = _auto_crawl_after_url_save(s, sku, src_id)
            s.commit()

        return _ok(saved=True, auto_crawl=auto_crawl, crawl=crawl_result)
    finally:
        s.close()


# ════════════════════════════════════════════
#  DELETE /api/options/<sku>/sources/<src_id>
# ════════════════════════════════════════════
@bp.delete('/options/<sku>/sources/<int:src_id>')
def delete_source_link(sku: str, src_id: int):
    s = SessionLocal()
    try:
        link = s.query(OptionSourceUrl).filter_by(
            canonical_sku=sku, source_id=src_id).first()
        if not link:
            return _err('매핑이 없어요.', 404)
        s.delete(link)
        s.commit()
        return _ok(deleted=True)
    finally:
        s.close()


# ════════════════════════════════════════════
#  [Phase 3] 옵션 소싱처 다중 URL — 한 소싱처에 URL 여러 개
#  GET/POST /api/options/<sku>/source-urls · DELETE .../source-urls/<url_id>
# ════════════════════════════════════════════
@bp.get('/options/<sku>/source-urls')
def list_option_source_urls(sku: str):
    """옵션의 모든 소싱처 URL + 소싱처 사전 (모달용)."""
    from lemouton.sourcing.option_source_service import list_source_urls
    s = SessionLocal()
    try:
        sources = (s.query(SourceRegistry)
                   .order_by(SourceRegistry.sort_order, SourceRegistry.id).all())
        src_name = {x.id: x.name for x in sources}
        urls = list_source_urls(s, sku)
        return _ok(
            urls=[{'id': u.id, 'source_id': u.source_id,
                   'source_name': src_name.get(u.source_id, '?'),
                   'product_url': u.product_url} for u in urls],
            sources=[{'id': x.id, 'name': x.name} for x in sources],
        )
    finally:
        s.close()


@bp.post('/options/<sku>/source-urls')
def add_option_source_url(sku: str):
    """옵션에 소싱처 URL 추가 — 같은 소싱처 다중 URL 허용 (Phase 3).

    Body: {source_id: int, product_url: str}
    """
    from lemouton.sourcing.option_source_service import add_source_url
    data = request.get_json(silent=True) or {}
    src_id = data.get('source_id')
    url = (data.get('product_url') or '').strip()
    if not src_id:
        return _err('소싱처를 선택하세요.')
    if not url:
        return _err('URL을 입력하세요.')
    s = SessionLocal()
    try:
        if not s.query(Option).filter_by(canonical_sku=sku).first():
            return _err('옵션을 찾을 수 없어요.', 404)
        row = add_source_url(s, sku, int(src_id), url)
        s.commit()
        return _ok(id=row.id)
    except Exception as e:
        s.rollback()
        return _err(str(e), 500)
    finally:
        s.close()


@bp.delete('/options/<sku>/source-urls/<int:url_id>')
def delete_option_source_url(sku: str, url_id: int):
    """옵션 소싱처 URL 1개 삭제 (url_id 기준)."""
    from lemouton.sourcing.option_source_service import delete_source_url
    s = SessionLocal()
    try:
        n = delete_source_url(s, url_id)
        s.commit()
        return _ok(deleted=n)
    finally:
        s.close()


# ════════════════════════════════════════════
#  POST /api/options/price-config/bulk
# ════════════════════════════════════════════
@bp.post('/options/price-config/bulk')
def bulk_set_price_config():
    """선택 옵션들의 가격 설정 일괄.

    Body: {
      skus: [...],
      auto_enabled: true|false,            # 옵션
      margin_rate: 0.10,                    # auto_enabled=True 시
      ss_fee_rate: 0.08,
      cp_fee_rate: 0.14,
      manual_ss_price: 120000,              # auto_enabled=False 시
      manual_cp_price: 135000,
      manual_stock: 5,
    }
    필드 누락 = 그 필드 변경 안 함.
    """
    data = request.get_json(silent=True) or {}
    skus = data.get('skus') or []
    if not skus:
        return _err('skus 비었어요.')
    s = SessionLocal()
    try:
        updated = 0
        for sku in skus:
            cfg = s.query(OptionPriceConfig).filter_by(canonical_sku=sku).first()
            if not cfg:
                cfg = OptionPriceConfig(canonical_sku=sku)
                s.add(cfg)
            for f in ('auto_enabled', 'margin_rate', 'ss_fee_rate', 'cp_fee_rate',
                      'manual_ss_price', 'manual_cp_price', 'manual_stock'):
                if f in data:
                    setattr(cfg, f, data[f])
            updated += 1
        s.commit()
        return _ok(updated=updated)
    finally:
        s.close()


# ════════════════════════════════════════════
#  GET /api/options/<sku>/price-calc
# ════════════════════════════════════════════
@bp.get('/options/<sku>/price-calc')
def get_price_breakdown(sku: str):
    """단일 옵션 자동계산 산출과정 (마진/수수료/배송비 + 단계별 금액)."""
    s = SessionLocal()
    try:
        opt = s.query(Option).filter_by(canonical_sku=sku).first()
        if not opt:
            return _err('옵션을 찾을 수 없어요.', 404)
        m = s.query(Model).filter_by(model_code=opt.model_code).first()
        cfg = s.query(OptionPriceConfig).filter_by(canonical_sku=sku).first()
        tpl = (s.query(PriceTemplate).filter_by(id=m.price_template_id).first()
               if m and m.price_template_id else None)
        margin = (cfg.margin_rate if cfg and cfg.margin_rate is not None
                  else (tpl.ss_margin_rate if tpl else 0.10))
        ss_fee = (cfg.ss_fee_rate if cfg and cfg.ss_fee_rate is not None
                  else (tpl.ss_fee_rate if tpl else 0.06))
        cp_fee = (cfg.cp_fee_rate if cfg and cfg.cp_fee_rate is not None
                  else (tpl.coupang_fee_rate if tpl else 0.1155))
        ss_ship = (tpl.ss_delivery_fee if tpl else 0) or 0
        cp_ship = (tpl.coupang_delivery_fee if tpl else 0) or 0
        rounding = (tpl.rounding_unit if tpl else 100) or 100
        # 원가 = 르무통 소싱처 크롤가 우선 (2026-05-09 fix)
        try:
            from lemouton.sourcing.models_v2 import OptionSourceCache
            _src_rows = (s.query(OptionSourceCache)
                         .filter_by(canonical_sku=sku)
                         .all())
            _lem = next((r for r in _src_rows
                         if r.source_id == 'lemouton' and r.crawled_price), None)
            _any = next((r for r in _src_rows if r.crawled_price), None) if not _lem else None
            _src_purchase = (_lem or _any).crawled_price if (_lem or _any) else None
        except Exception:
            _src_purchase = None
        purchase = (_src_purchase
                    or (tpl.boxhero_purchase_price if tpl else None)
                    or 95000)
        ss_price, ss_break = calc_auto_price(purchase, margin, ss_fee,
                                              ss_ship, rounding)
        cp_price, cp_break = calc_auto_price(purchase, margin, cp_fee,
                                              cp_ship, rounding)
        return _ok(
            sku=sku, color=opt.color_code, size=opt.size_code,
            auto_enabled=cfg.auto_enabled if cfg else True,
            ss=ss_break, cp=cp_break,
            ss_final=ss_price, cp_final=cp_price,
            template_name=(tpl.name if tpl else None),
        )
    finally:
        s.close()


# ════════════════════════════════════════════
#  POST /api/options/<sku>/sources/<src_id>/refetch
#  → OptionSourceUrl URL 을 크롤 → SourceProduct 자동 등록 + last_price 갱신
# ════════════════════════════════════════════
def _detect_site_from_url(url: str) -> str | None:
    """URL → site key 매핑 (크롤러 dict 키와 일치)."""
    if not url: return None
    u = url.lower()
    if 'lemouton.co.kr' in u: return 'lemouton'
    if 'musinsa.com' in u: return 'musinsa'
    if 'ssfshop.com' in u or 'ssg.com' in u: return 'ssf'
    if 'lotteon.com' in u or 'lotteimall.com' in u: return 'lotteon'
    if 'smartstore.naver.com' in u or 'shopping.naver.com' in u or 'brand.naver.com' in u: return 'ss_lemouton'
    return None


def _get_default_crawl_profile(session, site_key: str, ensure_login: bool = True) -> str | None:
    """해당 소싱처의 대표 크롤 계정 → ProfileStore 경로 반환.

    Args:
        ensure_login: True 면 만료 검사 + 자동 재로그인 (송장전송기 무제한 로그인 패턴)
                       False 면 그냥 경로만 (legacy)

    Returns: profile_dir 절대경로 문자열, 또는 None (대표 계정 미지정 / 재로그인 실패)
    """
    from lemouton.sourcing.models_v2 import SourcingAccount
    from lemouton.auth.profile_store import default_store as profile_default_store
    from lemouton.auth.profile_store import _safe_key
    from lemouton.auth.sourcing_credentials import default_store as creds_default_store

    acc = (session.query(SourcingAccount)
           .filter_by(source=site_key, is_default_for_crawl=True, is_active=True)
           .first())
    if not acc:
        return None
    # 실 ID 기반 프로필 디렉터리 (cookie checker 와 동일 패턴)
    creds = creds_default_store().load_all().get(site_key, {}).get(acc.account_key, {})
    actual_id = creds.get("id", acc.account_key)
    profile_store = profile_default_store()
    prof_path = profile_store.profiles_root / f"{_safe_key(site_key)}_{_safe_key(actual_id)}"

    if not prof_path.exists():
        # 프로필 자체가 없음 → 마법사 1회 실행 필요 시 ensure_login 으로 신규 생성
        if ensure_login:
            return _ensure_default_crawl_login(site_key, acc.account_key, actual_id, force=True)
        return None

    # ★ 송장전송기 무제한 로그인 패턴 — 만료 사전 검사 + 자동 재로그인
    if ensure_login:
        from lemouton.auth.cookie_checker import is_likely_logged_in
        if not is_likely_logged_in(prof_path, site_key):
            logging.getLogger(__name__).info(
                "[%s] 대표 계정 %s 쿠키 만료/없음 → 자동 재로그인 시도", site_key, acc.account_key
            )
            relogin_path = _ensure_default_crawl_login(site_key, acc.account_key, actual_id, force=True)
            return relogin_path or str(prof_path)

    return str(prof_path)


def _ensure_default_crawl_login(site_key: str, account_key: str, actual_id: str,
                                 force: bool = False) -> str | None:
    """대표 크롤 계정 무인 재로그인 — 송장전송기 ``ensure_logged_in`` 의 본 시스템 적용.

    저장된 PW 로 BackgroundLogin (heamless 도 가능하지만 봇 탐지 회피 위해 헤드 띄움).
    성공 시 프로필 경로 반환, 실패 시 None.

    Args:
        site_key: 'musinsa' | 'lemouton' | 'ssf' | 'lotteon'
        account_key: SourcingAccount.account_key (예: '영빈')
        actual_id: 실제 로그인 ID
        force: True 면 사전 검증 우회 (만료 확정 시)
    """
    from lemouton.auth.sourcing_credentials import default_store as creds_default_store
    from lemouton.auth.profile_store import default_store as profile_default_store
    from lemouton.auth.profile_store import _safe_key

    creds = creds_default_store().load_all().get(site_key, {}).get(account_key, {})
    pw = creds.get("pw", "")
    if not pw:
        logging.getLogger(__name__).warning(
            "[%s] %s 비밀번호 없음 → 자동 재로그인 불가", site_key, account_key
        )
        return None

    # 사이트별 스크래퍼 매핑 — 송장전송기 sourcing_scrapers 의 sync 포팅
    scraper_cls = None
    if site_key == "musinsa":
        from lemouton.auth.scrapers.musinsa import MusinsaScraper
        scraper_cls = MusinsaScraper
    elif site_key == "ssf":
        from lemouton.auth.scrapers.ssf import SSFShopScraper
        scraper_cls = SSFShopScraper
    elif site_key == "lotteon":
        from lemouton.auth.scrapers.lotteon import LotteonScraper
        scraper_cls = LotteonScraper
    elif site_key == "lotteimall":
        from lemouton.auth.scrapers.lotteimall import LotteimallScraper
        scraper_cls = LotteimallScraper
    # TODO: lemouton, ss_lemouton 스크래퍼는 신규 작성 필요
    if scraper_cls is None:
        logging.getLogger(__name__).warning(
            "[%s] 자동 재로그인 미지원 (스크래퍼 클래스 매핑 없음)", site_key
        )
        return None

    sc = scraper_cls()
    try:
        ok = sc.ensure_logged_in(
            account_id=actual_id,
            account_pw=pw,
            login_method="direct",
            max_retry=2,
            skip_if_logged_in=not force,
        )
        if not ok:
            return None
        ps = profile_default_store()
        prof_path = ps.profiles_root / f"{_safe_key(site_key)}_{_safe_key(actual_id)}"
        return str(prof_path) if prof_path.exists() else None
    finally:
        try:
            sc.close()
        except Exception:
            pass


@bp.post('/options/<sku>/sources/<int:src_id>/refetch')
def refetch_option_source(sku: str, src_id: int):
    """옵션의 특정 소싱처 URL 을 즉시 크롤 (SourceProduct 자동 등록 포함).

    대표 크롤 계정이 지정되면 → 해당 계정 프로필로 로그인 상태 크롤 (회원가).
    """
    from lemouton.sources.service import upsert_source_product, fetch_one_source
    from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
    from lemouton.sourcing.crawlers.musinsa import MusinsaCrawler
    from lemouton.sourcing.crawlers.ssf import SsfCrawler
    from lemouton.sourcing.crawlers.lotteon import LotteCrawler
    from lemouton.sourcing.crawlers.ss_lemouton import SsLemoutonCrawler

    s = SessionLocal()
    try:
        link = (s.query(OptionSourceUrl)
                .filter_by(canonical_sku=sku, source_id=src_id)
                .first())
        if not link or not link.product_url:
            return _err('소싱처 URL 매핑을 찾을 수 없어요.', 404)
        site = _detect_site_from_url(link.product_url)
        if not site:
            return _err(f'크롤러 미지원 사이트: {link.product_url[:60]}', 400)

        # ★ 대표 크롤 계정의 ProfileStore 경로 조회 (없으면 None — 비로그인 모드)
        profile_dir = _get_default_crawl_profile(s, site)
        login_used = False
        crawler_used = 'requests'  # 'requests' | 'playwright'

        # 크롤러 선택: profile_dir 있으면 Playwright 변종 시도 (회원가 가져옴)
        crawler_for_site = None
        if profile_dir and site == 'musinsa':
            try:
                from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
                crawler_for_site = MusinsaPlaywrightCrawler(profile_dir=profile_dir)
                login_used = True
                crawler_used = 'playwright'
            except (ImportError, TypeError):
                crawler_for_site = MusinsaCrawler()
        elif profile_dir and site == 'lemouton':
            try:
                from lemouton.sourcing.crawlers.lemouton_playwright import PlaywrightLemoutonCrawler
                crawler_for_site = PlaywrightLemoutonCrawler(profile_dir=profile_dir)
                login_used = True
                crawler_used = 'playwright'
            except (ImportError, TypeError):
                crawler_for_site = LemoutonCrawler()

        # 폴백: 기본 (requests 기반) 크롤러
        crawlers = {
            'lemouton': crawler_for_site if site == 'lemouton' and crawler_for_site else LemoutonCrawler(),
            'musinsa': crawler_for_site if site == 'musinsa' and crawler_for_site else MusinsaCrawler(),
            'ssf': SsfCrawler(),       # Phase C: Playwright 변종 추후
            'lotteon': LotteCrawler(),  # Phase C: Playwright 변종 추후
            'ss_lemouton': SsLemoutonCrawler(),  # Phase C
        }

        sp = upsert_source_product(s, site=site, url=link.product_url)
        s.flush()
        result = fetch_one_source(s, source_product_id=sp.id, crawlers=crawlers)

        # ★ 송장전송기 무제한 로그인 패턴 — LoginExpiredError 감지 + 자동 재로그인 + 1회 재시도
        err_msg = (result.get('error') or '')
        if profile_dir and ('세션 만료 감지' in err_msg or 'LoginExpiredError' in err_msg):
            logging.getLogger(__name__).info(
                "[%s] LoginExpiredError 포착 → 자동 재로그인 + 재시도", site
            )
            # 대표 계정 정보로 강제 재로그인
            from lemouton.sourcing.models_v2 import SourcingAccount
            from lemouton.auth.sourcing_credentials import default_store as creds_default_store
            acc = (s.query(SourcingAccount)
                   .filter_by(source=site, is_default_for_crawl=True, is_active=True)
                   .first())
            if acc:
                creds = creds_default_store().load_all().get(site, {}).get(acc.account_key, {})
                actual_id = creds.get("id", acc.account_key)
                new_profile_dir = _ensure_default_crawl_login(site, acc.account_key, actual_id, force=True)
                if new_profile_dir:
                    # 크롤러를 새 profile_dir 로 재구성 + 재시도
                    if site == 'musinsa':
                        from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
                        crawlers['musinsa'] = MusinsaPlaywrightCrawler(profile_dir=new_profile_dir)
                    elif site == 'lemouton':
                        from lemouton.sourcing.crawlers.lemouton_playwright import PlaywrightLemoutonCrawler
                        crawlers['lemouton'] = PlaywrightLemoutonCrawler(profile_dir=new_profile_dir)
                    result = fetch_one_source(s, source_product_id=sp.id, crawlers=crawlers)
                    profile_dir = new_profile_dir
        s.commit()

        # 최신 SP 다시 읽기 (last_price 가 갱신됨)
        sp2 = s.get(SourceProduct, sp.id)
        return _ok(
            status=result['status'],
            error=result.get('error'),
            source_product_id=sp.id,
            crawled_price=sp2.last_price if sp2 else None,
            crawled_stock=sp2.last_stock if sp2 else None,
            last_status=sp2.last_status if sp2 else None,
            login_used=login_used,           # ★ 로그인 세션으로 크롤했는지
            crawler_used=crawler_used,       # ★ 'requests' | 'playwright'
            profile_dir=profile_dir,         # ★ 사용된 프로필 경로 (디버깅)
        )
    except Exception as e:
        s.rollback()
        return _err(f'크롤 오류: {e}', 500)
    finally:
        s.close()


# ════════════════════════════════════════════
#  GET /api/bundles/<code>/crawl-status
#  → 상단 "크롤링 실행" 버튼의 백그라운드 완료 폴링용. 현재 last_crawled_at_iso 반환.
#    프론트는 초기값과 다른 값이 돌아오면 백그라운드 완료로 판단 → setLastCrawled 호출.
# ════════════════════════════════════════════
@bp.get('/bundles/<code>/crawl-status')
def get_crawl_status(code: str):
    """현재 Model.last_crawled_at 반환 — 백그라운드 크롤 완료 폴링용."""
    from datetime import timezone
    from lemouton.sourcing.models import BundleGroup
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            bg = s.query(BundleGroup).filter_by(group_code=code).first()
            if bg and bg.models:
                m = bg.models[0]
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        iso = ''
        if m.last_crawled_at is not None:
            dt = m.last_crawled_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            iso = dt.isoformat()
        return _ok(last_crawled_at=iso)
    finally:
        s.close()


# ════════════════════════════════════════════
#  POST /api/bundles/<code>/touch-crawled
#  → 매트릭스 측 per-source "전체 크롤" / "선택 크롤" 묶음 완료 시 호출.
#    Model.last_crawled_at 을 utcnow() 로 bump → 상단 "마지막 크롤링 ㅇㅇ전" 표시 즉시 반영.
#    sub-operation 이라 BundleRun 이력은 만들지 않고 timestamp 만 갱신.
#    그룹 모음전이면 그룹 내 모든 모델을 함께 bump (그룹 단위 일관성).
# ════════════════════════════════════════════
@bp.post('/bundles/<code>/touch-crawled')
def touch_bundle_crawled(code: str):
    """매트릭스 per-source 크롤 묶음 완료 시 호출 → Model.last_crawled_at bump."""
    from datetime import datetime, timezone
    from lemouton.sourcing.models import BundleGroup
    s = SessionLocal()
    try:
        # 1순위 model_code, 2순위 group_code
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            bg = s.query(BundleGroup).filter_by(group_code=code).first()
            if bg and bg.models:
                m = bg.models[0]
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        now = datetime.now(timezone.utc)
        # 그룹 내 모든 모델 동기 갱신
        targets = [m]
        if m.bundle_group_id:
            bg = s.query(BundleGroup).filter_by(id=m.bundle_group_id).first()
            if bg:
                targets = list(bg.models)
        for mm in targets:
            mm.last_crawled_at = now
        s.commit()
        return _ok(last_crawled_at=now.isoformat(), updated_count=len(targets))
    finally:
        s.close()


# ════════════════════════════════════════════
#  POST /api/sources/musinsa/relogin-and-refetch
#  → Phase 8.8.2 (2026-05-17) — 무신사 대표 계정 재로그인 + 전체 옵션 재크롤.
#    대시보드 ⚠ 카드 [🔑 재로그인 + 전체 재크롤] 버튼에서 호출.
#    1) 대표 계정 강제 재로그인 (저장된 PW 로 background_login)
#    2) musinsa SourceProduct 모두 fetch (새 profile_dir, MusinsaPlaywrightCrawler)
#    3) DB dyn 갱신 (member_price/is_member_price/login_marker_present)
#    4) 응답: {ok, refetched_count, member_price_count, errors}
# ════════════════════════════════════════════
@bp.post('/sources/musinsa/relogin-and-refetch')
def relogin_and_refetch_musinsa():
    """무신사 대표 계정 재로그인 + 전체 옵션 재크롤 (Phase 8.8.2)."""
    import json as _json
    import time as _time
    from lemouton.sourcing.models_v2 import SourcingAccount
    from lemouton.auth.sourcing_credentials import default_store as creds_default_store
    from lemouton.sources.models import SourceProduct, SourceOption
    s = SessionLocal()
    try:
        # 1) 대표 계정 조회
        acc = (s.query(SourcingAccount)
               .filter_by(source='musinsa', is_default_for_crawl=True, is_active=True)
               .first())
        if not acc:
            return _err('무신사 대표 크롤 계정 미지정', 400)
        creds = creds_default_store().load_all().get('musinsa', {}).get(acc.account_key, {})
        actual_id = creds.get('id', acc.account_key)

        # 2) 강제 재로그인 (force=True → 사전 검증 우회)
        t0 = _time.time()
        new_profile_dir = _ensure_default_crawl_login('musinsa', acc.account_key, actual_id, force=True)
        relogin_dt = _time.time() - t0
        if not new_profile_dir:
            return _err('재로그인 실패 — 자격증명 확인 또는 수동 로그인 필요', 500)

        # 3) musinsa SourceProduct 모두 재크롤 (Playwright + 새 profile_dir)
        from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
        crawler = MusinsaPlaywrightCrawler(profile_dir=new_profile_dir, headless=True)
        sps = s.query(SourceProduct).filter_by(site='musinsa', deleted_at=None).all()
        refetched = 0
        member_price_count = 0
        errors = []
        for sp in sps:
            try:
                t1 = _time.time()
                cr = crawler.fetch(sp.url)
                if not cr.options:
                    errors.append(f'sp_id={sp.id}: 옵션 0건')
                    continue
                opt = cr.options[0]
                _mp = opt.get('member_price')
                _is_member = bool(opt.get('is_member_price'))
                _login = bool(opt.get('login_marker_present'))
                _sale = opt.get('sale_price')
                # DB 직접 UPDATE (FK ORM 회피 — 빠르고 안전)
                import sqlite3
                con = sqlite3.connect('data/lemouton.db')
                c = con.cursor()
                if _sale:
                    c.execute('UPDATE source_products SET last_price=? WHERE id=?', (_sale, sp.id))
                # 모든 옵션의 dyn 에 신규 키 박기
                c.execute('SELECT id, dynamic_benefits_json FROM source_options WHERE source_product_id=? AND deleted_at IS NULL', (sp.id,))
                for so_id, dyn_str in c.fetchall():
                    try:
                        dyn = _json.loads(dyn_str or '{}') if dyn_str else {}
                    except Exception:
                        dyn = {}
                    dyn['member_price'] = _mp
                    dyn['is_member_price'] = _is_member
                    dyn['login_marker_present'] = _login
                    c.execute('UPDATE source_options SET dynamic_benefits_json=? WHERE id=?',
                              (_json.dumps(dyn, ensure_ascii=False), so_id))
                con.commit()
                con.close()
                refetched += 1
                if _is_member and _mp:
                    member_price_count += 1
            except Exception as e:
                errors.append(f'sp_id={sp.id}: {str(e)[:100]}')
        return _ok(
            refetched_count=refetched,
            member_price_count=member_price_count,
            errors=errors,
            relogin_seconds=round(relogin_dt, 1),
            account=f"{acc.account_key}/{actual_id}",
        )
    finally:
        s.close()


# ════════════════════════════════════════════
#  POST /api/options/<sku>/sources/<src_id>/open-with-profile
#  → 대표 크롤 계정 프로필로 Chrome 새 창 열기 (로그인 상태 + CMD 창 안 뜸)
# ════════════════════════════════════════════
@bp.post('/options/<sku>/sources/<int:src_id>/open-with-profile')
def open_url_with_profile(sku: str, src_id: int):
    """대표 크롤 계정 프로필로 새 Chrome 창 띄워 URL 열기.

    송장전송기 패턴 (marketplace_browser.spawn_native_chrome 동등):
      - chrome.exe 직접 실행 (--user-data-dir=<profile>) → 콘솔(CMD) 창 X
      - profile_dir 안의 쿠키/세션 그대로 사용 → 로그인 상태로 진입
      - Python+Playwright subprocess 우회 — CMD 창·실행 지연 없음

    동작:
      1. OptionSourceUrl 조회 → URL + site 감지
      2. 그 site 의 대표 크롤 계정 프로필 조회
      3. 없으면 → fallback URL 만 반환 (클라가 일반 새 탭으로 폴백)
      4. 있으면 → chrome.exe + --user-data-dir 로 새 창 detach 실행
    """
    import subprocess
    import os

    s = SessionLocal()
    try:
        link = (s.query(OptionSourceUrl)
                .filter_by(canonical_sku=sku, source_id=src_id)
                .first())
        if not link or not link.product_url:
            return _err('소싱처 URL 없음', 404)
        url = link.product_url
        site = _detect_site_from_url(url)
        if not site:
            return _ok(opened=False, fallback_url=url, reason='크롤러 미지원 사이트')

        profile_dir = _get_default_crawl_profile(s, site)
        if not profile_dir:
            return _ok(opened=False, fallback_url=url, reason=f'{site} 대표 크롤 계정 미지정')

        # Chrome 절대경로 (Edge/Brave/Aurora 가로채기 방지)
        chrome_candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        chrome_exe = next((p for p in chrome_candidates if os.path.exists(p)), None)
        if not chrome_exe:
            return _ok(opened=False, fallback_url=url,
                       reason='Chrome 미설치 — 일반 브라우저로 fallback')

        # detached subprocess (브라우저 창 닫을 때까지 살아있음, Flask 응답 즉시 반환)
        # ★ chrome.exe 는 GUI 앱 → CMD 창 안 뜸 (송장전송기 spawn_native_chrome 패턴)
        creationflags = 0
        if os.name == 'nt':
            creationflags = (subprocess.DETACHED_PROCESS
                             | subprocess.CREATE_NEW_PROCESS_GROUP
                             | subprocess.CREATE_NO_WINDOW)

        cmd = [
            chrome_exe,
            f'--user-data-dir={profile_dir}',
            '--no-first-run',
            '--no-default-browser-check',
            # 봇 탐지 우회 + Windows Hello 프롬프트 차단
            '--disable-blink-features=AutomationControlled',
            '--password-store=basic',
            '--disable-features='
            'BiometricAuthBeforeFilling,'
            'BiometricAuthIdentityCheck,'
            'WindowsHelloAuthForChrome,'
            'PasswordManagerOnboarding',
            url,
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
        except Exception as e:
            return _ok(opened=False, fallback_url=url, reason=f'chrome 실행 실패: {e}')

        return _ok(opened=True, site=site, profile_dir=profile_dir, url=url, pid=proc.pid)
    finally:
        s.close()


# ════════════════════════════════════════════════════════════
#  POST /api/options/<sku>/purchase  (개별 옵션 사입 설정)
#  POST /api/options/purchase/bulk   (일괄 사입 설정 — C9 panel)
#  M4 + P3 + C9 (2026-05-08 r2)
# ════════════════════════════════════════════════════════════

def _calc_purchase_price(opt: Option) -> int | None:
    """사입 활성 + 사입재고≥1 일 때 판매가 계산.

    mode='manual' → opt.purchase_manual_price (직접)
    mode='rate'   → avg_cost × (1 + value/10000)  (value 는 *100, 즉 1500 = 15%)
    mode='amount' → avg_cost + value
    None 반환 시 = 사입 사용 불가 (소싱 fallback)
    """
    if not opt.use_purchase_inventory:
        return None
    if (opt.boxhero_stock_total or 0) < 1:
        return None
    avg = opt.boxhero_avg_purchase_price or 0
    mode = opt.option_boxhero_margin_mode or 'rate'
    val = opt.option_boxhero_margin_value or 0
    if mode == 'manual':
        return opt.purchase_manual_price or None
    if mode == 'rate':
        return int(avg * (1 + val / 10000.0))
    if mode == 'amount':
        return int(avg + val)
    return None


def _resolve_priority(opt: Option) -> str:
    """우선순위 결정 — 2026-05-13 v4:
      재고 = Option.boxhero_stock_total (Excel) + InventoryTx (InventoryProduct 등록 옵션만)
      · 합산 ≥1 → 'purchase' (override 무관)
      · 합산 0:
        - priority='purchase' override → 'purchase'
        - priority='auto'/'source' → 'source'
    """
    pri = (opt.purchase_priority or 'auto').lower()
    _box = opt.boxhero_stock_total or 0
    _inv = 0
    try:
        from shared.db import SessionLocal as _SL
        from lemouton.inventory.models import InventoryTx, InventoryProduct
        _s = _SL()
        try:
            ip = _s.query(InventoryProduct).filter_by(canonical_sku=opt.canonical_sku).first()
            if ip is not None:
                txs = (_s.query(InventoryTx.tx_type, InventoryTx.qty)
                       .filter(InventoryTx.option_canonical_sku == opt.canonical_sku)
                       .filter(InventoryTx.status == 'completed')
                       .order_by(InventoryTx.created_at)
                       .all())
                for ttype, qty in txs:
                    qv = qty or 0
                    if ttype == 'in': _inv += qv
                    elif ttype == 'out': _inv -= qv
                    elif ttype == 'adjust': _inv = qv
        finally:
            _s.close()
    except Exception:
        pass
    if (_box + _inv) >= 1:
        return 'purchase'
    return 'purchase' if pri == 'purchase' else 'source'


@bp.route('/options/<sku>/purchase', methods=['POST'])
def update_option_purchase(sku: str):
    """단일 옵션 사입 설정 저장.

    Request body (JSON):
      {
        "use_purchase_inventory": bool,
        "purchase_priority": "auto"|"source"|"purchase",
        "boxhero_avg_purchase_price": int,
        "option_boxhero_margin_mode": "rate"|"amount"|"manual",
        "option_boxhero_margin_value": int (rate=*100, amount=원),
        "purchase_manual_price": int  (mode='manual' 시)
      }
    """
    data = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        opt = s.query(Option).filter_by(canonical_sku=sku).first()
        if opt is None:
            return jsonify({'ok': False, 'error': f'option {sku} not found'}), 404

        ALLOWED = {
            'use_purchase_inventory', 'purchase_priority',
            'boxhero_avg_purchase_price', 'option_boxhero_margin_mode',
            'option_boxhero_margin_value', 'purchase_manual_price',
            # [2026-05-25 M] 마켓별 지정가 활성화 + 가격 (소싱·사입 × 스마트·쿠팡)
            'src_fixed_ss_active', 'src_fixed_cp_active',
            'src_fixed_ss_price', 'src_fixed_cp_price',
            'pur_fixed_ss_active', 'pur_fixed_cp_active',
            'pur_fixed_ss_price', 'pur_fixed_cp_price',
        }
        for k, v in data.items():
            if k in ALLOWED:
                setattr(opt, k, v)
        s.commit()

        return jsonify({
            'ok': True,
            'sku': sku,
            'final_price': _calc_purchase_price(opt),
            'priority': _resolve_priority(opt),
            'stock': opt.boxhero_stock_total or 0,
        })
    finally:
        s.close()


@bp.route('/options/purchase/bulk', methods=['POST'])
def update_options_purchase_bulk():
    """C9 일괄 panel — 선택 옵션들에 사입 또는 소싱 일괄.

    Request body (JSON):
      {
        "skus": ["sku1", "sku2", ...],
        "tab": "purchase" | "source",   // 일괄 모드
        // tab=purchase:
        "use_purchase_inventory": true,
        "purchase_priority": "purchase",
        "boxhero_avg_purchase_price": int,
        "option_boxhero_margin_mode": "rate"|"amount"|"manual",
        "option_boxhero_margin_value": int,
        // tab=source:
        "use_purchase_inventory": false,  (또는 priority='source')
        "purchase_priority": "source",
        // 소싱 가격 모드는 별도 endpoint (price-config/bulk) 재사용
      }
    Returns: { applied: int, skipped_bh0: int (사입재고 0 자동 제외) }
    """
    data = request.get_json(silent=True) or {}
    skus = data.get('skus') or []
    tab = (data.get('tab') or 'purchase').lower()
    if not skus:
        return jsonify({'ok': False, 'error': 'skus 빈 배열'}), 400

    s = SessionLocal()
    try:
        opts = s.query(Option).filter(Option.canonical_sku.in_(skus)).all()
        ALLOWED = {
            'use_purchase_inventory', 'purchase_priority',
            'boxhero_avg_purchase_price', 'option_boxhero_margin_mode',
            'option_boxhero_margin_value', 'purchase_manual_price',
            # [2026-05-25 M] 마켓별 지정가 활성화 + 가격 (소싱·사입 × 스마트·쿠팡)
            'src_fixed_ss_active', 'src_fixed_cp_active',
            'src_fixed_ss_price', 'src_fixed_cp_price',
            'pur_fixed_ss_active', 'pur_fixed_cp_active',
            'pur_fixed_ss_price', 'pur_fixed_cp_price',
        }
        applied = 0
        skipped_bh0 = 0
        for opt in opts:
            # 사입 일괄 시 사입재고=0 자동 제외
            if tab == 'purchase' and (opt.boxhero_stock_total or 0) < 1:
                skipped_bh0 += 1
                continue
            for k, v in data.items():
                if k in ALLOWED:
                    setattr(opt, k, v)
            applied += 1
        s.commit()
        return jsonify({
            'ok': True, 'applied': applied,
            'skipped_bh0': skipped_bh0, 'total_selected': len(skus),
        })
    finally:
        s.close()
