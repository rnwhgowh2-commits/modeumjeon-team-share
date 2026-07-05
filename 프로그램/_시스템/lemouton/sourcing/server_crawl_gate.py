"""서버 직접 크롤 게이트 — 원칙: 크롤은 로컬 PC(크롬 확장)가 담당.

`LEMOUTON_SERVER_CRAWL=1` 일 때만 서버가 소싱처에 직접 접속해 크롤한다.
기본값(미설정/그 외) = **OFF** → 서버 크롤 진입점은 no-op, 실제 크롤은
로컬 확장(navGrab → /api/sources/parse → /api/sources/crawl-result)이 수행한다.

나중에 서버 크롤로 되돌릴 때: 배포 env 에 `LEMOUTON_SERVER_CRAWL=1` 추가.
(관련 원칙: CLAUDE.md 🔒 3대 원칙 — 크롤은 로컬 PC)
"""
from __future__ import annotations

import os


def server_crawl_enabled() -> bool:
    """서버 직접 크롤 허용 여부. 기본 False(=로컬 확장이 크롤)."""
    return os.environ.get("LEMOUTON_SERVER_CRAWL") == "1"


DISABLED_MESSAGE = (
    "서버 크롤은 비활성 상태예요. 크롤은 로컬 크롬 확장이 담당합니다 "
    "(각 모음전 '실행' 버튼 또는 크롤 위젯 사용)."
)
