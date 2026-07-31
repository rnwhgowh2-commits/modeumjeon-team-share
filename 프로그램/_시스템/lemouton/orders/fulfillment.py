"""주문 3분류 — 이행 / 미이행(재고없음·역마진) / 클레임.

사장님 확정 (2026-07-31):
    · S(재고없음) = 소싱처 URL 을 보면 재고를 알 수 있으니 그걸로 판정한다
    · P(역마진)   = 정산예정금(배송비포함) − 최종매입가 < 0 이면 역마진,
                    > 0 이면 이행 가능
    · 자동으로 판정한다

■ 계산식을 여기서 만들지 않는다
  최종매입가·SKU 매칭은 `orders.price_diff` 가 이미 하고 있다. 같은 값을 여기서
  또 만들면 두 화면이 다른 답을 내고, 이 저장소에서 그건 곧 금전 사고다.
  이 모듈은 **판정만** 한다.

■ 매출 기준 = `정산예정금(배송비포함)`
  마켓이 준 실값이다. 수수료율로 되계산하지 않는다 — 마켓마다 떼는 방식이 달라
  되계산하면 「에러 없이 틀린 숫자」가 된다(memory: 정답지=정산예정금(배송비포함)).

■ 🔴 모르면 「확인 불가」다 — 미이행도 이행도 아니다
  재고를 못 읽었거나 매입가를 못 구한 주문을 미이행으로 넣으면 **팔 수 있는 주문을
  버린다**. 반대로 이행으로 넣으면 손해 보는 주문을 그냥 내보낸다. 둘 다 돈이 샌다.
  그래서 확인 불가는 미이행 안에 **별도 사유**로 세워 눈으로 확인하게 한다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

GROUP_FULFILL = 'fulfill'        # 이행 — 보낼 수 있다
GROUP_UNFULFILL = 'unfulfill'    # 미이행 — 못 보낸다(사유 있음)
GROUP_CLAIM = 'claim'            # 클레임 — 취소·반품·교환

REASON_STOCK = 'S'               # 재고 없음
REASON_LOSS = 'P'                # 역마진
#: 🔴 「우리 상품이 아니다」와 「우리 상품인데 못 정했다」는 **다른 말**이다.
#:   뭉개면 모음전으로 관리하지도 않는 남의 상품 주문이 전부 「프로그램이 실패했다」로
#:   보인다 — 라이브 실측(2026-07-31) 쿠팡 97건 중 95건이 잔스포츠·마스마룰즈 등
#:   우리 시스템에 아예 없는 상품이었다.
REASON_NOT_OURS = 'not_ours'     # 모음전으로 관리하지 않는 상품 — 고칠 것이 없다
REASON_UNKNOWN = 'unknown'       # 우리 상품인데 자동 판정 불가 — 눈으로 확인
REASON_OTHER = 'other'           # 사람이 지정한 그 밖의 사유

GROUP_LABEL = {GROUP_FULFILL: '이행', GROUP_UNFULFILL: '미이행', GROUP_CLAIM: '클레임'}
REASON_LABEL = {REASON_STOCK: '재고없음', REASON_LOSS: '역마진',
                REASON_NOT_OURS: '우리 상품 아님',
                REASON_UNKNOWN: '확인 불가', REASON_OTHER: '기타'}

#: 매출 기준 칸. 이름을 바꾸지 않는다 — 엑셀 열문자가 아니라 필드명이 계약이다.
SETTLE_FIELD = '정산예정금(배송비포함)'


def _to_int(v):
    """숫자로 못 읽으면 None. 0 은 값이다(빈칸과 다르다)."""
    if v is None or v == '':
        return None
    try:
        return int(round(float(str(v).replace(',', '').replace('원', '').strip())))
    except (ValueError, TypeError):
        return None


def stock_state(option: dict) -> str:
    """소싱처 재고 3상태 — 'in' | 'out' | 'unknown'.

    ★ 「품절」과 「모름」을 뭉개지 않는다. 크롤이 실패했거나 아직 안 돈 옵션을
      품절로 읽으면 팔 수 있는 주문이 미이행으로 빠진다
      (memory: project_stock_parse_fail_unknown_gate).
    """
    srcs = (option or {}).get('sources') or []
    usable = [s for s in srcs if s.get('last_status') != 'error'
              and (s.get('crawled_price') or 0) > 0]
    if not usable:
        return 'unknown'                       # 값을 준 소싱처가 하나도 없다
    if any(not s.get('stock_out') for s in usable):
        return 'in'
    return 'out'                               # 값은 있는데 전부 품절


def _memo_matrix_loader(base=None):
    """모델코드당 매트릭스를 **한 번만** 읽는 로더. price_diff 와 나눠 쓴다."""
    if base is None:
        from webapp.routes.api_pricing import _option_matrix_data as base
    cache = {}

    def load(model_code):
        if model_code not in cache:
            cache[model_code] = base(model_code)
        return cache[model_code]
    load.cache = cache
    return load


def classify_rows(session, rows, *, matrix_loader=None) -> dict:
    """주문 행 목록 → {행키: {group, reason, stock, purchase, settle, profit}}.

    행키는 `price_diff.row_key` 와 **같은 것**을 쓴다 — 화면이 두 결과를 같은 행에
    붙여야 하는데 키가 다르면 붙지 않는다.
    """
    from lemouton.claims.service import claim_type_of
    from lemouton.orders import price_diff as _pd
    from lemouton.sourcing.models import Option

    out = {}
    rows = list(rows or [])
    if not rows:
        return out

    # ── 1) 클레임 먼저 갈라낸다 — 판정 자체가 필요 없다 ──────────────────────
    rest = []
    for r in rows:
        key = _pd.row_key(r)
        if claim_type_of(r):
            out[key] = {'group': GROUP_CLAIM, 'reason': None,
                        'claim_type': claim_type_of(r),
                        'stock': None, 'purchase': None,
                        'settle': _to_int(r.get(SETTLE_FIELD)), 'profit': None}
        else:
            rest.append(r)
    if not rest:
        return out

    loader = matrix_loader or _memo_matrix_loader()

    # ── 2) 주문행 → 우리 옵션(SKU). 매칭은 price_diff 것을 그대로 쓴다 ───────
    #   verbose 를 쓰는 이유: **왜 못 찾았는지**가 사장님에게 다른 뜻이기 때문이다.
    #   「우리 상품이 아니다」는 고칠 것이 없고, 「못 좁혔다」는 봐야 할 일이다.
    try:
        targets = _pd.resolve_targets_verbose(session, rest)
    except Exception:                       # noqa: BLE001
        logger.exception('주문→옵션 매칭 실패 — %d건 확인 불가', len(rest))
        targets = {}

    sku_by_key = {k: v['sku'] for k, v in (targets or {}).items() if v.get('sku')}
    #: 우리 연동 목록에 없다 = 모음전으로 관리하지 않는 상품
    #:   ① 번호를 줬는데 색인에 없다  ② 그 마켓에 연동이 한 건도 없다
    #:   ★ 연동이 통째로 0건인 상태(MATCH_NO_LINKS)는 여기 넣지 않는다 — 그건
    #:     「남의 상품」이 아니라 「판단할 근거가 없다」이다.
    not_ours = {k for k, v in (targets or {}).items()
                if v.get('reason') == _pd.MATCH_NOT_OURS}
    skus = sorted(set(sku_by_key.values()))

    # ── 3) 최종매입가 — price_diff 단일 원천 ────────────────────────────────
    finals = {}
    if skus:
        try:
            finals, _errs = _pd._current_purchase(session, skus, matrix_loader=loader)
        except Exception:                   # noqa: BLE001
            logger.exception('최종매입가 조회 실패 — %d건 확인 불가', len(skus))

    # ── 4) 재고 — 같은 매트릭스에서 읽는다(다시 부르지 않는다) ──────────────
    stock_by_sku = {}
    if skus:
        model_by_sku = {o.canonical_sku: o.model_code
                        for o in session.query(Option)
                        .filter(Option.canonical_sku.in_(skus)).all()}
        for mc in sorted(set(model_by_sku.values())):
            data = None
            try:
                data = loader(mc)
            except Exception:               # noqa: BLE001
                logger.exception('옵션 매트릭스 조회 실패 model=%s', mc)
            if not data or not data.get('ok'):
                continue
            for o in (data.get('options') or []):
                if o.get('sku') in model_by_sku:
                    stock_by_sku[o['sku']] = stock_state(o)

    # ── 5) 판정 ─────────────────────────────────────────────────────────────
    for r in rest:
        key = _pd.row_key(r)
        sku = sku_by_key.get(key)
        settle = _to_int(r.get(SETTLE_FIELD))
        purchase = finals.get(sku) if sku else None
        stock = stock_by_sku.get(sku) if sku else None
        profit = (settle - purchase) if (settle is not None and purchase is not None) else None

        d = {'sku': sku, 'stock': stock, 'purchase': purchase,
             'settle': settle, 'profit': profit}
        if stock == 'out':
            d.update(group=GROUP_UNFULFILL, reason=REASON_STOCK)
        elif profit is not None and profit < 0:
            d.update(group=GROUP_UNFULFILL, reason=REASON_LOSS)
        elif stock == 'in' and profit is not None:
            d.update(group=GROUP_FULFILL, reason=None)
        elif key in not_ours:
            # 모음전으로 관리하지 않는 상품이다 — 고칠 것이 없다.
            # 「확인 불가」로 뭉개면 남의 상품 주문이 전부 문제처럼 보인다.
            d.update(group=GROUP_UNFULFILL, reason=REASON_NOT_OURS)
        else:
            # 우리 상품인데 재고를 못 읽었거나 매입가·정산예정금을 못 구했다.
            # 「보낼 수 있다」고도 「못 보낸다」고도 말하지 않는다.
            d.update(group=GROUP_UNFULFILL, reason=REASON_UNKNOWN)
        out[key] = d
    return out


def summarize(result: dict) -> dict:
    """탭 머리에 붙일 건수 — {이행, 미이행, 클레임, 사유별}."""
    counts = {GROUP_FULFILL: 0, GROUP_UNFULFILL: 0, GROUP_CLAIM: 0}
    reasons = {REASON_STOCK: 0, REASON_LOSS: 0, REASON_NOT_OURS: 0,
               REASON_UNKNOWN: 0, REASON_OTHER: 0}
    for d in (result or {}).values():
        g = d.get('group')
        if g in counts:
            counts[g] += 1
        if g == GROUP_UNFULFILL and d.get('reason') in reasons:
            reasons[d['reason']] += 1
    return {'counts': counts, 'reasons': reasons}
