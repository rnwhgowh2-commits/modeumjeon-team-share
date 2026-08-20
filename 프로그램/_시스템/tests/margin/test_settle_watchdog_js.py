# -*- coding: utf-8 -*-
"""정산 자동 반복 「회차 감시」를 파이썬 전수 실행(pytest tests/)에 물린다.

★[2026-08-04 실사고] 걸린 회차(롯데온 페이지 무한 대기 등)가 _settleRunning 을 영영 쥐면
  1분 알람 틱이 매번 busy 로 빠져 다음 회차가 1~2시간씩 밀렸다(17:10 다음이 19:56).
  수정 = 30분 상한 감시 + 세대표(_settleGen)로 옛 회차 무장해제.

실체는 `tests/js/test_settle_watchdog.js` — **실제 background.js 의 settle 블록을 잘라**
가짜 chrome·가짜 시계로 돌리는 동작 테스트다(로직 사본 금지). 이 파일은 얇은 껍데기.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1] / 'js' / 'test_settle_watchdog.js'


@pytest.mark.skipif(shutil.which('node') is None,
                    reason='node 가 없어 회차 감시 고정을 돌리지 못했습니다 '
                           '(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).')
def test_회차_감시가_걸린_회차를_내려놓고_다음_회차를_살린다():
    r = subprocess.run(['node', str(HARNESS)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=60)
    assert r.returncode == 0, f'회차 감시 고정 실패:\n{r.stdout}\n{r.stderr}'


def test_감시_고정_파일이_실제로_있다():
    """스킵되더라도 파일이 사라진 것은 알아야 한다(테스트가 조용히 증발하는 것 방지)."""
    assert HARNESS.exists(), HARNESS
