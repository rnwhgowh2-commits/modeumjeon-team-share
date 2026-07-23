# -*- coding: utf-8 -*-
"""가공 규칙 **적용** 엔진 — lemouton/registration/process_apply.py.

여기까지 규칙은 정의·저장·편집만 됐고 **적용하는 코드가 없었다**(사장님이 화면에서
값을 넣어도 아무 데도 안 쓰이는 조용한 거짓 기능). 이 테스트가 고정하는 것:

  · 저장 드래프트를 **손대지 않는다** — 읽기 전용 사본에만 적용(notice_defaults 규율)
  · 적용 못 하면 **반드시 사유를 남긴다** — 조용히 원본 통과 금지
  · 마켓 상한은 **확인된 마켓만** — 확인 불가 마켓은 자르지 않는다
"""
# [2026-07-23] M4 가공 규칙 적용 엔진
import json

import pytest

from lemouton.registration import process_apply as PA


class _Draft:
    """ProductDraft 흉내 — 순수함수라 DB 가 필요 없다."""

    def __init__(self, **kw):
        self.name = kw.pop('name', '나이키 에어포스 1 화이트')
        self.brand = kw.pop('brand', '나이키')
        self.source_site = kw.pop('source_site', 'musinsa')
        self.source_category_path = kw.pop('source_category_path', '신발>스니커즈')
        self.options_json = kw.pop('options_json', '[]')
        self.notice_json = kw.pop('notice_json', '{}')
        for k, v in kw.items():
            setattr(self, k, v)


def _codes(skipped):
    return [s['code'] for s in skipped]


def _blocking(skipped):
    return [s for s in skipped if s['blocking']]


# ── 저장값 불변 ─────────────────────────────────────────────────────────────

def test_저장_드래프트를_바꾸지_않는다():
    d = _Draft(name='에어포스 1', brand='나이키')
    view, applied, _ = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name'],
                                                   'separator': ' '}})
    assert d.name == '에어포스 1', '원본 드래프트가 바뀌었습니다 — 저장값 불변 위반'
    assert view.name == '나이키 에어포스 1'
    assert applied, '무엇이 무엇으로 바뀌었는지 로그가 없습니다'


def test_사본에_쓰려_하면_막는다():
    d = _Draft(name='에어포스 1', brand='나이키')
    view, _, _ = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name']}})
    with pytest.raises(AttributeError):
        view.name = '덮어쓰기'


def test_규칙이_없으면_원본을_그대로_돌려준다():
    d = _Draft()
    view, applied, skipped = PA.apply_rules(d, {})
    assert view is d
    assert applied == []
    assert skipped == []


# ── 상품명 조립 ─────────────────────────────────────────────────────────────

def test_조립_순서와_구분자를_따른다():
    d = _Draft(name='에어포스 1', brand='나이키')
    view, _, _ = PA.apply_rules(d, {'name': {'token_order': ['origin_name', 'brand'],
                                             'separator': ' - '}})
    assert view.name == '에어포스 1 - 나이키'


def test_조립_순서에_임의_텍스트를_끼워_넣는다():
    """설계서 §7-1 「맨앞·맨뒤·중간에 임의 텍스트 삽입」."""
    d = _Draft(name='에어포스 1', brand='나이키')
    view, _, _ = PA.apply_rules(d, {'name': {'token_order': ['[정품]', 'brand', 'origin_name']}})
    assert view.name == '[정품] 나이키 에어포스 1'


def test_품번_칸이_없으면_사유를_남긴다():
    """model_no 는 ProductDraft 에 칸이 없다 — 조용히 빼지 않고 말한다."""
    d = _Draft(name='에어포스 1', brand='나이키')
    view, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name',
                                                                  'model_no']}})
    assert view.name == '나이키 에어포스 1'
    assert 'NO_MODEL_NO' in _codes(skipped)
    assert not _blocking(skipped), '품번 없음은 등록을 막을 일이 아니다'


def test_원본_상품명이_비면_막는다():
    d = _Draft(name='', brand='나이키')
    _, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name']}})
    assert 'NO_NAME' in _codes(skipped)
    assert _blocking(skipped)


def test_중복_단어를_제거한다():
    d = _Draft(name='나이키 에어포스 1 나이키', brand='나이키')
    view, applied, _ = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name'],
                                                   'dedupe_words': True}})
    assert view.name == '나이키 에어포스 1'
    assert any(a['field'] == 'dedupe_words' for a in applied)


