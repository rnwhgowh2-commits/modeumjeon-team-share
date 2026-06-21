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
from functools import lru_cache as _lru_cache

# config.SOURCING_AUTH['stock_cap'] 와 동일 — 무신사는 '충분'을 이 값으로 저장(센티넬).
_STOCK_CAP = 10


@_lru_cache(maxsize=16384)
def _stk_digits(x):
    # [perf 2026-06-12] 순수 함수 — 매트릭스 매칭에서 동일 size/color 문자열에 수천 번
    #   호출되므로 메모이즈. 입력은 옵션·SourceOption 의 size/color(유한 집합).
    return ''.join(c for c in str(x or '') if c.isdigit())


@_lru_cache(maxsize=16384)
def _stk_cnorm(x):
    """색상 비교용 정규화 — 공백·괄호·구분자 제거 + 소문자. (순수 함수 메모이즈)"""
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
    subs = []                                     # 부분일치 후보(정확매칭 없을 때만)
    for so in cands:
        st = (so.size_text or '').strip()
        s_size = _stk_digits(st) or _stk_digits(so.color_text)
        if not s_size or s_size != osz:
            continue
        has_color = bool(st) and bool((so.color_text or '').strip())
        if has_color:
            sc = _stk_cnorm(so.color_text)
            if not (oc and sc):
                continue
            if oc == sc:
                return so                         # ★ 정확 매칭 최우선 (즉시 확정)
            if oc in sc or sc in oc:
                subs.append(so)                   # 부분일치 — 일단 보류
            continue                              # 색 불일치 → 계속 탐색
        if size_only is None:
            size_only = so                        # 단일색 URL — 사이즈만으로 매칭
    # 정확 매칭이 없었던 경우: 부분일치는 '모호하지 않을 때만' 채택.
    #   [H1 2026-06-12] 기존엔 첫 부분일치를 즉시 반환 → '그레이'가 '라이트그레이'에
    #   붙는 비결정적 오매칭. 후보가 2개 이상이면 추측 금지(None)가 안전(금전 사고 방지).
    if len(subs) == 1:
        return subs[0]
    if len(subs) > 1:
        return None
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


def _resolve_sourcing_cost(cost_src):
    """소싱 카드 원가 = 크롤 실제가만. 폴백(사입가·하드코딩 95000) 금지.

    [#4 2026-06-13 — feedback_no_fallback_price_on_match_fail]
      소싱 카드는 '크롤된 소싱처에서 산다'는 전제라 원가는 크롤 실제가여야 한다.
      크롤 실패/누락 시 boxhero 사입가(다른 개념) 또는 95000 상수로 메우면 가짜
      판매가가 화면에 떠 수동주문을 유발 → 손실. 없으면 None(소싱 카드 가격없음).

    return: 크롤 원가 int | None
    """
    p = (cost_src or {}).get('crawled_price')
    return p if (p and p > 0) else None


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


def _opt_color_size(o):
    """옵션 dict → (color, size). 확장(color/size)·서버 parse(color_text/size_text) 둘 다 수용."""
    color = o.get('color') if o.get('color') is not None else o.get('color_text')
    size = o.get('size') if o.get('size') is not None else o.get('size_text')
    return color, size


def _ingest_option_stocks(session, source_product_id, options, price=None):
    """확장 options[{color,size,stock}] → SourceOption.current_stock 갱신 (색·사이즈 매칭).

    [2026-06-21] price(상품 균일가) 주면 갱신·생성 옵션의 current_price 도 함께 설정.
      사유: 기존엔 stock 만 설정 → 리셋/prune 후 새로 생긴 옵션은 가격 누락(상품가 bulk
      update 가 autoflush 안 된 신규행을 놓침) → noprice 둔갑(SSF 비-블랙 8색 사고).
      생성/갱신 시점에 가격을 직접 박아 타이밍 의존 제거.

    무신사·롯데온(확장 크롤)은 상품 레벨 stock 하나만 보내던 것을, 사이즈별 실재고
    (0=품절 / N=실수량 / 999=충분, 확장이 센티넬 적용 완료)로 옵션별 교정한다.

    매칭:
      - 단일색 상품(들어온 옵션 색이 전부 비었음): 그 사이즈의 SourceOption '전부' 갱신.
        (단일색 4800825 처럼 옛 다색 행이 섞여 by_cs 매칭이 막히던 잔여 제거.)
      - 다색 상품: 색+사이즈 정밀 매칭. 없으면 사이즈가 유일할 때만 사이즈 매칭.
    Returns: 갱신된 옵션 수.
    """
    if not isinstance(options, list) or not options:
        return 0
    from lemouton.sources.models import SourceOption
    rows = (session.query(SourceOption)
            .filter_by(source_product_id=source_product_id, deleted_at=None).all())
    by_cs, by_size = {}, {}
    for so in rows:
        sz = _stk_digits(so.size_text) or _stk_digits(so.color_text)
        if not sz:
            continue
        by_cs[(_stk_cnorm(so.color_text), sz)] = so
        by_size.setdefault(sz, []).append(so)
    # 단일색 판단: 들어온 옵션 색이 전부 비어있으면 단일색 상품 → 사이즈로만 매칭.
    in_colors = {_stk_cnorm(_opt_color_size(o)[0]) for o in options if isinstance(o, dict)}
    single_color = (in_colors <= {''})
    n = 0
    for o in options:
        if not isinstance(o, dict):
            continue
        st = o.get('stock')
        _color, _size = _opt_color_size(o)
        sz = _stk_digits(_size)
        if st is None or not sz:
            continue
        if single_color:
            targets = by_size.get(sz) or []     # 그 사이즈 전부(중복·옛 다색 행 포함) 교정
        else:
            # [2026-06-19 fix #4] 다색 상품: (색+사이즈) 정밀 매칭만 한다. 사이즈-단독 폴백 제거 —
            #   허브(다색 1URL)에 색 구분 없는 행이 사이즈당 1개뿐이면, 9색이 그 한 행을 차례로
            #   덮어써 색상별 재고가 통째로 뭉개지던(color-blind) 버그. 매칭 행 없으면 아래 else 의
            #   upsert 가 (색,사이즈) 행을 새로 만들어 색상별로 보존한다.
            t = by_cs.get((_stk_cnorm(_color), sz))
            targets = [t] if t is not None else []
        if targets:
            for target in targets:
                try:
                    target.current_stock = int(st)
                    if price is not None:
                        target.current_price = int(price)
                    n += 1
                except (TypeError, ValueError):
                    pass
        else:
            # [2026-06-14] 매칭 행 없음 → 생성(upsert). 롯데온·스스처럼 늘 상품레벨 stock
            #   하나만 저장해 per-size SourceOption 이 아예 없던 소싱처도, 이제 사이즈별
            #   재고 행을 만들어 매트릭스(Path B _match_option_so)가 옵션단위로 읽게 한다.
            #   (update-only 였을 때는 갱신할 행이 없어 상품레벨 999 폴백 = 한정수량 둔갑.)
            try:
                _st_int = int(st)
            except (TypeError, ValueError):
                continue
            from lemouton.sources.service import upsert_source_option
            so = upsert_source_option(
                session, source_product_id=source_product_id,
                color_text=(_color or ''), size_text=(_size or sz),
                current_stock=_st_int,
                current_price=(int(price) if price is not None else None))
            # 같은 크롤 내 동일 사이즈 재등장 대비 인덱스 갱신
            by_cs[(_stk_cnorm(_color), sz)] = so
            by_size.setdefault(sz, []).append(so)
            n += 1
    return n


