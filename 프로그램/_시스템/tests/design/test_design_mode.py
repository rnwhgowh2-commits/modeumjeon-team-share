# -*- coding: utf-8 -*-
"""디자인 모드 단일 원천 — 안전망(current)이 새 CSS 를 전혀 부르지 않는지가 핵심."""
import pytest

from webapp.design_mode import MODES, DEFAULT_MODE, normalize, body_class


def test_모드는_넷이다():
    assert list(MODES.keys()) == ['current', 'mono', 'layer', 'light']


def test_기본값은_현재디자인():
    assert DEFAULT_MODE == 'current'


def test_현재모드는_클래스를_붙이지_않는다():
    # 안전망의 핵심 — current 면 ds 가 한 글자도 안 붙어야 한다
    assert body_class('current') == ''


def test_검정한판은_ds_와_다크를_붙인다():
    assert body_class('mono') == 'ds ds-dark ds-mono'


def test_검정3단도_다크다():
    assert body_class('layer') == 'ds ds-dark ds-layer'


def test_밝은카드는_다크가_아니다():
    assert body_class('light') == 'ds ds-light'


@pytest.mark.parametrize('bad', ['', None, 'stripe', 'toss', '  ', 'MONO', '../etc'])
def test_모르는_값은_현재디자인으로_떨어진다(bad):
    assert normalize(bad) == 'current'


def test_아는_값은_그대로():
    assert normalize('layer') == 'layer'