def test_중복_제거를_끄면_그대로_둔다():
    d = _Draft(name='나이키 에어포스 1', brand='나이키')
    view, _, _ = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name'],
                                             'dedupe_words': False}})
    assert view.name == '나이키 나이키 에어포스 1'


# ── 치환표 ──────────────────────────────────────────────────────────────────

def test_치환표를_적용한다():
    d = _Draft(name='숏 재킷', brand='')
    view, applied, _ = PA.apply_rules(d, {'name': {
        'token_order': ['origin_name'],
        'replacements': [{'from': '재킷', 'to': '자켓 재킷'}]}})
    assert view.name == '숏 자켓 재킷'
    assert any(a['field'] == 'replacements' for a in applied)


def test_치환표_문자열_표기도_읽는다():
    d = _Draft(name='숏 재킷', brand='')
    view, _, _ = PA.apply_rules(d, {'name': {'token_order': ['origin_name'],
                                             'replacements': ['재킷 → 자켓 재킷']}})
    assert view.name == '숏 자켓 재킷'


def test_치환표가_비면_적용했다고_하지_않는다():
    """치환을 안 쓰는 것은 정상 상태다 — 「적용됨」으로도, 경고로도 치지 않는다.
    (경고로 두면 모든 마켓 행에 상시 떠서 진짜 경고가 안 읽힌다 — 리뷰 S2)"""
    d = _Draft(name='숏 재킷', brand='')
    _, applied, skipped = PA.apply_rules(d, {'name': {'token_order': ['origin_name'],
                                                      'replacements': []}})
    assert not any(a['field'] == 'replacements' for a in applied)
    assert 'EMPTY_REPLACEMENTS' not in _codes(skipped)


def test_읽을_수_없는_치환_규칙은_막는다():
    """반쯤 적용된 치환은 잘못된 상품명을 만든다 — 조용히 넘어가지 않는다."""
    d = _Draft(name='숏 재킷', brand='')
    _, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['origin_name'],
                                                'replacements': [12345]}})
    assert 'BAD_REPLACEMENT' in _codes(skipped)
    assert _blocking(skipped)


# ── 브랜드 표기 ─────────────────────────────────────────────────────────────

def test_브랜드_위치_뒤():
    d = _Draft(name='에어포스 1', brand='나이키')
    view, _, _ = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name']},
                                    'brand': {'mode': 'korean', 'position': 'back'}})
    assert view.name == '에어포스 1 나이키'


def test_브랜드_위치_없음이면_상품명에서_뺀다():
    d = _Draft(name='에어포스 1', brand='나이키')
    view, applied, _ = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name']},
                                          'brand': {'mode': 'korean', 'position': 'none'}})
    assert view.name == '에어포스 1'
    assert any(a['item'] == 'brand' for a in applied)


def test_영문_표기_요구인데_국문_브랜드뿐이면_보류한다():
    """지어내지 않는다 — 번역은 프로그램이 할 일이 아니다."""
    d = _Draft(name='에어포스 1', brand='나이키')
    _, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name']},
                                       'brand': {'mode': 'english', 'position': 'front'}})
    assert 'BRAND_MODE_UNMET' in _codes(skipped)
    assert _blocking(skipped)


def test_영문_브랜드_대문자_표기():
    d = _Draft(name='에어포스 1', brand='nike')
    view, _, _ = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name'],
                                             'brand_case': 'upper'},
                                    'brand': {'mode': 'english', 'position': 'front'}})
    assert view.name == 'NIKE 에어포스 1'


def test_국문영문_병기는_두_표기가_다_있어야_한다():
    ok = _Draft(name='눕시', brand='노스페이스 THE NORTH FACE')
    view, _, skipped = PA.apply_rules(ok, {'name': {'token_order': ['brand', 'origin_name'],
                                                    'brand_case': 'as_is'},
                                           'brand': {'mode': 'both', 'position': 'front'}})
    assert view.name == '노스페이스 THE NORTH FACE 눕시'
    assert 'BRAND_MODE_UNMET' not in _codes(skipped)

    bad = _Draft(name='눕시', brand='노스페이스')
    _, _, skipped2 = PA.apply_rules(bad, {'name': {'token_order': ['brand', 'origin_name']},
                                          'brand': {'mode': 'both', 'position': 'front'}})
    assert 'BRAND_MODE_UNMET' in _codes(skipped2)


# ── 글자수 상한 (마켓별) ────────────────────────────────────────────────────

