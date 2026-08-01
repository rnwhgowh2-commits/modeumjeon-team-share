# -*- coding: utf-8 -*-
"""합친 옵션명 — 「메이트 블랙 265」.

노션 — 「2/3축 쪼개져도 **하나의 옵션번호**임(메이트(모델명) 블랙(색상) 265(사이즈))」.
설계서 확정 — **매트릭스 옵션명 + 축 값들을 축 순서대로 공백으로 이어 붙임.**

축 값을 읽는 건 기존 `option_combo.option_axis_values` 를 그대로 쓴다 —
새로 만들면 2축/3축 폴백 규칙이 갈린다.
"""
from lemouton.matrix.option_name import full_name


class _O:
    def __init__(self, color=None, size=None, axis_values_json=None):
        self.color_code = color
        self.size_code = size
        self.axis_values_json = axis_values_json


def test_2축이면_묶음이름_색상_사이즈():
    assert full_name('메이트', _O('블랙', '265')) == '메이트 블랙 265'


def test_3축이면_값이_하나_더_붙는다():
    import json
    o = _O(axis_values_json=json.dumps(['메이트', '블랙', '265']))
    assert full_name('르무통 신발', o) == '르무통 신발 메이트 블랙 265'


def test_묶음_이름이_비면_축_값만():
    assert full_name('', _O('블랙', '265')) == '블랙 265'
    assert full_name(None, _O('블랙', '265')) == '블랙 265'


def test_축_값이_없으면_묶음_이름만():
    assert full_name('메이트', _O()) == '메이트'


def test_둘_다_없으면_빈_문자열():
    """지어내지 않는다 — 없는 이름을 만들어내면 화면에 가짜가 뜬다."""
    assert full_name(None, _O()) == ''


def test_앞뒤_공백은_정리한다():
    assert full_name('  메이트  ', _O(' 블랙 ', '265')) == '메이트 블랙 265'
