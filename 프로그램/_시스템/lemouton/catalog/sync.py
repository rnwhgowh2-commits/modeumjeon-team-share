# -*- coding: utf-8 -*-
"""동기화 — 계정 하나를 끝까지 훑고, 실패해도 나머지 계정으로 넘어간다.

규모(2026-07-23 실측): 약 28만 건 · 2,720 호출 · 30~60분(밤 1회).
실측 속도 0.59초/콜(11번가 131콜 77초) 기준.

★ 중간에 실패하면 '사라짐' 표시를 하지 않는다. 절반만 받고 나머지를 사라졌다고 하면
  멀쩡한 상품이 화면에서 사라진다.
"""
from __future__ import annotations

import logging
from typing import Optional

from . import repository as R
from .fetchers import PAGE_SIZE, fetch_page

logger = logging.getLogger(__name__)

#: 무한 루프 방지. 마켓이 이상한 총건수를 줘도 여기서 멈춘다.
#: 롯데온 최대 계정 47,960건 = 480페이지라 넉넉히 잡는다.
DEFAULT_MAX_PAGES = 800


def sync_account(session, market: str, account_key: str, *, client,
                 max_pages: int = DEFAULT_MAX_PAGES, **kw) -> dict:
    """계정 하나를 끝까지 훑어 캐시에 넣는다.

    Returns:
        {ok, saved, pages, missing, truncated, total, error, market, account_key}
    """
    size = PAGE_SIZE.get(market, 100)
    saved = 0
    pages = 0
    seen: set = set()
    total: Optional[int] = None
    token: Optional[str] = None
    truncated = False
    error: Optional[str] = None
    page_index = 1

    while pages < max_pages:
        try:
            page = fetch_page(market, client, page_index, next_token=token, **kw)
        except Exception as e:      # noqa: BLE001 — 실패를 삼키지 않고 표면화
            error = str(e)[:300]
            logger.warning('[catalog] %s/%s %d페이지 실패: %s',
                           market, account_key, page_index, error)
            break

        pages += 1
        if page.total is not None:
            total = page.total
        rows = page.rows
        if rows:
            saved += R.upsert_rows(session, market, account_key, rows)
            seen.update(r.market_product_id for r in rows)

        # 다음 페이지가 있나 — 마켓마다 판단이 다르다
        token = page.next_token
        if token:
            page_index += 1
            continue
        if total is not None:
            if saved >= total or not rows:
                break
        elif len(rows) < size:
            # 총건수를 안 주는 마켓 — 페이지가 덜 차면 마지막
            break
        page_index += 1

    if pages >= max_pages:
        truncated = True

    missing = 0
    if error is None and not truncated:
        # ★ 끝까지 성공했을 때만 사라짐 표시 — 절반만 받고 지우면 안 된다
        missing = R.mark_missing(session, market, account_key, seen)

    R.refresh_counts_from_cache(session, market, account_key)

    return {'ok': error is None, 'saved': saved, 'pages': pages,
            'missing': missing, 'truncated': truncated, 'total': total,
            'error': error, 'market': market, 'account_key': account_key}


# ── 전체 훑기 ────────────────────────────────────────────────

def _active_accounts(session, market: Optional[str] = None) -> list:
    """활성 판매처 계정 목록."""
    from lemouton.sourcing.models_v2 import UploadAccount
    q = session.query(UploadAccount).filter(UploadAccount.is_active.is_(True))
    if market:
        q = q.filter(UploadAccount.market == market)
    return q.order_by(UploadAccount.market, UploadAccount.account_key).all()


def _client_for(market: str, env_prefix: str):
    """계정 키로 마켓 클라이언트 생성. 기존 배선(market_fetch)을 그대로 쓴다."""
    from lemouton.uploader import market_fetch as MF
    if market == 'smartstore':
        return MF._smartstore_client(env_prefix)
    if market == 'coupang':
        return MF._coupang_client(env_prefix)
    if market == 'lotteon':
        return MF._lotteon_client(env_prefix)
    if market == 'eleven11':
        return MF._eleven11_client(env_prefix)
    if market in ('auction', 'gmarket'):
        return MF._esm_client(market, env_prefix)
    raise ValueError(f"모르는 마켓입니다: {market!r}")


def sync_all(session=None, *, market: Optional[str] = None,
             max_pages: int = DEFAULT_MAX_PAGES) -> dict:
    """활성 계정을 하나씩 훑는다. 한 계정이 실패해도 나머지는 계속한다.

    ★ 실패한 계정은 결과에 남긴다 — 화면이 「마지막 확인: 어제」로 정직하게 뜬다.
      조용히 옛 숫자를 최신인 척 보여주지 않는다.
    """
    own = session is None
    if own:
        from shared.db import SessionLocal
        session = SessionLocal()
    try:
        accounts = _active_accounts(session, market)
        results = []
        for a in accounts:
            try:
                client = _client_for(a.market, a.env_prefix)
                r = sync_account(session, a.market, a.account_key,
                                 client=client, max_pages=max_pages,
                                 vendor_id=getattr(client, 'vendor_id', None))
            except Exception as e:      # noqa: BLE001
                logger.warning('[catalog] %s/%s 동기화 실패: %s',
                               a.market, a.account_key, e)
                r = {'ok': False, 'saved': 0, 'pages': 0, 'missing': 0,
                     'truncated': False, 'total': None, 'error': str(e)[:300],
                     'market': a.market, 'account_key': a.account_key}
            results.append(r)
        return {
            'accounts': len(accounts),
            'ok_count': sum(1 for r in results if r['ok']),
            'failed_count': sum(1 for r in results if not r['ok']),
            'saved_total': sum(r['saved'] for r in results),
            'missing_total': sum(r['missing'] for r in results),
            'results': results,
        }
    finally:
        if own:
            session.close()
