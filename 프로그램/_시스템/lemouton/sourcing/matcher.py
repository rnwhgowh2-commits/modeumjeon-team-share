"""자동 디스커버리 매처 — 외부 데이터 → 표준 SKU 매칭 시도."""
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import select

from .models import Model, Option
from .color_dict import normalize as normalize_color


@dataclass
class MatchResult:
    canonical_sku: str | None
    suggested_model_code: str | None
    suggested_color_code: str | None
    suggested_size_code: str | None
    confidence: float


def _find_model_by_name(session: Session, brand: str, model_name_raw: str) -> Model | None:
    stmt = select(Model).where(
        Model.brand == brand,
        Model.model_name_raw == model_name_raw,
    )
    return session.scalars(stmt).first()


def try_match_canonical(
    session: Session,
    *,
    brand: str,
    model_name_raw: str,
    color_text: str,
    size_text: str,
) -> MatchResult:
    """텍스트 입력 → 표준 SKU 매칭 시도. 실패 시 부분 결과 반환."""
    # 1. 모델 매칭
    model = _find_model_by_name(session, brand, model_name_raw)
    if model is None:
        return MatchResult(None, None, normalize_color(session, color_text),
                           size_text or None, 0.0)

    # 2. 색상 정규화
    color_code = normalize_color(session, color_text)
    if color_code is None:
        return MatchResult(None, model.model_code, None, size_text or None, 0.3)

    # 3. 사이즈 정규화 — "230mm" → "230" (소싱처별 표기 차이 흡수)
    size_code = (size_text or "").strip()
    # 신발 사이즈: 끝의 mm/MM 제거
    if size_code.lower().endswith("mm"):
        size_code = size_code[:-2].strip()
    if not size_code:
        return MatchResult(None, model.model_code, color_code, None, 0.5)

    # 4. 옵션 매핑 조회
    canonical_sku = f"{model.model_code}-{color_code}-{size_code}"
    opt = session.get(Option, canonical_sku)
    if opt is None:
        return MatchResult(None, model.model_code, color_code, size_code, 0.7)

    return MatchResult(canonical_sku, model.model_code, color_code, size_code, 1.0)
