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


def axis_names_of(steps) -> list[str]:
    """단계 설계 → 축 이름 목록. `save_step_design` 과 같은 기본값 규칙을 쓴다."""
    return [(st.get('axis_name') or st.get('name') or f'단계{i}')
            for i, st in enumerate(steps or [], start=1)]


def apply_renames(session: Session, model_code: str, renames,
                  axis_names=None) -> dict:
    """축 값 이름 바꾸기 — **기존 옵션의 축 값만 갈아끼운다.**

    🔴 이 함수가 있는 이유 한 줄:
       옵션의 신원은 (모음전, 축 값 조합)이라, 이름을 고치면 프로그램 눈에는
       「처음 보는 조합」이 된다. 그대로 두면 **새 옵션번호가 나가고 옛 옵션이
       판매 켜진 채 남는다**(사장님 화면에서 24개여야 할 것이 42개였던 원인).
       여기서 갈아끼우면 옵션번호·소싱처 URL 매핑·재고·주문 이력이 그대로 따라온다.

    Args:
        renames: [{"axis": 0, "from": "색상1", "to": "블랙"}, ...]
                 축 번호는 단계 순서(0부터). 사장님이 확인창에서 짝지은 것만 온다 —
                 기계가 추측해서 만들지 않는다(틀린 짝 = URL·재고 오배치 = 돈).
        axis_names: 축 이름들. 옛 칸(color_code/size_code)을 **이름 기준**으로 채우기
                 위해 받는다. 안 주면 옛 규칙(1·2번째 축)대로 — 부르는 곳이 하나뿐이라
                 실제로는 늘 들어온다.

    Returns:
        {'renamed': 바뀐 옵션 수, 'conflicts': [이미 그 조합이 있어 못 바꾼 sku]}
    """
    from .axis_slot import legacy_pair
    from .option_orphans import axes_of

    pairs = []
    for r in (renames or []):
        try:
            ax = int(r.get('axis'))
        except (TypeError, ValueError):
            continue
        old, new = (r.get('from') or '').strip(), (r.get('to') or '').strip()
        if ax >= 0 and old and new and old != new:
            pairs.append((ax, old, new))
    if not pairs:
        return {'renamed': 0, 'conflicts': []}

    opts = session.query(Option).filter_by(model_code=model_code).all()
    taken = {axes_of(o) for o in opts}
    renamed, conflicts = 0, []

    for o in opts:
        cur = list(axes_of(o))
        nxt = list(cur)
        for ax, old, new in pairs:
            if ax < len(nxt) and nxt[ax] == old:
                nxt[ax] = new
        if nxt == cur:
            continue
        if tuple(nxt) in taken:
            # 🔴 같은 조합이 두 개가 되면 어느 쪽 가격·재고가 맞는지 알 수 없다 → 안 바꾼다.
            conflicts.append(o.canonical_sku)
            continue
        taken.discard(tuple(cur))
        taken.add(tuple(nxt))
        o.axis_values_json = json.dumps(nxt, ensure_ascii=False)
        # [2026-08-12] 옛 칸은 **축 이름**으로 채운다 — 「몇 번째 축인가」로 채우면
        #   모델을 1축에 둔 순간 `color_code` 에 모델명이 들어간다(lemouton/sourcing/axis_slot.py).
        o.color_code, o.size_code = legacy_pair(axis_names, nxt)
        renamed += 1

    if renamed:
        session.flush()
    return {'renamed': renamed, 'conflicts': conflicts}


