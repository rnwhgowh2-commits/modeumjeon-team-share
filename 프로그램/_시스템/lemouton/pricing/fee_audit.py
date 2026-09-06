# -*- coding: utf-8 -*-
"""수수료율이 지금 **어디에 어떤 값으로** 있는지 세고, 마켓별 기본값으로 맞추면
판매가가 얼마나 움직이는지 미리 잰다.

왜 필요한가 (2026-08-02):
  사장님 확정 마켓별 요율 — 스스 6% · 쿠팡 11.55% · **롯데온 13%** ·
  **11번가 13%**(계약 11 + 늘 켜는 가격비교 2 · 1년 이내 계정이면 10%) ·
  옥션 15% · G마켓 15%.  [2026-08-13 재확정]

  그런데 실제로 판매가를 정하는 수수료율은 세 군데를 차례로 본다:
    ① 정책(MarketPolicy)의 `price.fee_rate`
    ② 없으면 가격 정책(PriceTemplate)의 `<마켓>_fee_rate`   ← **여기 6% / 11.55% 가 박혀 있다**
    ③ 그것도 없으면 엔진 기본 `unified.default_fee_rate()`
  ②를 고칠 화면이 **아예 없었다**. 그래서 사장님은 빈칸을 보는데 속으로는 6% 가
  쓰이고 있었다 — 화면이 거짓말을 하고 있던 자리다.

🔴 이 모듈의 `audit()` 는 **아무것도 고치지 않는다.** 먼저 눈으로 보고,
   `apply_defaults()` 는 바꾸기 전 값을 그대로 돌려줘 되돌릴 수 있게 한다.
"""
from __future__ import annotations

from lemouton.pricing.unified import _PREFIX_MAP, default_fee_rate

#: PriceTemplate 이 마켓마다 들고 있는 수수료율 칸
FEE_COLUMNS = ('ss_fee_rate', 'coupang_fee_rate', 'lotteon_fee_rate',
               'eleven11_fee_rate', 'auction_fee_rate', 'gmarket_fee_rate')


def target_fee(prefix: str) -> float:
    """그 마켓이 맞춰야 할 요율 — **표를 베끼지 않고 물어본다.**

    🔴 수수료율은 마켓마다 다르다. **여기 숫자를 적어 두지 마라** — 표를 고쳐도
      이 도구만 옛 값으로 잰다. 실제로 롯데온이 18 로 굳어 있어 라이브에
      9.6%p 거짓 경고를 띄웠다(2026-08-13 정정).
    """
    return default_fee_rate(prefix)

def _prefix_of(column: str) -> str:
    return column[: -len('_fee_rate')]


def _margin_of(tpl, prefix: str):
    """그 마켓의 소싱품 마진율 — 엔진(`resolve_market_policy`)과 **같은 순서로** 찾는다.
    (여기서 다른 칸을 보면 배수가 실제와 어긋나 잘못된 안심을 준다.)"""
    for col in (f'{prefix}_rate_sourcing', f'{prefix}_margin_rate'):
        v = getattr(tpl, col, None)
        if v is not None:
            return float(v)
    return None


def price_multiplier(old_fee: float, new_fee: float, margin_rate: float) -> float | None:
    """수수료율만 바뀔 때 판매가가 몇 배가 되는가.

    판매가 = 매입가 / (1 − 수수료율 − 마진율) 이므로 배수는 매입가와 무관하다.
    성립하지 않는 조합(분모 ≤ 0)이면 None — 지어내지 않는다.
    """
    old_d = 1.0 - old_fee - margin_rate
    new_d = 1.0 - new_fee - margin_rate
    if old_d <= 0 or new_d <= 0:
        return None
    return old_d / new_d


def audit(session) -> dict:
    """지금 저장된 수수료율을 전부 센다. **읽기 전용.**

    Returns:
        {ok, target, templates: [...], policies: {...}, engine: {...}}
    """
    from lemouton.policy.models import MarketPolicy, MarketPolicyValue
    from lemouton.templates.models import PriceTemplate

    rows = []
    for t in session.query(PriceTemplate).order_by(PriceTemplate.id).all():
        cols = {}
        for col in FEE_COLUMNS:
            cur = getattr(t, col, None)
            if cur is None:
                continue
            prefix = _prefix_of(col)
            tgt = target_fee(prefix)
            margin = _margin_of(t, prefix)
            mult = (price_multiplier(float(cur), tgt, margin)
                    if margin is not None else None)
            cols[col] = {
                'now': float(cur),
                'target': tgt,
                'same_as_target': abs(float(cur) - tgt) < 1e-9,
                'margin_rate': None if margin is None else float(margin),
                # 판매가 배수 — 1.09 면 판매가가 9% 오른다는 뜻
                'price_multiplier': None if mult is None else round(mult, 4),
            }
        if cols:
            rows.append({'id': t.id, 'name': getattr(t, 'name', None), 'columns': cols})

    # 정책 쪽 — 수수료율을 **직접 정한** 칸이 몇 개인가
    set_by_policy = (session.query(MarketPolicyValue)
                     .filter(MarketPolicyValue.field_key == 'price').count())
    policies = session.query(MarketPolicy).filter(
        MarketPolicy.deleted_at.is_(None)).count()

    changing = sum(1 for r in rows for c in r['columns'].values()
                   if not c['same_as_target'])
    return {
        'ok': True,
        'target': {c: target_fee(_prefix_of(c)) for c in FEE_COLUMNS},
        'templates': rows,
        'template_count': len(rows),
        'columns_changing': changing,
        'policies': {'count': policies, 'price_rows': set_by_policy},
        'engine': {m: default_fee_rate(m) for m in sorted(set(_PREFIX_MAP.values()))},
    }


def apply_defaults(session, *, dry_run: bool = True) -> dict:
    """가격 정책(PriceTemplate)의 수수료율을 **마켓별 기본값**으로 맞춘다.

    🔴 `dry_run=True` 가 기본이다. 실제로 고치려면 부르는 쪽이 꺼야 한다.
    되돌릴 수 있게 **바꾸기 전 값을 그대로 돌려준다.**
    """
    from lemouton.templates.models import PriceTemplate

    before, changed = [], 0
    for t in session.query(PriceTemplate).order_by(PriceTemplate.id).all():
        for col in FEE_COLUMNS:
            cur = getattr(t, col, None)
            tgt = target_fee(_prefix_of(col))
            if cur is None or abs(float(cur) - tgt) < 1e-9:
                continue
            before.append({'id': t.id, 'column': col, 'was': float(cur), 'to': tgt})
            if not dry_run:
                setattr(t, col, tgt)
            changed += 1
    return {'ok': True, 'dry_run': dry_run, 'changed': changed, 'before': before}


def restore(session, before: list) -> dict:
    """`apply_thirteen` 이 돌려준 「바꾸기 전 값」으로 되돌린다."""
    from lemouton.templates.models import PriceTemplate

    done = 0
    for row in before or []:
        t = session.get(PriceTemplate, row.get('id'))
        col = row.get('column')
        if t is None or col not in FEE_COLUMNS:
            continue
        setattr(t, col, float(row['was']))
        done += 1
    return {'ok': True, 'restored': done}
