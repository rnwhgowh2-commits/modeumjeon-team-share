# -*- coding: utf-8 -*-
"""크롤 가이드 §5 에러이력 — 별표·백틱이 글자로 보이던 것을 파이썬 전수 실행에 물린다.

★[2026-08-12 라이브 실측] 카탈로그 글은 원문(.md)과 같은 표기를 쓰는데 보기 화면이
  표기를 안 살려서 화면에 별 두 개와 백틱이 그대로 떴다 — 16항목 · 30칸.
  수정 = map.html 의 rich()(막기 먼저 → 표기 나중).

실체는 `tests/js/test_guide_catalog_rich.js` — **실제 map.html 의 esc()·rich() 를 잘라**
진짜 카탈로그 93건을 통과시키는 동작 테스트다(로직 사본 금지). 이 파일은 얇은 껍데기.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1] / 'js' / 'test_guide_catalog_rich.js'


@pytest.mark.skipif(shutil.which('node') is None,
                    reason='node 가 없어 가이드 표기 고정을 돌리지 못했습니다 '
                           '(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).')
def test_에러이력_글에_별표가_글자로_남지_않는다():
    r = subprocess.run(['node', str(HARNESS)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=60)
    assert r.returncode == 0, f'가이드 표기 고정 실패:\n{r.stdout}\n{r.stderr}'


def test_표기_고정_파일이_실제로_있다():
    """스킵되더라도 파일이 사라진 것은 알아야 한다(테스트가 조용히 증발하는 것 방지)."""
    assert HARNESS.exists(), HARNESS
