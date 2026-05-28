"""tests/sourcing/test_option_combo.py — 단계형 옵션 조합 생성 (Phase 2 TDD).

ai-workflow cycle 20260521 · Phase 2 · Task 1
"""
from types import SimpleNamespace

from lemouton.sourcing.option_combo import (
    parse_comma_values, generate_combinations, build_sku, gen_canonical_sku,
    steps_from_rows, option_axis_values, option_sku, build_options_from_steps,
    option_is_offline,
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


# ============ gen_canonical_sku (Phase 1-1 — 사용자 룰) ============

import re

def test_gen_canonical_sku_format():
    """SKU-XXX 형식 (영숫자 대문자 8자) — 한글 없음."""
    sku = gen_canonical_sku(set())
    assert re.match(r'^SKU-[A-Z0-9]{8}$', sku), f"형식 위반: {sku}"


def test_gen_canonical_sku_dedup():
    """existing set 에 추가하여 중복 회피."""
    existing = set()
    skus = [gen_canonical_sku(existing) for _ in range(20)]
    assert len(set(skus)) == 20  # 모두 unique
    assert all(s in existing for s in skus)


# ============ build_options_from_steps (Phase 1-1 — SKU-XXX 형식) ============

def test_build_options_2axis():
    """[Phase 2-1] selected 명시 필수. None 이면 0건."""
    steps = [{"axis_name": "색상", "values": ["블랙", "화이트"]},
             {"axis_name": "사이즈", "values": ["250", "260"]}]
    # selected=None → 0건 (사용자 룰: 자동 카르테시안 금지)
    specs = build_options_from_steps("AF", steps)
    assert specs == []
    # selected 명시 → 그 조합만
    specs = build_options_from_steps(
        "AF", steps,
        selected=[["블랙", "250"], ["블랙", "260"], ["화이트", "250"], ["화이트", "260"]])
    assert len(specs) == 4
    for spec in specs:
        assert re.match(r'^SKU-[A-Z0-9]{8}$', spec["canonical_sku"])


def test_build_options_skips_existing_axes():
    """existing_axes 로 중복 옵션 회피 — selected 안에서도 동작."""
    steps = [{"axis_name": "색상", "values": ["블랙", "화이트", "그레이"]}]
    existing_axes = {("AF", ("블랙",))}
    specs = build_options_from_steps(
        "AF", steps,
        existing_axes=existing_axes,
        selected=[["블랙"], ["화이트"], ["그레이"]])
    axis_values = [s["axis_values"] for s in specs]
    assert ["블랙"] not in axis_values
    assert ["화이트"] in axis_values
    assert ["그레이"] in axis_values
    assert len(specs) == 2


def test_build_options_no_selected_returns_empty():
    """[Phase 2-1 핵심] selected=None 이면 자동 cartesian 생성 X."""
    steps = [{"axis_name": "색상", "values": ["블랙", "화이트", "그레이"]},
             {"axis_name": "사이즈", "values": ["220", "230", "240"]}]
    # selected 미전달 (None) → 0건 (3×3 = 9건 만들지 X)
    assert build_options_from_steps("AF", steps) == []
    # selected=[] → 0건
    assert build_options_from_steps("AF", steps, selected=[]) == []


def test_build_options_selected():
    """selected 만 처리. canonical_sku 는 SKU-XXX."""
    steps = [{"axis_name": "색상", "values": ["블랙", "화이트"]},
             {"axis_name": "사이즈", "values": ["250", "260"]}]
    specs = build_options_from_steps(
        "AF", steps, selected=[["블랙", "250"], ["화이트", "260"]])
    assert len(specs) == 2
    axis_values_set = {tuple(s["axis_values"]) for s in specs}
    assert axis_values_set == {("블랙", "250"), ("화이트", "260")}
    # SKU-XXX 형식 검증
    for spec in specs:
        assert re.match(r'^SKU-[A-Z0-9]{8}$', spec["canonical_sku"])


def test_build_options_axis_json():
    """selected 명시 → axis_values_json 정상 저장."""
    specs = build_options_from_steps(
        "AF", [{"axis_name": "색상", "values": ["블랙"]}],
        selected=[["블랙"]])
    import json as _j
    assert _j.loads(specs[0]["axis_values_json"]) == ["블랙"]


def test_build_options_no_korean_in_sku():
    """Phase 1 핵심 — selected 명시해도 canonical_sku 에 한글 X."""
    steps = [{"axis_name": "색상", "values": ["블랙", "화이트", "그레이"]},
             {"axis_name": "사이즈", "values": ["250", "260"]}]
    sel = [[c, sz] for c in ["블랙", "화이트", "그레이"] for sz in ["250", "260"]]
    specs = build_options_from_steps("르무통_메이트", steps, selected=sel)
    for spec in specs:
        assert not any('가' <= ch <= '힣' for ch in spec["canonical_sku"]), \
            f"한글 SKU 발견: {spec['canonical_sku']}"


# ============ option_is_offline (오프라인 전용 옵션 — Phase 3) ============

def test_option_is_offline():
    assert option_is_offline(SimpleNamespace(offline_only=True)) is True
    assert option_is_offline(SimpleNamespace(offline_only=False)) is False
    assert option_is_offline(SimpleNamespace()) is False
