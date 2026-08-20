# -*- coding: utf-8 -*-
"""가이드 스키마 확장 — 주소별 크롤 결과 + 주소·구분자 (S2).

배경(설계 2026-07-19-소싱처상세-지도흡수):
  ① 검증 결과가 세 곳(verification.last_new_check · saved_checks · examples)에 흩어져
     있고, last_new_check 는 **한 칸뿐**이라 마지막 1건만 남고 덮어써졌다.
     → 예시 주소마다 결과를 붙인다(sample_urls[].result).
  ② 소싱처 API 주소·구분자가 네 곳에 흩어져 있고 코드가 읽는 원천이 없다.
     → 가이드에 api{base, endpoints} 를 신설한다. 사용자가 전체 업데이트할 자리.

원칙: 값이 없거나 이상하면 **버리지 말고 안전하게 정제**한다(가격·재고는 금전 경로).
"""
import pytest

from lemouton.sourcing import crawl_guide as cg


def _v(**over):
    g = cg.empty_skeleton()
    g.update(over)
    return cg.validate_guide(g)


# ── ① 예시 주소: 이름·메모·크롤 결과 ──────────────────────────────────────

def test_sample_url_keeps_name_and_memo():
    g = _v(sample_urls=[{'url': 'https://a.com/1', 'is_lead': True,
                         'name': '기본 상품', 'memo': '옵션이 가장 많음'}])
    u = g['sample_urls'][0]
    assert u['name'] == '기본 상품'
    assert u['memo'] == '옵션이 가장 많음'
    assert u['is_lead'] is True


def test_sample_url_result_roundtrip():
    """크롤 결과가 주소에 붙어 그대로 보존된다."""
    g = _v(sample_urls=[{'url': 'https://a.com/1', 'result': {
        'surface_price': 129000, 'benefit_total': 11353, 'final_price': 117647,
        'stock_label': '재고 있음', 'status': 'done',
        'crawled_at': '2026-07-19T14:22:00Z', 'job_id': 77}}])
    r = g['sample_urls'][0]['result']
    assert r['surface_price'] == 129000
    assert r['final_price'] == 117647
    assert r['stock_label'] == '재고 있음'
    assert r['status'] == 'done'
    assert r['job_id'] == 77


def test_sample_url_without_result_is_none():
    """아직 안 긁은 주소 — result 는 None (0 이 아니다)."""
    g = _v(sample_urls=[{'url': 'https://a.com/1'}])
    assert g['sample_urls'][0]['result'] is None


def test_result_bad_numbers_become_none_not_zero():
    """숫자가 이상하면 0 이 아니라 None. 0원은 '공짜'로 읽혀 금전 사고가 된다."""
    g = _v(sample_urls=[{'url': 'https://a.com/1',
                         'result': {'surface_price': 'abc', 'final_price': None}}])
    r = g['sample_urls'][0]['result']
    assert r['surface_price'] is None
    assert r['final_price'] is None


def test_result_status_whitelist():
    g = _v(sample_urls=[{'url': 'https://a.com/1', 'result': {'status': '엉뚱한값'}}])
    assert g['sample_urls'][0]['result']['status'] is None


def test_sample_url_still_rejects_non_http():
    with pytest.raises(ValueError):
        _v(sample_urls=[{'url': 'ftp://a.com/1'}])


# ── ② 주소·구분자 ─────────────────────────────────────────────────────────

def test_api_base_and_endpoints_roundtrip():
    g = _v(api={'base': 'https://goods-detail.musinsa.com',
                'endpoints': {
                    'inventories': {'path': '/api2/goods/{id}/options/v2/prioritized-inventories',
                                    'method': 'POST',
                                    'response_fields': {'stock': 'data.optionItems'}},
                }})
    assert g['api']['base'] == 'https://goods-detail.musinsa.com'
    ep = g['api']['endpoints']['inventories']
    assert ep['method'] == 'POST'
    assert ep['path'].startswith('/api2/goods/')
    assert ep['response_fields']['stock'] == 'data.optionItems'


def test_api_method_defaults_to_get():
    g = _v(api={'endpoints': {'meta': {'path': '/api2/goods/{id}'}}})
    assert g['api']['endpoints']['meta']['method'] == 'GET'


def test_api_method_whitelist():
    g = _v(api={'endpoints': {'meta': {'path': '/x', 'method': 'DROP'}}})
    assert g['api']['endpoints']['meta']['method'] == 'GET'


