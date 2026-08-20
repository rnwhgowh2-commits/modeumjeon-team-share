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


def test_짝_없는_주석_닫힘을_잡는다():
    """2026-08-02 실제 사고 — 설명글을 고치다 `*/` 를 하나 더 남겼다.

    중괄호 짝은 멀쩡해서 검사 245개가 **전부 통과**했다. 그런데 화면에서는
    설명글이 CSS 선택자로 새어 나가 바로 뒤 규칙(배지 글자색)을 통째로 삼켰고,
    고쳤다고 믿은 자리가 그대로 안 읽혔다(라이브 대비 실측으로 겨우 발견).
    """
    깨진 = '/* 설명 끝 */\n   ★ 남은 설명 */\n.ds .a { color: red; }'
    assert 문제찾기(깨진), '짝 없는 `*/` 를 못 잡으면 그 뒤 규칙이 조용히 죽는다'
    assert not 문제찾기('/* 설명 끝 */\n.ds .a { color: red; }')


def test_안_닫힌_주석을_잡는다():
    assert 문제찾기('/* 안 닫은 설명\n.a{color:red}')


def test_주석_안의_괄호는_글자로_본다():
    """설명글에 `{` 나 `var(` 를 적었다고 짝이 안 맞는다고 하면 안 된다."""
    assert not 문제찾기('/* 예: .a{color:var(--x} 처럼 쓰면 안 된다 */\n.a{color:red}')


def _경계검사(_바꾸기, 원본, 뒷규칙, 원래값):
    """사고 재현 — 세미콜론 없이 `}` 로 끝나는 선언 다음에 규칙이 이어질 때.

    지켜야 할 성질은 「안 바꾼다」가 아니라 **「규칙 경계를 안 넘는다」** 이다.
    (2026-08-01 2차: `}` 로 끝나는 선언도 바꾸도록 넓혔다 — 그때까지 708곳을
     통째로 놓치고 있었다. 다만 다음 규칙을 삼키면 안 된다는 성질은 그대로다.)
    """
    새, _n = _바꾸기(원본)
    assert 뒷규칙 in 새, '뒤따르는 규칙이 삼켜졌다:\n%s' % 새
    assert 원래값 in 새, '원래 색이 예비값으로 안 남았다 — 기존 타입에서 색이 사라진다:\n%s' % 새
    assert not 문제찾기(새), '치환 결과의 괄호 짝이 안 맞는다:\n%s' % 새
    assert 새.count('{') == 원본.count('{') and 새.count('}') == 원본.count('}')


def test_흐린글자_치환기가_규칙_경계를_안_넘는다():
    from split_faint_text import _바꾸기
    _경계검사(_바꾸기,
              '.a{color:var(--faint,#9ca3af)}\n.b{border:1px solid var(--faint,#d1d6db);}',
              '.b{border:1px solid var(--faint,#d1d6db);}',
              '#9ca3af')


def test_의미색_치환기도_규칙_경계를_안_넘는다():
    from split_semantic_text import _바꾸기
    _경계검사(_바꾸기,
              '.a{color:var(--green,#16A34A)}\n.b{border:1px solid var(--green,#0F6E56);}',
              '.b{border:1px solid var(--green,#0F6E56);}',
              '#16A34A')


def test_배경치환기도_규칙_경계를_안_넘는다():
    from split_bg_from_text_token import _바꾸기
    원본 = '.a{background:var(--ink,#191F28)}\n.b{color:var(--ink,#191F28);}'
    새, _n = _바꾸기(원본)
    assert '.b{color:var(--ink,#191F28);}' in 새
    assert '#191F28' in 새
    assert not 문제찾기(새)
