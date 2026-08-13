# -*- coding: utf-8 -*-
"""크롬이 읽는 확장 폴더는 **저장소를 가리키는 연결**이다 — 사본이 아니다.

🔴🔴 왜 (2026-08-13, 사장님: 「새로고침해도 안 올라가」)
   여태 크롬이 읽는 폴더는 데스크톱의 **별도 사본**이었다. 그래서 코드를 고쳐도
   누군가 손으로 복사해 주기 전에는 `chrome://extensions` 의 ↻ 를 눌러도
   **아무 일이 없었다.** 이걸로 **네 번** 헛걸음했다.

     1차 — 배포는 됐는데 폴더가 옛 판이라 ↻ 가 무의미
     2차 — 새 판을 만들어 놓고 폴더 교체를 잊음
     3차 — 머지 전이라 폴더에 새 판이 아직 없었는데 ↻ 를 부탁함
     4차 — 같은 일 반복

★ 사람이 기억해야 하는 절차는 언젠가 잊힌다. **절차 자체를 없앴다** —
  폴더를 저장소를 가리키는 **연결(junction)** 로 바꿨다. 사본이 아니라 같은
  폴더라, 코드를 고치면 ↻ 만 누르면 바로 반영된다.

★★ 이 시험은 **연결을 알아보는 판정**을 지킨다. 윈도우 junction 은
   `os.path.islink` 가 False 를 돌려주므로(심볼릭 링크가 아니라 재파싱 지점)
   그걸로 재면 **늘 「사본」이라 오판**한다.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / 'scripts' / 'sync_loaded_extension.py')


def _mod():
    spec = importlib.util.spec_from_file_location('sync_ext', SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_연결_판정_함수가_있다():
    assert hasattr(_mod(), '_is_junction'), (
        '연결인지 보는 함수가 없습니다 — 연결인데도 사본으로 보고 덮으려 듭니다.'
    )


def test_보통_폴더는_연결이_아니다(tmp_path):
    d = tmp_path / '보통폴더'
    d.mkdir()
    assert _mod()._is_junction(d) is False


def test_진짜_연결을_알아본다(tmp_path):
    """🔴 `os.path.islink` 로 재면 윈도우 junction 을 못 알아본다."""
    if os.name != 'nt':
        pytest.skip('윈도우가 아닌 환경 — junction 을 만들 수 없다')
    import subprocess
    real = tmp_path / '진짜'
    real.mkdir()
    (real / 'x.txt').write_text('hi', encoding='utf-8')
    link = tmp_path / '연결'
    r = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(real)],
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip('junction 을 만들 수 없는 환경')
    assert _mod()._is_junction(link) is True, (
        'junction 을 못 알아봅니다 — os.path.islink 로 재면 늘 False 입니다.'
    )
    # 참고 — 실제로 islink 는 False 다(이 시험이 지키려는 바로 그 함정).
    assert os.path.islink(link) is False


def test_없는_폴더는_조용히_False():
    """못 읽는 경우에 터지면 도구가 아무 말도 못 하고 죽는다."""
    assert _mod()._is_junction(Path('/없는/폴더/입니다')) is False
