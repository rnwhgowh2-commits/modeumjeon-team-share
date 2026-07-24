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


def move_source(session, *, policy_id: int, source_key: str, brand: str, url: str = ""):
    """구성을 **이 정책으로 옮긴다** — 다른 정책에 붙어 있어도 옮긴다.

    :func:`attach_source` 는 다른 정책에 붙어 있으면 막는다(조용한 덮어쓰기 금지).
    사장님이 「옮기겠다」고 확인한 뒤에만 이 함수를 부른다.

    Returns:
        (구성 행, 이전 정책 이름 or None) — 이전 이름을 돌려주는 게 이 함수의 핵심이다.
        화면이 「정책 「A」 에서 「B」 로 옮겼습니다」라고 말할 수 있어야
        **모르는 사이에 옮겨지는 일**이 없다.
    """
    sk, br = _norm(source_key), _norm(brand)
    existing = (session.query(ProcessPolicySource)
                .filter(ProcessPolicySource.source_key == sk,
                        ProcessPolicySource.brand == br).first())
    came_from = None
    if existing:
        if existing.policy_id == policy_id:
            # 이미 이 정책 — 옮긴 게 아니다(「옮겼습니다」라고 거짓 안내하면 안 된다).
            if url:
                existing.url = url
            return existing, None
        came_from = existing.policy.name if existing.policy else None
        if not url:
            url = existing.url or ""       # 사장님이 넣어둔 URL 을 잃지 않는다
        session.delete(existing)
        session.flush()                    # UNIQUE 에 걸리지 않게 먼저 지운다
    row = ProcessPolicySource(policy_id=policy_id, source_key=sk, brand=br,
                              url=url or None)
    session.add(row)
    session.flush()
    return row, came_from


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


def detach_market(session, *, policy_id: int, market: str, account_key: str = "") -> bool:
    """정책에서 마켓을 뗀다. 붙어 있지 않았으면 False.

    ★ 계정까지 같아야 뗀다 — 다계정이라 「쿠팡 본계정」과 「쿠팡 부계정」은 다른 줄이다.
      아무거나 지우면 사장님이 안 지운 계정이 사라진다.
    """
    row = (session.query(ProcessPolicyMarket)
           .filter(ProcessPolicyMarket.policy_id == policy_id,
                   ProcessPolicyMarket.market == _norm(market),
                   ProcessPolicyMarket.account_key == _norm(account_key)).first())
    if not row:
        return False
    session.delete(row)
    session.flush()
    return True


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


def _live_sources_for(session, source_key):
    """그 소싱처에 붙은 구성 행들 — **살아 있는 정책**의 것만.

    ★ [2026-07-23 리뷰 S4] `deleted_at` 을 안 보면, 정책을 소프트 삭제한 뒤에도 구성
      행이 남아 「브랜드가 비면 보류」가 영영 안 풀린다(적용할 규칙은 이미 없는데).
    """
    sk = _norm(source_key)
    if not sk:
        return []
    return (session.query(ProcessPolicySource)
            .join(ProcessPolicy, ProcessPolicySource.policy_id == ProcessPolicy.id)
            .filter(ProcessPolicySource.source_key == sk)
            .filter(ProcessPolicy.deleted_at.is_(None)).all())


def policy_brands_for_source(session, *, source_key) -> list:
    """그 소싱처에 **가공정책이 붙어 있는 브랜드들**. 없으면 [].

    브랜드가 빈 초안이 「보류」인지 「애초에 정책이 없음」인지 가르는 근거다
    (:func:`lemouton.registration.process_apply.needs_brand_for_rules`).
    """
    return sorted({str(r.brand or '').strip()
                   for r in _live_sources_for(session, source_key)
                   if str(r.brand or '').strip()})


def collect_banned_for_source(session, *, source_key) -> list:
    """그 소싱처에 붙은 **모든 정책**의 수집 금지어 합집합 (브랜드·마켓 무관).

    ★ [2026-07-23 리뷰 I5] 수집 금지어는 「이 단어가 있으면 **아예 안 가져옵니다**」
      (설계서 §7-1)라 브랜드를 고르기 전에 이미 결론이 난다. 브랜드로 정책을 고른
      뒤에 읽으면, 브랜드가 빈 크롤 초안(대부분이 그렇다)에서 게이트가 통째로 꺼져
      「짝퉁 스니커즈」가 그대로 초안이 됐다 — 실측된 사고다.
      그래서 **소싱처 단위**로, 마켓 축과도 무관하게(공통·마켓별 규칙 전부) 모은다.

    ⚠️ [2026-07-24 2차 리뷰 I-6] 합집합이라 **과차단**이 가능하다: 소싱처에
      정책A(나이키, 금지어 '리셀')·정책B(아디다스, 금지어 없음)가 붙어 있으면
      아디다스 상품도 '리셀' 로 막힌다. 브랜드가 확정된 뒤에도 합집합을 쓸 것인지는
      **사장님 판단**이라 `docs/사장님_판단대기.md` 에 올려 두었다. 그때까지는
      안전한 쪽(fail-closed)을 유지하되, **어느 정책의 금지어인지**를 사유에 실어
      사장님이 어디 가서 지워야 하는지 알 수 있게 한다.

    Returns:
        [(단어, 정책이름)] — 단어는 문자열이 아닐 수도 있다(읽을 수 없는 항목도
        버리지 않고 넘긴다. process_apply 가 「읽을 수 없다」고 막는다 — 조용히
        버리면 걸러야 할 단어를 놓친 채 통과한다).
    """
    rows = _live_sources_for(session, source_key)
    if not rows:
        return []
    policy_ids = {r.policy_id for r in rows}
    names = {p.id: p.name for p in
             session.query(ProcessPolicy)
             .filter(ProcessPolicy.id.in_(policy_ids)).all()}
    out, seen = [], set()
    for rule in (session.query(ProcessRule)
                 .filter(ProcessRule.policy_id.in_(policy_ids))
                 .filter(ProcessRule.item_key == 'banned_words').all()):
        for w in (rule.config.get('collect_banned') or []):
            key = (repr(w), rule.policy_id)
            if key in seen:
                continue
            seen.add(key)
            out.append((w, names.get(rule.policy_id, '')))
    return out