def test_규칙_글자수_상한으로_자른다():
    d = _Draft(name='가' * 50, brand='')
    view, applied, _ = PA.apply_rules(d, {'name': {'token_order': ['origin_name'],
                                                   'max_len': 20}})
    assert len(view.name) == 20
    assert any(a['field'] == 'max_len' for a in applied)


def test_마켓_상한이_더_짧으면_마켓_상한을_쓴다():
    d = _Draft(name='가' * 300, brand='')
    view, applied, _ = PA.apply_rules(
        d, {'name': {'token_order': ['origin_name'], 'max_len': 250}}, market='coupang')
    assert len(view.name) == 100, '쿠팡 등록상품명 100자 (지도 근거)'
    assert any('쿠팡' in (a.get('note') or '') or 'coupang' in (a.get('note') or '')
               for a in applied)


def test_상한을_확인_못_한_마켓은_자르지_않는다():
    """잘못된 상한으로 자르면 잘린 채로 팔린다 — 확인 불가면 그대로 보낸다."""
    d = _Draft(name='가' * 300, brand='')
    view, _, skipped = PA.apply_rules(
        d, {'name': {'token_order': ['origin_name'], 'max_len': 0}}, market='auction')
    assert len(view.name) == 300
    assert 'NO_MARKET_LIMIT' in _codes(skipped)
    assert not _blocking(skipped)


def test_상한_0_은_제한_없음():
    d = _Draft(name='가' * 300, brand='')
    view, _, _ = PA.apply_rules(d, {'name': {'token_order': ['origin_name'], 'max_len': 0}})
    assert len(view.name) == 300


# ── 금지어 ──────────────────────────────────────────────────────────────────

def test_수집_금지어는_전_마켓_차단():
    d = _Draft(name='나이키 이월상품 에어포스', brand='나이키')
    _, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['origin_name']}},
                                   collect_banned_words=['이월상품'])
    hit = [s for s in skipped if s['code'] == 'COLLECT_BANNED']
    assert hit and hit[0]['blocking']
    assert '이월상품' in hit[0]['reason']


def test_업로드_금지어는_그_마켓만_차단():
    d = _Draft(name='나이키 정품 병행수입', brand='나이키')
    rules = {'name': {'token_order': ['origin_name']},
             'banned_words': {'collect_banned': [], 'upload_banned': ['병행수입']}}
    _, _, skipped = PA.apply_rules(d, rules, market='coupang')
    hit = [s for s in skipped if s['code'] == 'UPLOAD_BANNED']
    assert hit and hit[0]['blocking']


def test_금지어_목록이_비면_적용_성공으로_치지_않는다():
    d = _Draft(name='나이키 에어포스', brand='나이키')
    _, applied, skipped = PA.apply_rules(d, {'banned_words': {'collect_banned': [],
                                                              'upload_banned': []}},
                                         collect_banned_words=[])
    assert not any(a['item'] == 'banned_words' for a in applied)
    note = [s for s in skipped if s['code'] == 'EMPTY_BANNED_LIST']
    assert note and not note[0]['blocking']
    assert '금지어' in note[0]['reason']


def test_읽을_수_없는_금지어_항목은_막는다():
    d = _Draft(name='나이키 에어포스', brand='나이키')
    _, _, skipped = PA.apply_rules(d, {'banned_words': {'collect_banned': [],
                                                        'upload_banned': []}},
                                   collect_banned_words=[{'x': 1}])
    assert 'BAD_BANNED_ENTRY' in _codes(skipped)
    assert _blocking(skipped)


# ── 태그 ────────────────────────────────────────────────────────────────────

def test_고정_태그와_자동_태그를_합치고_개수를_지킨다():
    d = _Draft(name='에어포스 1', brand='나이키', source_category_path='신발>스니커즈',
               options_json=json.dumps([{'color': '화이트', 'size': '270'}]))
    view, applied, _ = PA.apply_rules(d, {'tags': {'auto_generate': True, 'max_count': 3,
                                                   'fixed_tags': ['신상']}})
    assert view.process_tags[0] == '신상'
    assert len(view.process_tags) == 3
    assert '나이키' in view.process_tags
    assert any(a['item'] == 'tags' for a in applied)


def test_태그는_아직_어느_마켓에도_전달되지_않는다는_사실을_남긴다():
    d = _Draft(brand='나이키')
    _, _, skipped = PA.apply_rules(d, {'tags': {'auto_generate': True, 'max_count': 10,
                                                'fixed_tags': []}})
    note = [s for s in skipped if s['code'] == 'TAGS_NOT_DELIVERED']
    assert note and not note[0]['blocking']


