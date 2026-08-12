# -*- coding: utf-8 -*-
"""크롬에 **실제로 로드된** 확장 폴더를 origin/main 판으로 맞춘다.

━━ 왜 이 스크립트가 있나 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
크롬이 읽는 폴더는 저장소가 아니라 **데스크톱의 별도 사본**이다. 그래서 배포를
끝내도 그 폴더를 손으로 바꾸지 않으면 사장님이 `chrome://extensions` 에서 ↻ 를
눌러도 **옛 판 그대로**다. 2026-08-08 이걸로 두 번 헛걸음했다.

  · 1차 — 배포는 됐는데 폴더가 0.7.88 이라 ↻ 가 무의미
  · 2차 — 새 판(0.7.93·0.7.94)을 만들어 놓고 폴더 교체를 잊음

🔴 **「↻ 를 눌러 주세요」라고 말하기 전에 반드시 이 스크립트를 돌린다.**
  안 그러면 사장님은 눌러도 아무 일이 없고, 나는 코드를 의심하며 헤맨다.

사용:
    python scripts/sync_loaded_extension.py           # 맞추기
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


def _ver(text: str, name: str) -> str:
    if name.endswith('.json'):
        return json.loads(text).get('version', '?')
    m = re.search(r'MOUM_EXT_VERSION = "([^"]+)"', text)
    return m.group(1) if m else '?'


def main() -> int:
    check_only = '--check' in sys.argv
    if not LOADED.is_dir():
        print(f'🔴 로드 폴더가 없습니다: {LOADED}')
        print('   chrome://extensions 의 확장 ID 로 Secure Preferences 에서 "path" 를 찾으세요.')
        return 2

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
    for n in ('background.js', 'content_mou.js'):
        only_here = [l for l in now[n].splitlines()
                     if l not in want[n] and 'MOUM_EXT_VERSION' not in l]
        if only_here:
            print(f'🔴 {n} 에 origin/main 에 없는 줄이 {len(only_here)}개 있습니다:')
            for l in only_here[:5]:
                print('   ', l.strip()[:100])
            print('   → 다른 세션이 손댔을 수 있습니다. 확인 전에는 덮지 마세요.')
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