def _prune_stale_option_sizes(session, source_product_id, options):
    """이번 크롤에 없는 (색,사이즈)의 SourceOption 을 soft-delete — 사라진/판매중지 옵션 정리.

    [2026-06-19 색+사이즈 정밀화 + 부분실패 가드] 4번째 케이스(옵션 자체가 사라짐) 처리:
      - 이번 크롤에 '그 색이 있었는데' (색,사이즈)가 없으면 → 사라진 옵션 → soft-delete
        → 매트릭스가 '옵션없음 혹은 매칭실패'로 표시(폴백 금지).
      - 이번 크롤에 '그 색 자체가 없으면'(부분실패·다른 색만 크롤) → 건드리지 않음(불확실 보존).
    단일색 상품(색-빈값)은 색='' 로 묶여 기존 '사이즈 기준'과 동일하게 동작.
    멀티색 1URL(딜 등)에서 특정 색의 사이즈만 사라진 갭을 이걸로 잡는다. 성공 크롤(옵션 ≥1)만.
    Returns: prune 된 수.
    """
    if not isinstance(options, list) or not options:
        return 0
    from lemouton.sources.models import SourceOption
    new_cs, new_colors = set(), set()
    for o in options:
        if not isinstance(o, dict):
            continue
        _c, _s = _opt_color_size(o)
        d = _stk_digits(_s)
        if d:
            cc = _stk_cnorm(_c)
            new_cs.add((cc, d))
            new_colors.add(cc)
    if not new_cs:
        return 0
    rows = (session.query(SourceOption)
            .filter_by(source_product_id=source_product_id, deleted_at=None).all())
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    n = 0
    for so in rows:
        st = (so.size_text or '').strip()
        sz = _stk_digits(st) or _stk_digits(so.color_text)
        if not sz:
            continue
        # 색 키: size_text·color_text 둘 다 있으면 진짜 색(다색), 아니면 단일색('')
        cc = _stk_cnorm(so.color_text) if (st and (so.color_text or '').strip()) else ''
        # 그 색이 이번 크롤에 있었는데 (색,사이즈)가 없으면 = 사라진 옵션 → prune.
        # 그 색 자체가 이번 크롤에 없으면(부분실패) → 보존(불확실 — 옛값 유지보다 다음 크롤 대기).
        if cc in new_colors and (cc, sz) not in new_cs:
            so.deleted_at = now
            n += 1
    return n


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

        # 소싱처 사전 — [perf 2026-06-12] 소싱처 레지스트리는 관리자가 가끔만 바꾸는
        #   설정 데이터(가격·재고 아님) → plain dict 를 60초 TTL 캐시(매 매트릭스 로드 쿼리 제거).
        from shared.ref_cache import cached as _ref_cached

        def _load_source_dict():
            _rows = (s.query(SourceRegistry)
                     .order_by(SourceRegistry.sort_order, SourceRegistry.id).all())
            return {src.id: {'id': src.id, 'name': src.name,
                             'main_url': src.main_url or ''} for src in _rows}
        source_dict = _ref_cached('matrix:source_dict', 60.0, _load_source_dict)

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
        # [perf 2026-06-12] SourceProduct 전체 풀스캔을 1회로 통합.
        #   기존: 여기(legacy URL 매칭) + 아래 신규 URL 모델 블록에서 각각 풀스캔 → 2회 왕복.
        #   SourceProduct 는 소량(수십행)이라 항상 1회 조회해 sp_by_norm 으로 재사용.
        sp_by_norm = {}  # normalized URL → SourceProduct
        for sp in (s.query(SourceProduct)
                   .filter(SourceProduct.deleted_at.is_(None)).all()):
            if sp.url:
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
                # [perf 2026-06-12] sp_by_norm 은 위에서 SourceProduct 전체를 이미 담았으므로
                #   재조회 없이 그대로 재사용 (기존: 여기서 풀스캔 1회 더 = 중복 왕복).
                _sp_by_norm2 = sp_by_norm
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
                    _match_failed = False
                    if sp:
                        _so_m = _match_option_so(
                            _so_index, sp.id,
                            _sku_color.get(lk.option_canonical_sku),
                            _sku_size.get(lk.option_canonical_sku))
                        if _so_m is not None:
                            _opt_stock = _so_m.current_stock
                            _opt_price = _so_m.current_price
                        elif _so_index.get(sp.id):
                            # [2026-06-13 폴백가 금지] 이 소싱처는 옵션(색·사이즈)을 크롤했는데
                            #   이 색/사이즈가 그 목록에 없음 = 소싱처가 실제로 안 파는 조합.
                            #   기존엔 상품 대표가(last_price)로 폴백 → '안 파는 사이즈에 가짜 가격'이
                            #   떠서(예: 르무통 오렌지 260·270 이 255와 동일가) 잘못된 매입 판단 → 손실.
                            #   폴백 금지하고 '매칭 실패'로 표면화한다(이상한 값 넣지 않음).
                            _match_failed = True
                    # 매칭 실패(안 파는 조합) = 폴백 금지(가격·재고 None). 그 외엔 옵션가(>0) 우선,
                    #   옵션 단위 가격이 없을 때만(=옵션 크롤 안 한 소싱처) 상품가 fallback.
                    if _match_failed:
                        _disp_price = None
                    else:
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
                        'crawled_stock': (None if _match_failed else
                                          (_opt_stock if _opt_stock is not None
                                           else (sp.last_stock if sp else None))),
                        'last_fetched_at': (sp.last_fetched_at.isoformat()
                                            if sp and sp.last_fetched_at else None),
                        'last_status': (sp.last_status if sp else None),
                        # [2026-06-13] 매칭 실패(소싱처가 안 파는 색/사이즈) — 프론트가 '매칭 실패'
                        #   로 표시하고 가격/재고 없는 것으로 처리(폴백가 금지).
                        'match_failed': _match_failed,
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
        _opl_psku_map = None  # [perf] 아래 get_stock_batch 재사용용 (OPL 1회 조회분)
        try:
            from lemouton.inventory.models import (
                InventoryProduct as _IP, OptionProductLink as _OPL,
            )
            from shared.inventory_stock import get_stock_batch as _gsb
            links = (s.query(_OPL)
                     .filter(_OPL.option_canonical_sku.in_(sku_list))
                     .all() if sku_list else [])
            # [perf 2026-06-12] 이 OPL 조회 결과를 옵션→재고제품 map 으로 만들어
            #   아래 get_stock_batch 에 넘겨 OptionProductLink 중복 조회 제거.
            _opl_psku_map = {lk.option_canonical_sku: lk.product_canonical_sku
                             for lk in links}
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
            inv_stock_dict = get_stock_batch(
                s, [o.canonical_sku for o in opts], psku_map=_opl_psku_map)
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
            #   (기존: 첫 번째 가격있는 소싱처 — 품절·크롤실패 stale 가격도 원가로 잡히던 버그.)
            #   [#4 2026-06-13] 소싱 카드 원가는 '크롤 실제가'만. 크롤 실패/누락 시 boxhero
            #   사입가·하드코딩 95000 폴백 '금지'(정책) → 가짜 판매가가 화면에 떠 수동주문
            #   유발하는 손실 차단. 없으면 소싱 카드 가격없음(None).
            sources_for_opt = sku_to_sources.get(o.canonical_sku, [])
            _cost_src = _pick_cheapest_buyable(sources_for_opt)
            purchase = _resolve_sourcing_cost(_cost_src)

            # [2026-06-02] 소싱 카드 가격 — 단일 진실 원천(compute_market_price)로 통일.
            #   크롤 실제가 있을 때만 산출. 없으면 None(가격없음/크롤실패) — 폴백 조작 금지.
            if purchase is not None:
                _src_ss_res = compute_market_price(tpl, 'ss', 'sourcing', purchase)
                _src_cp_res = compute_market_price(tpl, 'coupang', 'sourcing', purchase)
                ss_price, ss_break = _src_ss_res.final_price, _src_ss_res.breakdown
                cp_price, cp_break = _src_cp_res.final_price, _src_cp_res.breakdown
            else:
                ss_price = cp_price = None
                ss_break = cp_break = None

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
                # 옵션 매트릭스 활성 여부 (혜택 '옵션 직접 선택' 팝업이 활성 옵션만 노출)
                'is_active': bool(getattr(o, 'is_active', True)),
                # [2026-06-13] 크롤 실패/유효가격 없음 자동 판매차단 (is_active 와 분리, 화면 OFF 표시용)
                'crawl_blocked': bool(getattr(o, 'crawl_blocked', False)),
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
            # [perf 2026-06-12] sp_by_norm 재사용 — 위에서 SourceProduct 전체를 이미 로드함.
            #   (기존: 여기서 동일 풀스캔 1회 더 = 매트릭스 로드당 SourceProduct 3회 왕복.)
            _crawl_idx = {_k: (_sp.last_price, _sp.last_status)
                          for _k, _sp in sp_by_norm.items()}
            _bsus = (s.query(_BSU)
                     .filter(_BSU.model_code.in_(model_codes)).all())
            _bids = [b.id for b in _bsus]
            # [2026-06-19] 비활성(is_active=false) 옵션은 판매 대상이 아니므로 카드 집계(매핑 시도·성공)에서
            #   제외한다. (셀은 '비활성' 표시. 기존엔 비활성 옵션의 URL 링크가 map_try 에 잡혀, 그 사이즈를
            #   안 파는 소싱처에서 match_failed → '실패'로 둔갑. 예: 르무통 오렌지 260/270 수동 OFF.)
            _inactive_skus = {r['sku'] for r in opt_rows if not r.get('is_active', True)}
            _lcnt = {}
            if _bids:
                _q_lcnt = (s.query(_OSL.bundle_source_url_id, _func.count())
                           .filter(_OSL.bundle_source_url_id.in_(_bids)))
                if _inactive_skus:
                    _q_lcnt = _q_lcnt.filter(~_OSL.option_canonical_sku.in_(_inactive_skus))
                for _bid, _c in _q_lcnt.group_by(_OSL.bundle_source_url_id).all():
                    _lcnt[_bid] = _c
            # [2026-06-19] URL 통계(시도/성공/실패목록)는 URL 단위로 집계. 딜 URL 도 제외하지 않는다 —
            #   딜페이지가 대표 itemView 재크롤로 풀려 이제 정상 크롤되므로 일반 URL 로 취급.
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
                if _ok_url:
                    _st['url_done'] += 1
                else:
                    _st['fail_urls'].append({
                        'id': _b.id, 'label': _b.label or '', 'url': _b.url,
                        'affected': _links,
                        'status': (_rec[1] if _rec else 'not_crawled'),
                    })
            # [2026-06-19] map(옵션) 집계 = per-option(셀과 동일): 옵션이 그 소싱처에 등록되고, 그중 한
            #   URL이라도 usable(매칭성공+가격>0)이면 done. 같은 소싱처 여러 URL 중복제거 + 딜 URL 포함
            #   (딜이 가격 주면 그 옵션 성공) + 비활성 제외. (예: SSG 단품 매칭실패라도 딜이 커버하면 성공.)
            for _sku2, _entries in sku_to_sources.items():
                if _sku2 in _inactive_skus:
                    continue
                _by_src = {}
                for _e in _entries:
                    _by_src.setdefault(_e.get('source_key'), []).append(_e)
                for _ek, _elist in _by_src.items():
                    _rid2 = _k2reg.get(_ek)
                    _key2 = str(_rid2 if _rid2 is not None else 'key:' + str(_ek))
                    _st2 = source_stats.get(_key2)
                    if _st2 is None:
                        continue
                    _st2['map_try'] += 1
                    if any((not _e2.get('match_failed')) and ((_e2.get('crawled_price') or 0) > 0)
                           for _e2 in _elist):
                        _st2['map_done'] += 1
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


