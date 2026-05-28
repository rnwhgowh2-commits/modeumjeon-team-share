"""shared/sku_format.py — SKU·바코드·품번 컬럼 규칙 (단일 진실 원천).

[2026-05-28] Phase 1-4 — 모음전·재고관리 양쪽 경로에서 동일 함수 호출.

사용자 룰 (확정):
  - SKU       : 'SKU-' + 영숫자 대문자 8자 (한글 X). 비었으면 자동.
  - 바코드     : EAN-13 (200 prefix + 9자리 + 체크섬). 비었으면 자동.
  - 품번       : 영숫자+하이픈+언더스코어만 (한글 X / SKU 형식 X). 빈 값 = '-'.

이 모듈을 import 하지 않고 자체 헬퍼를 다시 만들지 말 것.
"""
from __future__ import annotations

import re
import secrets
import string


# ============ SKU ============

SKU_RE = re.compile(r'^SKU-[A-Z0-9]{8}$')


def is_valid_sku(s: str | None) -> bool:
    """SKU-XXX 형식 검증."""
    if not s:
        return False
    return bool(SKU_RE.match(s))


def gen_sku(existing: set[str] | None = None) -> str:
    """SKU-XXX 자동 생성. existing 받으면 중복 회피."""
    pool = existing if existing is not None else set()
    while True:
        suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits)
                         for _ in range(8))
        sku = f'SKU-{suffix}'
        if sku not in pool:
            pool.add(sku)
            return sku


# ============ 바코드 (EAN-13) ============

def gen_barcode() -> str:
    """EAN-13 자동 생성. 200 prefix (내부용) + 9자리 + 체크섬."""
    digits = '200' + ''.join(secrets.choice(string.digits) for _ in range(9))
    chk = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits))
    return digits + str((10 - chk % 10) % 10)


def is_valid_barcode(s: str | None) -> bool:
    """EAN-13 형식 + 체크섬 검증."""
    if not s or len(s) != 13 or not s.isdigit():
        return False
    body, chk = s[:12], int(s[12])
    expect = (10 - sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body)) % 10) % 10
    return chk == expect


# ============ 품번 ============

ARTICLE_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def is_valid_article_no(s: str | None) -> bool:
    """영숫자+하이픈+언더스코어. 한글·SKU 형식 X."""
    if not s:
        return False
    if not ARTICLE_RE.match(s):
        return False
    if s.startswith('SKU-'):
        return False
    return True


def clean_article_no(s: str | None) -> str:
    """입력값 → 유효 품번 또는 '-' (사용자 룰 fallback)."""
    if not s:
        return '-'
    s = s.strip()
    if not s or not is_valid_article_no(s):
        return '-'
    return s[:64]


# ============ 한글 검사 (보조) ============

def has_korean(s: str | None) -> bool:
    """문자열에 한글 (가-힣) 포함 여부."""
    if not s:
        return False
    return any('가' <= ch <= '힣' for ch in s)
