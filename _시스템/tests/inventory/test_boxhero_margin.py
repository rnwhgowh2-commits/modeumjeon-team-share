"""[I] tests/inventory/test_boxhero_margin.py — 사입 마진 3계층 + 판매가.

ai-workflow STEP 7 Sprint 2 Task 2.6 TDD
"""
import pytest
from types import SimpleNamespace

from lemouton.pricing.boxhero_margin import (
    resolve_margin, apply_margin, compute_sale_price,
)


# ============ resolve_margin (3계층 자체) ============

def _opt(self_mode=None, self_val=None, ext_mode=None, ext_val=None, avg=0):
    return SimpleNamespace(
        option_boxhero_margin_mode=self_mode,
        option_boxhero_margin_value=self_val,
        option_external_margin_mode=ext_mode,
        option_external_margin_value=ext_val,
        boxhero_avg_purchase_price=avg,
    )


def _model(mode=None, val=None):
    return SimpleNamespace(
        boxhero_margin_mode_override=mode,
        boxhero_margin_value_override=val,
    )


def _tpl(self_mode='rate', self_val=2500, ext_mode='rate', ext_val=2000):
    return SimpleNamespace(
        boxhero_margin_mode_self=self_mode,
        boxhero_margin_value_self=self_val,
        boxhero_margin_mode_external=ext_mode,
        boxhero_margin_value_external=ext_val,
    )


def test_self_option_wins():
    opt = _opt(self_mode='amount', self_val=30000)
    model = _model(mode='rate', val=3000)
    tpl = _tpl()
    mode, val, layer = resolve_margin(opt, model, tpl, 'self')
    assert mode == 'amount' and val == 30000 and layer == 'option'


def test_self_model_when_no_option():
    opt = _opt()
    model = _model(mode='rate', val=3500)
    tpl = _tpl()
    mode, val, layer = resolve_margin(opt, model, tpl, 'self')
    assert mode == 'rate' and val == 3500 and layer == 'model'


def test_self_template_when_no_option_no_model():
    opt = _opt()
    model = _model()
    tpl = _tpl(self_mode='rate', self_val=2500)
    mode, val, layer = resolve_margin(opt, model, tpl, 'self')
    assert mode == 'rate' and val == 2500 and layer == 'template'


def test_self_default_when_no_template():
    mode, val, layer = resolve_margin(_opt(), _model(), None, 'self')
    assert mode == 'rate' and val == 2500 and layer == 'default'


# ============ resolve_margin (외부) ============

def test_external_option_wins():
    opt = _opt(ext_mode='amount', ext_val=20000)
    tpl = _tpl()
    mode, val, layer = resolve_margin(opt, _model(), tpl, 'external')
    assert mode == 'amount' and val == 20000 and layer == 'option'


def test_external_skips_model_layer():
    """외부 사입은 Model 오버라이드 ❌ → Template 으로 직진."""
    opt = _opt()
    model = _model(mode='rate', val=9999)  # 무시되어야 함
    tpl = _tpl(ext_mode='rate', ext_val=2000)
    mode, val, layer = resolve_margin(opt, model, tpl, 'external')
    assert mode == 'rate' and val == 2000 and layer == 'template'


def test_invalid_source_type():
    with pytest.raises(ValueError):
        resolve_margin(_opt(), _model(), _tpl(), 'unknown')


# ============ apply_margin ============

def test_apply_rate():
    # 100,000 * (1 + 2500/10000) = 125,000
    assert apply_margin(100_000, 'rate', 2500) == 125_000


def test_apply_amount():
    assert apply_margin(100_000, 'amount', 30_000) == 130_000


def test_apply_zero_purchase():
    assert apply_margin(0, 'rate', 2500) == 0


def test_apply_invalid_mode():
    with pytest.raises(ValueError):
        apply_margin(100_000, 'unknown', 2500)


# ============ compute_sale_price (통합) ============

def test_compute_self_3layer_priority():
    opt = _opt(self_mode='rate', self_val=3000, avg=80_000)
    res = compute_sale_price(opt, _model(), _tpl(), 'self')
    assert res['purchase_price'] == 80_000
    assert res['source_layer'] == 'option'
    assert res['sale_price'] == 104_000  # 80k * 1.30
    assert res['margin_amount'] == 24_000


def test_compute_external_uses_template():
    opt = _opt(avg=70_000)
    res = compute_sale_price(opt, _model(), _tpl(ext_mode='rate', ext_val=2000), 'external')
    assert res['source_layer'] == 'template'
    assert res['sale_price'] == 84_000  # 70k * 1.20


def test_compute_zero_purchase():
    opt = _opt(avg=0)
    res = compute_sale_price(opt, _model(), _tpl(), 'self')
    assert res['purchase_price'] == 0
    assert res['sale_price'] == 0
    assert res['margin_amount'] == 0


def test_compute_purchase_override():
    opt = _opt(avg=80_000)
    res = compute_sale_price(opt, _model(), _tpl(self_val=2500), 'self',
                             purchase_price_override=100_000)
    assert res['purchase_price'] == 100_000
    assert res['sale_price'] == 125_000


def test_compute_amount_mode():
    opt = _opt(self_mode='amount', self_val=15_000, avg=80_000)
    res = compute_sale_price(opt, _model(), _tpl(), 'self')
    assert res['mode'] == 'amount'
    assert res['sale_price'] == 95_000
    assert res['margin_amount'] == 15_000