def source_gate(session, source_key):
    """소싱처 단위로 **한 번만** 읽으면 되는 것 — 수집 금지어 + 정책 붙은 브랜드들.

    ★ [2026-07-24 2차 리뷰 I-7] 둘 다 **마켓과 무관**한데, 사전 점검이 마켓 루프
      안에서 `resolve_rules_for_draft` 를 6번 부르며 6번씩 다시 읽었다.
      초안 생성(from-url)은 URL 50건 × 6마켓이라 요청 하나에 1,000쿼리 넘게
      원격 Supabase 로 나간다(이 저장소에 Cloudflare 100초 상한 이력이 있다).
      호출자가 드래프트당 한 번 만들어 `resolve_rules_for_draft(gate=...)` 로 넘긴다.

    Returns: {'collect_words': [...], 'policy_brands': [...]}
    """
    sk = _norm(source_key)
    if not sk:
        return {'collect_words': [], 'policy_brands': []}
    return {'collect_words': collect_banned_for_source(session, source_key=sk),
            'policy_brands': policy_brands_for_source(session, source_key=sk)}


def resolve_rules_for_draft(session, draft, market: str = '', *, gate=None):
    """드래프트 1건에 **실제로 적용될** 가공 규칙 한 벌 + 못 찾은 사유.

    ★ 규칙을 읽어 오는 자리는 여기 하나다. 사전 점검(preflight)·실제 등록(register)·
      초안 생성(from-url)이 전부 이 함수를 쓴다 — 세 화면이 서로 다른 규칙을 읽으면
      그게 곧 모순이다(preflight_rows docstring 의 규율과 같은 뜻).

    Args:
        gate: :func:`source_gate` 결과. 마켓 루프에서 되풀이 조회를 피하려고 미리
            만들어 넘긴다(리뷰 I-7). 안 주면 여기서 만든다 — 답은 같다.

    Returns:
        (rules, notes, collect_words)
          rules        : `{item_key: config}` (없으면 {})
          notes        : process_apply 형식의 skipped 항목들(왜 규칙을 못 찾았는지)
          collect_words: 수집 금지어 — **브랜드·마켓과 무관한 소싱처 단위 게이트**라
                         rules 가 {} 여도(브랜드 미확정 등) 항상 채워 돌려준다
                         (리뷰 I5). 호출자가 apply_rules 에 그대로 주입한다.
    """
    from lemouton.registration import process_apply as PA

    source_key = _norm(getattr(draft, 'source_site', ''))
    brand = _norm(getattr(draft, 'brand', ''))

    if not source_key:
        # 수기 드래프트 — 가공정책은 「소싱처 × 브랜드」 기준이라 붙을 자리가 없다.
        # 규칙이 없는 게 정상이므로 사유를 만들지 않는다(거짓 경고 금지).
        return ({}, [], [])

    if gate is None:
        gate = source_gate(session, source_key)
    collect_words = gate['collect_words']
    policy_brands = gate['policy_brands']

    # 🔴 브랜드 미확정 — 크롤 초안은 브랜드가 구조적으로 자주 빈다.
    #   「모름」을 「통과」로 읽지 않는다. 사장님이 브랜드를 넣으면 자동으로 풀린다.
    #   ★ 그래도 수집 금지어는 같이 돌려준다 — 소싱처 단위 게이트라 브랜드와 무관하다.
    hold = PA.needs_brand_for_rules(brand, policy_brands)
    if hold:
        return ({}, [{'item': 'name', 'field': 'brand',
                      'label': '가공 규칙', 'code': 'NO_BRAND_FOR_RULES',
                      'reason': hold, 'blocking': True}], collect_words)

    policy = policy_for_source(session, source_key=source_key, brand=brand)
    if policy is None or policy.deleted_at is not None:
        return ({}, [{'item': 'name', 'field': '', 'label': '가공 규칙',
                      'code': 'NO_POLICY',
                      'reason': f'「{source_key} > {brand or "(브랜드 없음)"}」 에 붙은 '
                                f'가공정책이 없습니다 — 데이터가공 탭에서 정책에 붙여 '
                                f'주세요. 지금은 크롤 값이 그대로 갑니다.',
                      'blocking': False}], collect_words)

    rules = rules_for(session, policy_id=policy.id, market=market)
    if not rules:
        return ({}, [{'item': 'name', 'field': '', 'label': '가공 규칙',
                      'code': 'NO_RULES',
                      'reason': f'정책 「{policy.name}」 에 저장된 규칙이 하나도 '
                                f'없습니다 — 정책 상세에서 항목을 저장해 주세요.',
                      'blocking': False}], collect_words)
    return (rules, [], collect_words)


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
