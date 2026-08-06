# -*- coding: utf-8 -*-
"""화면 전용 칸 3부류(공급방식·가격 전후·바로가기) 열 필터 — 배선 고정.

⚠️ 매입가(`_pp_purchase`)에서 났던 「(빈값) 462 하나뿐」 사고와 **같은 부류**가
   세 곳 더 남아 있었다. 문자열 검사로는 못 잡으므로(코드는 늘 「있다」) 실체는
   `tests/js/test_orders_misc_filters.mjs` 가 템플릿 **진짜 원문**을 떼어 Node 로
   돌리고, 마지막에 **뮤테이션**으로 RED 를 실증한다.
   이 파일은 그것을 pytest 전수 실행에 물려 주는 껍데기다
   (선례: test_order_status_js.py · test_purchase_upload_ux.py).
"""
import pathlib
import shutil
import subprocess

import pytest

JS = pathlib.Path(__file__).resolve().parents[1] / 'js'
FILTER = JS / 'test_orders_misc_filters.mjs'

_NO_NODE = shutil.which('node') is None
_SKIP = pytest.mark.skipif(
    _NO_NODE,
    reason='node 가 없어 배선 고정을 돌리지 못했습니다 '
           '(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).')


def test_배선_고정_파일이_실제로_있다():
    """node 가 없어 스킵되더라도 파일이 증발한 것은 알아야 한다."""
    assert FILTER.exists(), FILTER


@_SKIP
def test_공급방식_가격전후_바로가기_필터가_별도_map_의_진짜_값을_본다():
    """세 부류 모두 「(빈값) 전부」로 뭉개지지 않고 의미 묶음으로 갈린다."""
    r = subprocess.run(['node', str(FILTER)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, f'배선 고정 실패:\n{r.stdout}\n{r.stderr}'