@bp.post('/bundles/<code>/verify-urls')
def verify_urls(code: str):
    """[2026-06-20 재설계] URL 크롤링 검증 — URL 단위 결과 + 전체/소싱처 집계 + 실패 정산.

    body: {source_ids?: [...]} (생략=전체). 저장된 크롤 데이터 기준(재크롤은 recrawl-url 별도).
    옵션×URL 셀 status(4케이스):
      ok(매칭·재고·가격) / soldout(품절: 매칭·재고0·가격 → 성공 포함) /
      absent('옵션없음 or 매핑실패') / noprice(가격없음·크롤실패).
    성공률 = (ok+soldout) / 전체 셀(absent·noprice 분모 포함 = '해석 A').
    최저매입가 = status=ok(재고있음)만 후보(품절 제외 = 월드컵 in-stock).
    Returns: {global:{...}, sources:[{...urls:[{...options}]}], fail_detail:{...}}.
    """
    body = request.get_json(silent=True) or {}
    want = set(body.get('source_ids') or [])
    d = _option_matrix_data(code)
    if not d.get('ok'):
        return _err(d.get('error', '데이터 없음'), d.get('status', 404))
    rows = d.get('options') or []
    sname = {x['id']: x['name'] for x in (d.get('sources') or [])}
    s = SessionLocal()
    try:
        from webapp.routes.api_benefits import compute_breakdown, _build_breakdown_cache
        from lemouton.sources.models import SourceOption as _SO

        # 크롤 상품명/실패사유(SourceProduct) + URL옵션(소싱처 자체 라벨, SourceOption) 인덱스
        spids = set()
        for o in rows:
            for src in (o.get('sources') or []):
                if src.get('source_product_id'):
                    spids.add(src['source_product_id'])
        sp_info = {}
        so_index = {}
        if spids:
            _spl = list(spids)
            for sp in s.query(SourceProduct).filter(SourceProduct.id.in_(_spl)).all():
                sp_info[sp.id] = {'product_name': sp.product_name or '',
                                  'last_status': sp.last_status,
                                  'last_error': sp.last_error_msg}
            try:
                so_index = _build_so_index(
                    s.query(_SO).filter(_SO.source_product_id.in_(_spl),
                                        _SO.deleted_at.is_(None)).all())
            except Exception:
                so_index = {}

        # 최종매입가 캐시 (ok/soldout 셀 한정)
        items = []
        for o in rows:
            for src in (o.get('sources') or []):
                if (src.get('crawled_price') and not src.get('match_failed')
                        and src.get('source_id') is not None):
                    items.append({'sku': o['sku'], 'source_id': src['source_id'],
                                  'sale_price': src['crawled_price']})
        try:
            cache = _build_breakdown_cache(s, items)
        except Exception:
            cache = None

        # [2026-06-20] 사용자가 URL 매핑에서 사전 지정한 유형(dan/mo/deal) — 추정보다 우선.
        url_type_map = {}
        try:
            from lemouton.sourcing.models import BundleSourceUrl as _BSU
            from lemouton.sources.service import normalize_url as _nu
            for _b in (s.query(_BSU.url, _BSU.url_type)
                       .filter(_BSU.url_type.isnot(None)).all()):
                if _b.url and _b.url_type:
                    url_type_map[_nu(_b.url)] = _b.url_type
        except Exception:
            url_type_map = {}

        per_url = {}  # (sid, url) -> url dict
        for o in rows:
            for src in (o.get('sources') or []):
                sid = src.get('source_id')
                url = src.get('product_url')
                if sid is None or (want and sid not in want):
                    continue
                spid = src.get('source_product_id')
                key = (sid, url)
                u = per_url.get(key)
                if u is None:
                    _spi = sp_info.get(spid, {})
                    u = per_url[key] = {
                        'source_id': sid, 'source_name': sname.get(sid, '?'),
                        'product_url': url,
                        'product_name': _spi.get('product_name') or '',
                        'is_deal': bool(url and 'dealitemview' in url.lower()),
                        'last_status': _spi.get('last_status'),
                        'last_error': _spi.get('last_error'),
                        'ok': 0, 'soldout': 0, 'absent': 0, 'noprice': 0,
                        'min_final': None, '_colors': set(), 'options': [],
                    }
                # 4케이스 판정
                if src.get('match_failed'):
                    status = 'absent'
                elif (not src.get('crawled_price')) or src.get('last_status') == 'error':
                    status = 'noprice'
                elif src.get('stock_out'):
                    status = 'soldout'
                else:
                    status = 'ok'
                fin = None
                if status in ('ok', 'soldout') and src.get('crawled_price'):
                    try:
                        fin = (compute_breakdown(s, sku=o['sku'], source_id=int(sid),
                                                 sale_price=float(src['crawled_price']),
                                                 _cache=cache) or {}).get('final_price')
                    except Exception:
                        fin = None
                u[status] += 1
                if status == 'ok' and fin and (u['min_final'] is None or fin < u['min_final']):
                    u['min_final'] = fin
                if status != 'absent':
                    u['_colors'].add(o.get('color_code'))
                # URL옵션 (소싱처 자체 색/사이즈 라벨)
                url_opt = None
                if spid and so_index:
                    try:
                        _som = _match_option_so(so_index, spid,
                                                o.get('color_code'), o.get('size_code'))
                        if _som is not None:
                            _ct = (getattr(_som, 'color_text', '') or '').strip()
                            _st = (getattr(_som, 'size_text', '') or '').strip()
                            url_opt = (_ct + (' / ' if _ct and _st else '') + _st) or None
                    except Exception:
                        url_opt = None
                u['options'].append({
                    'color': o.get('color_display'), 'size': o.get('size_display'),
                    'status': status,
                    'stock_label': src.get('stock_label'), 'stock_out': src.get('stock_out'),
                    'surface': src.get('crawled_price'), 'final': fin,
                    'url_product_name': u['product_name'], 'url_option': url_opt,
                })

        # URL 마무리 + 소싱처 집계
        per_src = {}
        for (sid, url), u in per_url.items():
            total = len(u['options'])
            matched = u['ok'] + u['soldout']
            u['matched'] = matched
            u['total'] = total
            u['success_rate'] = round(matched / total * 100) if total else 0
            _stored_ty = None
            try:
                _stored_ty = url_type_map.get(_nu(url)) if url else None
            except Exception:
                _stored_ty = None
            # [2026-06-20] 미지정 기본 = 단품. 단 딜(dealItemView)은 '모델 모음전'(확실 감지).
            u['type'] = _stored_ty or ('deal' if u['is_deal'] else 'dan')
            u['crawl_error'] = bool(u['last_status'] == 'error'
                                    or (total > 0 and u['noprice'] == total and matched == 0))
            u.pop('_colors', None)
            ps = per_src.setdefault(sid, {'source_id': sid, 'name': sname.get(sid, '?'),
                                          'urls': [], 'ok': 0, 'soldout': 0,
                                          'absent': 0, 'noprice': 0, 'total': 0,
                                          'min_final': None})
            ps['urls'].append(u)
            for k in ('ok', 'soldout', 'absent', 'noprice', 'total'):
                ps[k] += u[k]
            if u['min_final'] is not None and (ps['min_final'] is None
                                               or u['min_final'] < ps['min_final']):
                ps['min_final'] = u['min_final']

        sources = []
        g_matched = g_absent = g_noprice = g_total = g_err = 0
        g_min = None
        g_min_src = None
        for sid, ps in per_src.items():
            ps['matched'] = ps['ok'] + ps['soldout']
            ps['success_rate'] = round(ps['matched'] / ps['total'] * 100) if ps['total'] else 0
            # 실패 많은 URL 위로
            ps['urls'].sort(key=lambda x: -(x['absent'] + x['noprice']))
            sources.append(ps)
            g_matched += ps['matched']
            g_absent += ps['absent']
            g_noprice += ps['noprice']
            g_total += ps['total']
            g_err += sum(1 for x in ps['urls'] if x['crawl_error'])
            if ps['min_final'] is not None and (g_min is None or ps['min_final'] < g_min):
                g_min = ps['min_final']
                g_min_src = ps['name']
        sources.sort(key=lambda x: (x['min_final'] is None, x['min_final'] or 0))

        # 실패 정산 — URL별 absent/noprice (합 = 전체 absent/noprice 와 일치)
        fail_urls = []
        for ps in sources:
            for u in ps['urls']:
                if u['absent'] or u['noprice']:
                    fail_urls.append({
                        'product_url': u['product_url'], 'product_name': u['product_name'],
                        'source_name': u['source_name'], 'is_deal': u['is_deal'],
                        'crawl_error': u['crawl_error'], 'last_error': u['last_error'],
                        'absent': u['absent'], 'noprice': u['noprice'],
                    })
        fail_urls.sort(key=lambda x: -(x['absent'] + x['noprice']))

        return _ok(
            sources=sources,
            fail_detail={'absent_total': g_absent, 'noprice_total': g_noprice,
                         'urls': fail_urls},
            **{'global': {
                'min_final': g_min, 'min_final_source': g_min_src,
                'matched': g_matched, 'absent': g_absent, 'noprice': g_noprice,
                'total': g_total,
                'success_rate': round(g_matched / g_total * 100) if g_total else 0,
                'crawl_error_urls': g_err,
            }},
        )
    finally:
        s.close()