def test_api_endpoint_without_path_is_dropped():
    """경로가 없으면 부를 수 없다 — 빈 껍데기를 남기지 않는다."""
    g = _v(api={'endpoints': {'meta': {'method': 'GET'}}})
    assert 'meta' not in g['api']['endpoints']


def test_empty_skeleton_has_api_block():
    g = cg.empty_skeleton()
    assert g['api'] == {'base': '', 'endpoints': {}}


@pytest.mark.parametrize('bad', [None, 'x', 3, []])
def test_api_bad_input_is_safe(bad):
    g = _v(api=bad)
    assert g['api'] == {'base': '', 'endpoints': {}}


# ── ③ 하위호환 — 기존 카드가 깨지지 않는다 ────────────────────────────────

def test_old_card_without_new_keys_still_valid():
    old = {'version': 3, 'sample_urls': [{'url': 'https://a.com/1', 'is_lead': False}],
           'fields': {}, 'pricing': {}, 'verification': {}}
    g = cg.validate_guide(old)
    assert g['sample_urls'][0]['name'] == ''
    assert g['sample_urls'][0]['result'] is None
    assert g['api'] == {'base': '', 'endpoints': {}}


# ── ④ [S5] 실패 사유 · 혜택 출처 ──────────────────────────────────────────
#
# S5 에서 주소별 「▶ 크롤」이 붙으면서 두 가지가 결과에 더 필요해졌다.
#
#   error         — 실패했을 때 **왜** 실패했는지. 빈칸으로 두면 사용자는
#                   "눌렀는데 아무 일도 안 일어났다"로 읽는다(조용한 실패 금지).
#   benefit_source— 이 최종매입가가 **크롤한 혜택**까지 반영한 값인지,
#                   **가이드 고정 혜택만** 반영한 값인지.
#                   확장은 무신사·롯데온에서만 benefit_lines 를 준다
#                   (background.js:1563). 나머지 소싱처는 고정 혜택만으로 계산되는데,
#                   그 사실을 표시하지 않으면 사장님이 "혜택 다 빠진 값"을
#                   "혜택 반영된 값"으로 오해한다 → 금전 오해.

def test_result_keeps_error_reason():
    """실패 사유가 보존된다 — 실패를 조용히 삼키지 않는다."""
    g = _v(sample_urls=[{'url': 'https://a.com/1', 'result': {
        'status': 'failed', 'error': '로그인이 풀렸습니다(무신사)'}}])
    r = g['sample_urls'][0]['result']
    assert r['status'] == 'failed'
    assert r['error'] == '로그인이 풀렸습니다(무신사)'


def test_result_error_absent_is_none():
    g = _v(sample_urls=[{'url': 'https://a.com/1', 'result': {'status': 'done'}}])
    assert g['sample_urls'][0]['result']['error'] is None


def test_result_benefit_source_roundtrip():
    """크롤 혜택까지 반영한 값인지, 고정 혜택만인지 구분해 보존한다."""
    g = _v(sample_urls=[{'url': 'https://a.com/1',
                         'result': {'status': 'done', 'benefit_source': 'fixed_only'}}])
    assert g['sample_urls'][0]['result']['benefit_source'] == 'fixed_only'


def test_result_benefit_source_whitelist():
    """모르는 값은 None — '크롤 반영됨'으로 둔갑시키지 않는다."""
    g = _v(sample_urls=[{'url': 'https://a.com/1',
                         'result': {'status': 'done', 'benefit_source': '아무거나'}}])
    assert g['sample_urls'][0]['result']['benefit_source'] is None


def test_result_explicit_none_error_stays_none():
    """★ str(None) == 'None' 함정 — 성공한 크롤에 '크롤 실패 — None' 이 뜨면 안 된다."""
    g = _v(sample_urls=[{'url': 'https://a.com/1',
                         'result': {'status': 'done', 'error': None}}])
    assert g['sample_urls'][0]['result']['error'] is None


def test_result_stock_label_explicit_none_stays_none():
    """같은 함정 — 다른 문자열 칸도 'None' 이 되면 안 된다."""
    g = _v(sample_urls=[{'url': 'https://a.com/1',
                         'result': {'status': 'failed', 'stock_label': None}}])
    assert g['sample_urls'][0]['result']['stock_label'] is None
