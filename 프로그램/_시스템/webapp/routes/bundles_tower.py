# -*- coding: utf-8 -*-
"""「모음전 상품관리」 컨트롤타워 — 확정 시안 v8 (상품관리_최종시안_v8_판매이력_추가.html).

겉 화면(/bundles) = 왼쪽 서랍(현황 4장·검색·브랜드·상태·정렬) + 핵심 요약 표.
줄을 누르면 그 줄 아래 전폭 펼침 — 탭 6개(한눈에·판매 이력·옵션 매트릭스·
소싱처 수집 이력·마켓 등록·정책·가격/재고 변동 이력).

🔴 값을 지어내지 않는다 — 모르면 None(화면 「확인 불가」/「—」).
🔴 같은 값을 다시 계산하지 않는다 — 전부 기존 단일 진실 원천을 **호출만** 한다:
   · 최종매입가(소싱처 크롤값) = webapp.routes.matrix._rows_for
     → api_pricing._attach_final_purchase (코드 이름은 여전히 min_final·final_price 다)
   · 정책 판매가·마진 = lemouton.policy.preview.result_by_market
   · 수수료율    = lemouton.pricing.fee_defaults (market_fee_defaults DB)
   · 주문 매칭   = lemouton.orders.price_diff.resolve_targets_verbose
   · 실매입가    = lemouton.markets.purchase_price.get_many (order_line_purchases)
   · 가격 이력   = 기존 /api/matrix/price-history 를 프론트가 직접 호출
   · 정산 예정은 저장된 값을 읽기만 하고, 실현 마진은 거기서 실매입가만 뺀다
     — 산식은 마진 계산기와 같고, 그 화면은 하나도 안 건드린다(설계서 §6.2).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, render_template, request

from shared.db import SessionLocal
from webapp.routes.bundles import bp

_log = logging.getLogger(__name__)

# 마켓 순서·글리프 — 시안 고정(쿠·스·롯·11·옥·G)
TOWER_MARKETS = [
    ('coupang', '쿠팡', '쿠'),
    ('smartstore', '스마트스토어', '스'),
    ('lotteon', '롯데온', '롯'),
    ('eleven11', '11번가', '11'),
    ('auction', '옥션', '옥'),
    ('gmarket', 'G마켓', 'G'),
]
_MK_LABEL = {k: l for k, l, _ in TOWER_MARKETS}

# ═══════════════════════════════════════════════════════════════════════════
#  상품이 「어디까지 왔나」 — 4가지 상태 (사장님 확정 2026-08-06)
#  🔴 단일 진실 원천. 상품관리(/bundles)와 옵션매트릭스(/optgen)가 **이 정의만** 쓴다.
#     말도 여기 것을 그대로 쓴다 — 두 화면이 같은 걸 다르게 부르면 안 된다.
# ═══════════════════════════════════════════════════════════════════════════
STAGE_MADE = 1          # 상품 생성                              (정책 ✕ · 마켓 ✕)
STAGE_POLICY = 2        # 상품 생성 + 정책 적용                   (정책 ○ · 마켓 ✕)
STAGE_NOPOLICY_SELL = 4  # 상품 생성 + 마켓 등록 ※ 정책 미적용      (정책 ✕ · 마켓 ○)
STAGE_SELLING = 3       # 상품 생성 + 정책 적용 + 마켓 등록        (정책 ○ · 마켓 ○)

#: 화면에 보이는 순서 — 막대 토막도 이 순서다(목록과 막대가 어긋나면 안 된다).
STAGES = (STAGE_MADE, STAGE_POLICY, STAGE_NOPOLICY_SELL, STAGE_SELLING)
#: 마켓에 올라간 = 판매중. 정책이 없어도 팔리고 있는 것은 팔리는 것이다.
SELLING_STAGES = (STAGE_NOPOLICY_SELL, STAGE_SELLING)

STAGE_LABEL = {
    STAGE_MADE: '상품 생성',
    STAGE_POLICY: '상품 생성 + 정책 적용',
    STAGE_NOPOLICY_SELL: '상품 생성 + 마켓 등록 (판매중) ※ 정책 미적용',
    STAGE_SELLING: '상품 생성 + 정책 적용 + 마켓 등록 (판매중)',
}
#: 옵션매트릭스 쪽 표현 — 사장님이 그 화면엔 「적용」을 넣어 부르신다.
STAGE_LABEL_MATRIX = {
    STAGE_MADE: '상품 생성 적용',
    STAGE_POLICY: '상품 생성 적용 + 정책 적용',
    STAGE_NOPOLICY_SELL: '상품 생성 적용 + 마켓 등록 (판매중) ※ 정책 미적용',
    STAGE_SELLING: '상품 생성 적용 + 정책 적용 + 마켓 등록 (판매중)',
}
#: 배지 색 — 회색 / 파랑 / 주황 / 초록. 색 뜻은 화면 어디서나 같다.
STAGE_CLS = {STAGE_MADE: 'wait', STAGE_POLICY: 'mid',
             STAGE_NOPOLICY_SELL: 'warn', STAGE_SELLING: 'sale'}


def stage_of(has_policy: bool, has_market: bool) -> int:
    """정책·마켓 두 사실만으로 상태를 정한다 — 지어내는 값이 없다."""
    if has_market:
        return STAGE_SELLING if has_policy else STAGE_NOPOLICY_SELL
    return STAGE_POLICY if has_policy else STAGE_MADE


def stages_for(session, codes: list[str]) -> dict:
    """model_code → 4가지 상태. **묶음 목록 화면들이 공용으로 쓴다.**

    🔴 옵션관리(/matrix)·옵션 목록(/optgen)·상품관리가 같은 함수를 쓴다 —
       판정이 두 벌이 되면 같은 상품을 화면마다 다르게 부른다.
    """
    codes = [c for c in codes if c]
    if not codes:
        return {}
    pol = policy_models(session, codes)
    mkt = _registered_markets(session, codes)
    return {c: stage_of(c in pol, bool(mkt.get(c))) for c in codes}


def policy_models(s, codes: list[str]) -> set:
    """정책이 붙은 model_code 집합 — **두 자리를 다 본다**(배치 2쿼리).

    🔴 상품 단위(BundlePolicyLink)만 보면 「구성(벌)마다 다른 정책」을 붙인 상품이
       「정책 없음」으로 잘못 잡힌다. 정책은 두 곳에 붙을 수 있다:
         ① BundlePolicyLink  — 상품에 하나 (구성이 따로 안 정했을 때 쓰는 바탕값)
         ② SetPolicyLink     — 구성(ProductSet)마다 하나 (「한 상품에 여러 정책」의 실체)
       둘 중 하나라도 있으면 「정책 적용됨」이다 — 그 상품은 실제로 정책값으로 나간다.
    """
    from lemouton.policy.models import BundlePolicyLink, SetPolicyLink
    from lemouton.sets.models import ProductSet

    if not codes:
        return set()
    got = {mc for (mc,) in
           s.query(BundlePolicyLink.model_code)
           .filter(BundlePolicyLink.model_code.in_(codes),
                   BundlePolicyLink.policy_id.isnot(None)).distinct().all()}
    got |= {mc for (mc,) in
            s.query(ProductSet.model_code)
            .join(SetPolicyLink, SetPolicyLink.set_id == ProductSet.id)
            .filter(ProductSet.model_code.in_(codes),
                    SetPolicyLink.policy_id.isnot(None)).distinct().all()}
    return got


#: 판매 이력 스캔 상한 — 전체 주문 풀스캔 방지(기간 필터 뒤에도 이 수를 넘지 않는다)
_SALES_ROW_CAP = 20000
#: [2026-08-06 속도] 60→300초. 스캔(주문 2만행 JSON)·최종매입가 일괄 계산이 비싸서
#: 60초마다 동기 재계산하면 목록이 「매우 느려」진다(사장님 실사용 피드백).
#: 300초 + 아래 stale-while-revalidate 로 「캐시가 있으면 즉시, 갱신은 뒤에서」.
_CACHE_TTL = 300         # 초 — 목록 열·판매 집계 공용

_cache_lock = threading.Lock()
#: {days: (ts, 실매입가 도장, per_model)} — 도장은 아래 `purchase_stamp` 참고.
_sales_cache: dict[int, tuple[float, str, dict]] = {}
#: (ts, per_model) — 도장이 없다. 이 열들(최종매입가·정책 판매가·재고)은
#: `order_line_purchases` 를 아예 안 읽어서 매입가가 바뀌어도 값이 안 변한다.
_price_cache: tuple[float, dict] | None = None
#: 진행 중인 백그라운드 갱신(single-flight) — 같은 키는 한 번만 돈다.
_refreshing: set[str] = set()
#: 테스트가 join 할 수 있게 마지막 스레드를 들고 있는다(운영엔 영향 없음).
_refresh_threads: dict[str, threading.Thread] = {}


def _kick_refresh(key: str, fn) -> None:
    """캐시가 낡았을 때 — 요청은 낡은 값으로 즉시 답하고, 갱신은 뒤에서 한 번만.

    램 주의(라이브 워커 2·컨테이너 램 작음): 스레드는 키당 1개(single-flight)이고
    캐시엔 집계 결과 dict 만 남는다 — 원본 행(주문 2만행)은 스레드 안에서 버려진다.
    """
    with _cache_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def _run():
        try:
            fn()
        finally:
            with _cache_lock:
                _refreshing.discard(key)

    t = threading.Thread(target=_run, name=f'tower-swr-{key}', daemon=True)
    _refresh_threads[key] = t
    t.start()


def _iso(dt) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _to_int(v):
    """'84,550' → 84550. 못 읽으면 None(0 으로 지어내지 않는다)."""
    if v is None or v == '':
        return None
    try:
        return int(round(float(str(v).replace(',', ''))))
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════════════
#  판매 집계 — 주문 내역(MarketOrderLine) 한 번 스캔 → model_code 별 묶음
# ═══════════════════════════════════════════════════════════════════════════

#: 날짜 → 그 주 월요일. 주문 2만 행이 도는 자리라 같은 날짜를 다시 계산하지 않는다
#: (하루 한 칸 · 1년치라야 365칸 — 램 걱정 없는 크기).
_week_memo: dict[str, str | None] = {}


def _week_start(date_str: str) -> str | None:
    """'2026-08-06…' → 그 주 월요일 'YYYY-MM-DD'. 못 읽으면 None(지어내지 않는다)."""
    key = str(date_str)[:10]
    if key in _week_memo:
        return _week_memo[key]
    try:
        y, m, d = key.split('-')
        day = date(int(y), int(m), int(d))
        got = (day - timedelta(days=day.weekday())).isoformat()
    except (TypeError, ValueError):
        got = None
    if len(_week_memo) > 4000:            # 오래 뜬 워커에서 무한히 자라지 않게
        _week_memo.clear()
    _week_memo[key] = got
    return got


def _build_sales_index(s, days: int) -> dict:
    """model_code → 판매 집계. 원천 = 주문 내역(전 마켓 수집분).

    · 행 → SKU 매칭은 price_diff.resolve_targets_verbose **호출만**(재구현 금지).
    · 매출 = 행의 「상품금액」(단가×수량 — order_export 가 계산해 둔 열). 없으면
      단가×수량으로 같은 정의를 적용(다른 값을 지어내는 게 아니다).
    · 취소·반품(상태에 「취소」·「반품」 포함)은 판매 합계에서 빼고 따로 센다
      — 시안 문구 「취소·반품은 매출에서 뺀 값」.
    · 정산 예정 = 행의 `fulfillment.SETTLE_FIELD`(=「정산예정금(배송비포함)」)를
      **읽어 더하기만** 한다 — 재계산 금지. 칸 이름을 여기서 고르지 않고 그 상수를
      쓴다: 주문 3분류·마진 계산기가 쓰는 그 칸이라야 화면끼리 숫자가 안 갈린다
      (`orders/fulfillment.py:49`, `margin/sell_source.py:271` — 둘 다 같은 칸).
      값이 없는 행은 settle_missing 으로 센다(없는 값을 0 으로 지어내지 않고,
      상품분만 든 「정산예정금액」으로 대신 채우지도 않는다 — 정의가 다르다).
    · 실현 마진 = 정산 예정 − **실매입가**(설계서 §6.2·3단계). 아래 「실현 마진」 참고.
    · weeks = 주(월요일 시작) × 마켓별 판매 수량 — 판매 추이 그래프 재료.

    ## 실현 마진 (설계서 §6.2)

    `realized = Σ(정산예정금(배송비포함) − 실매입가)` — **실매입가가 있는 줄만** 더한다.

    · 매입가 원천은 `order_line_purchases` 하나(`markets/purchase_price.get_many`).
      🔴 `resolve_purchase_price` 를 쓰지 않는다 — 그건 없을 때 사입가·소싱 예상가로
      내려가는데, 「실현」은 실제로 낸 돈으로만 만들어야 한다(설계서 §4 「예상가로 낸
      마진은 실적 숫자에 섞지 않는다」).
    · 산식은 마진 계산기의 순마진(`margin_flags.recompute_row`: 정산 − 구매가격)과
      같다 — 수량을 다시 곱하지 않는다(실매입가는 그 줄에 실제로 쓴 돈이다).
    · 🔴 **0 으로 채우지 않는다.** 실매입가 없는 줄은 `pp_missing` 으로 세고,
      쓴 줄 수는 `realized_basis` 로 밝힌다(화면 「27건 중 3건 기준」).
      정산을 못 읽은 줄은 이미 `settle_missing` 이고, 실현 마진에서도 빠진다.
    · 기준 줄이 하나도 없으면 `realized=None`(= 「확인 불가」). 0 이 아니다.
    """
    from lemouton.markets import purchase_price as _pp
    from lemouton.markets.models_orders import MarketOrderLine
    from lemouton.orders.fulfillment import SETTLE_FIELD
    from lemouton.orders.price_diff import MATCH_OK, resolve_targets_verbose, row_key
    from lemouton.sourcing.models import Option

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    # [2026-08-07 속도] 쓰는 칸만 가져온다. 예전엔 줄 전체(15칸)를 ORM 개체로 만들어
    #   2만 줄이면 개체 2만 개를 짓고 안 쓰는 칸까지 서버에서 끌어왔다.
    #   여기서 실제로 쓰는 건 아래 5칸뿐이다(row = 화면·집계용 JSON).
    #   🔴 날짜 단독 인덱스(ix_mol_date)와 한 쌍 — 기존 인덱스는 (market, order_date)
    #      복합이라 날짜만으로 거르는 이 조회에는 못 쓴다(shared/db.py 주석).
    #   🔴 `line_uid` 를 빠뜨리면 실매입가 조회(_pp.get_many)가 조용히 비어
    #      「실현 마진」이 소리 없이 사라진다 — 쓰는 칸을 전수로 세어 넣었다.
    lines = (s.query(MarketOrderLine.line_uid, MarketOrderLine.market,
                     MarketOrderLine.order_date, MarketOrderLine.status,
                     MarketOrderLine.account, MarketOrderLine.row)
             .filter(MarketOrderLine.order_date >= cutoff)
             .order_by(MarketOrderLine.order_date.desc())
             .limit(_SALES_ROW_CAP).all())
    rows = [(ln, dict(ln.row or {})) for ln in lines]
    targets = resolve_targets_verbose(s, [r for _, r in rows])

    matched = []               # (sku, line, row)
    for ln, r in rows:
        t = targets.get(row_key(r))
        if t and t['reason'] == MATCH_OK and t['sku']:
            matched.append((t['sku'], ln, r))
    skus = {sku for sku, _, _ in matched}
    sku_model = {}
    if skus:
        sku_model = dict(s.query(Option.canonical_sku, Option.model_code)
                         .filter(Option.canonical_sku.in_(list(skus))).all())

    # 실매입가 — 사람이 적은 값만. 없는 줄은 키가 아예 없다(0 이 아니다).
    real_pp = _pp.get_many(s, [ln.line_uid for _, ln, _ in matched])

    per_model: dict[str, dict] = {}
    for sku, ln, r in matched:
        mc = sku_model.get(sku)
        if not mc:
            continue
        agg = per_model.setdefault(mc, {
            'qty': 0, 'revenue': 0, 'count': 0,
            'settle': None, 'settle_missing': 0,
            # 실현 마진 — realized=None 은 「쓸 수 있는 줄이 하나도 없음」(0 아님)
            'realized': None, 'realized_basis': 0, 'purchase': 0, 'pp_missing': 0,
            'cancels': {'count': 0, 'amount': 0},
            'markets': {}, 'recent': [], 'weeks': {},
            'truncated': len(lines) >= _SALES_ROW_CAP,
        })
        status = str(ln.status or r.get('주문상태') or '')
        qty = _to_int(r.get('수량')) or 0
        amount = _to_int(r.get('상품금액'))
        if amount is None:
            unit = _to_int(r.get('단가'))
            amount = unit * qty if (unit is not None and qty) else None
        settle = _to_int(r.get(SETTLE_FIELD))
        # 실매입가 — 사람이 적은 값만. 없으면 None(🔴 0 이 아니다).
        #   취소 줄도 최근 주문 표에 나오므로 분기 **밖**에서 구한다.
        _row_pp = real_pp.get(ln.line_uid)
        _buy = int(_row_pp.purchase_price) if _row_pp is not None else None
        entry = {
            'at': r.get('주문일') or ln.order_date or '',
            'market': ln.market, 'market_label': _MK_LABEL.get(ln.market, ln.market),
            'account': r.get('쇼핑몰별칭') or ln.account or '',
            'option': r.get('옵션') or '', 'qty': qty,
            'amount': amount, 'status': status, 'sku': sku,
            # [2026-08-12 노션] 최근 주문 표의 「실매입가」 칸. 줄 하나짜리라
            #   합계와 달리 「몇 건 기준」 오해가 없다 — 값 그대로 싣는다.
            'purchase': _buy,
        }
        if ('취소' in status) or ('반품' in status):
            agg['cancels']['count'] += 1
            if amount:
                agg['cancels']['amount'] += amount
        else:
            agg['qty'] += qty
            agg['revenue'] += amount or 0
            agg['count'] += 1
            if settle is not None:
                agg['settle'] = (agg['settle'] or 0) + settle
            else:
                agg['settle_missing'] += 1
            mk = agg['markets'].setdefault(ln.market, {
                'market': ln.market,
                'label': _MK_LABEL.get(ln.market, ln.market),
                'count': 0, 'qty': 0, 'revenue': 0,
                'settle': None, 'settle_missing': 0,
                'realized': None, 'realized_basis': 0,
                'purchase': 0, 'pp_missing': 0, 'last': ''})
            mk['count'] += 1
            mk['qty'] += qty
            mk['revenue'] += amount or 0
            if settle is not None:
                mk['settle'] = (mk['settle'] or 0) + settle
            else:
                mk['settle_missing'] += 1
            if entry['at'] > mk['last']:
                mk['last'] = entry['at']
            # ── 실현 마진 = 정산 − 실매입가 (실매입가 있는 줄만) ──────────
            if _buy is None:
                agg['pp_missing'] += 1
                mk['pp_missing'] += 1
            elif settle is not None:
                _gain = settle - _buy
                agg['realized'] = (agg['realized'] or 0) + _gain
                agg['realized_basis'] += 1
                agg['purchase'] += _buy
                mk['realized'] = (mk['realized'] or 0) + _gain
                mk['realized_basis'] += 1
                mk['purchase'] += _buy
            # 매입가는 있는데 정산을 못 읽은 줄 — settle_missing 에서 이미 세고,
            # 실현 마진에서도 뺀다(없는 정산을 0 으로 지어내지 않는다).
            wk = _week_start(entry['at'])
            if wk:
                wkm = agg['weeks'].setdefault(wk, {})
                wkm[ln.market] = wkm.get(ln.market, 0) + qty
        if len(agg['recent']) < 30:
            agg['recent'].append(entry)
        # 옵션별 순위 재료
        opt = agg.setdefault('by_option', {})
        if ('취소' not in status) and ('반품' not in status):
            o = opt.setdefault(sku, {'sku': sku, 'option': entry['option'],
                                     'qty': 0, 'revenue': 0,
                                     'purchase': 0, 'pp_basis': 0, 'pp_missing': 0})
            o['qty'] += qty
            o['revenue'] += amount or 0
            # [2026-08-12] 옵션별 실매입가 — 🔴 합계(agg['purchase'])와 **같은 기준**.
            #   정산도 있고 실매입가도 있는 줄만 더한다. 기준이 갈리면 옵션별 합이
            #   합계와 안 맞아 어느 쪽이 맞는지 알 수 없게 된다.
            if _buy is None:
                o['pp_missing'] += 1
            elif settle is not None:
                o['purchase'] += _buy
                o['pp_basis'] += 1
    return per_model


# ═══════════════════════════════════════════════════════════════════════════
#  실매입가 「버전 도장」 — 워커가 둘이어도 낡은 돈 숫자를 안 보여주기 위한 장치
# ═══════════════════════════════════════════════════════════════════════════
#
#  🔴 이 자리에서 실제로 났던 버그(라이브 실측 2026-08-06):
#     주문 내역에서 실매입가 50,000 을 저장한 **직후** 판매 이력(days=30)을 열면
#     `realized:null, pp_missing:27`(옛 값)이 나왔다. 같은 순간 days=29 로 물으면
#     캐시 키가 달라 새로 계산돼 `realized:60545, realized_basis:1` 로 **정상**이었다.
#     → 계산은 맞았고 300초 캐시만 낡아 있었다. 사장님은 「저장이 안 됐나?」로 읽는다.
#
#  왜 도장(stamp)인가 — 캐시는 **프로세스 메모리**다. 라이브는 워커 2개라
#  저장을 받은 워커에서 캐시를 비워도 **다른 워커는 그대로 옛 값을 준다**
#  (새로고침 두 번에 값이 왔다갔다 하는, 더 나쁜 그림). 그래서 워커들이 공유하는
#  DB 에 이미 있는 사실 하나를 도장으로 삼는다 — 새 표를 만들지 않는다.
#
#  도장 = (order_line_purchases 의 마지막 updated_at, 행 수). 두 값이 **다 필요**하다:
#    · 수정      → updated_at 이 지금으로 올라간다      → 앞이 바뀐다
#    · 신규 저장 → 행이 하나 는다                        → 뒤가 바뀐다
#    · 삭제      → 지운 게 최신 행이 아니면 updated_at 은 그대로다 → **뒤로만 잡힌다**
#  하나만 쓰면 삭제(=「매입가 지움」)를 놓친다 — 그게 이번 버그의 반대 방향 함정이다.
_PP_STAMP_UNKNOWN = '?'


def purchase_stamp(session=None) -> str:
    """`order_line_purchases` 의 버전 도장 한 줄. 못 읽으면 `'?'`.

    쿼리는 집계 2개(max·count) 하나뿐 — 주문 2만 행 스캔에 비하면 없는 값이다.
    못 읽었을 때 매번 다른 값을 지어내면 요청마다 전체 재계산이 되어 화면이 죽는다.
    그래서 고정 `'?'` 를 돌려주고(그때는 TTL 만으로 간다) 사유는 로그에 남긴다.
    """
    from sqlalchemy import func

    from lemouton.markets.models_purchase import OrderLinePurchase

    s, own = (session, False) if session is not None else (SessionLocal(), True)
    try:
        mx, cnt = (s.query(func.max(OrderLinePurchase.updated_at),
                           func.count(OrderLinePurchase.line_uid)).one())
        # SQLite 는 집계 결과를 문자열로 돌려주기도 한다 — 둘 다 받는다
        # (여기서 터지면 도장이 '?' 로 굳어 무효화가 통째로 죽는다).
        if mx is None:
            mark = '-'
        else:
            mark = mx.isoformat() if hasattr(mx, 'isoformat') else str(mx)
        return f'{mark}|{int(cnt or 0)}'
    except Exception:                                  # noqa: BLE001
        _log.exception('[tower] 실매입가 도장 조회 실패 — TTL 만으로 갑니다')
        return _PP_STAMP_UNKNOWN
    finally:
        if own:
            s.close()


def invalidate_sales_cache(reason: str = '') -> None:
    """실매입가가 바뀌었다 — **이 워커의** 판매 집계 캐시를 통째로 버린다.

    ## 왜 「그 상품만」이 아니라 통째인가

    캐시 한 칸의 내용물은 `{days: {model_code: 집계, …}}` 로, **한 번의 주문 스캔에서
    전 상품이 같이 나온 dict** 다. 그래서 한 상품만 도려내려면 그 상품 몫을 다시
    계산해야 하는데, 그건 주문 스캔을 한 번 더 도는 것이라 전체를 버리는 것보다
    싸지 않고 집계 규칙이 두 벌이 된다(재계산 금지 위반). 저장 시점에 model_code 를
    알아낸다 해도 **쓸 데가 없다** — 캐시의 최소 단위가 기간(days) 통짜다.

    기간별로 키가 갈리므로(30·60·365…) `clear()` 로 **모든 기간 키**를 버린다.
    이번 버그가 딱 그 자리였다 — days=30 만 낡고 days=29 는 멀쩡했다.

    이건 「빠른 길」일 뿐 안전장치는 아니다. 진짜 보증은 위 `purchase_stamp` 다
    (이 함수가 안 불려도, 다른 워커라도, 도장이 다르면 다시 계산된다).
    """
    with _cache_lock:
        n = len(_sales_cache)
        _sales_cache.clear()
    _log.info('[tower] 판매 집계 캐시 비움(기간 키 %d개) — %s',
              n, reason or '실매입가 변경')


def _rebuild_sales(days: int) -> dict:
    t0 = time.perf_counter()
    s = SessionLocal()
    stamp = _PP_STAMP_UNKNOWN
    try:
        # 🔴 도장은 **집계를 만들기 전에** 찍는다. 만드는 도중에 매입가가 바뀌면
        #    저장되는 도장이 옛 것이라 다음 요청이 한 번 더 만든다 — 놓치는 쪽이
        #    아니라 한 번 더 하는 쪽으로 틀린다(돈 숫자라 그래야 한다).
        stamp = purchase_stamp(s)
        data = _build_sales_index(s, days)
    except Exception:                                  # noqa: BLE001
        _log.exception('[tower] 판매 집계 실패 days=%s', days)
        data = {}
    finally:
        s.close()
    _log.info('[tower][perf] sales_index(%s) 재계산 %.0fms',
              days, (time.perf_counter() - t0) * 1000)
    with _cache_lock:
        _sales_cache[days] = (time.time(), stamp, data)
    return data


def sales_index(days: int = 30, *, fresh: bool = False) -> dict:
    """300초 캐시 + stale-while-revalidate — 목록(모든 상품)과 탭(상품 하나)이
    같은 스캔을 나눠 쓴다. 캐시가 낡았으면 **낡은 값을 즉시 돌려주고**
    갱신은 백그라운드 스레드 한 개가 한다(첫 요청만 동기).

    🔴 단 **실매입가가 바뀐 것은 예외** — 그건 「낡음」이 아니라 「틀림」이다.
    실현 마진이 통째로 달라지므로 옛 값을 먼저 주지 않고 여기서 즉시 다시 만든다
    (SWR 로 미루면 사장님이 저장 직후 「매입가 미입력」을 보고 저장이 안 된 줄 안다).
    """
    now = time.time()
    stamp = purchase_stamp()
    with _cache_lock:
        hit = _sales_cache.get(days)
    if hit and not fresh:
        if hit[1] != stamp:
            _log.info('[tower] 실매입가 변경 감지(%s → %s) — 판매 집계 즉시 재계산 days=%s',
                      hit[1], stamp, days)
            return _rebuild_sales(days)
        if now - hit[0] >= _CACHE_TTL:
            _kick_refresh(f'sales:{days}', lambda: _rebuild_sales(days))
        return hit[2]
    return _rebuild_sales(days)


# ═══════════════════════════════════════════════════════════════════════════
#  가격 대표값 — 최저 최종매입가(기존 계산 재사용) + 정책 판매가(preview 재사용)
# ═══════════════════════════════════════════════════════════════════════════

def _rep_policy_price(values: dict, purchase, market: str = 'smartstore'):
    """정책 판매가 하나 — preview 의 부품 함수들을 **호출만** 해 조립한다.

    대표 마켓 = 스마트스토어(시안 KPI 가 스스 정책가를 대표로 보여준다).
    마진율·지정가 둘 다 없으면 None — 빈칸을 0%로 읽지 않는다(preview 와 같은 규칙).
    """
    from lemouton.policy.preview import (
        _default_fee, fee_rate_of, fixed_amount_of, margin_rate_of,
        shipping_fee_of,
    )
    from lemouton.pricing.unified import compute_sale_price_unified
    rate = margin_rate_of(values)
    fixed = fixed_amount_of(values)
    if rate is None and fixed is None:
        return None
    if fixed is None and purchase is None:
        return None
    fee = fee_rate_of(values)
    # 🔴 즉시할인을 안 넘기면 목록만 실제 업로드가보다 낮은 값을 보여 준다.
    #   부담 규칙은 `policy/discount.seller_share` 한 곳만 쓴다.
    from lemouton.policy.discount import seller_share
    d_unit, d_value = seller_share((values or {}).get('price') or {})
    try:
        r = compute_sale_price_unified(
            purchase or 0,
            margin_rate=(rate if rate is not None else 0) / 100.0,
            fee_rate=(fee / 100.0 if fee is not None else _default_fee(market)),
            shipping_fee=shipping_fee_of(values), rounding_unit=100,
            mode=('fixed' if fixed is not None else 'rate'),
            fixed_price=(fixed or 0),
            seller_discount_unit=d_unit, seller_discount_value=d_value)
        return r.final_price
    except Exception:                                  # noqa: BLE001
        _log.exception('[tower] 정책 판매가 계산 실패')
        return None


def _build_price_index(s) -> dict:
    """model_code → {buy, sell, margin_pct, soldout, stock, opts, active,
                     policy_id, policy_name} — 목록 한 판을 배치 몇 개로.

    최종매입가는 matrix._rows_for(→ api_pricing 최종매입가)를 전 SKU 한 번에
    태운다 — 5쿼리 + 순수 계산이라 목록에서도 감당된다(N+1 아님).
    margin_pct = (판매가−매입가)/판매가 — **수수료 반영 전**(시안 겉 표와 동일 정의,
    수수료 반영 후는 펼침 「한눈에」·「마켓 등록·정책」 탭이 마켓별로 보여준다).
    """
    import json as _json
    from lemouton.policy.models import BundlePolicyLink, MarketPolicy, MarketPolicyValue
    from lemouton.sourcing.models import Model, Option
    from webapp.routes.matrix import _rows_for

    models = (s.query(Model.model_code)
              .filter(~Model.model_code.like('단독_%'),
                      Model.is_option_box.is_(False)).all())
    codes = [c for (c,) in models]
    out: dict[str, dict] = {c: {'buy': None, 'sell': None, 'margin_pct': None,
                                'soldout': 0, 'stock': None, 'opts': 0, 'active': 0,
                                'policy_id': None, 'policy_name': None}
           for c in codes}
    if not codes:
        return out

    opts = (s.query(Option.canonical_sku, Option.model_code, Option.is_active)
            .filter(Option.model_code.in_(codes)).all())
    sku_model = {}
    for sku, mc, active in opts:
        sku_model[sku] = mc
        out[mc]['opts'] += 1
        if active:
            out[mc]['active'] += 1

    rows, _c, _z = _rows_for(s, list(sku_model))
    for r in rows:
        mc = sku_model.get(r['sku'])
        if mc is None:
            continue
        st = out[mc]
        if r['min_final'] is not None and (st['buy'] is None or r['min_final'] < st['buy']):
            st['buy'] = r['min_final']
        if r['stock'] is not None:
            st['stock'] = (st['stock'] or 0) + max(r['stock'], 0)
            if r['stock'] == 0:
                st['soldout'] += 1

    # 정책 — 링크·정책·스스 판매가 항목을 각 1쿼리로
    links = {l.model_code: l.policy_id for l in
             s.query(BundlePolicyLink).filter(
                 BundlePolicyLink.model_code.in_(codes)).all()}
    pol_ids = list({v for v in links.values() if v})
    pols = {p.id: p for p in s.query(MarketPolicy)
            .filter(MarketPolicy.id.in_(pol_ids or [-1]),
                    MarketPolicy.deleted_at.is_(None)).all()}
    vals: dict[int, dict] = {}
    if pols:
        for v in (s.query(MarketPolicyValue)
                  .filter(MarketPolicyValue.policy_id.in_(list(pols)),
                          MarketPolicyValue.market == 'smartstore',
                          MarketPolicyValue.field_key.in_(('price', 'shipping')))
                  .all()):
            try:
                vals.setdefault(v.policy_id, {})[v.field_key] = \
                    _json.loads(v.value) if v.value else {}
            except (TypeError, ValueError):
                pass
    for mc, st in out.items():
        pid = links.get(mc)
        pol = pols.get(pid) if pid else None
        if pol is None:
            continue
        st['policy_id'] = pol.id
        st['policy_name'] = pol.name
        _v = vals.get(pol.id) or {}
        st['sell'] = _rep_policy_price(_v, st['buy'])
        if st['sell'] and st['buy']:
            # 🔴 마진율 분모는 **우리 수입 기준가**(판매가 − 우리 부담 할인)다.
            #   올려 잡은 판매가를 그대로 나누면 20% 할인 상품의 마진율이
            #   실제보다 높아 보인다(판매가가 25% 부풀어 있으니까).
            from lemouton.policy.discount import exposed_price, seller_share
            _단위, _몫 = seller_share((_v or {}).get('price') or {})
            기준 = exposed_price(st['sell'], {'value': _몫, 'unitType': _단위}) \
                if _몫 else st['sell']
            if 기준:
                st['margin_pct'] = round((기준 - st['buy']) / 기준 * 100, 1)
    return out


def _rebuild_prices() -> dict:
    global _price_cache
    t0 = time.perf_counter()
    s = SessionLocal()
    try:
        data = _build_price_index(s)
    except Exception:                                  # noqa: BLE001
        _log.exception('[tower] 가격 대표값 집계 실패')
        data = {}
    finally:
        s.close()
    _log.info('[tower][perf] price_index 재계산 %.0fms',
              (time.perf_counter() - t0) * 1000)
    with _cache_lock:
        _price_cache = (time.time(), data)
    return data


def price_index(*, fresh: bool = False) -> dict:
    """300초 캐시 + stale-while-revalidate — sales_index 와 같은 규칙."""
    now = time.time()
    with _cache_lock:
        hit = _price_cache
    if hit and not fresh:
        if now - hit[0] >= _CACHE_TTL:
            _kick_refresh('price', _rebuild_prices)
        return hit[1]
    return _rebuild_prices()


# ═══════════════════════════════════════════════════════════════════════════
#  소싱처 URL 합집합 — matrix._index_stats 와 같은 규칙(옵션 매칭 ∪ 모델 주소)
# ═══════════════════════════════════════════════════════════════════════════

def _url_union(s, code: str, skus: list[str]) -> list[dict]:
    """주소별 {label, kind, url, matched, status, fetched}. 실태 그대로 —
    옵션 매칭이 없어도 모델에 붙인 주소(BundleSourceUrl)는 「주소만」으로 보인다."""
    from sqlalchemy import func
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sources.site_labels import SITE_LABEL
    from lemouton.sourcing.models import BundleSourceUrl

    agg: dict[str, dict] = {}
    if skus:
        for url, site, status, fetched, matched in (
                s.query(SourceProduct.url, SourceProduct.site,
                        SourceProduct.last_status, SourceProduct.last_fetched_at,
                        func.count(OptionSourceLink.canonical_sku.distinct()))
                .join(SourceOption, SourceOption.source_product_id == SourceProduct.id)
                .join(OptionSourceLink,
                      OptionSourceLink.source_option_id == SourceOption.id)
                .filter(OptionSourceLink.canonical_sku.in_(skus))
                .group_by(SourceProduct.url, SourceProduct.site,
                          SourceProduct.last_status, SourceProduct.last_fetched_at)
                .all()):
            agg[url] = {'label': SITE_LABEL.get(site, site), 'kind': '옵션 매칭',
                        'url': url, 'matched': int(matched or 0),
                        'status': status, 'fetched': _iso(fetched)}
    burls = s.query(BundleSourceUrl).filter(
        BundleSourceUrl.model_code == code).all()
    extra = [b.url for b in burls if b.url not in agg]
    meta = {}
    if extra:
        meta = {sp.url: sp for sp in
                s.query(SourceProduct).filter(SourceProduct.url.in_(extra)).all()}
    for b in burls:
        if b.url in agg:
            if b.label:
                agg[b.url]['kind'] = b.label
            continue
        sp = meta.get(b.url)
        agg[b.url] = {
            'label': SITE_LABEL.get(b.source_key, b.source_key),
            'kind': b.label or '주소만(매칭 0)', 'url': b.url, 'matched': 0,
            'status': sp.last_status if sp else None,
            'fetched': _iso(sp.last_fetched_at) if sp else None}
    return sorted(agg.values(), key=lambda x: x['label'])


def _fail_count(urls: list[dict]) -> int:
    return sum(1 for u in urls if u['status'] in ('error', 'timeout'))


# ═══════════════════════════════════════════════════════════════════════════
#  마켓 등록 판정 — 3원천 합집합 (배지·markets 탭 공용)
# ═══════════════════════════════════════════════════════════════════════════

def _registered_markets(s, codes: list[str]) -> dict[str, set]:
    """model_code → 등록된 마켓 집합. **3원천 합집합** — 배치 4쿼리.

    [2026-08-06] MarketRegistration 하나만 보면 실제 판매 중 상품도 회색(미등록)으로
    나온다(사장님 실측). 등록 기록이 3벌로 나뉘어 있어서다:
      ① MarketRegistration(sku×market, market_product_id 있음) — 업로더가 남긴 기록
      ② SetChannel(status=linked = market_product_id 있음) ∪ SetChannelOption
         (status='matched') — 구성(세트) 연동 기록. price_diff._target_index 가
         주문 매칭에 쓰는 그 원천이라, 주문이 잡히는 상품은 여기라도 걸린다.
      ③ MarketProductGroup(model_code 연결) → MarketProduct(deleted_at 없음)
         — 마켓에서 거꾸로 긁어온 캐시를 사장님이 상품에 담은 기록.
    셋 다 실존 기록을 읽기만 한다 — 판정을 지어내지 않는다.
    """
    from lemouton.catalog.models import MarketProduct, MarketProductGroup
    from lemouton.sets.models import ProductSet, SetChannel, SetChannelOption
    from lemouton.sourcing.models import Option
    from lemouton.uploader.models import MarketRegistration

    out: dict[str, set] = {c: set() for c in codes}
    if not codes:
        return out
    # ① 업로더 기록
    for mc, mk in (s.query(Option.model_code, MarketRegistration.market)
                   .join(MarketRegistration,
                         MarketRegistration.canonical_sku == Option.canonical_sku)
                   .filter(Option.model_code.in_(codes),
                           MarketRegistration.market_product_id.isnot(None))
                   .distinct().all()):
        out[mc].add(mk)
    # ② 세트 채널 — 마켓 상품번호가 붙었거나(=linked), 옵션이 matched 로 이어졌거나
    for mc, mk in (s.query(ProductSet.model_code, SetChannel.market)
                   .join(SetChannel, SetChannel.set_id == ProductSet.id)
                   .filter(ProductSet.model_code.in_(codes),
                           SetChannel.market_product_id.isnot(None))
                   .distinct().all()):
        out[mc].add(mk)
    for mc, mk in (s.query(ProductSet.model_code, SetChannel.market)
                   .join(SetChannel, SetChannel.set_id == ProductSet.id)
                   .join(SetChannelOption,
                         SetChannelOption.channel_id == SetChannel.id)
                   .filter(ProductSet.model_code.in_(codes),
                           SetChannelOption.status == 'matched')
                   .distinct().all()):
        out[mc].add(mk)
    # ③ 마켓 캐시(그룹으로 담은 것)
    for mc, mk in (s.query(MarketProductGroup.model_code, MarketProduct.market)
                   .join(MarketProduct,
                         MarketProduct.group_id == MarketProductGroup.id)
                   .filter(MarketProductGroup.model_code.in_(codes),
                           MarketProductGroup.deleted_at.is_(None),
                           MarketProduct.deleted_at.is_(None))
                   .distinct().all()):
        out[mc].add(mk)
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  겉 목록 — /bundles
# ═══════════════════════════════════════════════════════════════════════════

@bp.route('/bundles')
def bundle_list():
    """컨트롤타워 목록 — 서랍(어디까지 왔나·브랜드·정렬은 화면 JS 가 거른다).

    서랍 숫자(사장님 확정 2026-08-06 — 4가지 상태, 겹치지 않게 나눠 센다):
      전체                                       = 단독_·옵션함 제외 모든 상품
      상품 생성                                   = 정책 ✕ · 마켓 ✕
      상품 생성 + 정책 적용                        = 정책 ○ · 마켓 ✕
      상품 생성 + 마켓 등록 (판매중) ※ 정책 미적용   = 정책 ✕ · 마켓 ○
      상품 생성 + 정책 적용 + 마켓 등록 (판매중)     = 정책 ○ · 마켓 ○
      손 볼 것                                    = 크롤 실패 주소>0 or 품절 옵션>0 or 정책 없음

    🔴 예전에는 `판매 중 = display_no 있는 것`이었다. 상품번호는 만들 때 무조건 붙어서
       90개 전부가 「판매 중」으로 나왔다(사장님 실측 — 옆칸 「올라간 마켓」은 전부 회색인데도).
       **마켓에 하나라도 올라간 것만 판매중**이다 — 판정은 _registered_markets(3원천 합집합).
    """
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import BundleSourceUrl, Model, Option
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct

    t_route = time.perf_counter()
    s = SessionLocal()
    try:
        models = (s.query(Model)
                  .filter(~Model.model_code.like('단독_%'),
                          Model.is_option_box.is_(False))
                  .order_by(Model.created_at.desc().nullslast()).all())
        codes = [m.model_code for m in models]

        prices = price_index()
        sales = sales_index(30)

        # 마켓 등록 — 3원천 합집합(배치 쿼리, N+1 없음)
        reg_by_model = _registered_markets(s, codes)
        # 정책 — 상품(BundlePolicyLink) ∪ 구성(SetPolicyLink). 배치 2쿼리.
        has_policy = policy_models(s, codes)

        # 크롤 실패 — URL 합집합(옵션 매칭 ∪ 모델 주소) 중 error/timeout. 배치 2쿼리.
        fail_by_model: dict[str, set] = {c: set() for c in codes}
        if codes:
            for mc, url, status in (
                    s.query(Option.model_code, SourceProduct.url,
                            SourceProduct.last_status)
                    .join(OptionSourceLink,
                          OptionSourceLink.canonical_sku == Option.canonical_sku)
                    .join(SourceOption,
                          SourceOption.id == OptionSourceLink.source_option_id)
                    .join(SourceProduct,
                          SourceProduct.id == SourceOption.source_product_id)
                    .filter(Option.model_code.in_(codes),
                            SourceProduct.last_status.in_(('error', 'timeout')))
                    .distinct().all()):
                fail_by_model[mc].add(url)
            burl_rows = (s.query(BundleSourceUrl.model_code, BundleSourceUrl.url)
                         .filter(BundleSourceUrl.model_code.in_(codes))
                         .distinct().all())
            burl_urls = {u for _, u in burl_rows}
            bad = {url for (url,) in
                   s.query(SourceProduct.url)
                   .filter(SourceProduct.url.in_(list(burl_urls) or ['']),
                           SourceProduct.last_status.in_(('error', 'timeout')))
                   .all()} if burl_urls else set()
            for mc, url in burl_rows:
                if url in bad:
                    fail_by_model[mc].add(url)

        # 편집 링크 — 이 상품이 태어난 원본 매트릭스(/optgen/product/<id>)
        matrix_by_model = {}
        if codes:
            for mo in (s.query(MatrixOption)
                       .filter(MatrixOption.model_code.in_(codes),
                               MatrixOption.kind == KIND_ORIGIN,
                               MatrixOption.deleted_at.is_(None)).all()):
                matrix_by_model.setdefault(mo.model_code, mo.id)

        items = []
        for m in models:
            c = m.model_code
            p = prices.get(c) or {}
            sl = sales.get(c) or {}
            fails = len(fail_by_model.get(c) or ())
            mkts = sorted(reg_by_model.get(c) or ())
            policy_on = c in has_policy
            stage = stage_of(policy_on, bool(mkts))
            selling = stage in SELLING_STAGES
            # 「정책 없음」도 구성 정책까지 보고 센다 — 안 그러면 손 볼 것이 부풀려진다
            issues = fails + (p.get('soldout') or 0) + (0 if policy_on else 1)
            items.append({
                'code': c, 'no': m.display_no or '',
                'name': m.model_name_display or m.model_name_raw or c,
                'brand': m.brand or '',
                'stage': stage, 'stage_label': STAGE_LABEL[stage],
                'stage_cls': STAGE_CLS[stage],
                'selling': selling,
                'buy': p.get('buy'), 'sell': p.get('sell'),
                'margin_pct': p.get('margin_pct'),
                'policy_id': p.get('policy_id'),
                # ── 목록 거르기(C3) 재료 — 🔴 **추가 쿼리 0**.
                #   전부 이미 손에 있는 값이다. 여기서 새로 물어보면 상품 수만큼
                #   쿼리가 늘어(N+1) 목록이 즉사한다(§6 조사: 소싱처 필터가 276쿼리).
                'policy_name': p.get('policy_name') or '',
                'category': m.category or '',
                'sold_qty': sl.get('qty'), 'sold_revenue': sl.get('revenue'),
                'markets': mkts,
                'fails': fails, 'soldout': p.get('soldout') or 0,
                'issues': issues,
                'matrix_id': matrix_by_model.get(c),
                'created': _iso(m.created_at),
            })

        counts = {
            'all': len(items),
            'selling': sum(1 for i in items if i['selling']),
            'idle': sum(1 for i in items if not i['selling']),
            'fix': sum(1 for i in items if i['issues'] > 0),
        }
        # 4가지 상태 — 겹치지 않게. 합은 반드시 counts['all'] 과 같다(화면 막대의 근거).
        for st in STAGES:
            counts['s%d' % st] = sum(1 for i in items if i['stage'] == st)
        brand_counts: dict[str, int] = {}
        for i in items:
            if i['brand']:
                brand_counts[i['brand']] = brand_counts.get(i['brand'], 0) + 1
        brands = sorted(brand_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    finally:
        s.close()
    _log.info('[tower][perf] /bundles 목록 %.0fms (상품 %d)',
              (time.perf_counter() - t_route) * 1000, len(items))
    return render_template('bundles/tower.html', active='bundles',
                           items=items, counts=counts, brands=brands,
                           tower_markets=TOWER_MARKETS,
                           stages=STAGES, stage_label=STAGE_LABEL,
                           stage_cls=STAGE_CLS)


# ═══════════════════════════════════════════════════════════════════════════
#  탭 API — /bundles/api/tower/<code>/…
# ═══════════════════════════════════════════════════════════════════════════

def _model_or_404(s, code: str):
    from lemouton.sourcing.models import Model
    return s.query(Model).filter_by(model_code=code).first()


@bp.get('/bundles/api/tower/<path:code>/summary')
def tower_summary(code: str):
    """탭① 한눈에 — KPI·마켓별 판매가/마진·지금 필요한 일·메타."""
    from lemouton.policy.preview import result_by_market
    from lemouton.policy.service import policy_of, readiness
    from lemouton.pricing import fee_defaults
    from lemouton.registration.models import CategoryMapRow
    from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
    from lemouton.sourcing.models import Option
    from lemouton.sourcing.models_pricing import OptionSourceUrl
    from lemouton.uploader.models import MarketRegistration
    from webapp.routes.matrix import _rows_for

    s = SessionLocal()
    try:
        m = _model_or_404(s, code)
        if m is None:
            return jsonify({'ok': False, 'error': '상품을 찾을 수 없어요.'}), 404
        opts = s.query(Option).filter_by(model_code=code).all()
        skus = [o.canonical_sku for o in opts]
        rows, colors, sizes = _rows_for(s, skus)
        finals = [r['min_final'] for r in rows if r['min_final']]
        buy = min(finals) if finals else None
        soldout = sum(1 for r in rows if r['stock'] == 0)
        known = [r['stock'] for r in rows if r['stock'] is not None and r['stock'] > 0]
        stock_sum = sum(known) if known else None
        purchase_extra = sum(o.boxhero_stock_total or 0 for o in opts
                             if o.use_purchase_inventory)

        # 정책 → 마켓별 표 (계산 = preview.result_by_market 그대로)
        pol = policy_of(s, code)
        fees = fee_defaults.load(s)
        markets_rows, rep_price, price_empty = [], None, []
        if pol is not None:
            rd = readiness(s, pol.id)
            res = result_by_market(s, model_code=code, policy_id=pol.id)
            for r in res['rows']:
                mk = r['market']
                fee = fees.get(mk) or {}
                markets_rows.append({
                    'market': mk, 'label': r['label'],
                    'price': r['price'], 'fee_pct': fee_defaults.pretty(
                        fee.get('base_pct')),
                    'margin': r['margin'], 'margin_rate': r['margin_rate'],
                    'ready': r['ready'], 'reason': r['reason'],
                    'price_ready': rd.get(mk, {}).get('price_ready', False),
                })
                if not rd.get(mk, {}).get('price_ready', False):
                    price_empty.append(r['label'])
            rep = next((x for x in markets_rows
                        if x['market'] == 'smartstore' and x['price']), None) \
                or next((x for x in markets_rows if x['price']), None)
            rep_price = rep['price'] if rep else None
        else:
            price_empty = [l for _, l, _g in TOWER_MARKETS]

        # 쿠팡 쿠폰적용 노출가 — 마켓 캐시 실측(coupang_coupon.enrich 가 채운 값)만.
        cp = _coupang_cached_exposed(s, skus)
        for r in markets_rows:
            if r['market'] == 'coupang' and cp:
                r['exposed'] = cp.get('exposed')
                r['coupon'] = cp.get('coupon')

        # 지금 필요한 일
        urls = _url_union(s, code, skus)
        fails = [u for u in urls if u['status'] in ('error', 'timeout')]
        fail_opts = sum(u['matched'] for u in fails)
        cat_pending = 0
        seen_paths = set()
        if skus:
            for site, path in (s.query(SourceProduct.site,
                                       SourceProduct.category_path)
                               .join(SourceOption,
                                     SourceOption.source_product_id
                                     == SourceProduct.id)
                               .join(OptionSourceLink,
                                     OptionSourceLink.source_option_id
                                     == SourceOption.id)
                               .filter(OptionSourceLink.canonical_sku.in_(skus))
                               .distinct().all()):
                if path:
                    seen_paths.add((site, path))
        if seen_paths:
            # [2026-08-06 속도] 경로마다 count 쿼리(N+1) → OR 묶음 1쿼리
            from sqlalchemy import and_, or_
            cat_pending = (s.query(CategoryMapRow)
                           .filter(or_(*[
                               and_(CategoryMapRow.source_id == site,
                                    CategoryMapRow.source_path == path)
                               for site, path in seen_paths]),
                               CategoryMapRow.status != 'confirmed')
                           .count())

        # 메타 — 마지막 수집·전송
        fetched = [u['fetched'] for u in urls if u['fetched']]
        osu_last = (s.query(OptionSourceUrl.last_checked_at)
                    .filter(OptionSourceUrl.canonical_sku.in_(skus or ['']))
                    .order_by(OptionSourceUrl.last_checked_at.desc()).first())
        if osu_last and osu_last[0]:
            fetched.append(_iso(osu_last[0]))
        last_send = None
        if skus:
            row = (s.query(MarketRegistration.last_success_at)
                   .filter(MarketRegistration.canonical_sku.in_(skus),
                           MarketRegistration.last_success_at.isnot(None))
                   .order_by(MarketRegistration.last_success_at.desc()).first())
            last_send = _iso(row[0]) if row else None

        sl = sales_index(30).get(code) or {}
        return jsonify({'ok': True,
            'kpi': {
                'sold_qty': sl.get('qty'), 'sold_revenue': sl.get('revenue'),
                'rep_price': rep_price, 'buy': buy,
                # 예상 마진(대표) — 시안 그대로 「수수료 반영 전」. 반영 후는 마켓 표.
                'rep_margin': (rep_price - buy) if (rep_price and buy) else None,
                'rep_margin_rate': (round((rep_price - buy) / rep_price * 100, 1)
                                    if (rep_price and buy) else None),
                'opts': len(opts),
                'active': sum(1 for o in opts if o.is_active),
                'soldout': soldout,
                'stock': stock_sum, 'purchase_stock': purchase_extra or 0,
            },
            'markets': markets_rows,
            'policy': ({'id': pol.id, 'name': pol.name} if pol else None),
            'todo': {
                'crawl_fail': {'urls': len(fails), 'options': fail_opts,
                               'labels': [u['label'] for u in fails]},
                'category_pending': cat_pending,
                'price_empty_markets': price_empty,
            },
            'meta': {
                'model_code': code, 'no': m.display_no,
                'brand': m.brand, 'name': m.model_name_display or m.model_name_raw,
                'created': _iso(m.created_at),
                'last_fetch': max(fetched) if fetched else None,
                'last_send': last_send,
            },
            'options': [{'sku': r['sku'], 'color': r['color'], 'size': r['size']}
                        for r in rows],
        })
    except Exception as e:                             # noqa: BLE001
        _log.exception('[tower] summary 실패 code=%s', code)
        return jsonify({'ok': False, 'error': f'불러오지 못했어요: {e}'}), 500
    finally:
        s.close()


def _coupang_cached_exposed(s, skus: list[str]) -> dict | None:
    """쿠팡 노출가 — 캐시(MarketProduct) 실측값만. 없으면 None(계산·추측 금지)."""
    from lemouton.catalog.models import MarketProduct
    from lemouton.uploader.models import MarketRegistration
    if not skus:
        return None
    reg = (s.query(MarketRegistration)
           .filter(MarketRegistration.canonical_sku.in_(skus),
                   MarketRegistration.market == 'coupang',
                   MarketRegistration.market_product_id.isnot(None)).first())
    if reg is None:
        return None
    mp = (s.query(MarketProduct)
          .filter(MarketProduct.market == 'coupang',
                  MarketProduct.market_product_id == str(reg.market_product_id),
                  MarketProduct.deleted_at.is_(None)).first())
    if mp is None or mp.exposed_price is None:
        return None
    coupon = (mp.sale_price - mp.exposed_price) \
        if (mp.sale_price is not None and mp.sale_price >= mp.exposed_price) else None
    return {'exposed': mp.exposed_price, 'coupon': coupon}


@bp.get('/bundles/api/tower/<path:code>/sales')
def tower_sales(code: str):
    """탭⑥ 판매 이력 — 주문 내역 원천.

    · 정산 예정 = 주문 행의 `정산예정금(배송비포함)` 합(읽기만 — 재계산 금지).
    · 실현 마진 = 정산 예정 − **실매입가**(설계서 §6.2·3단계). 산식·거르개는
      `_build_sales_index` 주석 참고. 🔴 실매입가가 없는 줄은 0 으로 채우지 않고
      `pp_missing` 으로 세어 화면이 「매입가 미입력 N건」이라 말하게 한다.
      쓴 줄 수(`realized_basis`)도 같이 내보내 「N건 중 B건 기준」으로 밝힌다.
    · 🔴 예상가·사입가로는 실현 마진을 만들지 않는다 — 그건 「예상」이지 실적이 아니다.
      그 값들은 옵션 매트릭스의 「최종매입가」 쪽에서 따로 보여 준다.
    · 1단계 이전 기록: 실현 마진을 낼 수 없던 이유는 매입가가 서버에 없었기
      때문이다(더망고 엑셀 안에만 있었다). 이제 `order_line_purchases` 가
      단일 원천이라 상품 축(`canonical_sku`→`model_code`)으로 좁힐 수 있다.
      마진 계산기 화면은 **하나도 안 건드린다** — 링크는 그대로 남긴다.
    """
    s = SessionLocal()
    try:
        if _model_or_404(s, code) is None:
            return jsonify({'ok': False, 'error': '상품을 찾을 수 없어요.'}), 404
    finally:
        s.close()
    try:
        days = max(1, min(365, int(request.args.get('days') or 30)))
    except (TypeError, ValueError):
        days = 30
    fresh = request.args.get('fresh') == '1'
    agg = sales_index(days, fresh=fresh).get(code) or {}
    markets = sorted((agg.get('markets') or {}).values(),
                     key=lambda x: -x['revenue'])
    by_opt = sorted((agg.get('by_option') or {}).values(),
                    key=lambda x: -x['qty'])[:8]
    recent = sorted(agg.get('recent') or [], key=lambda x: x['at'],
                    reverse=True)[:5]
    # 주 단위 추이 — 판매 추이 그래프 재료(주=월요일 시작, 오름차순)
    weeks = [{'week': wk, 'by_market': bm}
             for wk, bm in sorted((agg.get('weeks') or {}).items())]
    return jsonify({'ok': True, 'days': days,
                    'total': {'qty': agg.get('qty', 0),
                              'revenue': agg.get('revenue', 0),
                              'count': agg.get('count', 0),
                              # 정산 예정 — 저장된 「정산예정금(배송비포함)」 합
                              # (재계산 아님). None = 이 기간에 값 가진 행이
                              # 하나도 없음 → 화면은 「확인 불가」로 적는다.
                              'settle': agg.get('settle'),
                              'settle_missing': agg.get('settle_missing', 0),
                              # 실현 마진 — 실매입가가 있는 줄만. None = 쓸 줄 없음
                              'realized': agg.get('realized'),
                              'realized_basis': agg.get('realized_basis', 0),
                              'purchase': agg.get('purchase', 0),
                              'pp_missing': agg.get('pp_missing', 0)},
                    'cancels': agg.get('cancels') or {'count': 0, 'amount': 0},
                    'markets': markets, 'top_options': by_opt, 'recent': recent,
                    'weeks': weeks,
                    'truncated': bool(agg.get('truncated')),
                    'margin_link': '/orders/?tab=margin',
                    # 「매입가 미입력」 탭이 열린 채로 주문 내역을 연다(설계서 §6.1)
                    'nopp_link': '/orders/?tab=list&mg=nopp'})


@bp.get('/bundles/api/tower/<path:code>/matrix')
def tower_matrix(code: str):
    """탭② 옵션 매트릭스 — matrix._rows_for 값 그대로(재계산 없음)."""
    from lemouton.sources.models import SourceProduct
    from lemouton.sourcing.models import Option
    from webapp.routes.matrix import _rows_for
    s = SessionLocal()
    try:
        if _model_or_404(s, code) is None:
            return jsonify({'ok': False, 'error': '상품을 찾을 수 없어요.'}), 404
        opts = s.query(Option).filter_by(model_code=code).all()
        skus = [o.canonical_sku for o in opts]
        rows, colors, sizes = _rows_for(s, skus)
        pinfo = {o.canonical_sku: (o.use_purchase_inventory,
                                   o.boxhero_stock_total or 0) for o in opts}
        # 소싱처 셀 상세에 수집 시각·상태를 붙인다(있는 값만)
        urls = {x['url'] for r in rows for x in r['sources'] if x['url']}
        meta = {}
        if urls:
            for sp in s.query(SourceProduct).filter(
                    SourceProduct.url.in_(list(urls))).all():
                meta[sp.url] = {'status': sp.last_status,
                                'fetched': _iso(sp.last_fetched_at)}
        cells = []
        for r in rows:
            best = None
            for x in r['sources']:
                if x['final'] is not None and (best is None
                                               or x['final'] < best['final']):
                    best = x
            up, pstock = pinfo.get(r['sku'], (False, 0))
            cells.append({
                'sku': r['sku'], 'color': r['color'], 'size': r['size'],
                'min_final': r['min_final'], 'stock': r['stock'],
                'soldout': r['stock'] == 0,
                'src': best['label'] if best else None,
                'purchase_stock': pstock if up else 0,
                'sources': [dict(x, **meta.get(x['url'], {}))
                            for x in r['sources']],
            })
        return jsonify({'ok': True, 'colors': colors, 'sizes': sizes,
                        'cells': cells})
    except Exception as e:                             # noqa: BLE001
        _log.exception('[tower] matrix 실패 code=%s', code)
        return jsonify({'ok': False, 'error': f'불러오지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.get('/bundles/api/tower/<path:code>/sources')
def tower_sources(code: str):
    """탭③ 소싱처 수집 이력 — 주소별 상태 + 최근 실행 기록(BundleRun)."""
    import json as _json
    from lemouton.sourcing.models import BundleRun, Option
    s = SessionLocal()
    try:
        if _model_or_404(s, code) is None:
            return jsonify({'ok': False, 'error': '상품을 찾을 수 없어요.'}), 404
        skus = [o.canonical_sku for o in
                s.query(Option).filter_by(model_code=code).all()]
        urls = _url_union(s, code, skus)
        runs = []
        for r in (s.query(BundleRun).filter(BundleRun.model_code == code)
                  .order_by(BundleRun.started_at.desc()).limit(10).all()):
            note = ''
            try:
                d = _json.loads(r.details_json or '{}')
                srcs = d.get('sources') or {}
                ok = sum(1 for v in srcs.values() if v.get('ok'))
                if srcs:
                    note = f'소싱처 {ok}/{len(srcs)} 성공'
            except Exception:                          # noqa: BLE001
                pass
            runs.append({'phase': r.phase, 'status': r.status, 'note': note,
                         'at': _iso(r.started_at)})
        return jsonify({'ok': True, 'total': len(skus), 'urls': urls,
                        'fail': _fail_count(urls), 'runs': runs})
    except Exception as e:                             # noqa: BLE001
        _log.exception('[tower] sources 실패 code=%s', code)
        return jsonify({'ok': False, 'error': f'불러오지 못했어요: {e}'}), 500
    finally:
        s.close()


#: 상품명을 「이 상품만」으로 덮어쓸 수 있는 마켓 — 담을 칸이 있는 곳만.
#:   🔴 나머지 4마켓엔 칸이 아예 없다. 화면에 내주면 없는 기능을 광고하게 된다.
#:   🔴 이 칸들은 **전송 코드가 이미 읽고 있었는데**(registration/coupang.py:106 ·
#:     smartstore.py:85) 적을 화면이 없어 **늘 비어 있었다**(인수인계 C1 「죽은 자료」).
_NAME_OVERRIDE_COL = {'coupang': 'coupang_product_name_override',
                      'smartstore': 'naver_product_name_override'}


def _coupon_status(s, code: str) -> dict:
    """쿠팡 쿠폰 — 지금 어떤 상태인지 화면이 가를 수 있게.

    돌려주는 것:
      coupon_state : none(아직) | queued(대기 중) | applied(걸림) | failed(실패)
      coupon_have  : 쿠팡에 **실제로 걸린** 값(쿠폰이 만든 것)
      coupon_want  : 우리가 **걸려는** 값(정책 또는 이 상품만의 값)
      coupon_own   : 「비정책」인가 — 정책을 바꿔도 안 따라가는 상품인가
      coupon_from  : 다음날 0시부터 — 언제부터 적용되나
      coupon_msg   : 실패했으면 왜인지(사람 말)

    🔴 `have` 와 `want` 를 **따로** 준다. 둘이 다를 수 있고(예: 아직 안 걸림),
      그 차이가 곧 「지금 할인이 나가고 있나」의 답이다. 하나로 합치면 못 가른다.
    """
    from lemouton.policy import coupon_service as CS
    out = {'coupon_state': 'none', 'coupon_have': None, 'coupon_want': None,
           'coupon_own': False, 'coupon_from': None, 'coupon_msg': ''}
    try:
        chans = CS.channels_of_model(s, code)
    except Exception:                                   # noqa: BLE001
        return out
    if not chans:
        return out
    ch = chans[0]                     # 구성이 여럿이면 첫 구성 — 표는 마켓당 한 줄이다
    rec = CS.record_of(ch)
    ov = CS.override_of(ch)
    queued = bool((ch.api_fields or {}).get(CS.REQUEST_KEY))
    want = CS.effective_discount(s, ch)
    out['coupon_own'] = (ov['mode'] == 'own')
    out['coupon_want'] = (want or {}).get('value')
    out['coupon_have'] = rec.get('value') if rec.get('ok') else None
    out['coupon_from'] = rec.get('starts_at')
    out['coupon_msg'] = rec.get('message') or ''
    if queued:
        out['coupon_state'] = 'queued'
    elif rec.get('ok'):
        out['coupon_state'] = 'applied'
    elif rec:
        out['coupon_state'] = 'failed'
    return out


@bp.get('/bundles/api/tower/<path:code>/markets')
def tower_markets_api(code: str):
    """탭④ 마켓 등록·정책 — 정책 계산(preview)·등록 실태(MarketRegistration)·
    등록 상품명(MarketProduct 캐시 — 없으면 null, 지어내지 않음)."""
    from lemouton.catalog.models import MarketProduct
    from lemouton.policy.preview import result_by_market
    from lemouton.policy.service import policy_of, readiness, values_for
    from lemouton.pricing import fee_defaults
    from lemouton.sourcing.models import Option
    from lemouton.uploader.models import MarketRegistration

    s = SessionLocal()
    try:
        if _model_or_404(s, code) is None:
            return jsonify({'ok': False, 'error': '상품을 찾을 수 없어요.'}), 404
        opts = s.query(Option).filter_by(model_code=code).all()
        axis = {o.canonical_sku:
                ' '.join(filter(None, [o.color_display or o.color_code,
                                       o.size_display or o.size_code]))
                for o in opts}
        skus = list(axis)
        pol = policy_of(s, code)
        res_rows = {}
        rd = {}
        if pol is not None:
            rd = readiness(s, pol.id)
            for r in result_by_market(s, model_code=code,
                                      policy_id=pol.id)['rows']:
                res_rows[r['market']] = r
        fees = fee_defaults.load(s)
        regs = (s.query(MarketRegistration)
                .filter(MarketRegistration.canonical_sku.in_(skus or [''])).all())
        by_mk: dict[str, list] = {}
        for r in regs:
            by_mk.setdefault(r.market, []).append(r)
        cp = _coupang_cached_exposed(s, skus)

        # 등록 판정 = 3원천 합집합(목록 배지와 같은 판정 — 화면끼리 안 갈리게)
        reg_union = _registered_markets(s, [code]).get(code) or set()
        # 원천 ②③의 마켓 상품번호 — MarketRegistration 에 없을 때 이름 붙일 실마리
        from lemouton.catalog.models import MarketProductGroup
        from lemouton.sets.models import ProductSet, SetChannel
        ch_pid = dict(s.query(SetChannel.market, SetChannel.market_product_id)
                      .join(ProductSet, ProductSet.id == SetChannel.set_id)
                      .filter(ProductSet.model_code == code,
                              SetChannel.market_product_id.isnot(None)).all())
        grp_mp = {}
        for _mp in (s.query(MarketProduct)
                    .join(MarketProductGroup,
                          MarketProductGroup.id == MarketProduct.group_id)
                    .filter(MarketProductGroup.model_code == code,
                            MarketProductGroup.deleted_at.is_(None),
                            MarketProduct.deleted_at.is_(None)).all()):
            grp_mp.setdefault(_mp.market, _mp)

        out = []
        for mk, label, _g in TOWER_MARKETS:
            rows = by_mk.get(mk) or []
            reg_pid = next((r.market_product_id for r in rows
                            if r.market_product_id), None) or ch_pid.get(mk)
            mp = None
            if reg_pid:
                mp = (s.query(MarketProduct)
                      .filter(MarketProduct.market == mk,
                              MarketProduct.market_product_id == str(reg_pid),
                              MarketProduct.deleted_at.is_(None)).first())
            if mp is None:
                mp = grp_mp.get(mk)
            lasts = [r.last_success_at for r in rows if r.last_success_at]
            pr = res_rows.get(mk) or {}
            item = {
                'market': mk, 'label': label,
                'policy': ({'id': pol.id, 'name': pol.name} if pol else None),
                'policy_price': pr.get('price'),
                'price_ready': rd.get(mk, {}).get('price_ready', False),
                'reason': pr.get('reason') or ('정책이 아직 없어요.'
                                               if pol is None else ''),
                'fee_pct': fee_defaults.pretty((fees.get(mk) or {}).get('base_pct')),
                'margin': pr.get('margin'), 'margin_rate': pr.get('margin_rate'),
                'registered': bool(reg_pid) or (mk in reg_union),
                'reg_name': (mp.name if mp else None),
                'reg_status': (mp.status if mp else None),
                # 마켓에 실제로 등록된 카테고리(캐시). 없으면 null — 화면이 「왜 없는지」를
                #  구분해서 말한다.
                # 🔴 [2026-08-12 정정] 롯데온을 「영영 못 받음」으로 두던 것을 거둔다.
                #   목록 API 에 없는 건 맞지만 **상세(product/detail)에는 scatNo·dcatLst 가
                #   온다**(등록이 그 두 필드를 복사해 라이브 성공 — products.py
                #   _REGISTER_TEMPLATE_FIELDS · 2026-07-21). 이제 판매가를 채우는 그 상세
                #   호출에서 카테고리도 같이 거둔다(catalog/lotteon_prices.category_of).
                #   → 아직 안 채워진 롯데온 줄은 「불러오기를 다시 하면 채워져요」가 **참**이다.
                'reg_category': (mp.category_code if mp else None),
                'reg_category_name': (mp.category_name if mp else None),
                # 롯데온만 채워지는 경로가 다르다(목록이 아니라 상세) → 화면이 그렇게 말한다.
                'category_via_detail': (mk == 'lotteon'),
                'last_send': _iso(max(lasts)) if lasts else None,
                'options': [{
                    'sku': r.canonical_sku,
                    'option': axis.get(r.canonical_sku, r.canonical_sku),
                    'market_option_id': r.market_option_id,
                    'last_synced_price': r.last_synced_price,
                    'last_synced_stock': r.last_synced_stock,
                    'last_success_at': _iso(r.last_success_at),
                    'status': r.status,
                } for r in sorted(rows, key=lambda x: x.canonical_sku)],
            }
            if mk == 'coupang' and cp:
                item['exposed'] = cp.get('exposed')
                item['coupon'] = cp.get('coupon')
            if mk == 'coupang':
                # 🔴 쿠폰은 **쿠팡만** 있다 — 다른 마켓에 붙이면 화면이 없는 기능을 광고한다.
                item.update(_coupon_status(s, code))
            # 상품명 「이 상품만」 — 칸이 있는 마켓만(쿠팡·스마트스토어).
            _col = _NAME_OVERRIDE_COL.get(mk)
            if _col:
                from lemouton.registration.market_limits import (
                    name_limit_unknown_reason, name_max_len)
                _v = getattr(_model_or_404(s, code), _col, None)
                item['name_override'] = _v
                item['name_own'] = bool(_v)
                # 글자수 카운터용 — 🔴 상한을 **모르면 지어내지 않고** 왜 모르는지를 준다.
                #   지어낸 상한으로 상품명을 자르면 그게 더 큰 손해다.
                item['name_cap'] = name_max_len(mk)
                item['name_cap_reason'] = name_limit_unknown_reason(mk)
            out.append(item)
        return jsonify({'ok': True, 'markets': out,
                        'policy': ({'id': pol.id, 'name': pol.name}
                                   if pol else None)})
    except Exception as e:                             # noqa: BLE001
        _log.exception('[tower] markets 실패 code=%s', code)
        return jsonify({'ok': False, 'error': f'불러오지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/bundles/api/tower/<path:code>/crawl-now')
def tower_crawl_now(code: str):
    """「이 상품 지금 수집」 — 크롤 큐에 우선순위 50 잡. 실제 수집은 로컬 확장이.

    enqueue_crawl 은 (model_code, priority, dedup) 시그니처 — 같은 대상의 미완
    잡이 있으면 그대로 재사용된다(기존 dedup 규칙, 재구현 안 함).
    """
    from lemouton.sourcing.crawl_queue import enqueue_crawl
    s = SessionLocal()
    try:
        if _model_or_404(s, code) is None:
            return jsonify({'ok': False, 'error': '상품을 찾을 수 없어요.'}), 404
    finally:
        s.close()
    try:
        got = enqueue_crawl(code, triggered_by='tower', priority=50)
    except Exception as e:                             # noqa: BLE001
        _log.exception('[tower] crawl-now 실패 code=%s', code)
        return jsonify({'ok': False, 'error': f'큐에 넣지 못했어요: {e}'}), 500
    return jsonify({'ok': True, 'queued': bool(got.get('created')),
                    'job_id': got.get('id'), 'status': got.get('status')})
