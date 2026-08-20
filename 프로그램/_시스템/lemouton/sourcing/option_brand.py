"""옵션별 브랜드 — 유효브랜드(상속)·저장·목록·일괄적용.

한 모음전(Model)에 여러 브랜드가 섞일 수 있게 Option.brand 를 다룬다.
- 유효 브랜드 = option.brand(있으면) → model.brand → 미지정(None).
- "르무통 자동 채움" 금지: 빈 문자열/공백은 None(미지정)으로 정규화.
순수 DB 오케스트레이션(호출자가 commit).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Model, Option


def _norm(brand) -> str | None:
    """빈 문자열/공백 → None(미지정). 앞뒤 공백 제거."""
    b = (brand or "").strip()
    return b or None


def effective_option_brand(option: Option) -> str | None:
    """옵션의 최종 브랜드: 옵션 자체 → 모델 상속 → 미지정(None)."""
    b = _norm(option.brand)
    if b:
        return b
    if option.model is not None:
        mb = _norm(option.model.brand)
        if mb:
            return mb
    return None


def set_option_brand(session: Session, canonical_sku: str, brand) -> str | None:
    """옵션 1개의 브랜드 저장. 빈값 = 미지정(None)으로 복귀. 호출자 commit."""
    opt = session.get(Option, canonical_sku)
    if opt is None:
        raise ValueError(f"option {canonical_sku!r} 없음")
    opt.brand = _norm(brand)
    session.flush()
    return opt.brand


def list_brands(session: Session) -> list[str]:
    """등록된 브랜드 목록(중복 제거·정렬) — Model.brand + Option.brand 합집합.

    검색 팔레트가 '있는 브랜드'를 보여줄 때 사용(없으면 「+새 브랜드」).
    """
    brands: set[str] = set()
    for (b,) in session.query(Model.brand).distinct():
        nb = _norm(b)
        if nb:
            brands.add(nb)
    for (b,) in session.query(Option.brand).distinct():
        nb = _norm(b)
        if nb:
            brands.add(nb)
    return sorted(brands)


def bulk_apply_brand(session: Session, model_code: str, brand,
                     *, mode: str = "all", skus=None) -> int:
    """모음전 내 옵션들에 브랜드 일괄 적용. 적용 개수 반환. 호출자 commit.

    mode:
      - 'all'      모든 옵션
      - 'empty'    옵션 자체 브랜드가 비어(미지정) 있는 것만  ← 스마트바 "빈 것만"
      - 'selected' skus 로 지정한 옵션만
    빈 brand = 미지정(None)으로 지움.
    """
    b = _norm(brand)
    opts = (session.query(Option)
            .filter(Option.model_code == model_code).all())
    if mode == "selected":
        sset = set(skus or [])
        target = [o for o in opts if o.canonical_sku in sset]
    elif mode == "empty":
        target = [o for o in opts if _norm(o.brand) is None]
    else:  # 'all'
        target = opts
    for o in target:
        o.brand = b
    session.flush()
    return len(target)


def brand_summary(session: Session, model_code: str) -> dict:
    """모음전의 브랜드 현황 — 스마트바("미지정 N개")·헤더 표시용.

    total / assigned(옵션 자체 브랜드 있음) / unassigned(미지정) / brands(고유 목록).
    """
    opts = (session.query(Option)
            .filter(Option.model_code == model_code).all())
    assigned = [o for o in opts if _norm(o.brand)]
    brands = sorted({_norm(o.brand) for o in assigned})
    return {
        "total": len(opts),
        "assigned": len(assigned),
        "unassigned": len(opts) - len(assigned),
        "brands": brands,
    }
