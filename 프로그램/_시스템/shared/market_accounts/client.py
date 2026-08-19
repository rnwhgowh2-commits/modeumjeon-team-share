# -*- coding: utf-8 -*-
"""판매처 계정 브리지 — samba-wave 가 가진 계정 창고에서 실 자격증명을 받아온다.

배경: 모음전은 지금까지 판매처(쿠팡·11번가 등) 자격증명을 환경변수로 직접 들고 있었다
(shared/platforms/__init__.py 의 COUPANG·SMARTSTORE 등 각 플랫폼 설정 상수). 앞으로는 samba-wave 가 표준
저장소(samba_market_account 테이블)를 갖고, 모음전은 이 모듈을 통해 물어서 받아온다.
samba-wave 는 완전히 별도로 배포·운영되는 시스템이다 — DB를 직접 열어보지 않는다.

의존: samba-wave 쪽 GET /internal/accounts/credentials (docs/interfaces.md 참조).
samba-wave 리포에 구현·커밋 완료(브랜치 feat/moum-account-credentials-internal-api,
fork로 push는 아직 안 함) — X-Internal-Token 헤더로 인증(기존 cs_internal_token 재사용).

설계 메모: shared/platforms/*(마켓별 client= 주입) 관례를 안 따르고 requests 직접 호출로
했다 — 그쪽은 마켓 5곳마다 다른 서명·재시도 로직을 바꿔 끼우는 게 목적이라 client 추상화가
필요하지만, 여긴 고정 헤더 하나로 내부 엔드포인트 하나만 부르는 호출 1곳뿐이라 클래스를
새로 만드는 게 오히려 과함. 재시도/backoff 가 필요해지면(Task2+ 실연결 시) 그때 재고.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketAccountCredential:
    """샘바웨이브 samba_market_account 1행을 모음전이 쓰기 좋은 형태로 받은 것.

    필드 shape 은 samba-wave 의 backend/domain/samba/account/credentials.py 가
    market_type 별로 이미 만들어주는 dict 를 그대로 옮긴 것 — 여기서 다시 변환하지 않는다.
    """
    # [코드리뷰 반영] 여기 적는 market_type 은 samba-wave DB 에 실제로 저장된 값이어야
    # 한다("coupang" | "11st" | "smartstore" | "lotteon" | "auction" | "gmarket" 등,
    # samba-wave backend/domain/samba/account/service.py 의 SUPPORTED_MARKETS 기준).
    # 모음전 자체 관례는 11번가를 "eleven11"이라 부르는데(shared/platforms/eleven11/),
    # samba-wave 는 "11st"다 — 값 변환 없이 그대로 넘기면 여기서 어긋난다. 5개 플랫폼
    # 클라이언트를 이 브리지에 연결하는 다음 사이클에서, 호출부가 반드시 모음전
    # 이름 → samba-wave 이름으로 변환한 뒤 호출하도록 확정해야 함(아직 미정 — 이
    # 클래스가 값 검증/변환을 하지 않는다는 걸 명시적으로 남겨둠).
    market_type: str
    account_label: str
    fields: dict[str, Any]    # 예: coupang → {"accessKey", "secretKey", "vendorId"}


class MarketAccountUnavailable(Exception):
    """samba-wave 에 활성 계정이 없거나, 연동 자체가 실패했을 때."""


def get_market_account(
    market_type: str,
    *,
    account_label: Optional[str] = None,
) -> MarketAccountCredential:
    """market_type 에 해당하는 활성 판매처 계정 1개를 가져온다.

    account_label 없으면 is_default=true 계정. 여러 계정 중 어느 것도 default 가
    아니면 MarketAccountUnavailable — 자동으로 아무거나 고르지 않는다(추측 금지).

    실패(연결 불가·계정 없음)를 삼키지 않는다 — 호출자가 결정하게 예외를 그대로 던진다.
    폴백 가격/폴백 계정 없음 — [[feedback_no_fallback_price_on_match_fail]] 과 같은 원칙.
    """

    base_url = os.environ.get("SAMBA_WAVE_URL", "").strip().rstrip("/")
    if not base_url:
        raise MarketAccountUnavailable(
            "samba-wave 연동 미설정 — SAMBA_WAVE_URL 환경변수가 없습니다"
        )
    token = os.environ.get("SAMBA_WAVE_INTERNAL_TOKEN", "").strip()
    if not token:
        raise MarketAccountUnavailable(
            "samba-wave 연동 미설정 — SAMBA_WAVE_INTERNAL_TOKEN 환경변수가 없습니다"
        )

    params = {"market_type": market_type}
    if account_label:
        params["account_label"] = account_label

    started = time.monotonic()
    try:
        resp = requests.get(
            f"{base_url}/api/v1/internal/accounts/credentials",
            params=params,
            headers={"X-Internal-Token": token},
            timeout=10,
        )
    except requests.RequestException as e:
        logger.warning(
            "[market_accounts] %s 조회 실패(연결) %.2fs: %s",
            market_type, time.monotonic() - started, e,
        )
        raise MarketAccountUnavailable(
            f"samba-wave 연결 실패 (market_type={market_type}): {e}"
        ) from e

    elapsed = time.monotonic() - started

    if resp.status_code == 404:
        logger.info(
            "[market_accounts] %s 계정 없음 %.2fs (account_label=%s)",
            market_type, elapsed, account_label,
        )
        raise MarketAccountUnavailable(
            f"'{market_type}' 활성 판매처 계정을 찾을 수 없습니다"
            + (f" (account_label={account_label})" if account_label else " (기본 계정 없음)")
        )

    if resp.status_code != 200:
        logger.warning(
            "[market_accounts] %s 조회 실패(status=%s) %.2fs",
            market_type, resp.status_code, elapsed,
        )
        raise MarketAccountUnavailable(
            f"samba-wave 응답 오류 (market_type={market_type}, status={resp.status_code})"
        )

    data = resp.json()
    logger.info("[market_accounts] %s 조회 성공 %.2fs", market_type, elapsed)
    return MarketAccountCredential(
        market_type=data["market_type"],
        account_label=data["account_label"],
        fields=data["fields"],
    )