# ════════════════════════════════════════════════════════════
#  크롤 시작 하드 리셋 + 종료 후 판매차단(crawl_blocked) 재계산
#  [2026-06-13] 옛 가격/재고가 재크롤에 안 덮이면 잘못된 값으로 판매 → 치명적 손실.
#   · 크롤 시작 시: 그 모음전의 SourceProduct/SourceOption 가격·재고·혜택을 비우고(NULL,
#     status='pending'), 옵션을 pessimistic 으로 crawl_blocked=True (유효가격 다시 잡히면 해제).
#   · 크롤 종료 시: 옵션별 '유효 소싱가(is_crawl_valid)' 유무로 crawl_blocked 재계산.
#   판매가능 = Option.is_active(사용자 수동) AND NOT Option.crawl_blocked(크롤 정상).
#   매칭 로직 중복 없이 _option_matrix_data(단일 진실 원천) 재사용.
# ════════════════════════════════════════════════════════════

def _reset_bundle_crawl_state(s, code: str) -> dict:
    """크롤 시작 직전 — 그 모음전의 소싱 가격/재고/혜택 비우고 옵션 pessimistic block."""
    from lemouton.sources.models import SourceProduct, SourceOption
    from lemouton.sourcing.models import Option
    data = _option_matrix_data(code)
    opts = data.get('options') or []
    sp_ids = {src.get('source_product_id')
              for o in opts for src in (o.get('sources') or [])
              if src.get('source_product_id')}
    if sp_ids:
        (s.query(SourceProduct).filter(SourceProduct.id.in_(sp_ids))
         .update({SourceProduct.last_price: None, SourceProduct.last_stock: None,
                  SourceProduct.last_status: 'pending',
                  SourceProduct.dynamic_benefits_json: None},
                 synchronize_session=False))
        (s.query(SourceOption).filter(SourceOption.source_product_id.in_(sp_ids))
         .update({SourceOption.current_price: None, SourceOption.current_stock: None,
                  SourceOption.dynamic_benefits_json: None},
                 synchronize_session=False))
    skus = [o['sku'] for o in opts if o.get('sku')]
    if skus:
        (s.query(Option).filter(Option.canonical_sku.in_(skus))
         .update({Option.crawl_blocked: True}, synchronize_session=False))
    s.commit()
    return {'reset_products': len(sp_ids), 'blocked_options': len(skus)}


