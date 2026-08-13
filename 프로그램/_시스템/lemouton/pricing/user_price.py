# -*- coding: utf-8 -*-
"""사람이 정한 가격 — **규칙 한 벌**.

🔴 [2026-08-13] 왜 생겼나
   화면에서 「자동 계산」을 끄고 가격을 손으로 넣으면 저장도 되고 매트릭스에도
   그 값이 보였다. **그런데 마켓으로는 자동 계산값이 나갔다.**
   전송 가격을 만드는 `uploader/preview.py:_resolve_option_upload(o, cfg, …)` 가
   `cfg`(수기 설정)를 인자로 받아 놓고 **본문에서 한 번도 안 썼다.**
   화면과 전송이 갈려 있었던 것이다 — `preview.py` 머리말이 못 박은
   「표시가 = 업로드가 단일 진실 원천」이 이 지점에서 깨져 있었다.

   그래서 규칙을 여기 한 곳에 두고, 화면·전송·되채움이 **같은 함수**를 부른다.
   집의 기존 관례와 같다 — cost_basis(어느 카드냐) · unified(정책 해석) ·
   formatter/stock_policy(보낼 재고)도 규칙을 함수 하나로 두고 여러 경로가 부른다.

우선순위 (위가 이긴다)
    ① 옵션 지정가  Option.{src|pur}_fixed_{ss|cp}_price
    ② 수기         OptionPriceConfig.manual_{ss|cp}_price  (auto_enabled=False)
    ③ 사람이 안 정함 → None → 정책·자동계산이 이어받는다

🔴 ①이 ②보다 위인 근거
   · 화면이 이미 그 순서다 — api_pricing 이 수기가로 표시값을 만든 **뒤** 지정가로 덮는다.
     다르게 이으면 「표시가 = 업로드가」가 그날로 깨진다.
   · `auto_enabled=False` 가 끄는 대상은 **「자동 계산」이지 「지정가」가 아니다**
     (화면 문구 「ON = 자동 / OFF = 수기」 · 모델 주석 models_pricing.py:80-83).
   · 범위가 좁은 쪽이 이긴다 — 지정가는 (카드 × 마켓) 4칸, 수기는 (마켓) 2칸.

🔴 스위치를 켰는데 값이 비면 **자동계산으로 되돌리지 않는다**(hold).
   「자동으로 팔지 마라」고 껐는데 값이 없다고 자동값으로 파는 건 정반대 행동이다.
   값을 못 만드는 것보다 **그 사실을 안 말하는 것이 더 큰 잘못**이다.
"""
from __future__ import annotations

from dataclasses import dataclass

#: 사람이 값을 넣을 칸이 실제로 **있는** 마켓 → 그 칸 접두어.
#: 🔴 나머지 4마켓(롯데온·11번가·옥션·G마켓)에 스스/쿠팡 값을 물려주면 안 된다 —
#:    수수료가 6%~18% 로 다르다(pricing/unified.py). 「모르면 지어내지 않는다.」
MANUAL_MARKETS = {"smartstore": "ss", "coupang": "cp"}


@dataclass(frozen=True)
class UserPrice:
    """사람이 정한 값의 판정 결과."""

    #: 사람이 정한 가격. None = 안 정했다(자동계산이 이어받는다).
    price: int | None = None
    #: 어디서 왔나 — 'option_fixed' | 'manual' | None
    origin: str | None = None
    #: 그 마켓에 사람이 값을 넣을 칸이 있는가.
    supported: bool = True
    #: True = **자동계산으로 되돌리지 말고 전송 보류**. 스위치는 켰는데 값이 없다.
    hold: bool = False
    warnings: tuple = ()


def _positive(v):
    """가격으로 쓸 수 있는 값인가. 0·음수·빈값은 아니다(0원은 무효)."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def resolve_user_price(*, opt, cfg, market: str, side: str) -> UserPrice:
    """이 옵션·이 마켓에 대해 **사람이 정한 가격**을 판정한다.

    Args:
        opt: Option — 옵션 지정가(src_fixed_* / pur_fixed_*)를 들고 있다.
        cfg: OptionPriceConfig | None — 자동/수기 스위치와 수기가.
        market: 'smartstore' | 'coupang' | 'lotteon' | 'eleven11' | 'auction' | 'gmarket'
        side: 'source'(소싱 카드) | 'purchase'(사입 카드) — 적용 카드.

    Returns:
        UserPrice. `price` 가 None 이고 `hold` 가 False 면 「사람이 안 정함」이라
        정책·자동계산이 이어받는다. `hold` 가 True 면 **전송을 멈춰야 한다.**
    """
    mkt = MANUAL_MARKETS.get(market)
    if not mkt:
        # 칸이 없는 마켓 — 「지원 안 함」을 조용히 넘기지 않고 표면화한다.
        # 사람이 안 정한 것이므로 보류가 아니라 자동계산으로 넘긴다.
        return UserPrice(supported=False)

    card = "pur" if side == "purchase" else "src"

    # ① 옵션 지정가
    if getattr(opt, f"{card}_fixed_{mkt}_active", False):
        v = _positive(getattr(opt, f"{card}_fixed_{mkt}_price", None))
        if v is not None:
            return UserPrice(price=v, origin="option_fixed")
        return UserPrice(
            hold=True,
            warnings=("지정가를 켰는데 값이 비었거나 0 입니다 — "
                      "자동 계산으로 되돌리지 않고 멈춥니다.",))

    # ② 수기 (자동 계산 끔)
    if cfg is not None and getattr(cfg, "auto_enabled", True) is False:
        v = _positive(getattr(cfg, f"manual_{mkt}_price", None))
        if v is not None:
            return UserPrice(price=v, origin="manual")
        return UserPrice(
            hold=True,
            warnings=("자동 계산을 껐는데 수기 가격이 비었거나 0 입니다 — "
                      "자동 계산으로 되돌리지 않고 멈춥니다.",))

    # ③ 사람이 안 정함
    return UserPrice()
