# -*- coding: utf-8 -*-
"""소싱처 번호 변환 — 화면 번호와 계산 번호가 다르다는 사실을 한 곳에 가둔다.

배경(2026-07-20): 두 체계가 8개 소싱처 전부에서 어긋나 있었고, 화면에서 저장한
혜택이 **다른 소싱처** 계산에 들어갔다(무신사 후기적립 500 → 롯데온).
"""
from lemouton.sourcing import source_ids as si


def test_pricing_id_for_builtin_keys():
    assert si.pricing_source_id('lemouton') == 1
    assert si.pricing_source_id('ss_lemouton') == 2
    assert si.pricing_source_id('musinsa') == 3
    assert si.pricing_source_id('ssf') == 4
    assert si.pricing_source_id('lotteon') == 5
    assert si.pricing_source_id('ssg') == 6


def test_catalog_keys_get_string_id():
    """정수 자리가 없는 카탈로그 소싱처는 'key:' 합성 id."""
    assert si.pricing_source_id('hmall') == 'key:hmall'
    assert si.pricing_source_id('lotteimall') == 'key:lotteimall'


def test_unknown_key_is_none():
    assert si.pricing_source_id('없는소싱처') is None


def test_blank_key_is_none():
    assert si.pricing_source_id('') is None
    assert si.pricing_source_id(None) is None


def test_site_key_round_trip():
    for k in ('lemouton', 'ss_lemouton', 'musinsa', 'ssf', 'lotteon', 'ssg'):
        assert si.site_key(si.pricing_source_id(k)) == k
    assert si.site_key('key:hmall') == 'hmall'


def test_site_key_bad_input_is_none():
    assert si.site_key(None) is None
    assert si.site_key(999) is None
    assert si.site_key('key:') is None


def test_site_key_accepts_numeric_string():
    """매트릭스가 문자열 '3' 을 넘기는 경로가 있어 정수 문자열도 받아야 한다."""
    assert si.site_key('3') == 'musinsa'


def test_templates_are_integer_only():
    """혜택 템플릿은 Integer 컬럼이라 카탈로그 소싱처엔 못 붙는다 — 호출자가 알 수 있게."""
    assert si.supports_benefit_templates('musinsa') is True
    assert si.supports_benefit_templates('hmall') is False
    assert si.supports_benefit_templates('lotteimall') is False
    assert si.supports_benefit_templates('없는소싱처') is False


def test_matches_api_benefits_hardcoded_table():
    """★ 드리프트 감시 — api_benefits.py 의 기존 표와 다르면 전 소싱처 금액이 틀어진다.

    Task 2 에서 그 표를 지우고 이 모듈을 쓰게 바꾼다. 그 전까지 둘이 같은지 지킨다.
    """
    import re, pathlib
    src = pathlib.Path(__file__).resolve().parents[2] / 'webapp' / 'routes' / 'api_benefits.py'
    text = src.read_text(encoding='utf-8')
    m = re.search(r"_SITE_BY_SRC\s*=\s*\{([^}]*)\}", text)
    if m is None:
        return          # Task 2 에서 제거됨 — 이 감시는 역할을 다한 것
    pairs = dict(re.findall(r"(\d+)\s*:\s*'([a-z_]+)'", m.group(1)))
    for num, key in pairs.items():
        assert si.pricing_source_id(key) == int(num), (
            f'api_benefits._SITE_BY_SRC 와 어긋남: {key} → {num}')
