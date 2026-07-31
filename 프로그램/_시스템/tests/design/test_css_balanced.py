# -*- coding: utf-8 -*-
"""CSS 괄호 짝 검사 — 안 맞으면 그 뒤 스타일이 통째로 죽는다.

2026-08-01 실제 사고
    색을 토큰으로 바꾸는 치환이 `}` 를 넘어가 다음 규칙까지 삼켰다.
        .mj-ar{color: var(--글자-희미, var(--faint,#9ca3af)}
        .mj-brand{border:1px solid var(--faint,#d1d6db));
    브라우저는 이런 자리를 만나면 **그 뒤 스타일을 전부 버린다.**
    마진계산기 <style> 은 50,506자인데 규칙이 112개만 살아남았고,
    브랜드 정리 팝업(.bfix-*) 규칙이 0개가 되어 날것으로 쏟아졌다.

    그때 테스트 472개가 **전부 통과했다.** 글자만 비교했지 「CSS 로서 말이 되는지」는
    아무도 안 봤기 때문이다. 그래서 이 검사를 만든다.
"""
import io
import os
import sys

import pytest

_시스템 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
sys.path.insert(0, os.path.join(_시스템, 'scripts'))

from check_css_balanced import 문제찾기, _STYLE_BLOCK, _대상  # noqa: E402


def _조각들(경로):
    글 = io.open(경로, encoding='utf-8', errors='replace').read()
    if 경로.endswith('.css'):
        return [글]
    return [m.group(2) for m in _STYLE_BLOCK.finditer(글)]


def test_모든_스타일의_괄호_짝이_맞는다():
    나쁜곳 = []
    for p in _대상():
        for 조각 in _조각들(p):
            for _위치, 설명 in 문제찾기(조각):
                나쁜곳.append((os.path.relpath(p, _시스템).replace(os.sep, '/'), 설명[:110]))
    assert not 나쁜곳, (
        'CSS 괄호 짝이 안 맞는 자리 %d곳 — 그 뒤 스타일이 통째로 죽는다:\n%s'
        % (len(나쁜곳), '\n'.join('  %s — %s' % x for x in 나쁜곳[:10]))
    )


@pytest.mark.parametrize('원본, 기대', [
    # 세미콜론 없이 `}` 로 끝나는 선언 — 여기서 다음 규칙을 삼키면 안 된다
    ('.a{color:var(--faint,#9ca3af)}\n.b{border:1px solid var(--faint,#d1d6db);}',
     '.a{color:var(--faint,#9ca3af)}'),
])
def test_치환기가_규칙_경계를_안_넘는다(원본, 기대):
    """흐린 글자 치환기가 `}` 를 넘어가지 않는지 — 사고 재현 그대로."""
    from split_faint_text import _바꾸기
    새, _n = _바꾸기(원본)
    assert 기대 in 새, '규칙 경계를 넘어 다음 규칙까지 삼켰다:\n%s' % 새
    assert not 문제찾기(새), '치환 결과의 괄호 짝이 안 맞는다:\n%s' % 새


def test_의미색_치환기도_규칙_경계를_안_넘는다():
    from split_semantic_text import _바꾸기
    원본 = '.a{color:var(--green,#16A34A)}\n.b{border:1px solid var(--green,#0F6E56);}'
    새, _n = _바꾸기(원본)
    assert '.a{color:var(--green,#16A34A)}' in 새
    assert not 문제찾기(새)
