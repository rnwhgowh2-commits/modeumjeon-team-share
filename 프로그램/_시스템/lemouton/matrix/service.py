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
    """모델 하나에 **살아 있는** 원본 매트릭스 하나를 보장한다(멱등).

    🔴 [2026-08-12] 지워진 원본을 그대로 돌려주고 있었다. 화면은 `deleted_at IS NULL`
       로 찾으므로 원본이 없는 상품이 되고, 백필 3경로(scheduler.jobs ·
       admin_owner_snapshot · admin_display_no)는 「이미 있다」며 건너뛰어 구멍이
       **영영** 안 메워졌다. 상품관리에서 「편집」이 딴 화면으로 새는 고장의 뿌리다
       (라이브 실측 2026-08-12: 92개 중 2개).

    ★ 새로 만들지 않고 **되살린다** — `uq_matrix_option_model_kind`(model_code, kind)
      가 `deleted_at` 을 안 보므로, 새 행을 넣으면 유니크 제약에 걸려 터진다.
      되살리는 편이 담긴 옵션·파생 관계도 그대로 살아나 뜻에도 맞다.
    """
    got = session.scalar(select(MatrixOption).where(
        MatrixOption.model_code == model.model_code,
        MatrixOption.kind == KIND_ORIGIN))
    if got is not None:
        if got.deleted_at is not None:
            got.deleted_at = None
            session.flush()
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
    # 🔴 「이미 있다」 판정은 ensure_origin 과 **같은 눈**이어야 한다 — 여기만
    #    지워진 것까지 세면 백필이 그 모델을 건너뛰어 구멍이 안 메워진다.
    have = set(session.scalars(select(MatrixOption.model_code).where(
        MatrixOption.kind == KIND_ORIGIN, MatrixOption.model_code.is_not(None),
        MatrixOption.deleted_at.is_(None))))
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


def create_option_box(session, *, name: str, brand: str = '',
                      category: str | None = None,
                      memo: str | None = None,
                      model_name: str | None = None,
                      band: int | None = None) -> MatrixOption:
    """옵션함을 만든다 — 「상품 없이 옵션만」의 입구. 설계서 규칙 1·3.

    겉(사장님이 보는 것) — 매트릭스 옵션 하나가 생기고 `U…` 번호가 붙는다.
    속(저장)           — 모델 1 + 매트릭스 1. 모델엔 `M…` 을 안 붙인다(안 파니까).

    🔴 왜 모델을 같이 만드나 — 옵션은 반드시 모델 하나에 매달려야 저장된다
       (`Option.model_code` NOT NULL). 그 제약을 푸는 대신, 짝이 되는 줄을 만들고
       `is_option_box` 로 판매용이 아님을 표시한다. 크롤·전송·주문매칭이 지금 그대로 돈다.

    🔴 model_code 는 `U…` 번호를 그대로 쓴다 — 사람이 지은 이름은 겹칠 수 있고,
       겹치면 저장이 터진다. 번호는 순번 예약이라 절대 안 겹친다.

    Args:
        model_name: 묶음에 따로 적어 두는 **모델명**(`Model.bundle_model_name`).
            색상 모음전처럼 모델이 하나뿐일 때만 쓴다.
            🔴 **모델 모음전이면 여기 넣지 마라.** 모델이 여럿인 묶음의 모델명은
               「모델」 축의 값이 정본이고, 여기 또 넣으면 같은 사실이 두 곳에 생긴다.
               `option_name.model_name_of` 의 판정 순서(① 축 값 → ② 이 칸)상
               조용히 가려져 있다가, 축이 바뀌는 날 두 값이 갈린다.
            비었으면 **None** 으로 남긴다 — 「따로 안 정함」과 「빈 이름」은 다르다.
        band: 순번 앞자리로 출처를 가른다(`shared/display_no.py` 의 band 그대로).
            🔴 기본값 `None` — 이러면 예전과 똑같은 `U…` 순번 한 줄(scope `'U'`)을
               그대로 쓴다. 여기서 뭘 넣어도 **기존 호출부(직접 생성)는 절대 안 건드린다**
               (band 인자를 아예 안 주므로). 「내마켓 불러오기」처럼 출처를 구별해야
               하는 새 호출부만 `band=1` 같은 값을 넘긴다 — 그러면 완전히 새 scope
               (`'U:1'`)에서 1부터 채번되어 기존 번호와 절대 안 겹친다.
    """
    from shared.display_no import PREFIX_MATRIX_ORIGIN, format_no, reserve
    from lemouton.sourcing.models import Model

    nm = (name or '').strip()
    if not nm:
        raise ValueError('매트릭스 옵션명을 적어주세요 — 이름이 없으면 나중에 찾을 수 없습니다.')

    # [2026-08-12 노션 옵션 b★ 「브랜드/모델명 입력되어야함」] 브랜드는 필수다.
    #   🔴 예전엔 비우면 조용히 「르무통」이 박혔다. 「누락 없이」의 뜻은
    #      「거짓으로 채우지 않기」다 — 다른 브랜드 물건이 르무통으로 잡히면
    #      브랜드별 정책·크롤 계수·정산 분류가 통째로 어긋난다.
    #   기존 데이터는 안 건드린다. 앞으로 만드는 것만 필수.
    br = (brand or '').strip()
    if not br:
        raise ValueError('브랜드를 적어주세요 — 비워 두면 엉뚱한 브랜드로 잡힙니다.')

    seq = reserve(session, PREFIX_MATRIX_ORIGIN, band=band)
    no = format_no(PREFIX_MATRIX_ORIGIN, seq, band=(band or 0))

    session.add(Model(model_code=no, model_name_raw=nm, model_name_display=nm,
                      brand=br, category=category,
                      bundle_model_name=((model_name or '').strip() or None),
                      is_option_box=True))
    session.flush()

    mo = MatrixOption(kind=KIND_ORIGIN, model_code=no, name=nm, display_no=no,
                      memo=(memo or None))
    session.add(mo)
    session.flush()
    return mo
