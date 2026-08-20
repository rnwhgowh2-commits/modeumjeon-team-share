# -*- coding: utf-8 -*-
"""크롬에 **실제로 로드된** 확장 폴더를 저장소와 맞춘다.

━━ 🎉 [2026-08-13] 이제 **연결(junction)** 이라 맞출 것이 없다 ━━━━━━━━━━━
크롬이 읽는 폴더를 **저장소 폴더를 가리키는 연결**로 바꿨다. 사본이 아니라
**같은 폴더**다. 그래서 코드를 고치면 `chrome://extensions` 의 ↻ 만 누르면
**바로 반영**된다 — 복사 단계가 아예 사라졌다.

  로드 폴더  C:\\Users\\seung\\Desktop\\moum-crawler-v0.7.63
     ↓ 연결(junction)
  저장소     C:\\dev\\_wt_bulksafe\\프로그램\\_시스템\\extension\\moum-crawler

━━ 왜 이렇게까지 했나 (사본이던 시절의 사고) ━━━━━━━━━━━━━━━━━━━━━━━━
사본이면 배포를 끝내도 그 폴더를 손으로 바꾸지 않는 한 ↻ 를 눌러도 **옛 판
그대로**다. 이걸로 **네 번** 헛걸음했다.

  · 1차 — 배포는 됐는데 폴더가 0.7.88 이라 ↻ 가 무의미
  · 2차 — 새 판(0.7.93·0.7.94)을 만들어 놓고 폴더 교체를 잊음
  · 3차 — 머지 전이라 폴더에 새 판이 아직 없었는데 ↻ 를 부탁함
  · 4차 — 같은 일 반복. 사장님이 「새로고침해도 안 올라가」

★ 사람이 기억해야 하는 절차는 언젠가 잊힌다 — **절차 자체를 없앴다.**

사용:
    python scripts/sync_loaded_extension.py           # 상태 보기(연결이면 할 일 없음)
    python scripts/sync_loaded_extension.py --check   # 어긋났는지 보기만
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 🔴 윈도우 명령창은 기본이 `cp949` 라 이모지(✅⚠️🔴)를 못 찍고 **UnicodeEncodeError 로
#   죽는다.** 이 스크립트는 모든 안내 줄에 이모지가 붙어 있어 성공·실패·「손댐 있음」
#   **어느 경로로도 결과를 못 내고 traceback 만 남겼다**(2026-08-12 실측, Python 3.14).
#   → 못 찍는 글자만 `?` 로 바꾸고 한글은 그대로 둔다. 안내가 끊기는 것보다 낫다.
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')

#: 크롬이 읽는 폴더. `chrome://extensions` 의 확장 ID 로 Secure Preferences 에서 찾는다.
#: 🔴 폴더 **이름은 옛 판 그대로**(v0.7.63)라 이름만 보고 판단하면 안 된다.
LOADED = Path(r'C:\Users\seung\Desktop\moum-crawler-v0.7.63')
FILES = ('background.js', 'content_mou.js', 'manifest.json')


def _from_main(name: str) -> str:
    """origin/main 의 그 파일 내용. 저장소 어디서 돌려도 같은 답이 나온다."""
    out = subprocess.run(
        ['git', 'show', f'origin/main:프로그램/_시스템/extension/moum-crawler/{name}'],
        capture_output=True, cwd=Path(__file__).resolve().parents[1])
    if out.returncode != 0:
        raise SystemExit(f'origin/main 에서 {name} 를 못 읽었습니다 — git fetch 먼저.')
    return out.stdout.decode('utf-8')


def _blob(path: Path) -> str:
    """그 파일 내용의 git 이름(해시). 같은 내용이면 같은 이름이 나온다."""
    out = subprocess.run(['git', 'hash-object', str(path)],
                         capture_output=True, cwd=Path(__file__).resolve().parents[1])
    return out.stdout.decode().strip()


def _is_a_past_main_version(name: str, path: Path, depth: int = 40) -> bool:
    """로드 폴더의 이 파일이 **origin/main 의 지난 판 그대로**인가.

    🔴 왜 이렇게 재나 — 처음엔 「origin/main 에 없는 줄이 있으면 손댐」으로 쟀는데
      그게 **늘 참**이었다. 새 판이 기존 줄을 고치면 옛 줄은 당연히 새 판에 없다.
      그래서 정상 갱신마다 안전장치가 걸려 도구를 아예 못 썼다(2026-08-12 실측:
      0.7.92 → 0.7.94 에서 「손댐 4줄」로 막힘 — 넷 다 우리가 갈아 끼운 옛 줄이었다).

    ★ 지난 판과 **글자까지 같으면** 아무도 손대지 않은 것이다. 어느 판과도 다르면
      그때가 진짜 손댐이다. 「무엇이 다른가」가 아니라 「이 내용이 우리 이력에 있나」로 잰다.
    """
    here = _blob(path)
    if not here:
        return False
    rel = f'프로그램/_시스템/extension/moum-crawler/{name}'
    cwd = Path(__file__).resolve().parents[1]
    # 🔴 `git log -- <경로>` 의 경로는 **지금 폴더 기준**이다(`git show rev:경로` 와 다르다).
    #   저장소 루트 기준 경로를 그냥 넘기면 **한 건도 안 걸려 늘 「손댐」**이 된다 —
    #   고친 판정이 옛 판정과 똑같이 늘 막히는 셈이라 알아채기 어렵다(2026-08-12 실측).
    #   `:(top)` 을 붙이면 어디서 돌려도 루트 기준이 된다.
    log = subprocess.run(['git', 'log', '--format=%H', f'-{depth}', 'origin/main',
                          '--', f':(top){rel}'],
                         capture_output=True, cwd=cwd)
    for c in log.stdout.decode().split():
        got = subprocess.run(['git', 'rev-parse', f'{c}:{rel}'], capture_output=True, cwd=cwd)
        if got.stdout.decode().strip() == here:
            return True
    return False


def _ver(text: str, name: str) -> str:
    if name.endswith('.json'):
        return json.loads(text).get('version', '?')
    m = re.search(r'MOUM_EXT_VERSION = "([^"]+)"', text)
    return m.group(1) if m else '?'


def _is_junction(p: Path) -> bool:
    """로드 폴더가 **저장소를 가리키는 연결**인가.

    윈도우의 junction 은 `os.path.islink` 가 False 를 돌려준다(심볼릭 링크가
    아니라 재파싱 지점이라서). `st_reparse_tag` 로 봐야 한다.
    """
    import stat
    try:
        return bool(p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:       # noqa: BLE001 — 윈도우가 아니거나 못 읽으면 사본으로 본다
        return False


def main() -> int:
    check_only = '--check' in sys.argv
    if not LOADED.is_dir():
        print(f'🔴 로드 폴더가 없습니다: {LOADED}')
        print('   chrome://extensions 의 확장 ID 로 Secure Preferences 에서 "path" 를 찾으세요.')
        return 2

    # 🎉 연결이면 사본이 아니라 **같은 폴더**다 — 맞출 것이 없다.
    #   코드를 고치면 ↻ 만 누르면 바로 반영된다.
    if _is_junction(LOADED):
        v = _ver((LOADED / 'manifest.json').read_text(encoding='utf-8'), 'manifest.json')
        print(f'✅ 연결돼 있습니다 — 저장소와 같은 폴더입니다 (지금 {v})')
        print('   맞출 것이 없습니다. chrome://extensions 에서 ↻ 만 누르면 바로 반영됩니다.')
        return 0

    want = {n: _from_main(n) for n in FILES}
    now = {n: (LOADED / n).read_text(encoding='utf-8') for n in FILES}
    diff = [n for n in FILES if want[n] != now[n]]

    print(f'로드 폴더 : {_ver(now["manifest.json"], "manifest.json")}')
    print(f'origin/main: {_ver(want["manifest.json"], "manifest.json")}')
    if not diff:
        print('✅ 이미 같습니다 — ↻ 를 눌러도 바뀌는 것이 없습니다.')
        return 0

    print(f'⚠️ 다른 파일 {len(diff)}개: {", ".join(diff)}')
    if check_only:
        print('   (--check 라 바꾸지 않았습니다)')
        return 1

    # 🔴 남의 손댐이 있는지 먼저 본다 — 통째로 덮기 전에 확인한다.
    #   판정은 「지난 판 그대로인가」로 한다(_is_a_past_main_version 주석 참조).
    for n in ('background.js', 'content_mou.js'):
        if not _is_a_past_main_version(n, LOADED / n):
            print(f'🔴 {n} 이 origin/main 의 어느 판과도 다릅니다.')
            print('   → 다른 세션이나 사람이 손댔을 수 있습니다. 확인 전에는 덮지 마세요.')
            print(f'   비교: git diff <(git show origin/main:프로그램/_시스템/extension/moum-crawler/{n}) "{LOADED / n}"')
            return 3

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for n in FILES:
        shutil.copy2(LOADED / n, LOADED / f'{n}.bak_{stamp}')
        (LOADED / n).write_text(want[n], encoding='utf-8')
    print(f'✅ 맞췄습니다 (백업 .bak_{stamp})')
    print('   이제 chrome://extensions 에서 ↻ 를 누르면 새 판이 들어갑니다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
