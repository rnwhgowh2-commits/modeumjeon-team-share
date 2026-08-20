"""서버 직접 크롤 게이트 — 원칙: 크롤은 로컬 PC(크롬 확장)가 담당.

`MOUM_SERVER_CRAWL=1` 일 때만 서버가 소싱처에 직접 접속해 크롤한다.
기본값(미설정/그 외) = **OFF** → 서버 크롤 진입점은 no-op, 실제 크롤은
로컬 확장(navGrab → /api/sources/parse → /api/sources/crawl-result)이 수행한다.

나중에 서버 크롤로 되돌릴 때: 배포 env 에 `MOUM_SERVER_CRAWL=1` 추가.
(관련 원칙: CLAUDE.md 🔒 3대 원칙 — 크롤은 로컬 PC)
"""
from __future__ import annotations

import os


def server_crawl_enabled() -> bool:
    """서버 직접 크롤 허용 여부. 기본 False(=로컬 확장이 크롤)."""
    return os.environ.get("MOUM_SERVER_CRAWL") == "1"


def server_detail_fetch_enabled() -> bool:
    """서버가 **상세 문서 한 장을 더 받는** 보강 접속 허용 여부. 기본 True.

    끄는 법(배포 불필요): 서버 env 에 ``MOUM_SERVER_DETAIL_FETCH=0``.

    ★ [2026-07-23 리뷰지적 I2] 위 `server_crawl_enabled` 와 **다른 손잡이**다.
      저건 '크롤 자체'(가격·재고 수집)를 서버가 하느냐이고, 이건 상세가 페이지에
      아예 없는 두 소싱처에서 **공개 문서 하나를 더 받는 것**만 켜고 끈다.
      · **SSG** `api_sources_parse.py` — `itemdesc.ssg.com` iframe 1회 GET
        (curl_cffi chrome120 impersonate 세션 · 홈 워밍업 · `DEFAULT_TIMEOUT=30`
         이 Flask 핫패스에서 **동기**로 돈다)
      · **현대H몰** `api_pricing.py::save_crawl_result` — `item-dtl` 1회 GET

      기본을 ON 으로 둔 이유 = 오늘 라이브가 이걸로 4마켓 상세 필수값을 채우고 있어서
      OFF 로 바꾸면 등록이 막힌다. SSG·현대H몰이 서버 IP 를 조이면 **배포 없이**
      이 값 하나로 끈다.
    """
    return os.environ.get("MOUM_SERVER_DETAIL_FETCH", "1") != "0"


DETAIL_FETCH_DISABLED_MESSAGE = (
    "서버측 상세 보강이 꺼져 있어요(MOUM_SERVER_DETAIL_FETCH=0). "
    "상세는 '확인불가'로 두고, 가격·재고 수집은 그대로 진행합니다."
)


DISABLED_MESSAGE = (
    "서버 크롤은 비활성 상태예요. 크롤은 로컬 크롬 확장이 담당합니다 "
    "(각 모음전 '실행' 버튼 또는 크롤 위젯 사용)."
)