def _sources_have_valid_price(sources) -> bool:
    """옵션의 소싱 목록 중 '판매에 쓸 수 있는 유효 가격'이 하나라도 있나 — 단일 판정.

    유효 = 매칭 실패(안 파는 조합) 아님 AND is_crawl_valid(가격>0, status!='error').
    리셋 후 미커버(NULL/pending)·크롤실패(error)·매칭실패는 모두 무효 → 판매차단 대상.
    """
    from lemouton.pricing.unified import is_crawl_valid
    return any(
        (not src.get('match_failed'))
        and is_crawl_valid(src.get('crawled_price'), src.get('last_status'))
        for src in (sources or [])
    )


def _finalize_bundle_crawl_block(s, code: str) -> dict:
    """크롤 종료 후 — 옵션별 유효 소싱가 유무로 crawl_blocked 재계산(성공=해제, 실패=차단)."""
    from lemouton.sourcing.models import Option
    data = _option_matrix_data(code)
    opts = data.get('options') or []
    blocked = sellable = 0
    for o in opts:
        sku = o.get('sku')
        if not sku:
            continue
        opt = s.get(Option, sku)
        if opt is None:
            continue
        # 오프라인 전용(소싱 URL 없이 사입만) 옵션은 크롤 차단 대상 아님
        if getattr(opt, 'offline_only', False):
            new_blocked = False
        else:
            new_blocked = not _sources_have_valid_price(o.get('sources') or [])
        opt.crawl_blocked = new_blocked
        blocked += int(new_blocked)
        sellable += int(not new_blocked)
    s.commit()
    return {'blocked': blocked, 'sellable': sellable}


