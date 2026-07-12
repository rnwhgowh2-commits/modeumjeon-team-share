"""[v2] 멀티 마켓 계정 service.

핵심:
  - 자격증명 Fernet 암호화 저장/조회
  - 모음전 → 계정 매핑 (BundleAccountRegistration)
  - 옵션 → 계정 매핑 (OptionAccountRegistration)
  - 자동 등록 호출 시 어느 계정 키를 쓸지 분기

설계 문서: docs/architecture_v2.md §3.2
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from .models import (
    MarketAccount, BundleAccountRegistration, OptionAccountRegistration,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fernet 키 관리
# ─────────────────────────────────────────────────────────────────────────────

_ENCRYPT_KEY_ENV = 'MOUM_SECRET_KEY'
_KEY_FILE = Path('.lemouton_secret.key')


def _load_or_create_key() -> bytes:
    """MOUM_SECRET_KEY 환경변수 우선, 없으면 .lemouton_secret.key 파일.

    파일도 없으면 새로 생성 (운영 시 백업 필수 — 분실하면 자격증명 복호화 불가).
    """
    env = os.environ.get(_ENCRYPT_KEY_ENV)
    if env:
        return env.encode() if isinstance(env, str) else env
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes().strip()
    new_key = Fernet.generate_key()
    _KEY_FILE.write_bytes(new_key)
    return new_key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def encrypt_credentials(creds: dict[str, Any]) -> str:
    """dict → Fernet 암호화 토큰 (str)."""
    raw = json.dumps(creds, ensure_ascii=False).encode()
    return _fernet().encrypt(raw).decode()


def decrypt_credentials(token: str) -> dict[str, Any]:
    """Fernet 토큰 → dict.

    Raises:
      InvalidToken: 키 불일치 또는 토큰 손상.
    """
    raw = _fernet().decrypt(token.encode())
    return json.loads(raw.decode())


# ─────────────────────────────────────────────────────────────────────────────
# MarketAccount CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_account(
    session: Session,
    *,
    market: str,
    account_name: str,
    credentials: dict[str, Any],
    note: str | None = None,
) -> MarketAccount:
    """신규 계정 등록 — 같은 (market, account_name) 있으면 IntegrityError.

    market: 'smartstore' | 'coupang' | ...
    credentials: 평문 dict — service가 즉시 암호화 저장.
    """
    if market not in ('smartstore', 'coupang'):
        raise ValueError(f"market 은 smartstore/coupang 중 하나: {market}")
    enc = encrypt_credentials(credentials)
    a = MarketAccount(market=market, account_name=account_name,
                      credentials_encrypted=enc, note=note)
    session.add(a)
    session.flush()
    return a


def get_account(session: Session, account_id: int) -> MarketAccount | None:
    a = session.get(MarketAccount, account_id)
    if a is None or a.deleted_at is not None:
        return None
    return a


def get_credentials(session: Session, account_id: int) -> dict[str, Any]:
    """계정 자격증명 평문 조회 — 자동 등록·동기화 시점에만 호출."""
    a = get_account(session, account_id)
    if a is None:
        raise LookupError(f"MarketAccount id={account_id} 없음")
    return decrypt_credentials(a.credentials_encrypted)


def list_accounts(session: Session, market: str | None = None,
                  active_only: bool = True) -> list[MarketAccount]:
    q = session.query(MarketAccount).filter_by(deleted_at=None)
    if market:
        q = q.filter_by(market=market)
    if active_only:
        q = q.filter_by(is_active=True)
    return q.order_by(MarketAccount.market, MarketAccount.account_name).all()


def update_credentials(session: Session, account_id: int,
                       credentials: dict[str, Any]) -> MarketAccount:
    a = get_account(session, account_id)
    if a is None:
        raise LookupError(f"MarketAccount id={account_id} 없음")
    a.credentials_encrypted = encrypt_credentials(credentials)
    return a


def soft_delete_account(session: Session, account_id: int) -> None:
    """soft-delete — 데이터·이력 보존, 신규 등록·동기화에서만 제외."""
    from datetime import datetime, timezone
    a = get_account(session, account_id)
    if a is None:
        raise LookupError(f"MarketAccount id={account_id} 없음")
    a.deleted_at = datetime.now(timezone.utc)
    a.is_active = False


# ─────────────────────────────────────────────────────────────────────────────
# 모음전 → 계정 매핑
# ─────────────────────────────────────────────────────────────────────────────

def upsert_bundle_registration(
    session: Session,
    *,
    model_code: str,
    account_id: int,
    external_product_id: str | None = None,
    display_name_override: str | None = None,
    sale_price_override: int | None = None,
    is_registered: bool | None = None,
) -> BundleAccountRegistration:
    """모음전 × 계정 등록 매핑 — 멱등.

    같은 (model_code, account_id) 있으면 갱신 (지정된 필드만).
    """
    existing = (session.query(BundleAccountRegistration)
                .filter_by(model_code=model_code, account_id=account_id)
                .first())
    if existing is not None:
        if external_product_id is not None:
            existing.external_product_id = external_product_id
        if display_name_override is not None:
            existing.display_name_override = display_name_override
        if sale_price_override is not None:
            existing.sale_price_override = sale_price_override
        if is_registered is not None:
            existing.is_registered = is_registered
            if is_registered and existing.registered_at is None:
                from datetime import datetime, timezone
                existing.registered_at = datetime.now(timezone.utc)
        return existing
    r = BundleAccountRegistration(
        model_code=model_code, account_id=account_id,
        external_product_id=external_product_id,
        display_name_override=display_name_override,
        sale_price_override=sale_price_override,
        is_registered=bool(is_registered),
    )
    if is_registered:
        from datetime import datetime, timezone
        r.registered_at = datetime.now(timezone.utc)
    session.add(r)
    session.flush()
    return r


def list_registrations_for_bundle(session: Session,
                                  model_code: str) -> list[BundleAccountRegistration]:
    """이 모음전이 등록된 모든 계정의 매핑 정보."""
    return (session.query(BundleAccountRegistration)
            .filter_by(model_code=model_code)
            .all())


def get_registration(session: Session, model_code: str,
                     account_id: int) -> BundleAccountRegistration | None:
    return (session.query(BundleAccountRegistration)
            .filter_by(model_code=model_code, account_id=account_id)
            .first())


# ─────────────────────────────────────────────────────────────────────────────
# 옵션 → 계정 매핑
# ─────────────────────────────────────────────────────────────────────────────

def upsert_option_registration(
    session: Session,
    *,
    canonical_sku: str,
    account_id: int,
    external_option_id: str | None = None,
    is_visible: bool = True,
) -> OptionAccountRegistration:
    existing = (session.query(OptionAccountRegistration)
                .filter_by(canonical_sku=canonical_sku, account_id=account_id)
                .first())
    if existing is not None:
        if external_option_id is not None:
            existing.external_option_id = external_option_id
        existing.is_visible = is_visible
        return existing
    r = OptionAccountRegistration(
        canonical_sku=canonical_sku, account_id=account_id,
        external_option_id=external_option_id, is_visible=is_visible,
    )
    session.add(r)
    session.flush()
    return r


def list_option_registrations_for_account(
    session: Session, account_id: int,
) -> list[OptionAccountRegistration]:
    return (session.query(OptionAccountRegistration)
            .filter_by(account_id=account_id, is_visible=True)
            .all())


# ─────────────────────────────────────────────────────────────────────────────
# 자동 등록 라우터 — 어느 계정 키를 쓸지 분기
# ─────────────────────────────────────────────────────────────────────────────

def get_credentials_for_bundle_registration(
    session: Session, model_code: str, account_id: int,
) -> dict[str, Any]:
    """자동 등록·동기화가 사용 — 모음전+계정 → 평문 자격증명.

    Raises:
      LookupError: 매핑이 없거나 계정 비활성.
    """
    reg = get_registration(session, model_code=model_code, account_id=account_id)
    if reg is None:
        raise LookupError(
            f"BundleAccountRegistration 없음: model={model_code}, account={account_id}"
        )
    return get_credentials(session, account_id)
