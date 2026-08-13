# -*- coding: utf-8 -*-
"""확장 맞추기 도구가 **윈도우 명령창(cp949)에서도 말을 한다**.

🔴 왜 이 시험이 있나 — 이 도구는 「↻ 를 눌러 주세요」라고 말하기 전에 반드시
   돌리는 물건인데, 안내 줄마다 이모지(✅⚠️🔴)가 붙어 있어 cp949 콘솔에서
   **UnicodeEncodeError 로 죽었다.** 성공·실패·「다른 세션이 손댐」 **어느 경로로도**
   결과를 못 내고 traceback 만 남았다(2026-08-12 실측).

   「죽는 것」과 「죽는데 아무 말도 안 하는 것」은 다른 잘못이다. 결과를 못 보면
   폴더를 안 맞춘 채 사장님께 ↻ 를 부탁하게 되고, 그러면 눌러도 아무 일이 없다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'sync_loaded_extension.py'


def _run_with_cp949():
    """cp949 콘솔인 척하고 돌린다 — 실제 사장님 PC 와 같은 조건."""
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'cp949'
    return subprocess.run(
        [sys.executable, str(SCRIPT), '--check'],
        capture_output=True, env=env, cwd=str(SCRIPT.parent.parent),
    )


def test_도구가_있다():
    assert SCRIPT.is_file(), f'맞추기 도구가 없습니다: {SCRIPT}'


def test_cp949_콘솔에서_안_죽는다():
    """🔴 이 시험이 이 파일의 전부다 — 이모지 때문에 죽으면 여기서 걸린다."""
    p = _run_with_cp949()
    err = p.stderr.decode('utf-8', 'replace')
    assert 'UnicodeEncodeError' not in err, (
        'cp949 콘솔에서 이모지를 못 찍어 죽었습니다. 안내 줄에 이모지를 넣을 거면 '
        f'stdout 에 errors=replace 를 걸어야 합니다.\n{err[-800:]}'
    )
    assert 'Traceback' not in err, f'뜻밖의 오류로 죽었습니다:\n{err[-800:]}'


def test_무슨_판인지_말한다():
    """폴더가 있든 없든 **사람이 읽을 안내 한 줄**은 반드시 나온다."""
    p = _run_with_cp949()
    out = p.stdout.decode('cp949', 'replace')
    assert out.strip(), '아무 말도 안 했습니다 — 결과를 사람이 알 수 없습니다.'
    # 셋 중 하나는 말해야 한다:
    #   ① 연결돼 있다(2026-08-13부터 — 사본이 아니라 저장소와 같은 폴더)
    #   ② 사본이라 판 번호를 견준다
    #   ③ 폴더가 아예 없다
    # 🔴 옛 시험은 ②만 기대했다가, 연결로 바꾼 날 애먼 실패를 냈다.
    #   **화면 글자에 목록을 박으면 그 글자가 바뀌는 날 낡는다.**
    assert (('연결돼 있습니다' in out) or ('origin/main' in out)
            or ('폴더가 없습니다' in out)), (
        f'연결 여부도, 판 번호도, 폴더 없음도 안 알려 줍니다:\n{out[:500]}'
    )
