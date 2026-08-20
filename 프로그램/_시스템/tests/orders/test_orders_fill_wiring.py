# -*- coding: utf-8 -*-
"""주문 표 「채우기」(가격 전후·3분류·매입가)가 제일 느린 마켓에 묶이지 않는지.

🔴 2026-08-06 라이브 버그 — 매입가가 절대 안 뜸.
   `rebuild()` 는 마켓이 하나 도착할 때마다 표를 다시 그리는데, 채우기 3종이
   `if(!loading)` 안에 있었다. `loading` 은 **고른 마켓이 전부 끝나야** false 라,
   옥션 하나가 125초 걸려 실패 → 15초 뒤 재시도 → 63초 더 → 또 실패하는 동안
   (라이브 실측 t=206초) 표는 t=3초에 다 그려진 채 매입가가 전 줄 「확인 불가」였다.

   ⚠️ 문자열 검사로는 못 잡는다 — 호출문 자체는 옛 코드에도 **멀쩡히 있었다**.
   그래서 실체는 `tests/js/test_orders_fill_not_gated_on_slowest_market.mjs` 로,
   템플릿의 진짜 `load()` 원문을 떼어 Node 에서 돌리고 느린 마켓을 영영 응답 안 하게
   잡아 둔 채 세 요청이 실제로 나가는지 본다(옛 코드로 되돌리면 0건 → 즉사 실증).
   이 파일은 그것을 pytest 전수 실행에 물려 주는 껍데기다.
"""
import pathlib
import shutil
import subprocess

import pytest

WIRING = pathlib.Path(__file__).resolve().parents[1] / 'js' / \
    'test_orders_fill_not_gated_on_slowest_market.mjs'


def test_배선_고정_파일이_실제로_있다():
    """node 가 없어 스킵되더라도 파일이 증발한 것은 알아야 한다."""
    assert WIRING.exists(), WIRING


@pytest.mark.skipif(shutil.which('node') is None,
                    reason='node 가 없어 배선 고정을 돌리지 못했습니다 '
                           '(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).')
def test_표를_그렸으면_매입가_가격전후_3분류를_반드시_부른다():
    r = subprocess.run(['node', str(WIRING)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=120)
    assert r.returncode == 0, f'채우기 배선 고정 실패:\n{r.stdout}\n{r.stderr}'
