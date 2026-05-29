"""tests/test_sku_format.py — SKU·바코드·품번 컬럼 규칙 (Phase 1-4)."""
import re

from shared.sku_format import (
    is_valid_sku, gen_sku,
    gen_barcode, is_valid_barcode,
    is_valid_article_no, clean_article_no,
    has_korean,
    clean_brand, clean_category, clean_model_name,
    clean_color, clean_size, clean_avg_price, clean_memo,
    normalize_label, color_matches, size_matches,
)


# ============ SKU ============

def test_gen_sku_format():
    sku = gen_sku()
    assert re.match(r'^SKU-[A-Z0-9]{8}$', sku)


def test_gen_sku_dedup():
    existing = set()
    for _ in range(30):
        s = gen_sku(existing)
        existing.add(s)
    assert len(existing) == 30


def test_is_valid_sku():
    assert is_valid_sku('SKU-ABC12345')
    assert not is_valid_sku('SKU-abc12345')
    assert not is_valid_sku('SKU-1234567')
    assert not is_valid_sku('르무통-블랙-220')
    assert not is_valid_sku('')
    assert not is_valid_sku(None)


# ============ 바코드 ============

def test_gen_barcode_format():
    bc = gen_barcode()
    assert len(bc) == 13
    assert bc.isdigit()
    assert bc.startswith('200')


def test_gen_barcode_valid_checksum():
    for _ in range(10):
        bc = gen_barcode()
        assert is_valid_barcode(bc), f"체크섬 위반: {bc}"


def test_is_valid_barcode_bad():
    assert not is_valid_barcode('123')
    assert not is_valid_barcode('abc1234567890')


# ============ 품번 ============

def test_is_valid_article_no():
    assert is_valid_article_no('CW2288-001')
    assert is_valid_article_no('FV5420_002')
    assert is_valid_article_no('N251ABG520')
    assert not is_valid_article_no('마스마룰즈_데일리백팩')
    assert not is_valid_article_no('SKU-ABC12345')
    assert not is_valid_article_no('')


def test_clean_article_no():
    assert clean_article_no('CW2288-001') == 'CW2288-001'
    assert clean_article_no('') == '-'
    assert clean_article_no(None) == '-'
    assert clean_article_no('한글') == '-'
    assert clean_article_no('SKU-XXX12345') == '-'


# ============ 한글 검사 ============

def test_has_korean():
    assert has_korean('르무통_메이트')
    assert has_korean('블랙')
    assert not has_korean('SKU-ABC12345')
    assert not has_korean('CW2288-001')
    assert not has_korean('')
    assert not has_korean(None)


# ============ [2026-05-29] 컬럼 규칙 강제 (10개 룰) ============

def test_clean_brand_fallback():
    assert clean_brand('나이키') == '나이키'
    assert clean_brand('') == '미상'
    assert clean_brand(None) == '미상'
    assert clean_brand('  ') == '미상'
    assert clean_brand('a' * 200) == 'a' * 100  # 100자 제한


def test_clean_category_blank_allowed():
    assert clean_category('스니커즈') == '스니커즈'
    assert clean_category('') == ''      # 빈 값 허용
    assert clean_category(None) == ''


def test_clean_model_name_required():
    assert clean_model_name('메이트') == '메이트'
    assert clean_model_name('') is None  # None = 미입력 (호출처 필수 체크)
    assert clean_model_name(None) is None
    assert clean_model_name('a' * 300) == 'a' * 255  # 255자


def test_clean_color_fallback():
    assert clean_color('블랙') == '블랙'
    assert clean_color('') == 'ONE'
    assert clean_color(None) == 'ONE'


def test_clean_size_fallback():
    assert clean_size('260') == '260'
    assert clean_size('') == 'FREE'
    assert clean_size(None) == 'FREE'


def test_clean_avg_price():
    assert clean_avg_price(50000) == 50000
    assert clean_avg_price('50,000') == 50000
    assert clean_avg_price('') == 0       # 0 허용
    assert clean_avg_price(None) == 0
    assert clean_avg_price('abc') == 0    # 비숫자
    assert clean_avg_price(-100) == 0     # 음수 차단


def test_clean_memo():
    assert clean_memo('테스트 메모') == '테스트 메모'
    assert clean_memo('') == ''
    assert clean_memo(None) == ''


# ============ 표기 차이 alias ============

def test_normalize_label():
    assert normalize_label('Sky Blue') == 'skyblue'
    assert normalize_label('  BLACK  ') == 'black'
    assert normalize_label('스카이블루') == '스카이블루'  # 한글은 보존


def test_color_matches_kr_en():
    assert color_matches('블랙', 'BLACK')
    assert color_matches('블랙', 'black')
    assert color_matches('블랙', 'BK')
    assert color_matches('스카이블루', 'Sky Blue')
    assert color_matches('스카이블루', 'SB')
    assert not color_matches('블랙', '화이트')


def test_size_matches_kr_us():
    assert size_matches('250', '250')
    assert size_matches('250', '7US')      # KR 250 ↔ US 7
    assert size_matches('245', '7.5US')
    assert size_matches('FREE', 'free')
    assert size_matches('FREE', 'OneSize')
    assert not size_matches('250', '260')
