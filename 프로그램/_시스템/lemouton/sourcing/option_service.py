"""단계형 옵션 — 조합 추가 서비스 (Phase 2 · Task 4).

ai-workflow cycle 20260521

단계 설계 저장 + 조합 옵션 일괄 생성. (DB 의존 — Session 사용)
순수 계산 로직은 option_combo.py, 여기는 DB 읽기/쓰기 오케스트레이션.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .models import Option, BundleOptionStep
from .option_combo import build_options_from_steps


def save_step_design(session: Session, model_code: str, steps: list[dict]) -> None:
    """모음전의 옵션 단계 설계 저장 — 기존 BundleOptionStep 전체 교체.

    steps: [{"axis_name": str, "values": list[str]}] (1~3개).
    """
    session.query(BundleOptionStep).filter_by(model_code=model_code).delete()
    for i, st in enumerate(steps, start=1):
        session.add(BundleOptionStep(
            model_code=model_code,
            step_no=i,
            axis_name=(st.get('axis_name') or f'단계{i}'),
            values_json=json.dumps(st.get('values') or [], ensure_ascii=False),
        ))


def create_combination_options(
    session: Session,
    model_code: str,
    steps: list[dict],
    selected: list[list[str]] | None = None,
    prune: bool = False,
) -> dict:
    """단계 설계 저장 + 조합 옵션 일괄 생성 (+ 선택 시 REPLACE 모드).

    1. 단계 설계(BundleOptionStep) 저장 — 기존 교체.
    2. 이미 있는 옵션은 제외하고 신규 조합만 Option 행 생성.
       color_code/size_code 는 레거시 호환용으로 단계 값 1·2번째를 채움.
    3. selected 지정 시 그 조합만 (2·3축 매트릭스 '선택 생성').
    4. [2026-05-25 A-2-FIX] prune=True 면 REPLACE 모드:
       selected 에 없는 기존 옵션을 모음전에서 제거 (모달 = 단일 진실 원천).
       다른 데이터(URL 매핑·재고 이력 등) 참조가 있어 삭제 못 하면 그 옵션은
       protected_skus 에 포함해서 응답 — 사용자에게 토스트로 알릴 수 있게.
       재고관리 상품 자체는 별도 시스템 — 모음전 옵션 행만 제거.

    Returns:
        {'created': int, 'deleted': int, 'protected': int,
         'skus': [...], 'skus_deleted': [...], 'skus_protected': [...]}
    """
    from sqlalchemy.exc import IntegrityError

    save_step_design(session, model_code, steps)

    existing = {
        row[0] for row in
        session.query(Option.canonical_sku).filter_by(model_code=model_code).all()
    }
    specs = build_options_from_steps(model_code, steps,
                                     existing_skus=existing, selected=selected)
    created: list[str] = []
    for spec in specs:
        values = spec['axis_values']
        session.add(Option(
            canonical_sku=spec['canonical_sku'],
            model_code=model_code,
            color_code=(values[0] if len(values) > 0 else ''),
            size_code=(values[1] if len(values) > 1 else ''),
            axis_values_json=spec['axis_values_json'],
        ))
        created.append(spec['canonical_sku'])

    deleted: list[str] = []
    protected: list[str] = []
    disabled: list[str] = []   # [2026-05-27 D1] is_active=False 로 mark 된 옵션
    if prune and selected is not None:
        # selected 의 조합만 유지 — 그 외 옵션은 삭제 또는 비활성
        from .option_combo import build_sku, generate_combinations
        from .models import OptionSourceUrlLink
        keep_skus = {build_sku(model_code, vals) for vals in selected}
        # 방금 생성한 신규도 keep (안전망)
        keep_skus.update(created)
        # [2026-05-25 SAFETY] 매트릭스 안 옵션만 prune 대상 (밖 옵션은 무조건 보호)
        matrix_skus = {build_sku(model_code, c['values'])
                       for c in generate_combinations(steps)}
        raw_to_delete = existing - keep_skus
        to_delete = raw_to_delete & matrix_skus
        untracked = raw_to_delete - matrix_skus
        protected.extend(sorted(untracked))

        # [2026-05-27 D1] 매핑 미리 조회 — 매핑 있으면 is_active=False 로 mark (삭제 X)
        skus_with_mapping = set()
        if to_delete:
            links = session.query(OptionSourceUrlLink.option_canonical_sku).filter(
                OptionSourceUrlLink.option_canonical_sku.in_(list(to_delete))
            ).all()
            skus_with_mapping = {ln[0] for ln in links}

        # 신규 추가는 한 트랜잭션에 flush 해야 FK 위반 검증 가능
        try:
            session.flush()
        except Exception:
            session.rollback()
            raise

        # [2026-05-27 D1] selected 안 옵션은 is_active=True 로 자동 복원 (사용자가 다시 ON)
        if keep_skus:
            (session.query(Option)
             .filter(Option.model_code == model_code,
                     Option.canonical_sku.in_(list(keep_skus)),
                     Option.is_active == False)  # noqa: E712
             .update({Option.is_active: True}, synchronize_session=False))

        for sku in to_delete:
            sp = session.begin_nested()
            try:
                obj = session.query(Option).filter_by(
                    canonical_sku=sku, model_code=model_code).first()
                if obj is None:
                    sp.rollback()
                    continue
                # 매핑 있으면 삭제 대신 is_active=False mark — 사용자 OFF 선택 영구 보존
                if sku in skus_with_mapping:
                    obj.is_active = False
                    sp.commit()
                    disabled.append(sku)
                    continue
                # 매핑 없으면 안전하게 삭제
                session.delete(obj)
                session.flush()
                sp.commit()
                deleted.append(sku)
            except IntegrityError:
                sp.rollback()
                # FK 위반 — 매핑 외 다른 데이터 (가격·재고 등) 가 있는 경우. is_active=False 로 fallback.
                try:
                    obj = session.query(Option).filter_by(
                        canonical_sku=sku, model_code=model_code).first()
                    if obj is not None:
                        obj.is_active = False
                        session.flush()
                        disabled.append(sku)
                        continue
                except Exception:
                    pass
                protected.append(sku)
            except Exception:
                sp.rollback()
                protected.append(sku)

    session.commit()
    return {
        'created': len(created),
        'deleted': len(deleted),
        'protected': len(protected),
        'disabled': len(disabled),
        'skipped': 0,
        'skus': created,
        'skus_deleted': deleted,
        'skus_protected': protected,
        'skus_disabled': disabled,
    }
