# -*- coding: utf-8 -*-
"""옵션 축으로 **모델**을 고를 수 있다 (2026-08-13 사장님 확정).

왜 필요한가
  마켓별 옵션 축 설정(`BundleGroup.option_config_json`)은 이미 있었고 1~3축을 받는다.
  그런데 고를 수 있는 값이 `color_code · size_code · model_code` 셋뿐이었다:
    · color_code / size_code — 색상·사이즈
    · model_code            — **묶음 코드(U…)** 라 옵션마다 **똑같다**
  그래서 축을 3개로 늘려도 셋째 칸에 넣을 값이 없었다.
  「메이트 / 스위트」는 `Option.axis_values_json` 에 멀쩡히 있는데 가리킬 이름이 없던 것.

  → `model_name` 을 고를 수 있게 한다. 값은 **모델 축의 값**이다.

⚠️ 마켓이 3축을 받는지는 **아직 확인불가**(스스 문서에 optionName3 근거 없음 ·
   쿠팡은 카테고리 메타로 오픈 속성 확인 필요). 그래서 **만드는 것까지만** 연다 —
   실제 전송의 3축 보류 막이는 `tests/test_formatter_axis_collision.py` 가 지킨다.
"""
import pytest

from lemouton.formatter.option_axes import (
    VALID_SOURCES, build_coupang_items, build_smartstore_option_combinations,
    build_smartstore_option_types,
)

#: 3축 모델모음전 옵션 — 모델만 다르고 색·사이즈는 같다(예전엔 이 둘이 겹쳤다)
ROWS = [
    {'canonical_sku': 'SKU-1', 'color_code': '블랙', 'size_code': '250',
     'model_code': 'U20260813-000001', 'model_name': '메이트'},
    {'canonical_sku': 'SKU-2', 'color_code': '블랙', 'size_code': '250',
     'model_code': 'U20260813-000001', 'model_name': '스위트'},
]
AXES3 = [{'name': '모델', 'source': 'model_name'},
         {'name': '색상', 'source': 'color_code'},
         {'name': '사이즈', 'source': 'size_code'}]


def test_모델을_축으로_고를_수_있다():
    assert 'model_name' in VALID_SOURCES


def test_모델_축을_쓰면_두_옵션이_안_겹친다():
    """🔴 예전엔 `model_code`(묶음 코드)뿐이라 두 줄이 같은 조합으로 접혔다."""
    out = build_smartstore_option_combinations(ROWS, AXES3)
    assert len(out) == 2, f'모델이 다른데 한 줄로 접혔다: {out}'
    assert {o['optionName1'] for o in out} == {'메이트', '스위트'}
    assert {o['optionName2'] for o in out} == {'블랙'}
    assert {o['optionName3'] for o in out} == {'250'}


def test_묶음코드로_고르면_예전처럼_한_줄로_접힌다():
    """`model_code` 는 옵션마다 같은 값이라 축으로 쓸 수 없다 — 그 사실을 못 박는다."""
    axes = [{'name': '모델', 'source': 'model_code'},
            {'name': '색상', 'source': 'color_code'},
            {'name': '사이즈', 'source': 'size_code'}]
    assert len(build_smartstore_option_combinations(ROWS, axes)) == 1


def test_축_이름은_사장님이_적은_그대로_나간다():
    types = build_smartstore_option_types(AXES3)
    assert [t['groupName'] for t in types] == ['모델', '색상', '사이즈']


def test_쿠팡도_모델을_속성으로_보낸다():
    items = build_coupang_items(ROWS, AXES3)
    assert len(items) == 2, items
    names = {a['attributeTypeName'] for it in items for a in it['attributes']}
    assert '모델' in names
    vals = {a['attributeValueName'] for it in items
            for a in it['attributes'] if a['attributeTypeName'] == '모델'}
    assert vals == {'메이트', '스위트'}


def test_모르는_이름은_그대로_거절한다():
    """오타를 조용히 받아 「?」로 채우면 마켓에 빈 옵션이 올라간다."""
    with pytest.raises(ValueError):
        build_smartstore_option_combinations(
            ROWS, [{'name': '모델', 'source': 'model_nane'}])


def test_모델_축이_없는_옵션은_물음표가_아니라_비어_보인다():
    """색상모음전 옵션에 모델 축을 걸면 값이 없다 — 조용히 「?」로 채우지 않는다."""
    rows = [{'canonical_sku': 'S', 'color_code': '블랙', 'size_code': '250',
             'model_code': 'U1'}]
    out = build_smartstore_option_combinations(rows, AXES3)
    assert out[0]['optionName1'] in ('', '?'), out[0]