def test_태그에서_금지어를_뺀다():
    d = _Draft(brand='나이키', source_category_path='신발>이월상품')
    view, _, _ = PA.apply_rules(d, {'tags': {'auto_generate': True, 'max_count': 10,
                                             'fixed_tags': ['이월상품특가']},
                                    'banned_words': {'collect_banned': [],
                                                     'upload_banned': ['이월상품']}})
    assert all('이월상품' not in t for t in view.process_tags)


def test_만들_태그가_없으면_사유를_남긴다():
    d = _Draft(brand='', source_category_path=None)
    _, _, skipped = PA.apply_rules(d, {'tags': {'auto_generate': True, 'max_count': 10,
                                                'fixed_tags': []}})
    assert 'NO_TAGS' in _codes(skipped)


# ── 브랜드 미확정 판정기 (함정 #4) ──────────────────────────────────────────

def test_브랜드가_비고_그_소싱처에_정책이_있으면_보류():
    assert PA.needs_brand_for_rules('', ['나이키', '아디다스'])
    assert '브랜드' in PA.needs_brand_for_rules('', ['나이키'])


def test_브랜드가_있으면_보류하지_않는다():
    assert PA.needs_brand_for_rules('나이키', ['나이키']) is None


def test_그_소싱처에_정책이_아예_없으면_보류하지_않는다():
    """정책이 없는 것은 「미배정」이지 「브랜드 미확정」이 아니다."""
    assert PA.needs_brand_for_rules('', []) is None


# ══ [2026-07-23 리뷰] 회귀 고정 ═══════════════════════════════════════════════

# ── C1 금지어 부분일치 (오늘 저장소가 카테고리 제안에서 고친 그 버그의 재발) ──

def test_짧은_영단어_금지어가_다른_단어에_안_걸린다():
    """수집 금지어 'Men' 이 'Mentoring Jacket' 을 막으면 **초안이 통째로 사라진다.**
    'SET'·'BAG'·'SALE' 을 넣는 순간 카탈로그가 없어지는 사고였다."""
    d = _Draft(name='Mentoring Jacket', brand='')
    _, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['origin_name']}},
                                   collect_banned_words=['Men'])
    assert 'COLLECT_BANNED' not in _codes(skipped), skipped


def test_말_단위로_걸리는_것은_그대로_걸린다():
    for name in ("Men's Shoes", 'MENS Jacket', 'men jacket'):
        d = _Draft(name=name, brand='')
        _, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['origin_name']}},
                                       collect_banned_words=['Men'])
        assert 'COLLECT_BANNED' in _codes(skipped), name


def test_한글_금지어는_합성어_안에서도_걸린다():
    """한글은 붙여 쓴다 — '이월상품' 이 '이월상품특가' 안에 있으면 같은 말이다."""
    d = _Draft(name='이월상품특가 패딩', brand='')
    _, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['origin_name']}},
                                   collect_banned_words=['이월상품'])
    assert 'COLLECT_BANNED' in _codes(skipped)


def test_두_글자_한글_금지어는_경계를_요구한다():
    """'반지' 가 '반지갑' 을 막으면 안 된다(짧을수록 우연히 낀다)."""
    d = _Draft(name='가죽 반지갑', brand='')
    _, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['origin_name']}},
                                   collect_banned_words=['반지'])
    assert 'COLLECT_BANNED' not in _codes(skipped)


def test_금지어_판정기는_카테고리_제안과_같은_것이다():
    """규칙을 두 벌 두면 한쪽만 고쳐져 갈린다 — 같은 함수를 쓰는지 못 박는다."""
    from lemouton.registration import word_match
    from lemouton.registration import category_suggest as CS
    assert CS._contains_word is word_match.contains_word


# ── C2 브랜드 표기를 고르지 않으면 강제하지 않는다 ──────────────────────────

def test_브랜드_규칙을_저장하지_않으면_영문_브랜드도_안_막힌다():
    """예전엔 기본값 'korean' 을 지어내 brand='NIKE' 상품이 6마켓 전부 막혔다."""
    d = _Draft(name='Air Force 1', brand='NIKE')
    view, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name']}})
    assert view.name == 'NIKE Air Force 1'
    assert not _blocking(skipped), skipped


