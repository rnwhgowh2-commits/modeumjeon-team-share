"""[v2] 외부 마켓 옵션 ↔ 우리 시스템 옵션 자동 매칭.

색상 사전 + 사이즈 사전 lookup 으로 자동 매칭.
매칭 실패·충돌 시 사용자 confirm 필요.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session


SIZE_NUMERIC_RE = re.compile(r'(\d{2,4})')


def _normalize(s: str) -> str:
    """공백·특수문자 제거 + 소문자."""
    return re.sub(r'[\s\-_/().,]+', '', (s or '').lower())


def _extract_size_number(text: str) -> Optional[str]:
    """'240mm', '240 mm', '240', 'XL(95)' 등에서 숫자 추출."""
    if not text:
        return None
    m = SIZE_NUMERIC_RE.search(text)
    return m.group(1) if m else None


@dataclass
class MatchResult:
    """단일 옵션 매칭 결과."""
    canonical_sku: str            # 우리 시스템 옵션
    color_code: str
    size_code: str
    matched_option_id: Optional[int] = None      # 매칭된 외부 옵션 ID
    matched_external_name: Optional[str] = None
    confidence: str = 'failed'    # 'auto' | 'fuzzy' | 'failed' | 'manual'
    candidates: list = field(default_factory=list)  # 충돌·실패 시 후보 list
    reason: Optional[str] = None


def _build_color_lookup(session: Session) -> dict[str, str]:
    """색상 사전 → {정규화된 변형텍스트: 표준_color_code}.

    예: '블랙' → '블랙', 'BK' → '블랙', 'Black' → '블랙'
    """
    from lemouton.sourcing.models import ColorDict
    lookup: dict[str, str] = {}
    for c in session.query(ColorDict).all():
        std = c.color_code
        # 표준 코드 자체도 매칭 키
        lookup[_normalize(std)] = std
        try:
            variants = json.loads(c.variants_json or '[]')
        except Exception:
            variants = []
        for v in variants:
            if v:
                lookup[_normalize(v)] = std
    return lookup


def match_external_options_to_ours(
    session: Session,
    *,
    model_code: str,
    external_options: list,   # list of OptionRow (option_id, name1, name2)
) -> list[MatchResult]:
    """외부 옵션 → 우리 옵션 매칭.

    Returns:
      list[MatchResult] — 우리 옵션 each 1개씩, 매칭된 외부 옵션 ID 또는 후보
    """
    from lemouton.sourcing.models import Option

    our_options = (session.query(Option)
                   .filter_by(model_code=model_code)
                   .all())
    color_lookup = _build_color_lookup(session)

    # 외부 옵션 인덱싱: (정규화_color, 정규화_size) → list[external_opt]
    external_index: dict[tuple, list] = {}
    for ext in external_options:
        norm_color = _normalize(ext.name1 or '')
        # 색상 lookup → 표준 색상 코드 (있으면 사용, 없으면 원본 정규화)
        std_color = color_lookup.get(norm_color, norm_color)
        # 사이즈는 숫자만 추출
        size_num = _extract_size_number(ext.name2 or '') or _normalize(ext.name2 or '')
        key = (_normalize(std_color), size_num)
        external_index.setdefault(key, []).append(ext)

    results = []
    used_external_ids = set()

    for o in our_options:
        our_color_norm = _normalize(o.color_code)
        our_size_num = _extract_size_number(o.size_code) or _normalize(o.size_code)
        key = (our_color_norm, our_size_num)

        candidates = external_index.get(key, [])
        # 이미 매칭에 사용된 ID 제외
        candidates = [c for c in candidates if c.option_id not in used_external_ids]

        if len(candidates) == 1:
            # 100% 자동 매칭
            ext = candidates[0]
            used_external_ids.add(ext.option_id)
            results.append(MatchResult(
                canonical_sku=o.canonical_sku,
                color_code=o.color_code,
                size_code=o.size_code,
                matched_option_id=ext.option_id,
                matched_external_name=ext.display_name,
                confidence='auto',
            ))
        elif len(candidates) > 1:
            # 충돌 (같은 색상·사이즈가 외부에 여러 개 — 예: 「블랙(블랙아웃솔)」 vs 「블랙(화이트아웃솔)」)
            results.append(MatchResult(
                canonical_sku=o.canonical_sku,
                color_code=o.color_code,
                size_code=o.size_code,
                confidence='fuzzy',
                candidates=[{
                    'option_id': c.option_id,
                    'name': c.display_name,
                    'stock': c.stock,
                } for c in candidates],
                reason='같은 색상·사이즈에 여러 외부 옵션 존재 — 사용자 선택 필요',
            ))
        else:
            # 매칭 실패
            # 사이즈만 같은 후보 (색상 다른) 도 보여줌 — 사용자 참고용
            same_size = [
                ext for (k_color, k_size), exts in external_index.items()
                if k_size == our_size_num
                for ext in exts if ext.option_id not in used_external_ids
            ]
            results.append(MatchResult(
                canonical_sku=o.canonical_sku,
                color_code=o.color_code,
                size_code=o.size_code,
                confidence='failed',
                candidates=[{
                    'option_id': c.option_id,
                    'name': c.display_name,
                    'stock': c.stock,
                } for c in same_size[:10]],
                reason='색상 사전에서 매칭 실패 — 사용자 수동 선택 필요',
            ))

    return results


def apply_matching(
    session: Session,
    *,
    model_code: str,
    matches: list[dict],    # [{canonical_sku, naver_option_id}]
) -> dict:
    """매칭 결과 → DB 저장 (Option.naver_option_id).

    Returns:
      {'updated': N, 'failed': N}
    """
    from lemouton.sourcing.models import Option
    updated = 0
    failed = 0
    for m in matches:
        sku = m.get('canonical_sku')
        opt_id = m.get('naver_option_id')
        if not sku or not opt_id:
            failed += 1
            continue
        o = session.query(Option).filter_by(canonical_sku=sku).first()
        if o is None:
            failed += 1
            continue
        o.naver_option_id = str(opt_id)
        updated += 1
    return {'updated': updated, 'failed': failed}


def auto_learn_color_variant(
    session: Session,
    *,
    standard_code: str,
    new_variant: str,
) -> bool:
    """사용자가 매핑 confirm 시 색상 사전에 변형 자동 추가.

    예: 사용자가 「스카이블루」 → 「라이트블루」 매핑하면
    「라이트블루」 사전에 「스카이블루」 변형 자동 추가.
    """
    from lemouton.sourcing.models import ColorDict
    c = session.query(ColorDict).filter_by(color_code=standard_code).first()
    if c is None:
        return False
    try:
        variants = json.loads(c.variants_json or '[]')
    except Exception:
        variants = []
    if new_variant not in variants:
        variants.append(new_variant)
        c.variants_json = json.dumps(variants, ensure_ascii=False)
        return True
    return False
