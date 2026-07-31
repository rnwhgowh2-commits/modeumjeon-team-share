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
    """정책값에서 마진율(%) — 안 정했으면 None. 0 은 「0%로 정함」이라 값이다."""
    cfg = (values or {}).get(PRICE_ITEM) or {}
    mode = cfg.get('mode') or 'margin_rate'
    if mode != 'margin_rate':
        return None
    v = cfg.get('margin_rate')
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def fixed_amount_of(values: dict):
    """고정 판매가 — 「고정 금액」 방식일 때만. 아니면 None."""
    cfg = (values or {}).get(PRICE_ITEM) or {}
    if (cfg.get('mode') or 'margin_rate') != 'fixed_amount':
        return None
    v = cfg.get('fixed_amount')
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        return None
    return int(v)


def _round_down_100(n: float) -> int:
    """백원 단위 버림 — 최종매입가와 같은 규칙(pricing/final_price.py)."""
    return int(n) // 100 * 100


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

    rows = []
    for o in options:
        sku = o.get('sku')
        purchase = finals.get(sku)
        if purchase is None:
            policy_price = None
        elif fixed is not None:
            policy_price = fixed
        else:
            policy_price = _round_down_100(purchase * (1 + rate / 100.0))
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
