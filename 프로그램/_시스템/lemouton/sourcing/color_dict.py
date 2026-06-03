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


def _ns(text: str) -> str:
    """공백 무시 비교용 정규화 — 모든 공백 제거 + 소문자.

    소싱처 옵션 색상명은 '올리브 그린'처럼 띄어쓰기가 있을 수 있어,
    우리 표준 '올리브그린'(붙임)과 매칭되도록 공백을 무조건 제거한다.
    """
    return "".join((text or "").split()).lower()


def normalize(session: Session, raw: str) -> str | None:
    """텍스트 → 표준 색상 코드 (한글). 매칭 안 되면 None.

    공백 무시 매칭 — '올리브 그린' == '올리브그린'.
    """
    if not raw:
        return None
    raw_ns = _ns(raw)
    if not raw_ns:
        return None

    for cd in list_colors(session):
        try:
            variants = json.loads(cd.variants_json)
        except (json.JSONDecodeError, TypeError):
            continue
        # color_code 자체도 후보에 포함 (사전에 없어도 코드명과 직접 일치 허용)
        if _ns(cd.color_code) == raw_ns:
            return cd.color_code
        for v in variants:
            if v and _ns(v) == raw_ns:
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