@bp.post('/bundles/<code>/crawl-reset')
def post_crawl_reset(code: str):
    """크롤 시작 직전 호출(확장·서버 공통) — 가격/재고/혜택 하드 리셋 + 옵션 pessimistic block."""
    s = SessionLocal()
    try:
        return _ok(**_reset_bundle_crawl_state(s, code))
    finally:
        s.close()


@bp.post('/bundles/<code>/crawl-finalize')
def post_crawl_finalize(code: str):
    """크롤 종료 후 호출 — 유효 소싱가 없는 옵션을 crawl_blocked=True 로 판매차단."""
    s = SessionLocal()
    try:
        return _ok(**_finalize_bundle_crawl_block(s, code))
    finally:
        s.close()


# ════════════════════════════════════════════════════════════
#  POST /api/sources/crawl-result — 크롬 확장(로그인 브라우저) 크롤 결과 저장
#  [2026-06-06] '모음전 크롤러' 확장이 로컬 브라우저로 긁은 가격/재고를 SourceProduct
#    에 반영(서버가 직접 못 긁는 무신사 회원가·롯데온 SPA 등). 매트릭스·fx 가
#    SourceProduct.last_price/last_stock/last_status 를 읽으므로 여기 쓰면 UI·계산식에
#    그대로 반영된다. 설계: docs/소싱처관리_아키텍처.md
# ════════════════════════════════════════════════════════════
def _build_crawl_snapshot(item: dict, *, now_iso: str) -> dict:
    """확장 크롤 1건(item)에서 '이번 브라우저 기준' 혜택 스냅샷을 만든다.

    benefit_lines/benefit_amounts 가 오면 benefits_ok=True. 없으면 빈 스냅샷
    (benefits_ok=False) — 빈 배열을 '혜택 없음'으로 둔갑시키지 않는다(미수집).
    """
    lines = item.get('benefit_lines')
    amounts = item.get('benefit_amounts')
    has = isinstance(lines, list) and bool(item.get('benefits_ok'))
    return {
        'crawled_at': now_iso,
        'is_logged_in': (None if item.get('is_logged_in') is None
                         else bool(item.get('is_logged_in'))),
        'benefits_ok': bool(has),
        'lines': list(lines) if isinstance(lines, list) else [],
        'amounts': dict(amounts) if isinstance(amounts, dict) else {},
    }


