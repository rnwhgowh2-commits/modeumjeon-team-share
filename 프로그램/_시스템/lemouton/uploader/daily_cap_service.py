"""업로드 상한을 **실제 이력에서** 센다 — daily_cap 엔진과 DB 사이의 다리.

설계서: 2026-07-19-크롤주기-변동주기-등급-design.md §5-1 · §5-1-1

━━ 왜 별도 파일인가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  :mod:`lemouton.uploader.daily_cap` 은 순수 판정(세션을 모른다).
  세는 일은 DB 를 알아야 하므로 여기서 한다 — 판정과 집계를 섞으면
  테스트가 DB 없이는 못 돌고, 판정 규칙이 쿼리에 숨어버린다.

━━ 「하루」는 한국 날짜다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ``uploaded_at`` 은 UTC 로 저장된다. UTC 자정으로 세면 한국 시각
  **오전 9시**에 상한이 초기화된다 — 사장님이 보는 '하루'와 다르다.
"""
from __future__ import annotations

import datetime as _dt

KST = _dt.timezone(_dt.timedelta(hours=9))

# 상한 설정 키 (GlobalSettings 가 아니라 대량등록 ⑧설정에서 관리할 값).
# 아직 화면이 없어 기본값을 쓴다 — 화면이 생기면 여기만 갈아끼운다.


def kst_day_start_utc(now: _dt.datetime | None = None) -> _dt.datetime:
    """'오늘'(한국 날짜)이 시작된 시각을 **UTC naive** 로.

    ``uploaded_at`` 이 tz 없이 저장돼 있어 비교 대상도 naive 로 맞춘다.
    """
    n = now or _dt.datetime.now(KST)
    if n.tzinfo is None:
        n = n.replace(tzinfo=KST)
    midnight = n.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(_dt.timezone.utc).replace(tzinfo=None)


def used_today(session, *, canonical_sku: str, market: str,
               account_key: str = "default", now=None) -> int:
    """오늘(한국 날짜) 이 상품이 이 마켓·계정으로 **실제로 나간** 횟수.

    ★ ``uploaded_at`` 이 있는 행만 센다. skip·hold 는 안 나간 것이다
      (:class:`lemouton.uploader.models.PriceSnapshot` 관례).
    """
    from sqlalchemy import func

    from .models import PriceSnapshot

    return int(session.query(func.count(PriceSnapshot.id))
               .filter(PriceSnapshot.canonical_sku == canonical_sku,
                       PriceSnapshot.market == market,
                       PriceSnapshot.account_key == (account_key or "default"),
                       PriceSnapshot.uploaded_at.isnot(None),
                       PriceSnapshot.uploaded_at >= kst_day_start_utc(now))
               .scalar() or 0)


def is_sold_out(stock) -> bool | None:
    """재고 센티넬 → 품절인가.

    ★ **True 만 품절**이다. 재고 센티넬 관례(lemouton/sources/lap_report.py):
        None = 미크롤 · -1 = 확인 불가 · 0 = 품절 · 그 외 = 있음
      확인 불가(-1)를 품절로 오인하면 멀쩡한 상품을 내린다
      (집 원칙: 파싱 실패는 0 이 아니라 '확인 불가').
    """
    if stock is None or stock < 0:
        return None
    return stock == 0


def decide_for_plan(session, *, canonical_sku: str, market: str,
                    account_key: str = "default", stock=None,
                    config=None, now=None):
    """이 상품을 지금 올려도 되나 — 이력을 세서 :func:`decide_cap` 에 넘긴다."""
    from .daily_cap import decide_cap

    return decide_cap(
        used_today=used_today(session, canonical_sku=canonical_sku,
                              market=market, account_key=account_key, now=now),
        is_sold_out=is_sold_out(stock),
        config=config,
    )
