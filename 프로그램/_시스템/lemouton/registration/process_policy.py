# -*- coding: utf-8 -*-
"""가공정책 — 여러 소싱처 URL 을 묶어 여러 마켓으로 내보내는 규칙 묶음.

설계서: 2026-07-17-신규상품등록-가공템플릿-design.md §7 / 시안 13 Ⅲ-E안
사장님 확정 (2026-07-19):
  "세트 → 가공정책(URL별). 가공정책 기준은 URL.
   여러 소싱처의 URL 을 넣을 수 있고, 여러 판매처 마켓에 올릴 수 있음."

    소싱처 URL 여럿  ──▶  가공정책 하나  ──▶  판매처 마켓 여럿
    (musinsa>나이키          13항목 규칙         스마트스토어·쿠팡
     ssg>나이키 …)                              ·11번가 …)

━━ 🔴 한 구성은 한 정책에만 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  한 구성(소싱처 × 브랜드)이 두 정책에 속하면 「이 URL 은 어느 규칙을 따르나」가
  모호해지고, 가공 결과가 실행 순서에 따라 달라진다.
  조용히 덮어쓰지 않고 :class:`PolicyConflict` 로 막는다.
  (프로젝트 최상위 원칙 — 중복·모순 금지)

━━ 정책 없는 URL 을 찾아낸다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  :func:`unassigned_sources` — 크롤은 되는데 **어디에도 안 올라가는** 구성.
  정책 중심 화면에서는 이 누락이 안 보인다. 그래서 URL 을 주인공으로 놓는다(E안).

Alembic 없음 — 신규 테이블이라 create_all 이 만든다(컬럼 추가만 migrations 리스트 필요).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from shared.db import Base

# 13항목 (시안 13 · 설계서 §7). 키를 바꾸면 저장된 규칙이 안 읽히므로 신중히.
ITEM_KEYS = (
    "name",          # 상품명
    "category",      # 카테고리
    "price",         # 판매가
    "options",       # 옵션
    "images",        # 이미지
    "detail",        # 상세설명
    "shipping",      # 배송
    "notice",        # 고시정보
    "brand",         # 브랜드
    "origin",        # 원산지
    "kc",            # KC인증
    "banned_words",  # 금지어
    "tags",          # 태그
)

ITEM_LABELS = {
    "name": "상품명", "category": "카테고리", "price": "판매가", "options": "옵션",
    "images": "이미지", "detail": "상세설명", "shipping": "배송", "notice": "고시정보",
    "brand": "브랜드", "origin": "원산지", "kc": "KC인증",
    "banned_words": "금지어", "tags": "태그",
}


class PolicyConflict(Exception):
    """한 구성을 두 정책에 붙이려 할 때. 어느 정책과 부딪히는지 메시지에 담는다."""


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ProcessPolicy(Base):
    """가공정책 1건."""

    __tablename__ = "process_policies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)
    description = Column(Text)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)

    sources = relationship("ProcessPolicySource", back_populates="policy",
                           cascade="all, delete-orphan", lazy="selectin")
    markets = relationship("ProcessPolicyMarket", back_populates="policy",
                           cascade="all, delete-orphan", lazy="selectin")
    rules = relationship("ProcessRule", back_populates="policy",
                         cascade="all, delete-orphan", lazy="selectin")


class ProcessPolicySource(Base):
    """정책 ← 소싱처 구성(소싱처 × 브랜드 = 하나의 URL 구성).

    ★ (source_key, brand) 에 UNIQUE — **테이블 전체에서 유일**하다.
      정책 안에서가 아니라 전체에서 유일해야 '한 구성은 한 정책' 이 지켜진다.
    """

    __tablename__ = "process_policy_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey("process_policies.id"), nullable=False, index=True)
    source_key = Column(String(64), nullable=False)
    brand = Column(String(128), nullable=False)
    url = Column(Text)                       # 목록 URL (대량등록 크롤 진입점)

    policy = relationship("ProcessPolicy", back_populates="sources")

    __table_args__ = (
        UniqueConstraint("source_key", "brand", name="uq_policy_source_once"),
    )


class ProcessPolicyMarket(Base):
    """정책 → 판매처 마켓 (다계정이라 계정까지 봐야 한다)."""

    __tablename__ = "process_policy_markets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey("process_policies.id"), nullable=False, index=True)
    market = Column(String(32), nullable=False)
    account_key = Column(String(64), nullable=False, default="")

    policy = relationship("ProcessPolicy", back_populates="markets")

    __table_args__ = (
        UniqueConstraint("policy_id", "market", "account_key", name="uq_policy_market"),
    )


class ProcessRule(Base):
    """정책 × **마켓** × 항목 하나의 규칙. 설정은 JSON 문자열로 보관.

    ★ 마켓 축이 있다 (2026-07-19 사장님 확정 1-2 = 「마켓마다 다른 규칙」).
      설계서 §7-12 「세트 단위 = 소싱처 × 마켓 조합마다」, 시안의 적용 대상
      「무신사 → 스마트스토어 / 무신사 → 쿠팡」과 같은 구조다.

          market = ''        모든 마켓 공통 기본값
          market = 'coupang' 쿠팡에서만 이걸로 덮어씀

      같은 항목에 둘 다 있으면 **마켓별이 이긴다**(:func:`rules_for`).
      「스스는 상품명 100자, 쿠팡은 50자」가 이 구조로 표현된다.
    """

    __tablename__ = "process_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey("process_policies.id"), nullable=False, index=True)
    market = Column(String(32), nullable=False, default="")   # '' = 모든 마켓 공통
    item_key = Column(String(32), nullable=False)
    config_json = Column(Text, nullable=False, default="{}")

    policy = relationship("ProcessPolicy", back_populates="rules")

    __table_args__ = (
        UniqueConstraint("policy_id", "market", "item_key", name="uq_policy_rule_item"),
    )

    @property
    def config(self) -> dict:
        try:
            return json.loads(self.config_json or "{}")
        except (ValueError, TypeError):
            return {}


# ── 서비스 ──────────────────────────────────────────────────────

def _norm(v) -> str:
    return (v or "").strip()


def create_policy(session, *, name: str, description: str = "") -> ProcessPolicy:
    """정책을 만든다. 호출자가 commit."""
    nm = _norm(name)
    if not nm:
        raise ValueError("정책 이름이 비었습니다.")
    dup = (session.query(ProcessPolicy)
           .filter(ProcessPolicy.name == nm,
                   ProcessPolicy.deleted_at.is_(None)).first())
    if dup:
        raise ValueError(f"같은 이름의 정책이 이미 있습니다: {nm}")
    p = ProcessPolicy(name=nm, description=_norm(description))
    session.add(p)
    session.flush()
    return p


def policy_for_source(session, *, source_key: str, brand: str):
    """이 구성이 붙어 있는 정책. 없으면 None."""
    row = (session.query(ProcessPolicySource)
           .filter(ProcessPolicySource.source_key == _norm(source_key),
                   ProcessPolicySource.brand == _norm(brand)).first())
    return row.policy if row else None


def attach_source(session, *, policy_id: int, source_key: str, brand: str, url: str = ""):
    """정책에 소싱처 구성을 붙인다.

    - 같은 정책에 이미 붙어 있으면 **조용히 넘어간다**(멱등 — 중복이 아니라 '이미 됨').
    - 다른 정책에 붙어 있으면 :class:`PolicyConflict`. 조용히 옮기지 않는다.
    """
    sk, br = _norm(source_key), _norm(brand)
    existing = (session.query(ProcessPolicySource)
                .filter(ProcessPolicySource.source_key == sk,
                        ProcessPolicySource.brand == br).first())
    if existing:
        if existing.policy_id == policy_id:
            if url:
                existing.url = url
            return existing
        raise PolicyConflict(
            f"「{sk} > {br}」 은(는) 이미 정책 「{existing.policy.name}」 에 붙어 있습니다. "
            f"먼저 떼어낸 뒤 다시 붙여주세요 — 한 구성이 두 정책을 따르면 "
            f"가공 결과가 실행 순서에 따라 달라집니다.")
    row = ProcessPolicySource(policy_id=policy_id, source_key=sk, brand=br, url=url or None)
    session.add(row)
    session.flush()
    return row


def detach_source(session, *, source_key: str, brand: str) -> bool:
    """구성을 정책에서 뗀다. 붙어 있지 않았으면 False."""
    row = (session.query(ProcessPolicySource)
           .filter(ProcessPolicySource.source_key == _norm(source_key),
                   ProcessPolicySource.brand == _norm(brand)).first())
    if not row:
        return False
    session.delete(row)
    session.flush()
    return True


def attach_market(session, *, policy_id: int, market: str, account_key: str = ""):
    """정책에 판매처 마켓을 붙인다(멱등)."""
    mk, ak = _norm(market), _norm(account_key)
    existing = (session.query(ProcessPolicyMarket)
                .filter(ProcessPolicyMarket.policy_id == policy_id,
                        ProcessPolicyMarket.market == mk,
                        ProcessPolicyMarket.account_key == ak).first())
    if existing:
        return existing
    row = ProcessPolicyMarket(policy_id=policy_id, market=mk, account_key=ak)
    session.add(row)
    session.flush()
    return row


def set_rule(session, *, policy_id: int, item_key: str, config: dict, market: str = ""):
    """항목 규칙을 저장(있으면 덮어씀).

    Args:
        market: '' 이면 **모든 마켓 공통 기본값**, 값이 있으면 그 마켓 전용.

    모르는 항목 키는 거부한다 — 오타로 만든 규칙이 조용히 저장되면
    「왜 안 먹지」로 한참 헤맨다.
    """
    key = _norm(item_key)
    if key not in ITEM_KEYS:
        raise ValueError(
            f"모르는 항목입니다: {item_key!r} — 쓸 수 있는 항목: {', '.join(ITEM_KEYS)}")
    # 항목마다 담을 수 있는 칸이 정해져 있다(설계서 §7). 모양을 여기서 검사한다 —
    # 오타로 만든 설정이 조용히 저장되면 「왜 안 먹지」로 한참 헤맨다.
    from lemouton.registration.process_rule_schema import validate_config
    config = validate_config(key, config)
    mk = _norm(market)
    row = (session.query(ProcessRule)
           .filter(ProcessRule.policy_id == policy_id,
                   ProcessRule.market == mk,
                   ProcessRule.item_key == key).first())
    payload = json.dumps(config or {}, ensure_ascii=False)
    if row:
        row.config_json = payload
    else:
        row = ProcessRule(policy_id=policy_id, market=mk, item_key=key,
                          config_json=payload)
        session.add(row)
    session.flush()
    return row


def rules_for(session, *, policy_id: int, market: str = "") -> dict:
    """그 마켓에 실제로 적용될 규칙 한 벌. `{item_key: config}`.

    ★ 공통(market='')을 깔고 **마켓별이 덮어쓴다.**
      「스스는 상품명 100자, 쿠팡은 50자」가 이렇게 표현된다.
      항목 단위로 덮어쓰므로, 마켓별로 한 항목만 달라도 나머지는 공통을 쓴다.
    """
    mk = _norm(market)
    rows = (session.query(ProcessRule)
            .filter(ProcessRule.policy_id == policy_id).all())
    out = {r.item_key: r.config for r in rows if (r.market or "") == ""}
    if mk:
        for r in rows:
            if (r.market or "") == mk:
                out[r.item_key] = r.config
    return out


def policy_brands_for_source(session, *, source_key) -> list:
    """그 소싱처에 **가공정책이 붙어 있는 브랜드들**. 없으면 [].

    브랜드가 빈 초안이 「보류」인지 「애초에 정책이 없음」인지 가르는 근거다
    (:func:`lemouton.registration.process_apply.needs_brand_for_rules`).
    """
    sk = _norm(source_key)
    if not sk:
        return []
    rows = (session.query(ProcessPolicySource.brand)
            .filter(ProcessPolicySource.source_key == sk).all())
    return sorted({str(r[0] or '').strip() for r in rows if str(r[0] or '').strip()})


def resolve_rules_for_draft(session, draft, market: str = ''):
    """드래프트 1건에 **실제로 적용될** 가공 규칙 한 벌 + 못 찾은 사유.

    ★ 규칙을 읽어 오는 자리는 여기 하나다. 사전 점검(preflight)·실제 등록(register)·
      초안 생성(from-url)이 전부 이 함수를 쓴다 — 세 화면이 서로 다른 규칙을 읽으면
      그게 곧 모순이다(preflight_rows docstring 의 규율과 같은 뜻).

    Returns:
        (rules, notes) — rules = `{item_key: config}` (없으면 {}),
        notes = process_apply 형식의 skipped 항목들(왜 규칙을 못 찾았는지).
    """
    from lemouton.registration import process_apply as PA

    source_key = _norm(getattr(draft, 'source_site', ''))
    brand = _norm(getattr(draft, 'brand', ''))

    if not source_key:
        # 수기 드래프트 — 가공정책은 「소싱처 × 브랜드」 기준이라 붙을 자리가 없다.
        # 규칙이 없는 게 정상이므로 사유를 만들지 않는다(거짓 경고 금지).
        return ({}, [])

    policy_brands = policy_brands_for_source(session, source_key=source_key)

    # 🔴 브랜드 미확정 — 크롤 초안은 브랜드가 구조적으로 자주 빈다.
    #   「모름」을 「통과」로 읽지 않는다. 사장님이 브랜드를 넣으면 자동으로 풀린다.
    hold = PA.needs_brand_for_rules(brand, policy_brands)
    if hold:
        return ({}, [{'item': 'name', 'field': 'brand',
                      'label': '가공 규칙', 'code': 'NO_BRAND_FOR_RULES',
                      'reason': hold, 'blocking': True}])

    policy = policy_for_source(session, source_key=source_key, brand=brand)
    if policy is None or policy.deleted_at is not None:
        return ({}, [{'item': 'name', 'field': '', 'label': '가공 규칙',
                      'code': 'NO_POLICY',
                      'reason': f'「{source_key} > {brand or "(브랜드 없음)"}」 에 붙은 '
                                f'가공정책이 없습니다 — 데이터가공 탭에서 정책에 붙여 '
                                f'주세요. 지금은 크롤 값이 그대로 갑니다.',
                      'blocking': False}])

    rules = rules_for(session, policy_id=policy.id, market=market)
    if not rules:
        return ({}, [{'item': 'name', 'field': '', 'label': '가공 규칙',
                      'code': 'NO_RULES',
                      'reason': f'정책 「{policy.name}」 에 저장된 규칙이 하나도 '
                                f'없습니다 — 정책 상세에서 항목을 저장해 주세요.',
                      'blocking': False}])
    return (rules, [])


def unassigned_sources(session, crawled_sources) -> list:
    """크롤은 되는데 **어느 정책에도 안 붙은** 구성 목록.

    Args:
        crawled_sources: (source_key, brand) 튜플 목록 — 지금 크롤 중인 구성들.

    시안 13 Ⅲ-E안의 존재 이유. 이게 없으면 「H몰 > 아식스는 크롤은 되는데
    어디에도 안 올라간다」 같은 누락을 아무도 모른다.
    """
    if not crawled_sources:
        return []
    assigned = {(r.source_key, r.brand)
                for r in session.query(ProcessPolicySource).all()}
    out = []
    for sk, br in crawled_sources:
        if (_norm(sk), _norm(br)) not in assigned:
            out.append((sk, br))
    return out
