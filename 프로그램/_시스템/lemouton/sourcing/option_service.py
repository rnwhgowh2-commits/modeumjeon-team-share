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
) -> dict:
    """단계 설계 저장 + 조합 옵션 일괄 생성.

    1. 단계 설계(BundleOptionStep) 저장 — 기존 교체.
    2. 이미 있는 옵션은 제외하고 신규 조합만 Option 행 생성.
       color_code/size_code 는 레거시 호환용으로 단계 값 1·2번째를 채움.
    3. selected 지정 시 그 조합만 (2·3축 매트릭스 '선택 생성').

    Returns:
        {'created': int, 'skipped': int, 'skus': [생성된 canonical_sku]}
    """
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
    session.commit()
    return {'created': len(created), 'skipped': 0, 'skus': created}
