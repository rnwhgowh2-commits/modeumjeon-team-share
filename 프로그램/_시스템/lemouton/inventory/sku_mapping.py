"""[I] sku_mapping.py — 박스히어로 SKU ↔ 모음전 옵션 fuzzy 자동 매핑.

Q3 결정: D (자동 + 수동 보완) — fuzzy 점수 기반 큐.

알고리즘 (LIGHT_SPEC §4-3):
  - exact (정규화 model+size+color 모두 일치) = 100
  - model_name + size 일치 = 80
  - model_name 일치 + size 다름 = 50
  - 그 외 = 0~50 부분 점수
  → ≥80 자동 적용 / 50~79 검토 큐 / <50 unmapped

ai-workflow STEP 7 Sprint 1B Task 1.7
"""
import re
from typing import NamedTuple, Optional
from sqlalchemy.orm import Session

from lemouton.sourcing.models import Option, Model


# ============ 정규화 ============

def normalize(text: Optional[str]) -> str:
    """공백·특수문자·하이픈 제거 + lowercase. 매칭 키 생성."""
    if not text:
        return ''
    t = re.sub(r'[\s\-_/\\.,()\[\]{}#]+', '', str(text))
    return t.lower()


def normalize_size(size: Optional[str]) -> str:
    """사이즈 정규화 — 숫자만 추출 (220mm → 220, 'L' → 'l')."""
    if not size:
        return ''
    s = str(size).strip().lower()
    # 숫자가 포함되면 숫자만 추출 (예: '225mm' → '225')
    nums = re.findall(r'\d+', s)
    if nums:
        return nums[0]
    return s


# ============ 매칭 후보 ============

class Match(NamedTuple):
    option_canonical_sku: str
    boxhero_sku: str
    score: int                   # 0~100
    reason: str                  # 'exact' | 'model_size' | 'model_only' | 'partial'
    boxhero_record: dict         # 박스히어로 원본 row (디버그·표시용)


def score_pair(option: Option, model: Model, bh: dict) -> tuple[int, str]:
    """단일 옵션-박스히어로 row 점수.

    매칭 원칙: model + size + color 가 모두 일치해야 자동 매핑 (1:1 보장).
    색상 무시는 1:N 잘못된 매핑을 야기하므로 금지.

    bh dict 키: model_name·size·color·name·sku 등 (boxhero_xlsx 파서 결과)
    """
    bh_model = normalize(bh.get('model_name') or bh.get('name') or '')
    bh_size = normalize_size(bh.get('size'))
    bh_color = normalize(bh.get('color_text') or bh.get('color') or '')

    our_model = normalize(model.model_name_display or model.model_name_raw)
    our_size = normalize_size(option.size_display or option.size_code)
    our_color = normalize(option.color_display or option.color_code)

    if not bh_model or not our_model:
        return 0, 'no_data'

    # 모델명: substring 일치 (정규화 후 한쪽이 다른 쪽에 포함)
    model_match = (bh_model in our_model) or (our_model in bh_model) or (bh_model == our_model)
    if not model_match:
        return 0, 'no_match'

    # 사이즈: 정확 일치 필수
    if not (bh_size and our_size and bh_size == our_size):
        return 0, 'size_mismatch'

    # 색상: 정확 일치 → 100 (자동매핑). 색상 다름 → 0 (매핑 거부).
    if bh_color and our_color:
        if bh_color == our_color:
            return 100, 'exact'
        return 0, 'color_mismatch'

    # 색상 데이터 한쪽 누락 — 검토 큐로 (model+size 만 일치)
    return 60, 'model_size_only'


# ============ 자동 매핑 ============

def fuzzy_match_option(session: Session, option: Option, boxhero_records: list[dict],
                       threshold_auto: int = 80, threshold_review: int = 50
                       ) -> list[Match]:
    """한 옵션에 대한 박스히어로 후보 매치 list (점수 desc)."""
    model = session.query(Model).filter(Model.model_code == option.model_code).first()
    if not model:
        return []

    matches = []
    for bh in boxhero_records:
        score, reason = score_pair(option, model, bh)
        if score >= threshold_review:
            matches.append(Match(
                option_canonical_sku=option.canonical_sku,
                boxhero_sku=bh.get('sku', ''),
                score=score,
                reason=reason,
                boxhero_record=bh,
            ))
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


def auto_map_all(session: Session, boxhero_records: list[dict],
                 threshold_auto: int = 80) -> dict:
    """전체 옵션 ↔ 박스히어로 자동 매핑.

    Returns:
        {
            'mapped': [(option_sku, boxhero_sku, score), ...],  # 자동 매핑 적용
            'queued': [(option_sku, boxhero_sku, score), ...],  # 검토 큐 (50~79)
            'unmapped': [option_sku, ...],                       # 후보 ❌
            'already_mapped': [option_sku, ...],                 # 이미 boxhero_sku 있음
        }
    """
    options = session.query(Option).all()
    result = {'mapped': [], 'queued': [], 'unmapped': [], 'already_mapped': []}

    # 1:1 보장 lock — 이미 다른 옵션에 매핑된 박스히어로 SKU 는 재사용 금지
    used_bh_skus = set(
        s for (s,) in session.query(Option.boxhero_sku).filter(Option.boxhero_sku.isnot(None)).all()
        if s
    )

    for opt in options:
        if opt.boxhero_sku:
            result['already_mapped'].append(opt.canonical_sku)
            continue

        matches = fuzzy_match_option(session, opt, boxhero_records,
                                      threshold_review=50)
        # 이미 다른 옵션에 매핑된 박스히어로 SKU 는 후보에서 제외
        matches = [m for m in matches if m.boxhero_sku not in used_bh_skus]
        if not matches:
            result['unmapped'].append(opt.canonical_sku)
            continue

        top = matches[0]
        if top.score >= threshold_auto:
            opt.boxhero_sku = top.boxhero_sku
            used_bh_skus.add(top.boxhero_sku)
            result['mapped'].append((opt.canonical_sku, top.boxhero_sku, top.score))
        else:
            result['queued'].append((opt.canonical_sku, top.boxhero_sku, top.score))

    return result


def list_unmapped_options(session: Session) -> list[Option]:
    """boxhero_sku 가 NULL 인 옵션 목록 (수동 매핑 큐)."""
    return (
        session.query(Option)
        .filter(Option.boxhero_sku.is_(None))
        .all()
    )
