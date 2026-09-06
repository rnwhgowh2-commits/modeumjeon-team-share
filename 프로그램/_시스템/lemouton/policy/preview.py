"""「이 정책으로 계산하면」 미리보기 — 실제 전송 경로는 건드리지 않는다.

사장님 확정 (2026-07-30): 판매가의 기준은 **최종매입가**다.
    판매가 = 최종매입가 × (1 + 마진율/100)

■ 🔴 이 모듈은 **보여주기만** 한다
  정책의 수수료율·마진율이 아직 비어 있다. 빈칸을 0으로 읽으면 그 가격이 그대로
  마켓에 나간다(가격 오류 = 금전 손실). 그래서 계산에 물리기 전에, 사장님이 숫자를
  눈으로 확인할 자리를 먼저 만든다. 실제 업로드 경로는 여기서 부르지 않는다.

■ 계산을 새로 만들지 않는다
  최종매입가 = `orders.price_diff._current_purchase` (→ 매트릭스 → compute_breakdown)
  지금 판매가 = 매트릭스가 이미 들고 있는 마켓별 값
  같은 값을 두 곳에서 만들면 화면끼리 갈린다.

■ 마진율이 없으면 계산하지 않는다
  「안 정함」과 「0%」는 다른 뜻이다. 안 정했으면 `sale_price=None` 으로 두고
  `reason` 에 왜 못 냈는지 적는다 — 0원짜리 판매가를 지어내지 않는다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: 정책 13항목 중 판매가를 정하는 항목·칸 (process_rule_schema 의 'price')
PRICE_ITEM = 'price'


def margin_rate_of(values: dict):
    """정책값에서 마진율(%) — 안 정했으면 None. 0 은 「0%로 정함」이라 값이다.

    ★ 미리보기의 매입가는 **소싱처 최종매입가**라 소싱품 쪽을 본다.
      옛 칸 번역은 price_cfg 가 맡는다 — 여기서 또 번역하면 두 벌이 갈린다.
    """
    from lemouton.policy.price_cfg import read_side
    s = read_side((values or {}).get(PRICE_ITEM) or {}, 'sourcing')
    return s.rate if s.mode == 'margin_rate' else None


def fixed_amount_of(values: dict):
    """지정 판매가 — 「지정가」 방식일 때만. 아니면 None."""
    from lemouton.policy.price_cfg import read_side
    s = read_side((values or {}).get(PRICE_ITEM) or {}, 'sourcing')
    if s.mode != 'fixed_price' or s.fixed is None or s.fixed <= 0:
        return None
    return s.fixed


def _default_fee(market: str) -> float:
    """수수료율을 안 정했을 때 쓰는 값 — 마진 엔진에게 **물어본다**.
    (여기 숫자를 베껴 두면 엔진에서 바뀔 때 미리보기만 뒤처진다.)"""
    from lemouton.pricing.unified import default_fee_rate
    return default_fee_rate(market)


def fee_rate_of(values: dict):
    """정책값에서 수수료율(%) — 안 정했으면 None(마켓 기본값을 쓴다는 뜻)."""
    cfg = (values or {}).get(PRICE_ITEM) or {}
    v = cfg.get('fee_rate')
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def shipping_fee_of(values: dict) -> int:
    """정책의 배송비 — 판매가 계산에 들어간다(무료면 0)."""
    cfg = (values or {}).get('shipping') or {}
    if (cfg.get('fee_mode') or 'free') == 'free':
        return 0
    v = cfg.get('fee_amount')
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def margin_lines(*, price, purchase, fee_pct, discount) -> dict:
    """[2026-08-13 사장님 확정] 마진을 **두 줄**로 — 정가 기준 / 할인가 기준.

    사장님 정의:
        「할인가 = 판매가 − 즉시할인 − 쿠폰적용. **정산되는 기준이 되는 금액이 할인가**」
    쿠팡 정산 엑셀 상품행 299건 전수로 확인됐다(`정산금액 = 할인가 − 수수료`, 예외 0).
    쿠팡에서 「즉시할인」은 즉시할인쿠폰으로 구현되므로 둘은 같은 값이다.

    종전엔 정가 기준 한 줄뿐이라, 즉시할인을 걸어 두면 **실제로 남는 돈보다 크게** 보였다.

    🔴 수수료는 **할인가에** 물린다 — 정가에 물리면 마진이 실제보다 커 보인다.
    🔴 즉시할인이 없으면 `discounted` 는 `None` — 정가와 같은 값을 두 줄로 보여주면
      「할인이 걸린 것처럼」 읽힌다.
    🔴 매입가·수수료율을 모르면 마진은 `None`(「확인 불가」) — 0 으로 채우지 않는다.
    """
    from lemouton.policy.discount import exposed_price

    def _one(p):
        if p is None:
            return None
        row = {'price': int(p), 'margin': None, 'margin_rate': None}
        if purchase is None or fee_pct is None:
            return row                      # 모르면 「확인 불가」 — 0 으로 안 채운다
        fee = round(int(p) * float(fee_pct) / 100.0)
        m = int(p) - int(purchase) - fee
        row['margin'] = m
        row['margin_rate'] = round(m / int(p) * 100, 1) if p else None
        return row

    out = {'list': _one(price), 'discounted': None}
    dc = exposed_price(price, discount)
    if discount and dc is not None and dc != price:
        out['discounted'] = _one(dc)
    return out


def preview_for_model(session, *, model_code: str, values: dict, market: str,
                      matrix_loader=None) -> dict:
    """상품 하나를 이 정책으로 계산하면 — 옵션별 표.

    Returns:
        {ok, reason, rate, rows: [{sku, color, size, purchase, policy_price,
                                   current_price, diff}]}
        · purchase(최종매입가)를 모르는 옵션은 policy_price=None (지어내지 않음)
        · reason 이 있으면 계산을 아예 못 한 것 — 화면이 그대로 보여준다
    """
    from lemouton.orders import price_diff as _pd

    rate = margin_rate_of(values)
    fixed = fixed_amount_of(values)
    if rate is None and fixed is None:
        return {'ok': False, 'rate': None, 'rows': [],
                'reason': '이 마켓의 마진율이 아직 비어 있어 판매가를 계산할 수 없어요 — '
                          '빈칸을 0%로 읽으면 그 가격이 그대로 마켓에 나갑니다. '
                          '「판매가」 항목에 마진율을 넣어 주세요.'}

    if matrix_loader is None:
        from webapp.routes.api_pricing import _option_matrix_data as matrix_loader
    try:
        data = matrix_loader(model_code)
    except Exception:                                  # noqa: BLE001
        logger.exception('옵션 매트릭스 조회 실패 model=%s', model_code)
        data = None
    if not data or not data.get('ok'):
        return {'ok': False, 'rate': rate, 'rows': [],
                'reason': '이 상품의 옵션 정보를 읽지 못했어요.'}

    options = data.get('options') or []
    skus = [o.get('sku') for o in options if o.get('sku')]
    finals, errors = ({}, {})
    if skus:
        try:
            finals, errors = _pd._current_purchase(session, skus,
                                                   matrix_loader=lambda _mc: data)
        except Exception:                              # noqa: BLE001
            logger.exception('최종매입가 조회 실패 model=%s', model_code)

    # 지금 올라가 있는 판매가 — 매트릭스가 마켓별로 들고 있는 값.
    #   'ss'·'coupang' 두 마켓만 매트릭스가 낸다(unified._PREFIX_MAP). 나머지는 None.
    cur_key = {'smartstore': 'ss_price', 'coupang': 'cp_price'}.get(market)

    # 🔴 계산은 마켓 판매가 단일 원천(unified)이 한다. 여기서 산식을 다시 쓰면
    #   화면과 실제 업로드가가 갈린다 — 이 저장소에서 그건 곧 금전 사고다.
    #   ★ 2026-07-31 이전엔 `매입가 × (1+마진율)` 만 했다. 수수료를 빼먹어
    #     **마진이 실제보다 크게** 보였다(스스 6% · 쿠팡 11.55% · 나머지 13%).
    from lemouton.pricing.unified import compute_sale_price_unified
    fee = fee_rate_of(values)
    ship = shipping_fee_of(values)
    # 🔴 즉시할인은 **판매가에 물린다** — 안 넘기면 미리보기가 실제 업로드가보다
    #   낮게 나와 사장님이 「올라간 값이 다르다」로 겪는다. 부담 규칙은
    #   `policy/discount.seller_share` 한 곳만 쓴다(여기서 다시 쓰지 않는다).
    from lemouton.policy.discount import seller_share
    d_unit, d_value = seller_share((values or {}).get('price') or {})

    def _price(purchase):
        try:
            r = compute_sale_price_unified(
                purchase,
                margin_rate=(rate if rate is not None else 0) / 100.0,
                # 안 정했으면 마켓 기본값 — resolve_market_policy 와 같은 표를 쓴다.
                fee_rate=(fee / 100.0 if fee is not None else _default_fee(market)),
                shipping_fee=ship, rounding_unit=100,
                mode=('fixed' if fixed is not None else 'rate'),
                fixed_price=(fixed or 0),
                seller_discount_unit=d_unit, seller_discount_value=d_value)
            return r.final_price
        except Exception:                              # noqa: BLE001
            logger.exception('정책 판매가 계산 실패 market=%s', market)
            return None

    rows = []
    for o in options:
        sku = o.get('sku')
        purchase = finals.get(sku)
        policy_price = None if purchase is None else _price(purchase)
        current = o.get(cur_key) if cur_key else None
        rows.append({
            'sku': sku, 'color': o.get('color'), 'size': o.get('size'),
            'purchase': purchase,
            'purchase_error': errors.get(sku),
            'policy_price': policy_price,
            'current_price': current,
            'diff': (policy_price - current)
                    if (policy_price is not None and current) else None,
        })
    return {'ok': True, 'rate': rate, 'fixed': fixed, 'rows': rows,
            'reason': ('이 마켓은 지금 판매가를 매트릭스가 내지 않아 「지금 판매가」가 '
                       '비어 있어요 — 정책 판매가만 보여 드립니다.') if not cur_key else ''}


def result_by_market(session, *, model_code: str, policy_id: int) -> dict:
    """이 상품 × 이 정책 → **마켓별 한 줄 요약** (노션 H1 표).

    각 마켓은 이미 있는 :func:`preview_for_model` 을 그대로 쓴다 —
    산식을 여기서 다시 쓰면 화면과 업로드가 갈린다.

    Returns:
        {ok, rows: [{market, label, ready, reason, price, purchase,
                     margin, margin_rate, options, priced}]}
        · 계산 못 한 마켓은 price=None + reason (지어내지 않는다)
        · margin 은 **수수료를 뺀** 값이다 — 뺄 수 없으면 None
    """
    from lemouton.policy.discount import exposed_price, seller_share
    from lemouton.policy.fields import MARKETS
    from lemouton.policy.service import values_for

    rows = []
    for mk, label in MARKETS:
        values = values_for(session, policy_id, mk)
        단위_몫, 우리몫 = seller_share((values or {}).get('price') or {})
        got = preview_for_model(session, model_code=model_code,
                                values=values, market=mk)
        opts = got.get('rows') or []
        priced = [r for r in opts if r.get('policy_price') is not None
                  and r.get('purchase') is not None]
        row = {'market': mk, 'label': label, 'ready': bool(got.get('ok')),
               'reason': got.get('reason') or '',
               'options': len(opts), 'priced': len(priced),
               'price': None, 'purchase': None, 'margin': None, 'margin_rate': None}
        if priced:
            # 대표값 = 가장 흔한 판매가가 아니라 **가장 싼 매입가 기준 한 줄**.
            #   옵션마다 매입가가 달라 평균을 내면 어느 옵션에도 없는 숫자가 된다.
            base = min(priced, key=lambda r: r['purchase'])
            fee = fee_rate_of(values)
            if fee is None:
                fee = _default_fee(mk) * 100.0
            price, purchase = base['policy_price'], base['purchase']
            # 🔴 마진은 **우리 수입 기준**(판매가 − 우리 부담 할인)으로 잰다.
            #   표시 판매가로 재면 할인 걸린 상품의 마진이 크게 부풀어 보이고
            #   (스스 20% 기준 3.5배), 사장님이 남는 줄 알고 그대로 올린다.
            기준 = exposed_price(price, {'value': 우리몫, 'unitType': 단위_몫}) \
                if 우리몫 else price
            margin = 기준 - purchase - round(기준 * fee / 100.0)
            row.update(price=price, purchase=purchase, margin=margin,
                       margin_rate=round(margin / price * 100, 1) if price else None)
        rows.append(row)
    return {'ok': True, 'rows': rows}
