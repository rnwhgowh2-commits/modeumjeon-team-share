"""색상 정규화 사전 — 변형 텍스트를 표준 코드로 매핑.

User decision: color_code는 한글로 저장. variants_json에 한글 + 영문 변형 포함.
"""
import json
from sqlalchemy.orm import Session
from sqlalchemy import select

from .models import ColorDict


def set_color(session: Session, color_code: str, variants: list[str]) -> ColorDict:
    existing = session.get(ColorDict, color_code)
    payload = json.dumps(variants, ensure_ascii=False)
    if existing is None:
        cd = ColorDict(color_code=color_code, variants_json=payload)
        session.add(cd)
        return cd
    existing.variants_json = payload
    return existing


def get_color(session: Session, color_code: str) -> ColorDict | None:
    return session.get(ColorDict, color_code)


def list_colors(session: Session) -> list[ColorDict]:
    return list(session.scalars(select(ColorDict)).all())


def normalize(session: Session, raw: str) -> str | None:
    """텍스트 → 표준 색상 코드 (한글). 매칭 안 되면 None."""
    if not raw:
        return None
    raw_clean = raw.strip()

    for cd in list_colors(session):
        try:
            variants = json.loads(cd.variants_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for v in variants:
            if v and v.strip().lower() == raw_clean.lower():
                return cd.color_code
    return None


# 르무통 기본 색상 사전 — color_code 한글
_DEFAULTS = {
    "브라운":      ["브라운", "Brown", "BR", "갈색", "다크브라운"],
    "블랙":        ["블랙", "Black", "BK", "검정", "검은색"],
    "화이트":      ["화이트", "White", "WT", "흰색"],
    "네이비":      ["네이비", "Navy", "NV", "남색"],
    "그레이":      ["그레이", "Grey", "Gray", "GY", "회색"],
    "블랙블랙":    ["블랙블랙", "블랙(블랙아웃솔)"],
}


def bootstrap_defaults(session: Session) -> int:
    """기본 색상 사전을 등록 (이미 있는 코드는 덮어쓰기)."""
    for code, variants in _DEFAULTS.items():
        set_color(session, code, variants)
    return len(_DEFAULTS)
