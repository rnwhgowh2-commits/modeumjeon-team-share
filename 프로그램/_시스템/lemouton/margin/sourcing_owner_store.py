# -*- coding: utf-8 -*-
"""소싱처 계정 담당자(owner) 라벨 저장소 — 작은 사이드 테이블 헬퍼.

마진 계산기 소싱처 계정 관리 탭의 '담당자' 입력을 (source, account_key)→owner
로 영속한다. 자격증명(SourcingCredential)·운영센터 라벨(SourcingAccount.
display_name)을 건드리지 않도록 별도 테이블(SourcingAccountOwner)에 담는다.
owner 는 비밀이 아닌 라벨 → 평문 컬럼. 세션은 호출 시점에 `shared.db.SessionLocal`
을 읽어 열므로(테스트 monkeypatch 호환) DbSourcingCredentialsStore 와 동일 패턴.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def load_all() -> dict:
    """전체 owner 맵 반환 — {source: {account_key: owner}}."""
    from shared.db import SessionLocal
    from lemouton.margin.models import SourcingAccountOwner
    out: dict = {}
    s = SessionLocal()
    try:
        for r in s.query(SourcingAccountOwner).all():
            out.setdefault(r.source, {})[r.account_key] = r.owner or ""
    finally:
        s.close()
    return out


def get_owner(source: str, account_key: str) -> str:
    """단일 owner 라벨 — 없으면 빈 문자열."""
    from shared.db import SessionLocal
    from lemouton.margin.models import SourcingAccountOwner
    s = SessionLocal()
    try:
        row = (s.query(SourcingAccountOwner)
               .filter_by(source=source, account_key=account_key).one_or_none())
        return (row.owner or "") if row else ""
    finally:
        s.close()


def set_owner(source: str, account_key: str, owner: str) -> None:
    """owner 라벨 저장/갱신. 빈 값이면 행을 제거(빈 행 축적 방지)."""
    owner = (owner or "").strip()
    if not owner:
        remove_owner(source, account_key)
        return
    from shared.db import SessionLocal
    from lemouton.margin.models import SourcingAccountOwner
    s = SessionLocal()
    try:
        row = (s.query(SourcingAccountOwner)
               .filter_by(source=source, account_key=account_key).one_or_none())
        if row is None:
            s.add(SourcingAccountOwner(source=source, account_key=account_key, owner=owner))
        else:
            row.owner = owner
        s.commit()
    finally:
        s.close()


def remove_owner(source: str, account_key: str) -> bool:
    """owner 행 삭제 — 있었으면 True."""
    from shared.db import SessionLocal
    from lemouton.margin.models import SourcingAccountOwner
    s = SessionLocal()
    try:
        row = (s.query(SourcingAccountOwner)
               .filter_by(source=source, account_key=account_key).one_or_none())
        if row is None:
            return False
        s.delete(row)
        s.commit()
        return True
    finally:
        s.close()
