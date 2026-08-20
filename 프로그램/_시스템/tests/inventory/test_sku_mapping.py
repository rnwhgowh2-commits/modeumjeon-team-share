"""[TEST] sku_mapping.py — fuzzy 매칭 알고리즘 단위 테스트.

ai-workflow STEP 7 Sprint 1B Task 1.7
"""
from types import SimpleNamespace

from lemouton.inventory.sku_mapping import (
    normalize, normalize_size, score_pair,
)


def make_option(canonical_sku, size_code, color_code, **kw):
    return SimpleNamespace(
        canonical_sku=canonical_sku, size_code=size_code, size_display=kw.get('size_display'),
        color_code=color_code, color_display=kw.get('color_display'),
        model_code=kw.get('model_code', 'M-1'),
    )


def make_model(name_raw, name_display=None):
    return SimpleNamespace(model_code='M-1', model_name_raw=name_raw,
                            model_name_display=name_display)


# ============ 정규화 ============

def test_normalize_removes_spaces_and_special():
    assert normalize('르무통 클래식 (A)') == '르무통클래식a'
    assert normalize('나이키-코르테즈 / 블랙') == '나이키코르테즈블랙'
    assert normalize(None) == ''


def test_normalize_size_extracts_digits():
    assert normalize_size('225mm') == '225'
    assert normalize_size('225') == '225'
    assert normalize_size('L') == 'l'
    assert normalize_size(None) == ''


# ============ 점수 ============

def test_score_exact_match():
    """모델·사이즈·컬러 모두 일치 = 100"""
    o = make_option('K1', '225', 'BLK', size_display='225', color_display='블랙')
    m = make_model('르무통 클래식')
    bh = {'sku': 'BH-1', 'model_name': '르무통 클래식', 'size': 225, 'color_text': '블랙'}
    score, reason = score_pair(o, m, bh)
    assert score == 100
    assert reason == 'exact'


def test_score_color_mismatch_rejected():
    """[정합성] 모델·사이즈 일치라도 색상 다르면 매핑 거부(0).

    색상 무시 매핑은 1:N 오매핑을 야기 → 금지(score_pair 정책). 옛 '80 model_size'는 폐기.
    """
    o = make_option('K1', '225', 'BLK', size_display='225', color_display='블랙')
    m = make_model('르무통 클래식')
    bh = {'sku': 'BH-2', 'model_name': '르무통 클래식', 'size': 225, 'color_text': '화이트'}
    score, reason = score_pair(o, m, bh)
    assert score == 0
    assert reason == 'color_mismatch'


def test_score_size_mismatch_rejected():
    """[정합성] 모델 일치라도 사이즈 다르면 매핑 거부(0). 옛 '50 model_only'는 폐기."""
    o = make_option('K1', '225', 'BLK', size_display='225', color_display='블랙')
    m = make_model('르무통 클래식')
    bh = {'sku': 'BH-3', 'model_name': '르무통 클래식', 'size': 230, 'color_text': '블랙'}
    score, reason = score_pair(o, m, bh)
    assert score == 0
    assert reason == 'size_mismatch'


def test_score_color_missing_goes_to_review():
    """모델·사이즈 일치 + 색상 데이터 한쪽 누락 = 60(자동매핑 아닌 검토 큐)."""
    o = make_option('K1', '225', 'BLK', size_display='225', color_display='블랙')
    m = make_model('르무통 클래식')
    bh = {'sku': 'BH-7', 'model_name': '르무통 클래식', 'size': 225, 'color_text': ''}
    score, reason = score_pair(o, m, bh)
    assert score == 60
    assert reason == 'model_size_only'


def test_score_no_match_different_model():
    """모델명 자체가 다름 = 0"""
    o = make_option('K1', '225', 'BLK', size_display='225', color_display='블랙')
    m = make_model('르무통 클래식')
    bh = {'sku': 'BH-4', 'model_name': '나이키 코르테즈', 'size': 225, 'color_text': '블랙'}
    score, _ = score_pair(o, m, bh)
    assert score == 0


def test_score_substring_match():
    """모델명 부분일치 (substring)도 인정."""
    o = make_option('K1', '225', 'BLK', size_display='225', color_display='블랙')
    m = make_model('르무통 클래식')
    # 박스히어로 측은 더 긴 이름 — 우리 모델명이 박스히어로 안에 포함
    bh = {'sku': 'BH-5', 'model_name': '르무통 클래식 신상', 'size': 225, 'color_text': '블랙'}
    score, _ = score_pair(o, m, bh)
    assert score >= 80  # exact 또는 model_size 인정


def test_normalize_handles_special_chars():
    """공백·특수문자 무시."""
    o = make_option('K1', '225', 'BLK', size_display='225', color_display='블랙')
    m = make_model('르무통-클래식 / A')
    bh = {'sku': 'BH-6', 'model_name': '르무통_클래식.A', 'size': 225, 'color_text': '블랙'}
    score, _ = score_pair(o, m, bh)
    # 정규화 후 같음
    assert score == 100


# ============ 정수 점수 보장 ============

def test_score_returns_int():
    o = make_option('K1', '225', 'BLK')
    m = make_model('르무통')
    bh = {'sku': 'X', 'model_name': '르무통', 'size': 225, 'color_text': ''}
    score, _ = score_pair(o, m, bh)
    assert isinstance(score, int)
