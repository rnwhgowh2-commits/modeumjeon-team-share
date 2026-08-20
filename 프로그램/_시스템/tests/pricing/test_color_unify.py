"""마켓별 색상 통일 (color_unify) — 통일가 규칙 + rows 적용 + 회귀(기본 no-op)."""
from types import SimpleNamespace

from lemouton.pricing.color_unify import unify_price, apply_color_unify


def test_unify_price_max_and_cheapest():
    assert unify_price([90000, 100000, 95000], 'max') == 100000
    assert unify_price([90000, 100000, 95000], 'src_cheapest') == 90000


def test_unify_price_filters_invalid():
    assert unify_price([0, None, 100000], 'max') == 100000
    assert unify_price([0, None, 100000], 'src_cheapest') == 100000
    assert unify_price([], 'max') is None
    assert unify_price([0, None], 'max') is None


def _rows():
    # 같은 색 블랙 2사이즈 (가격 다름) + 다른 색 화이트 1
    return [
        {'color': '블랙', 'ss_price': 106300, 'cp_price': 133900},
        {'color': '블랙', 'ss_price': 110200, 'cp_price': 140000},
        {'color': '화이트', 'ss_price': 99000, 'cp_price': 120000},
    ]


def test_apply_color_unify_ss_max_only():
    tpl = SimpleNamespace(ss_pricing_policy='color', ss_unify_rule='max',
                          coupang_pricing_policy='cheapest', coupang_unify_rule='max')
    rows = _rows()
    apply_color_unify(rows, tpl)
    # 블랙 두 사이즈 SS = 최고가 110200 통일
    assert rows[0]['ss_price'] == 110200
    assert rows[1]['ss_price'] == 110200
    # 화이트는 혼자라 그대로
    assert rows[2]['ss_price'] == 99000
    # 쿠팡은 cheapest(꺼짐) → 손 안 댐
    assert rows[0]['cp_price'] == 133900
    assert rows[1]['cp_price'] == 140000


def test_apply_color_unify_cheapest_rule():
    tpl = SimpleNamespace(ss_pricing_policy='color', ss_unify_rule='src_cheapest',
                          coupang_pricing_policy='cheapest', coupang_unify_rule='max')
    rows = _rows()
    apply_color_unify(rows, tpl)
    assert rows[0]['ss_price'] == 106300  # 블랙 최저
    assert rows[1]['ss_price'] == 106300


def test_default_cheapest_is_noop_regression():
    # 기본 템플릿(둘 다 cheapest) → 아무 값도 안 바뀜 (라이브 회귀 0 보장)
    tpl = SimpleNamespace(ss_pricing_policy='cheapest', ss_unify_rule='max',
                          coupang_pricing_policy='cheapest', coupang_unify_rule='max')
    rows = _rows()
    before = [dict(r) for r in rows]
    apply_color_unify(rows, tpl)
    assert rows == before


def test_none_tpl_and_missing_attrs_safe():
    rows = _rows(); before = [dict(r) for r in rows]
    apply_color_unify(rows, None)
    assert rows == before
    # 속성 없는 tpl → getattr 기본 'cheapest' → no-op
    apply_color_unify(rows, SimpleNamespace())
    assert rows == before


def test_coupang_color_unify():
    tpl = SimpleNamespace(ss_pricing_policy='cheapest', ss_unify_rule='max',
                          coupang_pricing_policy='color', coupang_unify_rule='max')
    rows = _rows()
    apply_color_unify(rows, tpl)
    assert rows[0]['cp_price'] == 140000  # 블랙 쿠팡 최고가
    assert rows[1]['cp_price'] == 140000
    assert rows[0]['ss_price'] == 106300  # ss 는 꺼짐 → 그대로