def test_표기_지정_안_함을_저장해도_안_막힌다():
    d = _Draft(name='Air Force 1', brand='NIKE')
    view, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name']},
                                          'brand': {'mode': 'as_is', 'position': 'front'}})
    assert view.name == 'NIKE Air Force 1'
    assert not _blocking(skipped)


def test_스키마_기본값이_지정_안_함이다():
    from lemouton.registration.process_rule_schema import default_config
    assert default_config('brand')['mode'] == 'as_is'
    # 품번 칸이 없으니 기본 조립 순서에서도 뺐다(상시 경고 방지 — 리뷰 S2)
    assert 'model_no' not in default_config('name')['token_order']


def test_국문을_직접_고르면_그때는_막는다():
    """사장님이 실제로 고른 것은 존중한다 — 지어낸 기본값만 없앤 것이다."""
    d = _Draft(name='Air Force 1', brand='NIKE')
    _, _, skipped = PA.apply_rules(d, {'name': {'token_order': ['brand', 'origin_name']},
                                       'brand': {'mode': 'korean', 'position': 'front'}})
    assert 'BRAND_MODE_UNMET' in _codes(skipped)


# ── I1 치환으로 지운 금지어는 통과한다 ──────────────────────────────────────

def test_치환으로_지운_업로드_금지어는_통과한다():
    """「금지어를 치환으로 처리한다」가 정상 운영이다 — 원본까지 보면 원천 봉쇄된다."""
    d = _Draft(name='병행수입 숏 패딩', brand='')
    view, _, skipped = PA.apply_rules(
        d, {'name': {'token_order': ['origin_name'],
                     'replacements': [{'from': '병행수입', 'to': ''}]},
            'banned_words': {'collect_banned': [], 'upload_banned': ['병행수입']}},
        market='coupang')
    assert view.name == '숏 패딩'
    assert 'UPLOAD_BANNED' not in _codes(skipped), skipped


def test_수집_금지어는_원본_기준이라_치환으로_못_피한다():
    """「아예 안 가져옵니다」니까 소싱처가 준 이름이 기준이다."""
    d = _Draft(name='이월상품 숏 패딩', brand='')
    _, _, skipped = PA.apply_rules(
        d, {'name': {'token_order': ['origin_name'],
                     'replacements': [{'from': '이월상품', 'to': ''}]}},
        collect_banned_words=['이월상품'])
    assert 'COLLECT_BANNED' in _codes(skipped)


# ── I2 치환은 전부 되거나 전부 안 되거나 ────────────────────────────────────

def test_치환_한_줄을_못_읽으면_한_줄도_적용하지_않는다():
    d = _Draft(name='숏 재킷 패딩', brand='')
    view, applied, skipped = PA.apply_rules(d, {'name': {
        'token_order': ['origin_name'],
        'replacements': [['재킷', '자켓'], 12345, ['패딩', '점퍼']]}})
    assert view.name == '숏 재킷 패딩', '반쯤 가공된 이름이 만들어졌습니다'
    assert not any(a['field'] == 'replacements' for a in applied)
    assert 'BAD_REPLACEMENT' in _codes(skipped)
    assert _blocking(skipped)


# ── I6 치환으로 말이 빠지면 공백을 정리한다 ─────────────────────────────────

def test_치환_뒤_겹친_공백을_정리한다():
    d = _Draft(name='나이키 재킷 패딩', brand='')
    view, _, _ = PA.apply_rules(d, {'name': {
        'token_order': ['origin_name'],
        'dedupe_words': False,
        'replacements': [{'from': '재킷', 'to': ''}]}})
    assert view.name == '나이키 패딩', repr(view.name)


# ── S3 / S5 사본 방어 ───────────────────────────────────────────────────────

def test_태그는_밖에서_고칠_수_없다():
    d = _Draft(brand='나이키')
    view, _, _ = PA.apply_rules(d, {'tags': {'auto_generate': True, 'max_count': 5,
                                             'fixed_tags': []}})
    with pytest.raises((AttributeError, TypeError)):
        view.process_tags.append('몰래추가')


def test_이미_가공된_사본을_다시_넣으면_거부한다():
    """두 번 적용하면 브랜드가 두 번 붙는다 — 조용히 하지 않고 터뜨린다."""
    d = _Draft(name='에어포스 1', brand='나이키')
    rules = {'name': {'token_order': ['brand', 'origin_name'], 'dedupe_words': False}}
    view, _, _ = PA.apply_rules(d, rules)
    with pytest.raises(TypeError):
        PA.apply_rules(view, rules)
