# -*- coding: utf-8 -*-
"""「판매가」 항목 값 읽기 — 옛 칸 ↔ 새 칸 번역을 여기 한 곳에 둔다.

2026-08-01 이전 저장분은 소싱/사입 구분이 없고 방식이 둘(마진율·고정금액)뿐이었다.
읽는 쪽이 저마다 번역하면 세 벌이 갈린다 — 미리보기·대량등록 점검·화면이 모두 여기를 쓴다.

🔴 **안 정한 것은 None 이다.** 0 으로 채우면 그 가격이 그대로 마켓에 나간다.
"""
from __future__ import annotations

from dataclasses import dataclass

SIDES = ('sourcing', 'purchase')
MODES = ('margin_rate', 'margin_amount', 'fixed_price')


@dataclass(frozen=True)
class PriceSide:
    """한쪽(소싱품 또는 사입품)의 가격 정하는 법."""

    mode: str
    rate: float | None
    amount: int | None
    fixed: int | None


def _num(v):
    """숫자만 값으로 본다.

    ★ True/False 를 먼저 걸러낸다 — 파이썬에선 True 가 1 로 통해서,
      체크박스 값이 새어 들어오면 「마진율 100%」가 된다.
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def read_side(cfg: dict, side: str) -> PriceSide:
    """정책 「판매가」 설정에서 한쪽을 읽는다. 옛 칸도 알아본다."""
    if side not in SIDES:
        raise ValueError(f"모르는 쪽입니다: {side!r} — 쓸 수 있는 값: {', '.join(SIDES)}")
    cfg = cfg or {}

    mode = cfg.get(f'{side}_mode')
    rate = _num(cfg.get(f'{side}_rate'))
    amount = _num(cfg.get(f'{side}_amount'))
    fixed = _num(cfg.get(f'{side}_fixed'))

    # ── 옛 칸 번역 (새 칸이 하나도 없을 때만) ──
    #   새 칸이 하나라도 있으면 사장님이 새 화면에서 고친 것이다 — 그게 이긴다.
    if mode is None and rate is None and amount is None and fixed is None:
        old_mode = cfg.get('mode')
        if old_mode == 'fixed_amount':
            mode = 'fixed_price'
            fixed = _num(cfg.get('fixed_amount'))
        elif old_mode == 'margin_rate':
            mode = 'margin_rate'
            rate = _num(cfg.get('margin_rate'))

    return PriceSide(mode=(mode or 'margin_rate'),
                     rate=None if rate is None else float(rate),
                     amount=None if amount is None else int(amount),
                     fixed=None if fixed is None else int(fixed))


def effective_value(cfg: dict, side: str):
    """그 쪽에서 **지금 실제로 쓰는 값** — 고른 방식의 칸 하나. 안 정했으면 None.

    화면이 「쓰는 값」 배지를 다는 자리와 같은 판정이어야 한다(확정 I2).
    """
    s = read_side(cfg, side)
    return {'margin_rate': s.rate, 'margin_amount': s.amount,
            'fixed_price': s.fixed}.get(s.mode)
