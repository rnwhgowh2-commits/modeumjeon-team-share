"""매트릭스 옵션 규칙 — 원본 보장 · 파생 생성 · 멤버 조회 · 수정 위치 판정.

🔴 이 모듈의 존재 이유 한 줄:
   **파생은 원본의 옵션을 그대로 가리킨다.** 그래서 파생에서 소싱처 URL·사입품번을
   고치면 원본이 바뀐다. 화면이 그걸 모르면 「왜 딴 상품이 같이 바뀌지?」가 된다.
   `edit_target()` 이 「어디서 고쳐야 하는가」의 단일 판정처다.

원본 멤버는 여기 저장하지 않는다 — `Option.model_code` 가 이미 안다.
같은 사실을 두 곳에 두면 반드시 갈린다.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from lemouton.matrix.models import KIND_DERIVED, KIND_ORIGIN, MatrixOption, MatrixOptionMember


class MatrixError(Exception):
    """사용자에게 그대로 보여줄 수 있는 실패 사유."""


# ── 원본 ──────────────────────────────────────────────────────────────────

def ensure_origin(session, model) -> MatrixOption:
    """모델 하나에 원본 매트릭스 하나를 보장한다(멱등)."""
    got = session.scalar(select(MatrixOption).where(
        MatrixOption.model_code == model.model_code,
        MatrixOption.kind == KIND_ORIGIN))
    if got is not None:
        return got
    mo = MatrixOption(
        kind=KIND_ORIGIN, model_code=model.model_code,
        name=(model.model_name_display or model.model_name_raw or model.model_code))
    session.add(mo)
    session.flush()
    return mo


def ensure_all_origins(session, *, limit: int | None = 500) -> int:
    """원본 매트릭스가 없는 모델에 만들어 준다. 붙인 수를 돌려준다."""
    from lemouton.sourcing.models import Model
    have = set(session.scalars(select(MatrixOption.model_code).where(
        MatrixOption.kind == KIND_ORIGIN, MatrixOption.model_code.is_not(None))))
    q = select(Model).order_by(Model.created_at.asc(), Model.model_code.asc())
    made = 0
    for m in session.scalars(q):
        if m.model_code in have:
            continue
        ensure_origin(session, m)
        made += 1
        if limit and made >= limit:
            break
    return made


# ── 파생 ──────────────────────────────────────────────────────────────────

def create_derived(session, *, origin: MatrixOption, name: str,
                   skus: list[str], on: date | None = None) -> MatrixOption:
    """개별 옵션을 골라 파생 매트릭스를 만든다.

    Raises:
        MatrixError: 원본이 아닌 것에서 갈라뜨리려 하거나, 고른 옵션이
                     원본에 속하지 않거나, 하나도 안 골랐을 때.
    """
    from shared.display_no import PREFIX_MATRIX_DERIVED, issue_one
    from lemouton.sourcing.models import Option

    if origin.kind != KIND_ORIGIN:
        raise MatrixError('파생은 원본에서만 갈라낼 수 있어요. '
                          '파생에서 또 파생을 만들면 원본이 어디인지 알 수 없게 됩니다.')
    picked = [s for s in dict.fromkeys(skus or []) if s]
    if not picked:
        raise MatrixError('옵션을 하나도 고르지 않았어요.')
    owned = set(session.scalars(select(Option.canonical_sku).where(
        Option.model_code == origin.model_code,
        Option.canonical_sku.in_(picked))))
    missing = [s for s in picked if s not in owned]
    if missing:
        raise MatrixError(f'원본에 없는 옵션이 섞여 있어요: {", ".join(missing[:5])}'
                          + (f' 외 {len(missing) - 5}개' if len(missing) > 5 else ''))

    mo = MatrixOption(kind=KIND_DERIVED, origin_id=origin.id,
                      name=(name or '').strip() or f'{origin.name} 일부')
    session.add(mo)
    session.flush()
    mo.display_no = issue_one(session, PREFIX_MATRIX_DERIVED, on=on)
    for i, sku in enumerate(picked):
        session.add(MatrixOptionMember(matrix_option_id=mo.id,
                                       canonical_sku=sku, sort_no=i))
    session.flush()
    return mo


# ── 조회 ──────────────────────────────────────────────────────────────────

def member_skus(session, mo: MatrixOption) -> list[str]:
    """이 매트릭스에 담긴 개별 옵션번호(SKU) 목록.

    원본이면 모델이 소유한 옵션 전부, 파생이면 골라 담은 것만.
    """
    from lemouton.sourcing.models import Option
    if mo.kind == KIND_ORIGIN:
        return list(session.scalars(select(Option.canonical_sku).where(
            Option.model_code == mo.model_code).order_by(Option.canonical_sku)))
    return list(session.scalars(
        select(MatrixOptionMember.canonical_sku)
        .where(MatrixOptionMember.matrix_option_id == mo.id)
        .order_by(MatrixOptionMember.sort_no, MatrixOptionMember.id)))


def origin_of(session, mo: MatrixOption) -> MatrixOption | None:
    """이 매트릭스의 원본. 자기가 원본이면 자기 자신."""
    if mo.kind == KIND_ORIGIN:
        return mo
    return session.get(MatrixOption, mo.origin_id) if mo.origin_id else None


def derived_of(session, origin: MatrixOption) -> list[MatrixOption]:
    """이 원본에서 갈라져 나간 파생들."""
    return list(session.scalars(
        select(MatrixOption).where(MatrixOption.origin_id == origin.id,
                                   MatrixOption.deleted_at.is_(None))
        .order_by(MatrixOption.created_at)))


def edit_target(session, mo: MatrixOption) -> dict:
    """소싱처 URL·사입품번을 **어디서 고쳐야 하는가**.

    Returns:
        {'editable': bool, 'origin': MatrixOption|None, 'reason': str}
        editable=False 면 화면은 입력칸을 잠그고 origin 으로 보내야 한다.
    """
    if mo.kind == KIND_ORIGIN:
        return {'editable': True, 'origin': mo, 'reason': ''}
    org = origin_of(session, mo)
    return {
        'editable': False, 'origin': org,
        'reason': ('파생 옵션이라 여기서는 못 고쳐요. '
                   '원본에서 고치면 이 옵션에도 함께 반영됩니다.'),
    }
