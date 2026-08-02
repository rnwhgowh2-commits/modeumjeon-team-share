# -*- coding: utf-8 -*-
"""어두운 모드에서 글자가 배경에 묻히는 사고를 다시 못 내게 막는다.

무슨 사고였나 — 주문 화면 CSS 안에 `.o7 { --ink:#191F28 }` 처럼 **밝은 모드 색이
못 박혀** 있었다. 위(.ds.ds-light)에서 색을 뒤집어도 그 화면 안쪽은 못 박힌 값을 쓰니
검정 배경에 검정 글자가 된다. 라이브 실측 507곳, 최악 대비 1.11 — 사실상 안 보였다.

여기서 지키는 것
  1) 화면이 공용 색 이름을 못 박았으면, 어두운 모드용 되돌림 규칙이 **반드시** 있어야 한다.
  2) 그 규칙 파일은 생성물이라 최신이어야 한다(새 화면이 못 박으면 바로 빨간불).
  3) 되돌림 규칙은 어두운 모드에만 걸려야 한다 — 「현재」(안전망)를 건드리면 안 된다.
"""
import io
import os
import re

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SYS = os.path.dirname(os.path.dirname(_HERE))
_FIX = os.path.join(_SYS, 'webapp', 'static', 'scope_fix.css')


def _gen():
    import importlib.util
    p = os.path.join(_SYS, 'scripts', 'gen_scope_fix.py')
    spec = importlib.util.spec_from_file_location('gen_scope_fix', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_되돌림_파일이_최신이다():
    """새 화면이 공용 색 이름을 못 박았는데 되돌림을 안 만들면 여기서 걸린다."""
    g = _gen()
    기대 = g.build()
    실제 = io.open(_FIX, encoding='utf-8').read()
    assert 실제 == 기대, (
        'scope_fix.css 가 최신이 아니다. '
        '화면 CSS 가 공용 색 이름(--ink·--bg·--line …)을 새로 못 박았을 가능성이 크다 → '
        'python scripts/gen_scope_fix.py 를 다시 돌려라.')


def test_못박은_선택자마다_되돌림이_있다():
    g = _gen()
    tokens = g._strip_comments(io.open(g.TOKENS, encoding='utf-8').read())
    덮어쓴 = g.덮어쓴_곳(g.색이름들(tokens))
    css = io.open(_FIX, encoding='utf-8').read()
    빠짐 = [sel for sel in 덮어쓴 if ('.ds.ds-light %s ' % sel) not in css]
    assert not 빠짐, '되돌림 규칙이 없는 화면: %s' % 빠짐


def test_되돌림은_어두운_모드에만_걸린다():
    """「현재」·「밝은 카드」에 새어 나가면 안 된다 — 안전망이 흔들린다."""
    css = io.open(_FIX, encoding='utf-8').read()
    css = re.sub(r'/\*.*?\*/', ' ', css, flags=re.S)
    규칙 = re.findall(r'([^{}]+)\{', css)
    허용 = ('.ds.ds-light ', '.ds.ds-light.ds-layer ', '.ds.ds-light ')
    새는것 = [s.strip() for s in 규칙 if not s.strip().startswith(허용)]
    assert not 새는것, '「현재」(안전망)까지 새는 규칙: %s' % 새는것


def test_주문화면_되돌림에_글자색이_들어있다():
    """주문 화면이 자기 안에서 못 박은 --ink 를 화이트 타입 값으로 되돌리는지."""
    css = io.open(_FIX, encoding='utf-8').read()
    m = re.search(r'\.ds\.ds-light \.o7 \{([^}]*)\}', css)
    assert m, '.o7 되돌림 규칙이 없다'
    assert '--ink:' in m.group(1)


def test_화면에_실제로_실린다(client):
    html = client.get('/').get_data(as_text=True)
    assert 'scope_fix.css' in html, 'base.html 이 되돌림 CSS 를 안 부른다'


def test_밝은카드도_화면이_못박은_보조글자색을_되돌린다():
    """흰 바탕에서 화면이 못 박은 --sub(#8B95A1)은 3.04 로 기준 미달이었다.
    어두운 쪽만 고치면 밝은 쪽은 그대로 안 읽힌다."""
    css = io.open(_FIX, encoding='utf-8').read()
    m = re.search(r'\.ds\.ds-light \.o7 \{([^}]*)\}', css)
    assert m, '.ds.ds-light .o7 되돌림이 없다'
    assert '--sub: #6E6E73' in m.group(1)
    assert '#8B95A1' not in m.group(1)


def test_흐린글자는_글자용_이름으로_갈라져_있다():
    """--faint 한 이름이 글자(204)와 테두리(37)를 겸하고 있어 어둡게도 밝게도 못 했다."""
    import importlib.util
    p = os.path.join(_SYS, 'scripts', 'split_faint_text.py')
    spec = importlib.util.spec_from_file_location('split_faint_text', p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    남은 = []
    for f in m.대상파일():
        t = io.open(f, encoding='utf-8').read()
        _새, n = m._바꾸기(t)
        if n:
            남은.append((os.path.relpath(f, m.WEBAPP), n))
    assert not 남은, '글자용 이름으로 안 바꾼 자리: %s' % 남은[:5]


def test_생성물이_토큰의_최신값을_쓴다():
    """실제로 났던 사고 — 생성물이 색 이름 블록의 **첫 번째만** 읽어서,
    나중에 올린 값을 옛 값으로 도로 덮었다. 값을 박아 두지 않고 **원천과 맞대** 본다.

    [2026-08-02] 어두운 타입을 지우면서 기준을 화이트로 옮겼다. 지킬 성질은 그대로다 —
    「생성물의 값 = tokens.css 에서 **마지막에 정한** 값」.
    """
    import re as _re
    tokens = io.open(os.path.join(_SYS, 'webapp', 'static', 'tokens.css'),
                     encoding='utf-8').read()
    g = _gen()
    최신 = dict(g._token_block(g._strip_comments(tokens), '.ds'))
    최신.update(g._token_block(g._strip_comments(tokens), '.ds.ds-light'))
    css = _re.sub(r'/\*.*?\*/', ' ', io.open(_FIX, encoding='utf-8').read(), flags=_re.S)
    for 이름, 값 in 최신.items():
        for m in _re.finditer(_re.escape(이름) + r'\s*:\s*([^;]+);', css):
            assert m.group(1).strip() == 값, (
                '생성물이 %s 를 옛 값으로 박아 넣었다: %s (최신 %s)'
                % (이름, m.group(1).strip(), 값))
