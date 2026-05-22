"""tests/sourcing/test_option_combo.py — 단계형 옵션 조합 생성 (Phase 2 TDD).

ai-workflow cycle 20260521 · Phase 2 · Task 1
"""
from types import SimpleNamespace

from lemouton.sourcing.option_combo import (
    parse_comma_values, generate_combinations, build_sku, steps_from_rows,
    option_axis_values, option_sku, build_options_from_steps, option_is_offline,
)


# ============ parse_comma_values (1축 쉼표 입력) ============

def test_parse_basic():
    assert parse_comma_values("블랙, 화이트, 그레이") == ["블랙", "화이트", "그레이"]


def test_parse_trims_spaces():
    assert parse_comma_values("블랙 ,  화이트 ") == ["블랙", "화이트"]


def test_parse_dedup_keeps_order():
    assert parse_comma_values("블랙, 블랙, 화이트") == ["블랙", "화이트"]


def test_parse_empty():
    assert parse_comma_values("") == []
    assert parse_comma_values("   ") == []
    assert parse_comma_values(",,,") == []


# ============ generate_combinations (1~3축 cartesian) ============

def test_combo_1axis():
    steps = [{"axis_name": "색상", "values": ["블랙", "화이트", "그레이"]}]
    combos = generate_combinations(steps)
    assert len(combos) == 3
    assert combos[0] == {"axes": {"색상": "블랙"}, "values": ["블랙"]}


def test_combo_2axis():
    steps = [
        {"axis_name": "색상", "values": ["블랙", "화이트"]},
        {"axis_name": "사이즈", "values": ["250", "260"]},
    ]
    combos = generate_combinations(steps)
    assert len(combos) == 4          # 2 × 2
    assert combos[0] == {"axes": {"색상": "블랙", "사이즈": "250"},
                         "values": ["블랙", "250"]}
    assert combos[3] == {"axes": {"색상": "화이트", "사이즈": "260"},
                         "values": ["화이트", "260"]}


def test_combo_3axis():
    steps = [
        {"axis_name": "모델", "values": ["에어포스", "덩크"]},
        {"axis_name": "색상", "values": ["블랙", "화이트"]},
        {"axis_name": "사이즈", "values": ["260", "270"]},
    ]
    combos = generate_combinations(steps)
    assert len(combos) == 8          # 2 × 2 × 2


def test_combo_empty_steps():
    assert generate_combinations([]) == []


def test_combo_step_with_no_values():
    steps = [{"axis_name": "색상", "values": []}]
    assert generate_combinations(steps) == []


# ============ build_sku ============

def test_build_sku_2axis():
    assert build_sku("AF", ["블랙", "260"]) == "AF-블랙-260"


def test_build_sku_1axis():
    assert build_sku("AF", ["블랙"]) == "AF-블랙"


def test_build_sku_no_values():
    assert build_sku("AF", []) == "AF"


def test_build_sku_skips_blanks():
    assert build_sku("AF", ["블랙", "", "  "]) == "AF-블랙"


# ============ steps_from_rows (BundleOptionStep 행 → 조합 입력) ============

def _step(step_no, axis_name, values_json):
    return SimpleNamespace(step_no=step_no, axis_name=axis_name,
                           values_json=values_json)


def test_steps_from_rows_sorts_and_parses():
    rows = [
        _step(2, "사이즈", '["250", "260"]'),
        _step(1, "색상", '["블랙", "화이트"]'),
    ]
    assert steps_from_rows(rows) == [
        {"axis_name": "색상", "values": ["블랙", "화이트"]},
        {"axis_name": "사이즈", "values": ["250", "260"]},
    ]


def test_steps_from_rows_bad_json():
    rows = [_step(1, "색상", "not-json")]
    assert steps_from_rows(rows) == [{"axis_name": "색상", "values": []}]


def test_steps_from_rows_empty():
    assert steps_from_rows([]) == []


def test_steps_from_rows_to_combinations():
    # steps_from_rows → generate_combinations 연계
    rows = [_step(1, "색상", '["블랙"]'), _step(2, "사이즈", '["250", "260"]')]
    combos = generate_combinations(steps_from_rows(rows))
    assert len(combos) == 2
    assert combos[0]["axes"] == {"색상": "블랙", "사이즈": "250"}


# ============ option_axis_values / option_sku (N축 + 레거시 폴백) ============

def _opt(model_code='AF', axis_values_json=None, color_code=None, size_code=None):
    return SimpleNamespace(model_code=model_code, axis_values_json=axis_values_json,
                           color_code=color_code, size_code=size_code)


def test_axis_values_from_json():
    o = _opt(axis_values_json='["블랙", "260"]')
    assert option_axis_values(o) == ["블랙", "260"]


def test_axis_values_legacy_fallback():
    o = _opt(axis_values_json=None, color_code="BK", size_code="250")
    assert option_axis_values(o) == ["BK", "250"]


def test_axis_values_bad_json_fallback():
    o = _opt(axis_values_json='oops', color_code="BK", size_code="250")
    assert option_axis_values(o) == ["BK", "250"]


def test_axis_values_empty():
    assert option_axis_values(_opt()) == []


def test_option_sku_naxis():
    o = _opt(model_code="AF", axis_values_json='["블랙", "260"]')
    assert option_sku(o) == "AF-블랙-260"


def test_option_sku_legacy():
    o = _opt(model_code="AF", color_code="BK", size_code="250")
    assert option_sku(o) == "AF-BK-250"


# ============ build_options_from_steps (조합 추가 핵심 — 순수) ============

def test_build_options_2axis():
    steps = [{"axis_name": "색상", "values": ["블랙", "화이트"]},
             {"axis_name": "사이즈", "values": ["250", "260"]}]
    specs = build_options_from_steps("AF", steps)
    assert len(specs) == 4
    assert specs[0]["canonical_sku"] == "AF-블랙-250"
    assert specs[0]["axis_values"] == ["블랙", "250"]


def test_build_options_skips_existing():
    steps = [{"axis_name": "색상", "values": ["블랙", "화이트", "그레이"]}]
    specs = build_options_from_steps("AF", steps, existing_skus={"AF-블랙"})
    skus = [s["canonical_sku"] for s in specs]
    assert "AF-블랙" not in skus and len(specs) == 2


def test_build_options_selected():
    steps = [{"axis_name": "색상", "values": ["블랙", "화이트"]},
             {"axis_name": "사이즈", "values": ["250", "260"]}]
    specs = build_options_from_steps(
        "AF", steps, selected=[["블랙", "250"], ["화이트", "260"]])
    assert sorted(s["canonical_sku"] for s in specs) == \
        ["AF-블랙-250", "AF-화이트-260"]


def test_build_options_axis_json():
    specs = build_options_from_steps("AF", [{"axis_name": "색상",
                                             "values": ["블랙"]}])
    import json as _j
    assert _j.loads(specs[0]["axis_values_json"]) == ["블랙"]


# ============ option_is_offline (오프라인 전용 옵션 — Phase 3) ============

def test_option_is_offline():
    assert option_is_offline(SimpleNamespace(offline_only=True)) is True
    assert option_is_offline(SimpleNamespace(offline_only=False)) is False
    assert option_is_offline(SimpleNamespace()) is False
