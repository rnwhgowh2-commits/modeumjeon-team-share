# -*- coding: utf-8 -*-
"""🔴 화면에서 손으로 정한 가격이 **마켓 전송값이 되는가**.

이 시험이 없어서 못 잡았다. `uploader/preview.py:_resolve_option_upload(o, cfg, …)` 가
`cfg`(수기 설정)를 인자로 **받아 놓고 본문에서 한 번도 안 썼다.**
저장도 되고 매트릭스에도 보이는데 마켓엔 자동 계산값이 나갔다.

「끊겼다」는 걸 아무도 몰랐던 이유가 이것이다 — 전송값이 수기값을 따르는지
확인하는 시험이 **하나도 없었다.** 여기서 못 박는다.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

from lemouton.uploader.preview import _resolve_option_upload


def _opt(**kw):
    base = dict(
        canonical_sku="SKU1",
        boxhero_avg_purchase_price=0,      # 사입 후보 없음 → 소싱 카드가 적용된다
        src_fixed_ss_active=False, src_fixed_ss_price=None,
        src_fixed_cp_active=False, src_fixed_cp_price=None,
        pur_fixed_ss_active=False, pur_fixed_ss_price=None,
        pur_fixed_cp_active=False, pur_fixed_cp_price=None,
    )
    base.update(kw)
    return NS(**base)


def _cfg(**kw):
    base = dict(auto_enabled=True, manual_ss_price=None, manual_cp_price=None)
    base.update(kw)
    return NS(**base)


def _run(opt, cfg, monkeypatch, *, crawl_price=50000):
    """크롤가·템플릿을 고정해 「자동 계산이면 얼마가 나오는지」를 안정시킨다."""
    import webapp.routes.api_pricing as AP
    monkeypatch.setattr(AP, "_pick_cheapest_buyable", lambda srcs: {"price": crawl_price})
    monkeypatch.setattr(AP, "_resolve_sourcing_cost", lambda src: crawl_price)

    import lemouton.uploader.preview as PV
    monkeypatch.setattr(PV, "compute_market_price",
                        lambda tpl, mkt, side, cost: NS(final_price=cost * 2))
    tpl = NS(boxhero_purchase_price=0, price_source_priority="template")
    return _resolve_option_upload(opt, cfg, tpl, sources_for_opt=[], stock=5)


def test_수기값이_없으면_자동계산값이_나간다(monkeypatch):
    """기준선 — 이게 지금까지의 동작이다."""
    r = _run(_opt(), _cfg(), monkeypatch)

    assert r["upload"]["ss"] == 100000


def test_자동을_끄고_넣은_값이_그대로_전송된다(monkeypatch):
    """🔴 이게 끊겨 있던 지점이다. 자동계산값(100,000)이 아니라 수기값이 나가야 한다."""
    r = _run(_opt(), _cfg(auto_enabled=False, manual_ss_price=120000,
                          manual_cp_price=135000), monkeypatch)

    assert r["upload"]["ss"] == 120000, f"수기 가격이 전송에 안 실린다: {r['upload']}"
    assert r["upload"]["cp"] == 135000


def test_옵션_지정가가_수기를_이긴다(monkeypatch):
    """화면이 이미 그 순서다 — 전송도 같아야 「표시가 = 업로드가」가 지켜진다."""
    r = _run(_opt(src_fixed_ss_active=True, src_fixed_ss_price=99000),
             _cfg(auto_enabled=False, manual_ss_price=120000), monkeypatch)

    assert r["upload"]["ss"] == 99000


def test_자동을_껐는데_값이_비면_보내지_않는다(monkeypatch):
    """🔴 조용한 실패 금지 — 자동값으로 되돌려 팔면 안 된다."""
    r = _run(_opt(), _cfg(auto_enabled=False, manual_ss_price=None), monkeypatch)

    assert r["upload"]["ss"] is None, \
        f"자동으로 팔지 말라고 껐는데 자동값이 나간다: {r['upload']}"
    assert r.get("holds", {}).get("ss"), "왜 멈췄는지 말해야 한다"


def test_설정이_아예_없으면_예전과_똑같다(monkeypatch):
    """cfg=None 인 옵션(설정 행이 없는 옛 데이터)이 깨지면 안 된다."""
    r = _run(_opt(), None, monkeypatch)

    assert r["upload"]["ss"] == 100000
