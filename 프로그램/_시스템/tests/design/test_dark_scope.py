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


def test_검정3단_전용값도_같이_나온다():
    """검정 3단은 바탕이 한 단 밝아 같은 색이 문턱 아래로 떨어진다.
    화면 안쪽(.o7)까지 3단 값을 내보내지 않으면 `.ds.ds-dark .o7` 이 이겨 안 먹는다."""
    css = io.open(_FIX, encoding='utf-8').read()
    assert '.ds.ds-dark.ds-layer .o7 {' in css
    m = re.search(r'\.ds\.ds-dark\.ds-layer \.o7 \{([^}]*)\}', css)
    assert '--sub: #98989D' in m.group(1) and '--red: #FF6961' in m.group(1)


def test_되돌림은_어두운_모드에만_걸린다():
    """「현재」·「밝은 카드」에 새어 나가면 안 된다 — 안전망이 흔들린다."""
    css = io.open(_FIX, encoding='utf-8').read()
    css = re.sub(r'/\*.*?\*/', ' ', css, flags=re.S)
    규칙 = re.findall(r'([^{}]+)\{', css)
    허용 = ('.ds.ds-dark ', '.ds.ds-dark.ds-layer ', '.ds.ds-light ')
    새는것 = [s.strip() for s in 규칙 if not s.strip().startswith(허용)]
    assert not 새는것, '「현재」(안전망)까지 새는 규칙: %s' % 새는것


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


# ── 배지 짝 맞추기 (바탕·글자 중 한쪽만 테마를 따라가 어긋났던 곳) ──────────
_BADGE = os.path.join(_SYS, 'webapp', 'static', 'dark_badge_fix.css')


def test_배지_되돌림도_어두운_모드에만_걸린다():
    css = re.sub(r'/\*.*?\*/', ' ', io.open(_BADGE, encoding='utf-8').read(), flags=re.S)
    새는것 = [s.strip() for s in re.findall(r'([^{}]+)\{', css) if not s.strip().startswith('.ds.ds-dark ')]
    assert not 새는것, '어두운 모드 밖으로 새는 배지 규칙: %s' % 새는것


def test_배지_규칙은_토큰을_쓴다():
    """여기서 색을 새로 만들면 tokens.css 가 더 이상 단일 원천이 아니게 된다."""
    css = re.sub(r'/\*.*?\*/', ' ', io.open(_BADGE, encoding='utf-8').read(), flags=re.S)
    본문 = ' '.join(re.findall(r'\{([^{}]*)\}', css))
    굳은색 = re.findall(r'(?<!var\()(?<!,\s)#[0-9A-Fa-f]{6}(?!\s*\))', 본문)
    assert not [c for c in 굳은색], '토큰 없이 굳힌 색: %s' % 굳은색


def test_새_토큰이_밝고_어두운_모드_둘_다_있다():
    tok = io.open(os.path.join(_SYS, 'webapp', 'static', 'tokens.css'), encoding='utf-8').read()
    for 이름 in ('--연한-노랑', '--연한-보라', '--보라'):
        assert tok.count(이름 + ':') >= 2, '%s 가 한쪽 모드에만 있다' % 이름
    # `.ds.ds-dark` 블록이 여러 개다 — CSS 는 **뒤에 온 것**이 이기므로 마지막을 본다.
    값들 = re.findall(r'\.ds\.ds-dark\s*\{[^{}]*?--faint:\s*([^;]+);', tok, re.S)
    assert 값들, '어두운 모드에 --faint 정의가 없다'
    assert '#8E8E93' in 값들[-1], (
        '어두운 모드에서 실제로 이기는 --faint 가 %r 이다 — 밝게 올린 값이 아니다' % 값들[-1])


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


def test_배지_CSS_가_화면에_실린다(client):
    assert 'dark_badge_fix.css' in client.get('/').get_data(as_text=True)


def test_생성물이_토큰의_최신값을_쓴다():
    """실제로 났던 사고 — 생성물이 `.ds.ds-dark` **첫 블록**만 읽어서,
    나중에 올린 --faint(#8E8E93)를 옛 값(#6E6E73)으로 도로 덮었다."""
    css = io.open(_FIX, encoding='utf-8').read()
    옛값 = [l for l in css.splitlines() if '--faint: var(--ap-g45)' in l or '--faint: #6E6E73' in l]
    assert not 옛값, '생성물이 옛 --faint 값을 박아 넣었다: %s' % 옛값[:2]
    assert '--faint: #8E8E93' in css, '생성물에 최신 --faint 가 없다'


def test_흰글자판_보정은_기존타입에_안_샌다():
    """badge_bg_fix.css — 밝은 타입에도 걸려야 하지만 「기존 타입」엔 절대 안 걸린다.

    사장님 확정(2026-08-02): 기존 타입은 예전 화면 그대로 두는 안전망이다.
    그 타입에는 .ds 가 안 붙으므로, 모든 규칙이 `.ds` 로 시작하면 통째로 잠든다.
    """
    import re
    경로 = os.path.join(_SYS, 'webapp', 'static', 'badge_bg_fix.css')
    css = io.open(경로, encoding='utf-8').read()
    껍질 = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    새는것 = [s.strip() for s in re.findall(r'([^{}]+)\{', 껍질)
              if s.strip() and not s.strip().startswith('.ds')]
    assert not 새는것, '기존 타입까지 새는 규칙(안전망 훼손): %s' % 새는것