@bp.post('/sources/crawl-result')
def save_crawl_result():
    """확장 크롤 결과 일괄 저장.

    body: { items: [{url, price, stock?, status?, product_name?, error?}] }
    url(정규화) 로 SourceProduct 를 찾아 last_price/last_stock/last_status 갱신.
    """
    import datetime as _dt
    from lemouton.sources.service import normalize_url
    from lemouton.sources.models import SourceOption
    body = request.get_json(silent=True) or {}
    items = body.get('items') or []
    if not isinstance(items, list) or not items:
        return _err('items(배열)가 필요해요.', 400)

    s = SessionLocal()
    try:
        # 정규화 url → SourceProduct 인덱스 (1회 빌드)
        #  ★ [2026-06-21] 같은 정규화 URL 에 SourceProduct 가 여러 개일 수 있음(트래킹 파라미터
        #  다른 중복행). crawl-result(첫 행 갱신)와 verify/_option_matrix_data(마지막 행 읽기)가
        #  서로 다른 행을 골라 가격이 화면에 안 뜨던 사고 → dup_ids 로 '모든 중복행' 옵션가를 갱신.
        idx = {}
        dup_ids = {}
        for sp in (s.query(SourceProduct)
                   .filter(SourceProduct.deleted_at.is_(None)).all()):
            if sp.url:
                _nu = normalize_url(sp.url)
                idx.setdefault(_nu, sp)
                dup_ids.setdefault(_nu, []).append(sp.id)

        now = _dt.datetime.now(_dt.timezone.utc)
        updated, not_found, item_errors = 0, [], []
        for it in items:
            url = (it or {}).get('url')
            if not url:
                continue
            sp = idx.get(normalize_url(url))
            if sp is None:
                not_found.append(str(url)[:80])
                continue
            price = it.get('price')
            stock = it.get('stock')
            # [2026-06-12 방어] 비정상 저가(<100원, 예: 1원) 거부 — 추출 오류값이
            #   last_price/current_price 를 덮어써 잘못된 최저가가 잡히는 금전 사고 방지.
            #   (전 소싱처 공통 안전망 — 확장 버전 무관)
            rejected_low = False
            try:
                if price not in (None, '', 0) and int(price) < 100:
                    rejected_low = True
            except Exception:
                pass
            status = it.get('status') or ('ok' if (price and not rejected_low) else 'error')
            if rejected_low:
                status = 'error'
            if price not in (None, '', 0) and not rejected_low:
                try:
                    sp.last_price = int(price)
                except Exception:
                    pass
            if stock is not None:
                try:
                    sp.last_stock = int(stock)
                except Exception:
                    pass
            sp.last_status = status
            sp.last_fetched_at = now
            sp.last_error_msg = ('비정상 저가 거부(%s원)' % price) if rejected_low else (it.get('error') or None)
            pn = it.get('product_name')
            if pn:
                sp.product_name = str(pn)[:255]
            # ★ 2026-06-14 — 사이즈별 재고 반영 (확장 options[{color,size,stock}] → current_stock).
            #   기존 상품레벨 stock(=확장 anyStock?999:0)만 저장 → 전 사이즈 '재고있음'
            #   둔갑(한정수량·품절 누락 = 오발주 손실) 교정. status=ok 인 성공 크롤만.
            if status == 'ok':
                _opts_in = it.get('options')
                # [2026-06-18] 옵션 재고 반영을 savepoint 로 격리 — 한 건이 예외(예: ssf 특정
                #   옵션 데이터로 internal_error) 나도 그 건만 롤백하고 배치 전체(다른 소싱처·이 건의
                #   가격)는 보존·커밋되게. 기존엔 한 건 예외가 루프를 깨 commit 미도달 → 배치 전량
                #   0건 저장 → 하드리셋만 남아 가격 소실되는 사고였음. 에러는 item_errors 로 표면화.
                try:
                    _price_int = (int(price) if (price not in (None, '', 0) and not rejected_low) else None)
                    with s.begin_nested():
                        # 먼저 이번에 없는 사이즈 prune(옛 다색·날조 행 제거) → 단일색 매칭 모호성 해소.
                        _prune_stale_option_sizes(s, sp.id, _opts_in)
                        # [2026-06-21] 가격도 함께 박음(생성·갱신 시점) → 신규 옵션 가격 누락 사고 방지.
                        _ingest_option_stocks(s, sp.id, _opts_in, price=_price_int)
                except Exception as _e:
                    item_errors.append({'url': str(url)[:80], 'where': 'option_stock', 'error': str(_e)[:160]})
            # [2026-06-06] 옵션단위 표시가 갱신 — 매트릭스는 SourceOption.current_price 우선(상품
            #   last_price 는 fallback). 상품 내 가격 균일(무신사 회원가·SSF 등)하므로 전 옵션 일괄 반영.
            #   ★ [2026-06-21] _ingest 가 생성·갱신 옵션에 가격을 박지만, 이번 옵션배열에 없던 기존
            #   옵션까지 균일가로 맞추는 안전망. s.flush()로 신규 옵션을 먼저 DB 반영(autoflush off
            #   환경에서도 bulk update 가 신규행을 놓치지 않게).
            if price not in (None, '', 0) and not rejected_low:
                try:
                    s.flush()
                    _all_ids = dup_ids.get(normalize_url(url)) or [sp.id]
                    s.query(SourceOption).filter(
                        SourceOption.source_product_id.in_(_all_ids),
                        SourceOption.deleted_at.is_(None)
                    ).update({SourceOption.current_price: int(price)},
                             synchronize_session=False)
                except Exception:
                    pass
            # ★ 2026-06-14 — '있는 그대로(현재 브라우저)' 혜택 스냅샷 저장.
            #   확장이 현재 페이지에서 긁은 혜택 라인/금액을 dynamic_benefits_json['_crawl']에
            #   타임스탬프·로그인상태와 함께 기록. 크롤 실패(status='error')면 스냅샷 미갱신
            #   → 신선도 게이트(benefits_fresh)가 옛 값을 자동 배제. (폴백 금지)
            if getattr(sp, 'site', None) == 'musinsa' and status != 'error':
                import json as _json
                try:
                    _dyn = _json.loads(sp.dynamic_benefits_json) if sp.dynamic_benefits_json else {}
                except (ValueError, TypeError):
                    _dyn = {}
                _dyn['_crawl'] = _build_crawl_snapshot(it, now_iso=now.isoformat())
                if price not in (None, '', 0):
                    try:
                        _dyn['surface_price'] = int(price)
                    except Exception:
                        pass
                sp.dynamic_benefits_json = _json.dumps(_dyn, ensure_ascii=False)
            updated += 1
        s.commit()
        return _ok(updated=updated, not_found=not_found, item_errors=item_errors, total=len(items))
    finally:
        s.close()


