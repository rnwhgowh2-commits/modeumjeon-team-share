"""표시번호 부여 — 아직 번호가 없는 행에 붙인다 (소급·신규 공통, 멱등).

사장님 확정 (2026-07-30):
  · 기존 것도 전부 소급 부여. 옛날 것이라도 **현재 날짜 기준**으로 번호를 준다.
  · 순번은 **등록된 순서**(created_at)대로. 소싱처마다 따로 1번부터.

이미 번호가 있는 행은 절대 다시 붙이지 않는다 — 번호가 바뀌면 사장님이 적어둔
번호가 딴 상품을 가리키게 된다.

규칙 자체는 shared/display_no.py 가 단일 진실 원천. 여기는 「어디에 붙일지」만 담당.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from shared.display_no import (
    BAND_OPTION, BAND_PRODUCT, PREFIX_BUNDLE_PRODUCT,
    PREFIX_MATRIX_DERIVED, PREFIX_MATRIX_ORIGIN,
    format_no, prefix_for_site, reserve,
)

_CHUNK = 500        # 한 번에 예약·저장하는 크기. 라이브에서 오래 잠그지 않게.


def _assign_models(session, on: date | None, limit: int | None) -> int:
    from lemouton.sourcing.models import Model
    # [2026-08-01] 옵션함(아직 안 파는 묶음)은 건너뛴다 — 설계서 규칙 3.
    #   🔴 안 막으면 옵션만 만들어 둔 묶음에 판매용 M… 번호가 저절로 박힌다.
    q = (select(Model).where(Model.display_no.is_(None),
                             Model.is_option_box.is_(False))
         .order_by(Model.created_at.asc(), Model.model_code.asc()))
    if limit:
        q = q.limit(limit)
    rows = list(session.scalars(q))
    if not rows:
        return 0
    start = reserve(session, PREFIX_BUNDLE_PRODUCT, count=len(rows))
    for i, r in enumerate(rows):
        r.display_no = format_no(PREFIX_BUNDLE_PRODUCT, start + i, on=on)
    session.flush()
    return len(rows)


def _assign_source_products(session, on: date | None, limit: int | None) -> tuple[int, int]:
    """(붙인 수, 소싱처를 몰라 건너뛴 수)."""
    from lemouton.sources.models import SourceProduct
    q = (select(SourceProduct).where(SourceProduct.display_no.is_(None))
         .order_by(SourceProduct.created_at.asc(), SourceProduct.id.asc()))
    if limit:
        q = q.limit(limit)
    rows = list(session.scalars(q))
    by_prefix: dict[str, list] = {}
    skipped = 0
    for r in rows:
        p = prefix_for_site(r.site)
        if not p:
            skipped += 1        # 모르는 소싱처 — 번호를 지어내지 않는다
            continue
        by_prefix.setdefault(p, []).append(r)
    done = 0
    for p, items in by_prefix.items():
        start = reserve(session, p, band=BAND_PRODUCT, count=len(items))
        for i, r in enumerate(items):
            r.display_no = format_no(p, start + i, band=BAND_PRODUCT, on=on)
        done += len(items)
    session.flush()
    return done, skipped


def _assign_source_options(session, on: date | None, limit: int | None) -> tuple[int, int]:
    """옵션 접두는 **부모 상품의 소싱처**를 따른다."""
    from lemouton.sources.models import SourceOption, SourceProduct
    q = (select(SourceOption, SourceProduct.site)
         .join(SourceProduct, SourceOption.source_product_id == SourceProduct.id)
         .where(SourceOption.display_no.is_(None))
         .order_by(SourceOption.created_at.asc(), SourceOption.id.asc()))
    if limit:
        q = q.limit(limit)
    by_prefix: dict[str, list] = {}
    skipped = 0
    for opt, site in session.execute(q).all():
        p = prefix_for_site(site)
        if not p:
            skipped += 1
            continue
        by_prefix.setdefault(p, []).append(opt)
    done = 0
    for p, items in by_prefix.items():
        start = reserve(session, p, band=BAND_OPTION, count=len(items))
        for i, r in enumerate(items):
            r.display_no = format_no(p, start + i, band=BAND_OPTION, on=on)
        done += len(items)
    session.flush()
    return done, skipped


def _assign_matrix(session, on: date | None, limit: int | None) -> int:
    """매트릭스 옵션 — 원본은 U, 파생은 P. 종류가 섞여 있으므로 나눠 예약한다."""
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    q = (select(MatrixOption).where(MatrixOption.display_no.is_(None))
         .order_by(MatrixOption.created_at.asc(), MatrixOption.id.asc()))
    if limit:
        q = q.limit(limit)
    rows = list(session.scalars(q))
    if not rows:
        return 0
    groups: dict[str, list] = {}
    for r in rows:
        p = PREFIX_MATRIX_ORIGIN if r.kind == KIND_ORIGIN else PREFIX_MATRIX_DERIVED
        groups.setdefault(p, []).append(r)
    for p, items in groups.items():
        start = reserve(session, p, count=len(items))
        for i, r in enumerate(items):
            r.display_no = format_no(p, start + i, on=on)
    session.flush()
    return len(rows)


def assign_missing(session, *, on: date | None = None,
                   limit: int | None = _CHUNK) -> dict:
    """번호 없는 행에 표시번호를 붙인다. 커밋은 호출한 쪽 책임.

    Args:
        on: 번호에 박을 날짜. 기본 = 오늘(사장님 확정 — 옛날 것도 현재 기준).
        limit: 종류별 한 번에 처리할 최대 행수. None = 전부.

    Returns:
        {'models': n, 'source_products': n, 'source_options': n, 'skipped': n}
        skipped = 소싱처를 몰라 번호를 못 준 행 (지어내지 않는다).
    """
    n_model = _assign_models(session, on, limit)
    n_prod, skip_p = _assign_source_products(session, on, limit)
    n_opt, skip_o = _assign_source_options(session, on, limit)
    n_mx = _assign_matrix(session, on, limit)
    return {
        'models': n_model,
        'source_products': n_prod,
        'source_options': n_opt,
        'matrix_options': n_mx,
        'skipped': skip_p + skip_o,
    }


def pending_counts(session) -> dict:
    """아직 번호가 없는 행 수 — 얼마나 남았는지 화면·로그에서 보기 위함."""
    from sqlalchemy import func
    from lemouton.matrix.models import MatrixOption
    from lemouton.sourcing.models import Model
    from lemouton.sources.models import SourceOption, SourceProduct
    out = {}
    for key, M in (('models', Model), ('source_products', SourceProduct),
                   ('source_options', SourceOption),
                   ('matrix_options', MatrixOption)):
        q = session.query(func.count()).select_from(M).filter(M.display_no.is_(None))
        if M is Model:
            # 옵션함은 번호를 안 붙이기로 한 것이라 「대기」가 아니다.
            #   여기 남겨두면 「아직 안 끝났다」로 영원히 보인다.
            q = q.filter(Model.is_option_box.is_(False))
        out[key] = q.scalar() or 0
    return out
