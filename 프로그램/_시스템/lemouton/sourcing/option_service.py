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
            axis_name=(st.get('axis_name') or st.get('name') or f'단계{i}'),
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

    # [2026-05-28] Phase 1-2 — canonical_sku 형식 통일 (SKU-XXX) + axis 기반 중복 검사
    #   - existing_skus: 전체 DB의 SKU 중복 회피 (UNIQUE PK 충돌 방지)
    #   - existing_axes: 이 모음전 model 안의 (axis_tuple) 중복 회피
    existing_skus = {row[0] for row in session.query(Option.canonical_sku).all()}
    existing_axes: set[tuple] = set()
    for (av_json,) in session.query(Option.axis_values_json).filter_by(
            model_code=model_code).all():
        try:
            vals = json.loads(av_json or '[]')
            if vals:
                existing_axes.add((model_code, tuple(vals)))
        except (ValueError, TypeError):
            pass
    specs = build_options_from_steps(model_code, steps,
                                     existing_skus=existing_skus,
                                     existing_axes=existing_axes,
                                     selected=selected)
    # [2026-05-28] Phase 1-2/1-4 — 컬럼 규칙: shared.sku_format 모듈로 통일
    from shared.sku_format import gen_barcode

    created: list[str] = []
    for spec in specs:
        values = spec['axis_values']
        session.add(Option(
            canonical_sku=spec['canonical_sku'],
            boxhero_sku=spec['canonical_sku'],  # 사용자 룰: 자체 SKU 가 박스히어로 SKU
            barcode=gen_barcode(),               # 자동 EAN-13
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
        # [2026-05-27 FIX] sku 형식(옛 `르무통-오렌지-280` vs 새 `SKU-XXX`)에 의존하지 않고
        #   axis_values (색상·사이즈 조합) 로 매칭. 같은 색상·사이즈 조합이면 옛/새 형식
        #   둘 다 묶어서 is_active 토글.
        from .option_combo import generate_combinations

        # 사용자가 켠 조합 (axis 값 튜플)
        keep_axes = {tuple(vals) for vals in selected}
        # 현재 단계 설계의 전체 매트릭스 조합
        matrix_axes = {tuple(c['values']) for c in generate_combinations(steps)}

        def _opt_axes(opt: Option) -> tuple:
            """옵션에서 axis 값 추출 — axis_values_json 우선, 없으면 color/size fallback."""
            try:
                vals = json.loads(opt.axis_values_json or '[]')
                if vals:
                    return tuple(vals)
            except Exception:
                pass
            return tuple(v for v in [opt.color_code or '', opt.size_code or ''] if v)

        # 신규 추가 옵션 먼저 flush — 아래 쿼리에서 함께 잡히도록
        try:
            session.flush()
        except Exception:
            session.rollback()
            raise

        # 이 모음전의 모든 옵션 (방금 생성한 것 포함)
        all_opts = session.query(Option).filter_by(model_code=model_code).all()
        created_set = set(created)

        for opt in all_opts:
            axes = _opt_axes(opt)
            if axes in keep_axes:
                # 사용자가 켠 조합 → is_active=True 로 복원
                if not opt.is_active:
                    opt.is_active = True
            elif axes in matrix_axes:
                # 매트릭스 안인데 사용자가 끔 → is_active=False
                if opt.is_active:
                    opt.is_active = False
                    disabled.append(opt.canonical_sku)
            else:
                # 매트릭스 밖 → 추적 불가, 보호 (건드리지 않음)
                if opt.canonical_sku not in created_set:
                    protected.append(opt.canonical_sku)

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
