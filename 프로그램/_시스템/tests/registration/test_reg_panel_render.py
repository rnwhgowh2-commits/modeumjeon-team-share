# -*- coding: utf-8 -*-
"""등록 패널이 **화면에 실제로 그리는 것**을 pytest 안에서도 고정한다.

★★ [2026-07-24 4차리뷰 치명①] 왜 이 파일이 필요한가 —
  라우트 테스트(POST …/market-confirm)는 서버가 6마켓을 받는다는 것만 증명했다. 그런데
  화면은 확정 버튼을 **조회 결과 목록 안**에만 그려서, 조회 API 가 없는 4마켓
  (스스·쿠팡·옥션·G마켓)에는 확정할 방법이 아예 없었다. 서버 문구는 「이 상품번호로
  확정」을 누르라고 하는데 그 버튼이 화면에 없었다 — 남는 행동은 「다시 올리기」뿐이라
  **문구가 사람을 중복 등록 쪽으로 밀었다.** 하필 상품번호를 콕 집어 주는
  PARTIAL(옵션 부착 실패)이 옥션·G마켓 전용이라 최악의 조합이었다.
  「서버는 됐는데 화면이 빠진」 형태를 다음부터 이 테스트가 잡는다.

실체는 `tests/js/test_reg_panel_confirm.mjs`(실제 bulk_manual.js 를 떼어 Node 로 렌더)
이고, 이 파일은 그것을 파이썬 전수 실행(`pytest tests/`)에 물려 주는 얇은 껍데기다.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1] / 'js' / 'test_reg_panel_confirm.mjs'


@pytest.mark.skipif(shutil.which('node') is None,
                    reason='node 가 없어 화면 렌더 고정을 돌리지 못했습니다 '
                           '(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).')
def test_등록패널이_6마켓_전부에_확정_경로를_그린다():
    r = subprocess.run(['node', str(HARNESS)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=60)
    assert r.returncode == 0, f'화면 렌더 고정 실패:\n{r.stdout}\n{r.stderr}'


def test_렌더_고정_파일이_실제로_있다():
    """스킵되더라도 파일이 사라진 것은 알아야 한다(테스트가 조용히 증발하는 것 방지)."""
    assert HARNESS.exists(), HARNESS
