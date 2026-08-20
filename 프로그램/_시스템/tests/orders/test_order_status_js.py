# -*- coding: utf-8 -*-
"""「주문 관리」 상태 열 — 화면 배선 고정(Node 하네스를 pytest 전수 실행에 물린다).

⚠️ 문자열 검사로는 못 잡는다(코드는 늘 「있다」). 그래서 실체는 `tests/js/*.mjs` 로,
   템플릿의 **진짜 원문**(filterKey · ostFilterKey · rowPass …)을 떼어 Node 에서 돌리고
   실제로 필터 목록·거르기 결과를 만들어 본다. 마지막에 **뮤테이션**으로 RED 를 실증한다.
   이 파일은 그것을 pytest 에 물려 주는 껍데기다(선례: test_purchase_upload_ux.py).
"""
import pathlib
import shutil
import subprocess

import pytest

JS = pathlib.Path(__file__).resolve().parents[1] / 'js'
FILTER = JS / 'test_orders_status_filter.mjs'

_NO_NODE = shutil.which('node') is None
_SKIP = pytest.mark.skipif(
    _NO_NODE,
    reason='node 가 없어 배선 고정을 돌리지 못했습니다 '
           '(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).')


def test_배선_고정_파일이_실제로_있다():
    """node 가 없어 스킵되더라도 파일이 증발한 것은 알아야 한다."""
    assert FILTER.exists(), FILTER


@_SKIP
def test_상태_열_필터가_ostMap_의_진짜_값을_본다():
    """「(빈값) 전부」 하나로 뭉개지지 않고 항목 이름 + 「지정 안 함」으로 갈린다."""
    r = subprocess.run(['node', str(FILTER)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, f'배선 고정 실패:\n{r.stdout}\n{r.stderr}'
