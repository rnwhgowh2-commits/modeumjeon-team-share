# -*- coding: utf-8 -*-
"""check_design_tokens 안전 규칙 고정 테스트 (T13 Job 1).

배경: design_sweep 이 만드는 치환 결과는 항상 `var(--토큰,#원래색)` 형태의
예비값을 동반한다(현재 모드 안전망). check_design_tokens 의 색 검사가
문자열 어디든 `#hex` 이면 무조건 위반으로 셌었는데, 그러면 var() 안의
예비값까지 위반으로 잡혀 "더 나빠지지 않게" 막는 기준선 숫자 자체가
스윕을 하면 할수록 커지는 역설이 생긴다(예비값이 늘수록 위반도 늘어 보임).

이 테스트는 var(...) 안의 hex 는 위반으로 세지 않되, var() 밖의 진짜
하드코딩 hex 는 여전히 잡히는지를 고정한다.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / 'scripts' / 'check_design_tokens.py'
)
_spec = importlib.util.spec_from_file_location('check_design_tokens', _SCRIPT_PATH)
cdt = importlib.util.module_from_spec(_spec)
sys.modules.setdefault('check_design_tokens', cdt)
_spec.loader.exec_module(cdt)  # type: ignore[union-attr]


def test_var_예비값_안의_hex는_위반이_아니다():
    본문 = '<div style="color:var(--ink,#191F28)">x</div>'
    나온것 = cdt.검사('x.html', 본문)
    종류들 = [종 for 종, _v, _ln in 나온것]
    assert '색' not in 종류들


def test_var_밖의_하드코딩_hex는_여전히_위반이다():
    본문 = '<div style="color:#191F28">x</div>'
    나온것 = cdt.검사('x.html', 본문)
    종류들 = [종 for 종, _v, _ln in 나온것]
    assert '색' in 종류들


def test_var_예비값_옆에_진짜_하드코딩도_있으면_그것만_잡힌다():
    본문 = (
        '<div style="color:var(--ink,#191F28);background:#123ABC">x</div>'
    )
    나온것 = cdt.검사('x.html', 본문)
    색값들 = [값 for 종, 값, _ln in 나온것 if 종 == '색']
    assert 색값들 == ['#123abc']


def test_var_규칙안에_있는_색이어도_예비값이면_위반아니다():
    # 규칙에 있는 색(COLORS)이든 없든, var() 안이면 애초에 검사 대상이 아니다.
    본문 = '<div style="color:var(--x,#0071e3)">x</div>'
    나온것 = cdt.검사('x.html', 본문)
    assert 나온것 == []


def test_중첩_var_폴백_안의_hex도_위반이_아니다():
    # design_sweep 의 실측 사례: --sub2:var(--n500,var(--sub,#8b95a1));
    본문 = '<style>.x{--sub2:var(--n500,var(--sub,#8b95a1));}</style>'
    나온것 = cdt.검사('x.html', 본문)
    종류들 = [종 for 종, _v, _ln in 나온것]
    assert '색' not in 종류들


def test_var_구간_괄호_중첩을_정확히_닫는다():
    본문 = 'a var(--x,#111) b var(--y,var(--z,#222)) c #333'
    구간 = cdt._var_구간(본문)
    s0, e0 = 구간[0]
    assert 본문[s0:e0] == 'var(--x,#111)'
    s1, e1 = 구간[1]
    assert 본문[s1:e1] == 'var(--y,var(--z,#222))'
    # #333 은 var() 밖 — 어느 구간에도 안 들어간다
    assert not cdt._구간안(구간, 본문.index('#333'))


@pytest.mark.parametrize('바깥색,예비값', [
    ('#0071e3', '#0071e3'),  # 규칙에 있는 색이라도 예비값이면 무시
    ('#123abc', '#123abc'),  # 규칙에 없는 색도 예비값이면 무시
])
def test_var_밖_사용은_규칙표에_있어야만_통과한다(바깥색, 예비값):
    본문 = f'<div style="border:1px solid {바깥색};color:var(--ink,{예비값})">x</div>'
    나온것 = cdt.검사('x.html', 본문)
    색값들 = {값 for 종, 값, _ln in 나온것 if 종 == '색'}
    if 바깥색.lower() in cdt.COLORS:
        assert 색값들 == set()
    else:
        assert 색값들 == {바깥색.lower()}
