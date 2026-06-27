"""linker 매칭 코어 — 오프라인 단위 테스트 (DB·네트워크 불필요)."""
from lemouton.uploader.linker import MarketOption, match_market_options_to_skus


def _bundle():
    return [
        {"canonical_sku": "AF-블랙-260", "color_code": "블랙", "color_display": "블랙",
         "size_code": "260", "size_display": "260"},
        {"canonical_sku": "AF-블루-270", "color_code": "블루", "color_display": "블루",
         "size_code": "270", "size_display": "270"},
    ]


def test_exact_match_by_display():
    rows = match_market_options_to_skus(
        _bundle(), [MarketOption(option_id="opt1", color="블랙", size="260")])
    assert rows[0].status == "matched"
    assert rows[0].canonical_sku == "AF-블랙-260"
    assert rows[0].market_option_id == "opt1"


def test_english_korean_color_match():
    # 마켓이 'navy' 로 표기 → normalize 가 '블루' 로 매핑
    rows = match_market_options_to_skus(
        _bundle(), [MarketOption(option_id="o2", color="navy", size="270")])
    assert rows[0].status == "matched"
    assert rows[0].canonical_sku == "AF-블루-270"


def test_size_unit_normalized():
    # '270mm' 의 단위 mm 제거 후 '270' 매칭
    rows = match_market_options_to_skus(
        _bundle(), [MarketOption(option_id="o3", color="블루", size="270mm")])
    assert rows[0].status == "matched"
    assert rows[0].canonical_sku == "AF-블루-270"


def test_unmatched_when_no_pair():
    rows = match_market_options_to_skus(
        _bundle(), [MarketOption(option_id="o4", color="레드", size="999")])
    assert rows[0].status == "unmatched"
    assert rows[0].canonical_sku is None


def test_ambiguous_when_two_bundle_share_color_size():
    dupe = _bundle() + [
        {"canonical_sku": "AF-블랙-260-DUP", "color_code": "블랙", "color_display": "블랙",
         "size_code": "260", "size_display": "260"}]
    rows = match_market_options_to_skus(
        dupe, [MarketOption(option_id="o5", color="블랙", size="260")])
    assert rows[0].status == "ambiguous"
    assert rows[0].canonical_sku is None


def test_empty_color_size_is_unmatched():
    # 빈 색상·사이즈는 빈 번들옵션과 거짓매칭되면 안 됨 → unmatched
    rows = match_market_options_to_skus(
        _bundle(), [MarketOption(option_id="ox", color="", size="")])
    assert rows[0].status == "unmatched"
    assert rows[0].canonical_sku is None
