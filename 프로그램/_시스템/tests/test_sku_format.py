"""tests/test_sku_format.py — SKU·바코드·품번 컬럼 규칙 (Phase 1-4)."""
import re

from shared.sku_format import (
    is_valid_sku, gen_sku,
    gen_barcode, is_valid_barcode,
    is_valid_article_no, clean_article_no,
    has_korean,
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
