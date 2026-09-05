# -*- coding: utf-8 -*-
"""사람이 정한 가격 — **화면에서 정한 값이 마켓까지 가는지**.

🔴 [2026-08-13 사장님 지적] 「자동 계산」을 끄고 가격을 손으로 넣으면 저장도 되고
   매트릭스 화면에도 그 값이 보인다. **그런데 마켓으로는 자동 계산값이 나갔다.**
   전송 가격을 만드는 `uploader/preview.py:_resolve_option_upload(o, cfg, …)` 가
   `cfg`(수기 설정)를 인자로 받아 놓고 **본문에서 한 번도 안 썼다.**
   사장님 말씀: 「안써봤어. 끊긴데 이어줘.」

이 파일은 그 규칙 한 벌(`resolve_user_price`)을 못 박는다. 규칙을 한 곳에 두어야
화면과 전송이 갈리지 않는다(`preview.py` 머리말의 「표시가 = 업로드가」).

우선순위 (위가 이긴다)
    ① 옵션 지정가  Option.{src|pur}_fixed_{ss|cp}_price
    ② 수기         OptionPriceConfig.manual_{ss|cp}_price  (auto_enabled=False)
    ③ 사람이 안 정함 → None → 정책·자동계산이 이어받는다

🔴 ①이 ②보다 위인 근거 — 화면이 이미 그 순서다(api_pricing 이 수기가로 표시값을
   만든 뒤 지정가로 덮는다). 그리고 `auto_enabled=False` 가 끄는 대상은 「자동 계산」
   이지 「지정가」가 아니다(화면 문구 · 모델 주석).
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from lemouton.pricing.user_price import resolve_user_price


def _opt(**kw):
    base = dict(src_fixed_ss_active=False, src_fixed_ss_price=None,
                src_fixed_cp_active=False, src_fixed_cp_price=None,
                pur_fixed_ss_active=False, pur_fixed_ss_price=None,
                pur_fixed_cp_active=False, pur_fixed_cp_price=None)
    base.update(kw)
    return NS(**base)


def _cfg(**kw):
    base = dict(auto_enabled=True, manual_ss_price=None, manual_cp_price=None)
    base.update(kw)
    return NS(**base)


# ── 사람이 안 정한 경우 ──────────────────────────────────────────────────────
def test_아무것도_안_정했으면_자동계산에_맡긴다():
    r = resolve_user_price(opt=_opt(), cfg=_cfg(), market="smartstore", side="source")

    assert r.price is None
    assert r.hold is False


# ── 수기 ─────────────────────────────────────────────────────────────────────
def test_자동을_끄고_넣은_값이_전송가가_된다():
    """이게 끊겨 있던 지점이다."""
    r = resolve_user_price(opt=_opt(), cfg=_cfg(auto_enabled=False, manual_ss_price=120000),
                           market="smartstore", side="source")

    assert r.price == 120000
    assert r.origin == "manual"


def test_마켓마다_제_값을_쓴다():
    cfg = _cfg(auto_enabled=False, manual_ss_price=120000, manual_cp_price=135000)

    assert resolve_user_price(opt=_opt(), cfg=cfg, market="smartstore",
                              side="source").price == 120000
    assert resolve_user_price(opt=_opt(), cfg=cfg, market="coupang",
                              side="source").price == 135000


def test_자동이_켜져_있으면_수기값은_무시한다():
    """옛 값이 남아 있어도 자동이 켜져 있으면 자동계산이 맞다."""
    r = resolve_user_price(opt=_opt(), cfg=_cfg(auto_enabled=True, manual_ss_price=999),
                           market="smartstore", side="source")

    assert r.price is None


def test_자동을_껐는데_값이_비면_자동으로_되돌리지_않는다():
    """🔴 조용한 실패 금지.

    「자동으로 팔지 마라」고 껐는데 값이 없다고 자동값으로 파는 건 정반대 행동이다.
    보류(hold)로 표면화해 사람이 채우게 한다.
    """
    r = resolve_user_price(opt=_opt(), cfg=_cfg(auto_enabled=False, manual_ss_price=None),
                           market="smartstore", side="source")

    assert r.price is None
    assert r.hold is True
    assert r.warnings, "왜 멈췄는지 말해야 한다"


def test_수기값이_0이면_보류한다():
    """0원은 무효다. 그렇다고 자동값으로 되돌리면 안 된다."""
    r = resolve_user_price(opt=_opt(), cfg=_cfg(auto_enabled=False, manual_ss_price=0),
                           market="smartstore", side="source")

    assert r.price is None
    assert r.hold is True


# ── 옵션 지정가가 수기보다 위 ────────────────────────────────────────────────
def test_옵션_지정가가_수기를_이긴다():
    r = resolve_user_price(
        opt=_opt(src_fixed_ss_active=True, src_fixed_ss_price=99000),
        cfg=_cfg(auto_enabled=False, manual_ss_price=120000),
        market="smartstore", side="source")

    assert r.price == 99000
    assert r.origin == "option_fixed"


def test_적용_카드에_맞는_지정가를_쓴다():
    """소싱 카드가 적용됐으면 소싱 지정가, 사입이면 사입 지정가."""
    opt = _opt(src_fixed_ss_active=True, src_fixed_ss_price=99000,
               pur_fixed_ss_active=True, pur_fixed_ss_price=88000)

    assert resolve_user_price(opt=opt, cfg=_cfg(), market="smartstore",
                              side="source").price == 99000
    assert resolve_user_price(opt=opt, cfg=_cfg(), market="smartstore",
                              side="purchase").price == 88000


def test_지정가를_켰는데_값이_비면_보류한다():
    r = resolve_user_price(opt=_opt(src_fixed_ss_active=True, src_fixed_ss_price=None),
                           cfg=_cfg(), market="smartstore", side="source")

    assert r.price is None
    assert r.hold is True


# ── 칸이 없는 마켓 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("market", ["lotteon", "eleven11", "auction", "gmarket"])
def test_수기_칸이_없는_마켓은_그렇다고_말한다(market):
    """🔴 스스·쿠팡 값을 물려주면 안 된다 — 수수료가 다르다(6% ~ 18%).

    「지원 안 함」을 조용히 넘기지 말고 supported=False 로 표면화한다.
    """
    r = resolve_user_price(opt=_opt(), cfg=_cfg(auto_enabled=False, manual_ss_price=120000),
                           market=market, side="source")

    assert r.supported is False
    assert r.price is None
    assert r.hold is False, "칸이 없는 건 사람이 안 정한 것 — 자동계산이 이어받는다"
