# -*- coding: utf-8 -*-
"""어두운 모드에서 글자가 배경에 묻히는 사고를 다시 못 내게 막는다.

무슨 사고였나 — 주문 화면 CSS 안에 `.o7 { --ink:#191F28 }` 처럼 **밝은 모드 색이
못 박혀** 있었다. 위(.ds.ds-dark)에서 색을 뒤집어도 그 화면 안쪽은 못 박힌 값을 쓰니
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
_FIX = os.path.join(_SYS, 'webapp', 'static', 'dark_scope_fix.css')


def _gen():
    import importlib.util
    p = os.path.join(_SYS, 'scripts', 'gen_dark_scope_fix.py')
    spec = importlib.util.spec_from_file_location('gen_dark_scope_fix', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_되돌림_파일이_최신이다():
    """새 화면이 공용 색 이름을 못 박았는데 되돌림을 안 만들면 여기서 걸린다."""
    g = _gen()
    기대 = g.build()
    실제 = io.open(_FIX, encoding='utf-8').read()
    assert 실제 == 기대, (
        'dark_scope_fix.css 가 최신이 아니다. '
        '화면 CSS 가 공용 색 이름(--ink·--bg·--line …)을 새로 못 박았을 가능성이 크다 → '
        'python scripts/gen_dark_scope_fix.py 를 다시 돌려라.')


def test_못박은_선택자마다_되돌림이_있다():
    g = _gen()
    tokens = g._strip_comments(io.open(g.TOKENS, encoding='utf-8').read())
    덮어쓴 = g.덮어쓴_곳(g.색이름들(tokens))
    css = io.open(_FIX, encoding='utf-8').read()
    빠짐 = [sel for sel in 덮어쓴 if ('.ds.ds-dark %s ' % sel) not in css]
    assert not 빠짐, '되돌림 규칙이 없는 화면: %s' % 빠짐


def test_되돌림은_어두운_모드에만_걸린다():
    """「현재」·「밝은 카드」에 새어 나가면 안 된다 — 안전망이 흔들린다."""
    css = io.open(_FIX, encoding='utf-8').read()
    css = re.sub(r'/\*.*?\*/', ' ', css, flags=re.S)
    규칙 = re.findall(r'([^{}]+)\{', css)
    새는것 = [s.strip() for s in 규칙 if not s.strip().startswith('.ds.ds-dark ')]
    assert not 새는것, '어두운 모드 밖으로 새는 규칙: %s' % 새는것


def test_주문화면_되돌림에_글자색이_들어있다():
    """실제로 안 보였던 그 값 — .o7 의 --ink 가 밝은 글자색으로 뒤집혀야 한다."""
    css = io.open(_FIX, encoding='utf-8').read()
    m = re.search(r'\.ds\.ds-dark \.o7 \{([^}]*)\}', css)
    assert m, '.o7 되돌림 규칙이 없다'
    assert '--ink:' in m.group(1)
    assert '#191F28' not in m.group(1), '되돌림인데 다시 밝은 모드 글자색을 넣었다'


def test_화면에_실제로_실린다(client):
    html = client.get('/').get_data(as_text=True)
    assert 'dark_scope_fix.css' in html, 'base.html 이 되돌림 CSS 를 안 부른다'


@pytest.mark.parametrize('모드', ['mono', 'layer'])
def test_어두운_모드_주문화면이_되돌림을_싣는다(client_with_auth, 모드):
    from tests.design.test_topnav import _사용자_만들기
    _사용자_만들기(email='darkscope-%s@test.local' % 모드)
    client_with_auth.post('/auth/design-mode', data={'mode': 모드, 'next': '/'})
    r = client_with_auth.get('/orders/?tab=list')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'dark_scope_fix.css' in html