def create_combination_options(
    session: Session,
    model_code: str,
    steps: list[dict],
    selected: list[list[str]] | None = None,
    prune: bool = False,
    renames=None,
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

    from .option_orphans import design_axes

    # 🔴 **지우기 전에 읽는다** — save_step_design 이 옛 단계 설계를 갈아엎는다.
    #    「이번 저장으로 밖이 된 옵션」과 「원래부터 밖이던 옛 옵션」을 가르는 유일한 근거다.
    prev_axes = design_axes(session, model_code) or set()

    save_step_design(session, model_code, steps)

    axis_names = axis_names_of(steps)

    # 이름 바꾸기 먼저 — 아래 중복 검사가 **갈아끼운 뒤의 값**을 보게 한다.
    #   순서가 바뀌면 옛 이름이 「없는 조합」으로 잡혀 새 옵션이 또 생긴다.
    rn = apply_renames(session, model_code, renames, axis_names=axis_names)

    # [2026-05-28] Phase 1-2 — canonical_sku 형식 통일 (SKU-XXX) + axis 기반 중복 검사
    #   - existing_skus: 전체 DB의 SKU 중복 회피 (UNIQUE PK 충돌 방지)
    #   - existing_axes: 이 모음전 model 안의 (axis_tuple) 중복 회피
    existing_skus = {row[0] for row in session.query(Option.canonical_sku).all()}
    existing_axes: set[tuple] = set()
    # [2026-06-13 중복 차단] axis_values_json 우선, 비었으면 color_code/size_code 폴백.
    #   기존엔 axis_values_json 만 봐 그 값이 NULL/빈 옛 행을 못 보고 같은 (색·사이즈)
    #   조합을 또 생성 → 스카이블루 처럼 사이즈별 2행 중복. 폴백으로 그 사각을 닫는다.
    for color_code, size_code, av_json in session.query(
            Option.color_code, Option.size_code, Option.axis_values_json
    ).filter_by(model_code=model_code).all():
        try:
            vals = json.loads(av_json or '[]')
        except (ValueError, TypeError):
            vals = []
        if not vals:
            vals = [v for v in [color_code or '', size_code or ''] if v]
        if vals:
            existing_axes.add((model_code, tuple(vals)))
    specs = build_options_from_steps(model_code, steps,
                                     existing_skus=existing_skus,
                                     existing_axes=existing_axes,
                                     selected=selected)
    # [2026-05-28] Phase 1-2/1-4 — 컬럼 규칙: shared.sku_format 모듈로 통일
    from shared.sku_format import gen_barcode

    from .axis_slot import legacy_pair

    created: list[str] = []
    for spec in specs:
        values = spec['axis_values']
        # [2026-08-12] 옛 칸(color_code/size_code)은 **축 이름**으로 채운다.
        #   예전엔 `values[0]`·`values[1]` 이라, 노션대로 모델을 1축에 두면
        #   색상 칸에 모델명이 들어갔다 — 그 칸은 마켓 전송·재고·마진이 다 읽는다.
        #   규칙은 lemouton/sourcing/axis_slot.py 한 곳에만 있다.
        color_code, size_code = legacy_pair(axis_names, values)
        session.add(Option(
            canonical_sku=spec['canonical_sku'],
            boxhero_sku=spec['canonical_sku'],  # 사용자 룰: 자체 SKU 가 박스히어로 SKU
            barcode=gen_barcode(),               # 자동 EAN-13
            model_code=model_code,
            color_code=color_code,
            size_code=size_code,
            axis_values_json=spec['axis_values_json'],
        ))
        created.append(spec['canonical_sku'])

    deleted: list[str] = []
    protected: list[str] = []
    disabled: list[str] = []   # [2026-05-27 D1] is_active=False 로 mark 된 옵션
    orphaned: list = []        # [2026-08-02] 이번 저장으로 매트릭스 밖이 된 옵션 (치운다)
    purged: dict = {'deleted': [], 'kept': []}
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
            elif axes in prev_axes:
                # [2026-08-02] **이번 저장으로** 밖이 된 옵션 — 사장님이 방금 축에서 뺐다.
                #   사장님 확정: 「정정하면 기존 것은 없던 것처럼 사라진다」 → 묻지 않고 치운다.
                #   그대로 두면 판매 켜진 채 남아 마켓에 올라간다(옛 `색상1 260` 유출).
                if opt.canonical_sku not in created_set:
                    orphaned.append(opt)
            else:
                # 🔴 원래부터 매트릭스 밖이던 옛 옵션 — 건드리지 않는다.
                #   단계 설계가 생기기 전부터 팔리던 것일 수 있고, 한 번의 저장이
                #   그걸 조용히 내리면 그게 더 큰 사고다. 정리는 유령 창구에서
                #   사장님이 눈으로 보고 고른다(option_orphans.resolve_orphans).
                if opt.canonical_sku not in created_set:
                    protected.append(opt.canonical_sku)

        if orphaned:
            from .option_orphans import purge as _purge
            purged = _purge(session, orphaned)

    # [순서 v33] axis(steps) 순서대로 Option.sort_order 기록.
    #   → 매트릭스 메인 트리·옵션 목록·업로드가 사용자가 배치한 순서를 따르게 한다.
    #   (정렬 실패해도 옵션 저장 자체는 진행 — best effort)
    try:
        from .option_combo import generate_combinations as _gen_combos

        _order_index: dict[tuple, int] = {}
        for _idx, _c in enumerate(_gen_combos(steps)):
            _order_index[tuple(_c['values'])] = _idx

        def _axes_of(_opt) -> tuple:
            try:
                _v = json.loads(_opt.axis_values_json or '[]')
                if _v:
                    return tuple(_v)
            except Exception:
                pass
            return tuple(x for x in [_opt.color_code or '', _opt.size_code or ''] if x)

        for _opt in session.query(Option).filter_by(model_code=model_code).all():
            _oi = _order_index.get(_axes_of(_opt))
            if _oi is not None and _opt.sort_order != _oi:
                _opt.sort_order = _oi
    except Exception:
        pass

    session.commit()
    return {
        'created': len(created),
        'deleted': len(deleted),
        'protected': len(protected),
        'disabled': len(disabled),
        'orphaned': len(orphaned),
        'orphan_deleted': len(purged['deleted']),
        'orphan_kept': len(purged['kept']),
        'renamed': rn['renamed'],
        'rename_conflicts': rn['conflicts'],
        'skipped': 0,
        'skus': created,
        'skus_deleted': deleted,
        'skus_protected': protected,
        'skus_disabled': disabled,
        'skus_orphan_deleted': purged['deleted'],
        'skus_orphan_kept': purged['kept'],
    }
