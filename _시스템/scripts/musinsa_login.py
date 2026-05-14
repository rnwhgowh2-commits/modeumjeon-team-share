"""무신사 수동 로그인 → storage_state 저장.

실행:
    cd "C:/Users/seung/OneDrive/바탕 화면/르무통 재고 업데이트"
    python -m scripts.musinsa_login

브라우저 창이 뜨면 직접 로그인 → 자동 감지 후 ``data/auth/무신사_default.json`` 저장.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from lemouton.sourcing.auth import save_state_after_manual_login, get_state_path


def main() -> int:
    source = "무신사"
    account = "default"
    print(f"=== {source} 로그인 세션 저장 ===")
    print(f"저장 경로: {get_state_path(source, account)}")
    print()

    ok = save_state_after_manual_login(
        source=source,
        account_name=account,
        headless=False,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
