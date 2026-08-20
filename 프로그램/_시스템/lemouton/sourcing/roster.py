# -*- coding: utf-8 -*-
"""소싱처 단일 명부 서비스 — SourcingSource 기준 (빌트인+커스텀).

spec: docs/superpowers/specs/2026-06-30-소싱처-단일명부-통합-design.md
- source_key = 고정 정체(크롤이 씀, 불변) / label = 수정 가능한 껍데기 / favicon_url = URL 자동
- 빌트인은 삭제 불가(숨김만). 커스텀 삭제는 참조(BundleSourceUrl) 0 일 때만.
- 가이드 문서(crawl_guide JSON)는 source_key 에 1:1 부착.
"""
from __future__ import annotations

from shared.db import SessionLocal
from lemouton.sourcing.models import SourcingSource, BundleSourceUrl
from lemouton.sourcing import source_registry as sr
import lemouton.sourcing.crawl_guide as cg


def seed_if_needed() -> None:
    sr.seed_builtins()


def list_roster() -> list:
    """전 소싱처 명부(빌트인+커스텀, 비활성 제외 X — 사전은 숨김도 보여줘야)."""
    seed_if_needed()
    return sr.get_all_sources()


def get(key: str) -> dict | None:
    for x in sr.get_all_sources():
        if x.get("key") == key:
            return x
    return None


def list_all() -> list:
    """사전 관리용 — 숨김(is_active=False) 포함 전 명부 행. 빌트인 seed 후 직접 조회."""
    seed_if_needed()
    s = SessionLocal()
    try:
        rows = (s.query(SourcingSource)
                  .order_by(SourcingSource.is_builtin.desc(),
                            SourcingSource.sort_order, SourcingSource.id)
                  .all())
        return [{
            "key": r.source_key, "label": r.label, "domain": r.domain or "",
            "favicon_url": r.favicon_url or "", "logo_color": r.logo_color or "",
            "logo_letter": r.logo_letter or "", "is_builtin": bool(r.is_builtin),
            "is_active": bool(r.is_active), "has_adapter": bool(r.has_adapter),
        } for r in rows]
    finally:
        s.close()


def usage_by_key() -> dict:
    """source_key → BundleSourceUrl 참조 수(삭제 가드·표시용)."""
    from sqlalchemy import func
    s = SessionLocal()
    try:
        rows = (s.query(BundleSourceUrl.source_key, func.count(BundleSourceUrl.id))
                  .group_by(BundleSourceUrl.source_key).all())
        return {k: c for k, c in rows}
    finally:
        s.close()


def _row(s, key: str):
    return s.query(SourcingSource).filter_by(source_key=key).first()


def rename(key: str, label: str) -> None:
    """이름(껍데기) 수정 — source_key 는 불변."""
    label = (label or "").strip()
    if not label:
        raise ValueError("이름을 입력하세요.")
    s = SessionLocal()
    try:
        r = _row(s, key)
        if not r:
            raise ValueError("소싱처를 찾을 수 없어요.")
        r.label = label[:80]
        s.commit()
    finally:
        s.close()


def set_logo(key: str, favicon_url=None, logo_color=None, domain=None) -> None:
    s = SessionLocal()
    try:
        r = _row(s, key)
        if not r:
            raise ValueError("소싱처를 찾을 수 없어요.")
        if favicon_url is not None:
            r.favicon_url = (favicon_url or None)
        if logo_color:
            r.logo_color = logo_color
        if domain:
            r.domain = domain
        s.commit()
    finally:
        s.close()


def set_active(key: str, active: bool) -> None:
    s = SessionLocal()
    try:
        r = _row(s, key)
        if not r:
            raise ValueError("소싱처를 찾을 수 없어요.")
        r.is_active = bool(active)
        s.commit()
    finally:
        s.close()


def add(source_key: str, label: str, domain: str, favicon_url=None,
        logo_color=None, logo_letter=None, needs_login=False) -> None:
    source_key = (source_key or "").strip().lower()
    if not source_key:
        raise ValueError("source_key 가 필요해요.")
    s = SessionLocal()
    try:
        if _row(s, source_key):
            raise ValueError(f"'{source_key}' 는 이미 있는 소싱처예요.")
        s.add(SourcingSource(
            source_key=source_key, label=(label or source_key)[:80],
            domain=domain or (source_key + ".com"),
            favicon_url=favicon_url, logo_color=logo_color, logo_letter=logo_letter,
            needs_login=bool(needs_login), has_adapter=False,
            is_active=True, is_builtin=False, sort_order=100,
        ))
        s.commit()
    finally:
        s.close()


def delete(key: str) -> None:
    """커스텀 + 참조 0 일 때만 삭제. 빌트인은 차단(숨김 set_active(False) 사용)."""
    s = SessionLocal()
    try:
        r = _row(s, key)
        if not r:
            raise ValueError("소싱처를 찾을 수 없어요.")
        if r.is_builtin:
            raise ValueError("빌트인 소싱처는 삭제할 수 없어요(숨김만 가능).")
        used = s.query(BundleSourceUrl).filter_by(source_key=key).count()
        if used:
            raise ValueError(f"사용중({used}건) — 삭제 불가. 먼저 URL 매핑을 정리하세요.")
        s.delete(r)
        s.commit()
    finally:
        s.close()


def migrate_guides_from_registry() -> int:
    """[멱등] 기존 SourceRegistry.crawl_guide → SourcingSource.crawl_guide.

    매칭: main_url 도메인 → source_key(catalog), 실패 시 이름(label==name). target 이
    비어있을 때만 복사(이미 있으면 skip) → 사용자 수정분·재실행 안전. 원본 보존.
    Returns: 복사한 건수.
    """
    seed_if_needed()
    try:
        from lemouton.sourcing.models_pricing import SourceRegistry
    except Exception:
        return 0
    copied = 0
    s = SessionLocal()
    try:
        srcs = {r.source_key: r for r in s.query(SourcingSource).all()}
        label_to_key = {(r.label or "").strip(): k for k, r in srcs.items() if r.label}
        for reg in s.query(SourceRegistry).all():
            if not reg.crawl_guide:
                continue
            key = None
            c = sr.catalog_by_domain(reg.main_url or "")
            if c:
                key = c["key"]
            if not key and reg.name:
                key = label_to_key.get(reg.name.strip())
            if not key:
                continue
            tgt = srcs.get(key)
            if not tgt or tgt.crawl_guide:          # 멱등: target 이미 있으면 skip
                continue
            tgt.crawl_guide = reg.crawl_guide        # 원본 문자열 그대로(검증은 read 시)
            copied += 1
        s.commit()
    except Exception:
        try:
            s.rollback()
        except Exception:
            pass
    finally:
        s.close()
    return copied


def get_guide(key: str) -> dict:
    s = SessionLocal()
    try:
        r = _row(s, key)
        return cg.loads(r.crawl_guide if r else None)
    finally:
        s.close()


def set_guide(key: str, guide: dict) -> None:
    s = SessionLocal()
    try:
        r = _row(s, key)
        if not r:
            raise ValueError("소싱처를 찾을 수 없어요.")
        r.crawl_guide = cg.dumps(guide)
        s.commit()
    finally:
        s.close()
