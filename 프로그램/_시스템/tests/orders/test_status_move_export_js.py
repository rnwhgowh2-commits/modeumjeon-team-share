# -*- coding: utf-8 -*-
"""「주문 관리」 상태 열 마무리(▲▼ 순서 · 엑셀 값) — 화면 배선 고정.

실체는 `tests/js/test_orders_status_move_export.mjs` 가 템플릿 **진짜 원문**을 떼어
Node 로 돌리고, 마지막에 **뮤테이션**으로 RED 를 실증한다. 이 파일은 그것을 pytest
전수 실행에 물려 주는 껍데기다(선례: test_order_status_js.py).
"""
import pathlib
import shutil
import subprocess

import pytest

JS = pathlib.Path(__file__).resolve().parents[1] / 'js'
MOVE = JS / 'test_orders_status_move_export.mjs'

_NO_NODE = shutil.which('node') is None
_SKIP = pytest.mark.skipif(
    _NO_NODE,
    reason='node 가 없어 배선 고정을 돌리지 못했습니다 '
           '(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).')


def test_배선_고정_파일이_실제로_있다():
    assert MOVE.exists(), MOVE


@_SKIP
def test_화살표_순서바꾸기와_엑셀_상태값_배선():
    """▲▼ 가 끌기와 같은 reorder 길을 쓰고, 엑셀 행에 「주문 관리」가 얹힌다."""
    r = subprocess.run(['node', str(MOVE)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, f'배선 고정 실패:\n{r.stdout}\n{r.stderr}'