@bp.get('/bundles/codes')
def list_bundle_codes():
    """전체 모음전 코드 목록 — 이 PC 스케줄 크롤(ext_bridge)이 순회하는 데 사용."""
    s = SessionLocal()
    try:
        rows = s.query(Model.model_code).order_by(Model.model_code).all()
        return _ok(codes=[r[0] for r in rows if r[0]])
    finally:
        s.close()


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
        # [2026-06-14 #1 폴백금지] 원가 = 크롤 실제가만. 사입가·하드코딩 95000 폴백 금지
        #   (전 시스템 공통 정책 — 매트릭스/업로더와 동일). 크롤가 없으면 '가격없음'으로 표면화.
        purchase = _src_purchase  # 크롤 실제가 int | None
        if purchase is None:
            return _ok(
                sku=sku, color=opt.color_code, size=opt.size_code,
                auto_enabled=cfg.auto_enabled if cfg else True,
                ss=None, cp=None, ss_final=None, cp_final=None,
                template_name=(tpl.name if tpl else None),
                price_missing=True, reason='크롤 실제가 없음 (가격없음/크롤실패)',
            )
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
    # [2026-06-05] 송장자동화와 동일 프로필 위치·네이밍으로 통일 — 사용자가 송장자동화로
    #   이미 로그인해둔 %LOCALAPPDATA%/invoice_profiles/{...} 프로필을 그대로 재사용.
    #   direct=한글사이트명_{id}, naver 등=site_key_method_{id}. (login_method 반영)
    from lemouton.auth.profile_store import resolve_profile_dir
    creds = creds_default_store().load_all().get(site_key, {}).get(acc.account_key, {})
    actual_id = creds.get("id", acc.account_key)
    login_method = creds.get("login_method", "direct")
    prof_path = resolve_profile_dir(site_key, actual_id, login_method)

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

    # [2026-06-06] 전 소싱처 스크래퍼 매핑 (네이버 포함) — 어떤 계정이든 로그인.
    login_method = creds.get("login_method", "direct")
    _SCRAPER_MAP = {
        "musinsa":    ("lemouton.auth.scrapers.musinsa", "MusinsaScraper"),
        "ssf":        ("lemouton.auth.scrapers.ssf", "SSFShopScraper"),
        "lotteon":    ("lemouton.auth.scrapers.lotteon", "LotteonScraper"),
        "lotteimall": ("lemouton.auth.scrapers.lotteimall", "LotteimallScraper"),
        "abc":        ("lemouton.auth.scrapers.abc", "ABCMartScraper"),
        "abcGs":      ("lemouton.auth.scrapers.abc", "ABCMartGSScraper"),
        "grandstage": ("lemouton.auth.scrapers.abc", "GrandStageScraper"),
        "gs":         ("lemouton.auth.scrapers.gs", "GSScraper"),
        "folder":     ("lemouton.auth.scrapers.gs", "FolderScraper"),
        "ssg":        ("lemouton.auth.scrapers.ssg", "SSGScraper"),
    }
    scraper_cls = None
    if site_key in _SCRAPER_MAP:
        import importlib
        _mod, _cls = _SCRAPER_MAP[site_key]
        try:
            scraper_cls = getattr(importlib.import_module(_mod), _cls)
        except Exception as _e:
            logging.getLogger(__name__).warning("[%s] 스크래퍼 import 실패: %s", site_key, _e)
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
            login_method=login_method,   # ★ 실제 방식(direct/naver) 반영 (하드코딩 제거)
            max_retry=2,
            skip_if_logged_in=not force,
        )
        if not ok:
            return None
        # [2026-06-06] 로그인 후 프로필 경로 = 송장자동화식(invoice_profiles, login_method 반영)
        from lemouton.auth.profile_store import resolve_profile_dir as _rpd
        prof_path = _rpd(site_key, actual_id, login_method)
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


# ════════════════════════════════════════════
#  [2026-06-13] 가격/재고 무결성 전수 점검 — 읽기 전용 관리자 페이지
#    라이브에서 URL 한 번으로 불변식 위반 건수 확인. 데이터 변경 0(SELECT만).
#    /api/admin/price-integrity        → 사람이 읽는 HTML
#    /api/admin/price-integrity?format=json → JSON
#    점검 로직은 scripts/verify_integrity.run_checks (CLI 와 동일 단일 진실 원천).
# ════════════════════════════════════════════
@bp.get('/admin/price-integrity')
def admin_price_integrity():
    from scripts.verify_integrity import run_checks
    import html as _html
    s = SessionLocal()
    try:
        results = run_checks(s)
        try:
            dialect = s.bind.dialect.name
        except Exception:
            dialect = '?'
        data = [c.to_dict() for c in results]
        total = sum(c['count'] for c in data if c['count'] > 0)
        errored = sum(1 for c in data if c['errored'])

        if (request.args.get('format') or '').lower() == 'json':
            return jsonify({'ok': errored == 0 and total == 0, 'db': dialect,
                            'total_violations': total, 'errored': errored,
                            'checks': data})

        rows = []
        for c in data:
            if c['errored']:
                icon, color = '⚠️', '#b8860b'
            elif c['count'] == 0:
                icon, color = '✅', '#1a7f37'
            else:
                icon, color = '❌', '#cf222e'
            samples = ''
            if c['count'] > 0:
                lis = ''.join(f"<li>{_html.escape(str(x))}</li>" for x in c['samples'])
                more = (f"<li>… 외 {c['count'] - len(c['samples'])}건</li>"
                        if c['count'] > len(c['samples']) else '')
                samples = (f"<div class='imp'>영향: {_html.escape(c['money_impact'])}</div>"
                           f"<ul class='samp'>{lis}{more}</ul>")
            cnt = '-' if c['errored'] else c['count']
            rows.append(
                f"<tr style='color:{color}'><td class='code'>{_html.escape(c['code'])}</td>"
                f"<td class='ic'>{icon}</td><td class='num'>{cnt}</td>"
                f"<td><b>{_html.escape(c['title'])}</b>{samples}</td></tr>")

        if errored:
            banner = (f"<div class='ban err'>⚠️ 점검 {errored}건 실행 실패 — "
                      f"DB 연결/스키마 확인 필요(판정 불가)</div>")
        elif total == 0:
            banner = "<div class='ban ok'>✅ 모든 불변식 위반 0건 — 이 시점 전 데이터에서 성립</div>"
        else:
            banner = f"<div class='ban err'>❌ 총 위반 {total}건 — 아래 ❌ 항목 확인</div>"

        page = f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>가격/재고 무결성 점검</title><style>
body{{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:920px;margin:24px auto;padding:0 16px;color:#1f2328}}
h1{{font-size:20px}} .sub{{color:#656d76;font-size:13px;margin-bottom:16px}}
.ban{{padding:12px 16px;border-radius:8px;font-weight:600;margin:14px 0}}
.ban.ok{{background:#e6f4ea;color:#1a7f37}} .ban.err{{background:#ffebe9;color:#cf222e}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
td{{border-top:1px solid #d0d7de;padding:10px 8px;vertical-align:top}}
.code{{font-family:monospace;white-space:nowrap;color:#656d76}} .ic{{text-align:center;width:28px}}
.num{{text-align:right;font-variant-numeric:tabular-nums;font-weight:700;width:48px}}
.imp{{color:#656d76;font-size:12px;margin:4px 0}} .samp{{margin:4px 0 0;padding-left:18px;font-size:12px;color:#57606a}}
</style></head><body>
<h1>가격/재고 무결성 전수 점검</h1>
<div class=sub>DB={_html.escape(dialect)} · 읽기 전용(데이터 변경 없음) · 위반 0 = 그 시점 전 데이터에서 불변식 성립</div>
{banner}
<table><tbody>{''.join(rows)}</tbody></table>
<p class=sub style='margin-top:18px'>※ 이 페이지는 SELECT 만 수행합니다. 중복행 정리 등 수정은 별도 관리자 액션에서 dry-run 확인 후 진행하세요.</p>
</body></html>"""
        return page, 200, {'Content-Type': 'text/html; charset=utf-8'}
    finally:
        s.close()
