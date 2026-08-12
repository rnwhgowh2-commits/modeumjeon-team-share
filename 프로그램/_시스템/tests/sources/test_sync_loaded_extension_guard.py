# -*- coding: utf-8 -*-
"""확장 맞추기 도구의 **손댐 안전장치** — 헛짚지도, 놓치지도 않는다.

🔴 왜 이 시험이 있나 — 처음 안전장치는 「origin/main 에 없는 줄이 있으면 손댐」이었다.
   그런데 그게 **늘 참**이다. 새 판이 기존 줄을 고치면 옛 줄은 당연히 새 판에 없다.
   2026-08-12 실측: 0.7.92 → 0.7.94 갱신에서 「손댐 4줄」로 막혔고, 넷 다 우리가
   갈아 끼운 옛 줄이었다. 즉 **정상 갱신마다 늘 막혀 도구를 아예 못 쓴다.**

   「막는 안전장치」와 「늘 막는 안전장치」는 다르다. 후자는 안전장치가 아니라 고장이다.

★ 그래서 판정을 바꿨다 — 「무엇이 다른가」가 아니라 **「이 내용이 우리 이력에 있나」**.
  지난 판과 글자까지 같으면 아무도 안 건드린 것이고, 어느 판과도 다르면 진짜 손댐이다.
  이 시험은 그 둘을 **양쪽 다** 못박는다(놓침도, 헛짚음도 사고다).
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

SYS_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = SYS_ROOT / 'scripts' / 'sync_loaded_extension.py'
REL = '프로그램/_시스템/extension/moum-crawler/background.js'


def _mod():
    spec = importlib.util.spec_from_file_location('sync_ext', SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _have_origin_main() -> bool:
    r = subprocess.run(['git', 'rev-parse', '--verify', 'origin/main'],
                       capture_output=True, cwd=SYS_ROOT)
    return r.returncode == 0


def _history_shas() -> list[str]:
    """🔴 `git log -- <경로>` 는 **지금 폴더 기준**이라 루트 경로를 그냥 넘기면 0건이다.
    0건이면 판정이 늘 「손댐」이 되는데, 그건 고치기 전과 똑같은 고장이다."""
    log = subprocess.run(['git', 'log', '--format=%H', '-20', 'origin/main',
                          '--', f':(top){REL}'], capture_output=True, cwd=SYS_ROOT)
    return log.stdout.decode().split()


def _past_version_text(back: int = 1) -> str | None:
    """origin/main 이력에서 `back` 번째로 옛 판의 내용."""
    shas = _history_shas()
    if len(shas) <= back:
        return None
    got = subprocess.run(['git', 'show', f'{shas[back]}:{REL}'],
                         capture_output=True, cwd=SYS_ROOT)
    return got.stdout.decode('utf-8') if got.returncode == 0 else None


def test_이력을_실제로_읽는다():
    """🔴 이 시험이 먼저다 — 이력이 0건이면 아래 시험들이 **아무것도 안 보고 통과**한다.

    실제로 겪었다: 경로를 루트 기준으로 넘겨 `git log` 가 0건을 냈고, 판정은 늘
    「손댐」이었는데 「손댐이다」 시험은 그대로 통과, 「손댐 아니다」 시험은 건너뛰어져
    **고친 줄 알았던 것이 안 고쳐진 채** 지나갈 뻔했다.
    """
    if not _have_origin_main():
        import pytest
        pytest.skip('origin/main 이 없는 환경(얕은 클론) — 이력 비교 불가')
    shas = _history_shas()
    assert len(shas) >= 2, (
        f'background.js 의 origin/main 이력이 {len(shas)}건입니다. '
        '경로 지정이 틀려 0건을 읽고 있을 수 있습니다 — 그러면 판정이 늘 「손댐」이 됩니다.'
    )


def test_지난_판_그대로면_손댐이_아니다(tmp_path):
    """🔴 헛짚음 차단 — 이걸 놓치면 정상 갱신이 영영 막힌다."""
    if not _have_origin_main():
        import pytest
        pytest.skip('origin/main 이 없는 환경(얕은 클론) — 이력 비교 불가')
    old = _past_version_text(back=1)
    assert old is not None, 'origin/main 이력을 못 읽었습니다 — 경로 지정을 확인하세요.'
    f = tmp_path / 'background.js'
    f.write_text(old, encoding='utf-8', newline='')
    assert _mod()._is_a_past_main_version('background.js', f) is True, (
        '지난 판 그대로인데 「손댐」이라 했습니다 — 이러면 갱신이 늘 막힙니다.'
    )


def test_한_글자라도_고쳐졌으면_손댐이다(tmp_path):
    """🔴 놓침 차단 — 남이 고친 판을 덮으면 그 작업이 조용히 사라진다."""
    if not _have_origin_main():
        import pytest
        pytest.skip('origin/main 이 없는 환경(얕은 클론) — 이력 비교 불가')
    old = _past_version_text(back=1) or ''
    f = tmp_path / 'background.js'
    f.write_text(old + '\n// 다른 세션이 넣은 줄\n', encoding='utf-8', newline='')
    assert _mod()._is_a_past_main_version('background.js', f) is False, (
        '남이 손댄 파일을 「지난 판」이라 했습니다 — 그대로 덮으면 그 작업이 사라집니다.'
    )


def test_빈_파일도_손댐으로_본다(tmp_path):
    if not _have_origin_main():
        import pytest
        pytest.skip('origin/main 이 없는 환경(얕은 클론) — 이력 비교 불가')
    f = tmp_path / 'background.js'
    f.write_text('', encoding='utf-8')
    assert _mod()._is_a_past_main_version('background.js', f) is False
