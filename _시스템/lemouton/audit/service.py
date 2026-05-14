"""[v2] 감사 로그 + Soft-delete + Dry-run service.

핵심:
  - record(): 변경 사건 기록
  - history(): 특정 행의 변경 이력 조회
  - soft_delete(), restore(): 휴지통 + 복구
  - preview_change(): 변경 영향 미리보기 (Dry-run)

설계 문서: docs/architecture_v2.md §3.3
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .models import AuditLog


def _utcnow():
    return datetime.now(timezone.utc)


def _default_actor() -> str:
    """팀공유 모드면 로그인 사용자 이메일, 아니면 'system'.

    Day 3 RBAC — 기존 audit_log 가 이미 actor 필드 지원하므로,
    이 헬퍼만 추가하면 변경 이력에 자동으로 사용자 이메일 기록됨.
    기존 모드 (ENVIRONMENT 미설정) 는 항상 'system'.
    """
    try:
        import os
        if os.environ.get("ENVIRONMENT") != "team-share-dev":
            return "system"
        # team-share 모드 — Flask-Login current_user
        from flask import has_request_context
        if not has_request_context():
            return "system"  # CLI·스케줄러·이벤트 hook 컨텍스트
        from flask_login import current_user
        if current_user and current_user.is_authenticated:
            return getattr(current_user, "email", None) or "system"
    except Exception:
        pass
    return "system"


def _safe_json(obj: dict | None) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# 변경 기록
# ─────────────────────────────────────────────────────────────────────────────

def record(
    session: Session,
    *,
    target_table: str,
    target_id: str | int,
    action: str,
    actor: str | None = None,   # None → _default_actor() 자동 (팀공유 모드면 user email)
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> AuditLog:
    """변경 사건 1건 기록.

    action: 'create' | 'update' | 'delete' | 'restore'
    before/after: 변경 전·후 상태 (관련 컬럼만 — 전체 dump 권장 X)
    actor: None 이면 _default_actor() — 팀공유 모드 시 자동 user email, 아니면 'system'
    """
    if actor is None:
        actor = _default_actor()
    log = AuditLog(
        actor=actor,
        target_table=target_table,
        target_id=str(target_id),
        action=action,
        before_json=_safe_json(before),
        after_json=_safe_json(after),
        reason=reason,
    )
    session.add(log)
    session.flush()
    return log


def record_create(session: Session, *, target_table: str, target_id: Any,
                  state: dict, actor: str | None = None,
                  reason: str | None = None) -> AuditLog:
    return record(session, target_table=target_table, target_id=target_id,
                  action='create', actor=actor, after=state, reason=reason)


def record_update(session: Session, *, target_table: str, target_id: Any,
                  before: dict, after: dict, actor: str | None = None,
                  reason: str | None = None) -> AuditLog | None:
    """변경된 항목만 추출해 기록. before==after 면 None 반환."""
    diff_before = {k: before.get(k) for k in after
                   if before.get(k) != after.get(k)}
    diff_after = {k: after[k] for k in after
                  if before.get(k) != after.get(k)}
    if not diff_after:
        return None
    return record(session, target_table=target_table, target_id=target_id,
                  action='update', actor=actor,
                  before=diff_before, after=diff_after, reason=reason)


def record_delete(session: Session, *, target_table: str, target_id: Any,
                  state: dict | None = None, actor: str | None = None,
                  reason: str | None = None) -> AuditLog:
    return record(session, target_table=target_table, target_id=target_id,
                  action='delete', actor=actor, before=state, reason=reason)


def record_restore(session: Session, *, target_table: str, target_id: Any,
                   actor: str | None = None,
                   reason: str | None = None) -> AuditLog:
    return record(session, target_table=target_table, target_id=target_id,
                  action='restore', actor=actor, reason=reason)


# ─────────────────────────────────────────────────────────────────────────────
# 변경 이력 조회
# ─────────────────────────────────────────────────────────────────────────────

def history(
    session: Session,
    *,
    target_table: str | None = None,
    target_id: Any | None = None,
    actor: str | None = None,
    limit: int = 100,
) -> list[AuditLog]:
    """이력 조회 — 필터 조합 가능.

    - 특정 행: target_table + target_id
    - 특정 사용자: actor
    - 모든 변경: 인자 없이
    """
    q = session.query(AuditLog)
    if target_table:
        q = q.filter(AuditLog.target_table == target_table)
    if target_id is not None:
        q = q.filter(AuditLog.target_id == str(target_id))
    if actor:
        q = q.filter(AuditLog.actor == actor)
    return q.order_by(AuditLog.at.desc()).limit(limit).all()


def recent_activity(session: Session, limit: int = 50) -> list[AuditLog]:
    """전체 시스템 최근 활동 — 운영센터 대시보드용."""
    return (session.query(AuditLog)
            .order_by(AuditLog.at.desc())
            .limit(limit).all())


# ─────────────────────────────────────────────────────────────────────────────
# Soft-delete + Restore
# ─────────────────────────────────────────────────────────────────────────────

def soft_delete(
    session: Session,
    target_obj: Any,
    *,
    actor: str | None = None,
    reason: str | None = None,
) -> AuditLog:
    """deleted_at 컬럼이 있는 객체를 soft-delete + 감사 기록."""
    if not hasattr(target_obj, 'deleted_at'):
        raise AttributeError(f"{type(target_obj).__name__} 에 deleted_at 컬럼 없음 — soft-delete 미지원")
    target_obj.deleted_at = _utcnow()
    table = target_obj.__tablename__
    pk_col = list(target_obj.__table__.primary_key.columns)[0].name
    target_id = getattr(target_obj, pk_col)
    return record_delete(session, target_table=table, target_id=target_id,
                         actor=actor, reason=reason)


def restore(
    session: Session,
    target_obj: Any,
    *,
    actor: str | None = None,
    reason: str | None = None,
) -> AuditLog:
    """soft-deleted 객체 복원 + 감사 기록."""
    if not hasattr(target_obj, 'deleted_at'):
        raise AttributeError(f"{type(target_obj).__name__} 에 deleted_at 컬럼 없음")
    target_obj.deleted_at = None
    table = target_obj.__tablename__
    pk_col = list(target_obj.__table__.primary_key.columns)[0].name
    target_id = getattr(target_obj, pk_col)
    return record_restore(session, target_table=table, target_id=target_id,
                          actor=actor, reason=reason)


def list_trash(
    session: Session,
    target_table: str | None = None,
    limit: int = 100,
) -> list[AuditLog]:
    """휴지통 — soft-deleted 항목 (action='delete' 마지막 + restore 안 됨).

    실제 deleted_at 행 조회는 각 모델마다 다르므로,
    감사 로그를 통한 "최근 삭제" 목록 반환 (단순화).
    """
    q = session.query(AuditLog).filter_by(action='delete')
    if target_table:
        q = q.filter_by(target_table=target_table)
    return q.order_by(AuditLog.at.desc()).limit(limit).all()


# ─────────────────────────────────────────────────────────────────────────────
# Dry-run preview — 변경 영향 미리보기
# ─────────────────────────────────────────────────────────────────────────────

def preview_price_change(
    session: Session,
    *,
    model_code: str,
    new_sale_price: int,
) -> dict:
    """가격 변경 영향 미리보기.

    Returns:
      {
        'affected_options': N,
        'affected_accounts': N,    # BundleAccountRegistration N행
        'guardrail_violation': bool,
        'guardrail_lower': int|None,
        'guardrail_upper': int|None,
        'price_diff_pct': float,
        'current_price': int|None,
      }
    """
    from lemouton.sourcing.models import Model, Option
    from lemouton.templates.models import PriceTemplate
    from lemouton.multitenancy.models import BundleAccountRegistration

    m = session.query(Model).filter_by(model_code=model_code).first()
    if m is None:
        raise LookupError(f"Model {model_code} 없음")

    options_count = (session.query(Option)
                     .filter_by(model_code=model_code).count())
    accounts_count = (session.query(BundleAccountRegistration)
                      .filter_by(model_code=model_code).count())

    pt = (session.query(PriceTemplate)
          .filter_by(id=m.price_template_id).first()) if m.price_template_id else None

    lower = m.guardrail_lower_override or (pt.guardrail_lower if pt else None)
    upper = m.guardrail_upper_override or (pt.guardrail_upper if pt else None)
    current = pt.ss_boxhero_sale_price if pt else None

    violation = False
    if lower is not None and new_sale_price < lower:
        violation = True
    if upper is not None and new_sale_price > upper:
        violation = True

    diff_pct = 0.0
    if current:
        diff_pct = ((new_sale_price - current) / current) * 100

    return {
        'affected_options': options_count,
        'affected_accounts': accounts_count,
        'guardrail_violation': violation,
        'guardrail_lower': lower,
        'guardrail_upper': upper,
        'price_diff_pct': round(diff_pct, 2),
        'current_price': current,
    }


def preview_bundle_delete(
    session: Session,
    model_code: str,
) -> dict:
    """모음전 삭제 영향 — 옵션·계정 등록·이력 손실 사전 표시."""
    from lemouton.sourcing.models import Option
    from lemouton.multitenancy.models import (
        BundleAccountRegistration, OptionAccountRegistration,
    )
    from lemouton.sources.models import ModelSourceLink

    options = (session.query(Option)
               .filter_by(model_code=model_code).all())
    sku_list = [o.canonical_sku for o in options]

    bundle_regs = (session.query(BundleAccountRegistration)
                   .filter_by(model_code=model_code).count())
    registered_accounts = (session.query(BundleAccountRegistration)
                           .filter_by(model_code=model_code,
                                      is_registered=True).count())
    option_regs = 0
    if sku_list:
        option_regs = (session.query(OptionAccountRegistration)
                       .filter(OptionAccountRegistration.canonical_sku.in_(sku_list))
                       .count())
    source_links = (session.query(ModelSourceLink)
                    .filter_by(model_code=model_code).count())

    return {
        'options_to_remove': len(options),
        'bundle_registrations': bundle_regs,
        'registered_in_marketplaces': registered_accounts,
        'option_registrations': option_regs,
        'source_links': source_links,
        'warning': (
            '실제 마켓에 등록된 상품이 있습니다 — 시스템에서 삭제해도 마켓엔 남아있습니다.'
            if registered_accounts > 0 else None
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 마켓 등록 후 검증 (Day 7 brainstorm iv)
# ─────────────────────────────────────────────────────────────────────────────

def verify_market_registration(
    session: Session,
    *,
    model_code: str,
    account_id: int,
    fetch_external_state: callable | None = None,
) -> dict:
    """자동 등록 후 마켓 API 재조회로 실제 등록 상태 확인.

    fetch_external_state: 마켓 API 호출 함수 (테스트 시 mock 가능)
                         signature: (external_product_id) -> dict|None

    Returns:
      {'verified': bool, 'discrepancies': [...], 'external_state': dict|None}
    """
    from lemouton.multitenancy.models import (
        BundleAccountRegistration, OptionAccountRegistration,
    )
    from lemouton.sourcing.models import Option

    reg = (session.query(BundleAccountRegistration)
           .filter_by(model_code=model_code, account_id=account_id).first())
    if reg is None:
        return {'verified': False, 'discrepancies': ['등록 매핑 없음'],
                'external_state': None}
    if not reg.external_product_id:
        return {'verified': False,
                'discrepancies': ['external_product_id 없음 — 등록 미완료'],
                'external_state': None}

    discrepancies = []
    external_state = None
    if fetch_external_state is not None:
        try:
            external_state = fetch_external_state(reg.external_product_id)
        except Exception as e:
            return {'verified': False,
                    'discrepancies': [f'마켓 API 호출 실패: {e}'],
                    'external_state': None}

        if external_state is None:
            discrepancies.append('마켓에 상품 없음 (등록 실패 또는 삭제됨)')
        else:
            # 옵션 수 비교
            local_opts = (session.query(OptionAccountRegistration)
                          .filter_by(account_id=account_id, is_visible=True)
                          .filter(OptionAccountRegistration.canonical_sku.in_(
                              [o.canonical_sku for o in
                               session.query(Option).filter_by(model_code=model_code)]
                          )).count())
            ext_opts = len(external_state.get('options', []))
            if local_opts != ext_opts:
                discrepancies.append(
                    f'옵션 수 불일치: 로컬 {local_opts}개 vs 마켓 {ext_opts}개'
                )

    return {
        'verified': len(discrepancies) == 0,
        'discrepancies': discrepancies,
        'external_state': external_state,
    }
