# -*- coding: utf-8 -*-
"""업로드→분석 스테이징 저장소 (DB 단일 행).

🔴 프로세스 전역 dict 를 쓰면 안 되는 이유 — 앱은 gunicorn 워커 3개로 돈다.
   업로드가 A워커 메모리에 들어가고 분석이 B워커로 가면 "먼저 더망고 매입 엑셀을
   업로드하세요"가 뜬다(2026-07-23 실제 사고). 워커가 여럿이면 전역 변수는 저장이 아니다.

원본 **바이트**를 저장하고 읽을 때 다시 파싱한다(DataFrame 피클 금지 — pandas 버전이
바뀌면 못 읽는다).
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from lemouton.margin.models import MarginPendingUpload

_ROW_ID = 1


def _row(session, create: bool = False) -> Optional[MarginPendingUpload]:
    row = session.get(MarginPendingUpload, _ROW_ID)
    if row is None and create:
        row = MarginPendingUpload(id=_ROW_ID)
        session.add(row)
    return row


def stage_buy(session, *, raw: bytes, filename: str,
              period_from: _dt.date | None, period_to: _dt.date | None) -> None:
    """매입 엑셀 스테이징. 새 매입 업로드는 **이전 샵마인을 반드시 비운다**(stale 방지)."""
    row = _row(session, create=True)
    row.buy_bytes = raw
    row.buy_filename = filename
    row.period_from = period_from
    row.period_to = period_to
    row.shop_bytes = None
    row.shop_filename = None
    session.commit()


def stage_shopmine(session, *, raw: bytes, filename: str) -> None:
    row = _row(session, create=True)
    row.shop_bytes = raw
    row.shop_filename = filename
    session.commit()


def get(session) -> dict:
    """{buy_bytes, buy_filename, period_from, period_to, shop_bytes, shop_filename}.

    매입이 없으면 buy_bytes 가 None — 호출부가 그걸로 '업로드 안 됨'을 판정한다.
    """
    row = _row(session)
    if row is None:
        return {}
    return {
        "buy_bytes": row.buy_bytes, "buy_filename": row.buy_filename,
        "period_from": row.period_from, "period_to": row.period_to,
        "shop_bytes": row.shop_bytes, "shop_filename": row.shop_filename,
    }


def has_buy(session) -> bool:
    return bool((get(session) or {}).get("buy_bytes"))


def clear(session) -> None:
    row = _row(session)
    if row is not None:
        session.delete(row)
        session.commit()
