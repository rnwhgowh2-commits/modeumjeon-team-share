"""무신사 단품 SourceOption dedup 마이그레이션.

단품 SourceProduct 에 오염된 형제색·대소문자 중복 행을 안전하게 정리한다.

핵심 보장:
  - soft-delete ONLY (deleted_at 설정) — hard-delete 절대 금지
  - dry_run=True 가 기본값 (명시적 False 만 실제 변경)
  - reg_color=None 이면 no-op (보수적)
  - 한 사이즈에 등록색 후보가 없으면 기존 행 유지 (0행 방지)
  - commit 은 caller 가 함 (이 함수 내에서 commit 안 함)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import SourceOption, SourceProduct
from .service import _cnorm_color, _norm_size

_log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dedup_dan_sp(
    session: Session,
    source_product: SourceProduct,
    reg_color: str | None,
    dry_run: bool = True,
) -> dict:
    """단품 SourceProduct 의 오염된 SourceOption 행을 정리한다.

    Args:
      session:        SQLAlchemy 세션 (commit 은 caller 가 함)
      source_product: 대상 SourceProduct
      reg_color:      등록 색상 (예: '오렌지'). None 이면 no-op.
      dry_run:        True(기본)=분류만/DB무변경, False=실제 soft-delete

    Returns:
      {
        sp_id:      int,
        reg_color:  str | None,
        total:      int,            # 처리 대상 행 수
        keep:       [{id, color, size, stock}],   # 유지 행
        delete:     [{id, color, size, stock}],   # soft-delete 행
        skipped:    [{id, color, size, stock}],   # 보수적 유지 (해당 사이즈 등록색 없음)
      }

    Canonical-pick rule (사이즈 그룹 내 등록색 후보 중):
      1. current_stock 이 non-None 인 행 우선 (실재고 데이터 보존)
      2. 동점이면 current_stock 값 높은 행 우선 (최대 재고)
      3. 최종 동점이면 id 가 낮은(먼저 upsert된) 행 우선 (안정성)
      4. 하나만 keep, 나머지는 delete
    """
    sp_id = source_product.id
    result: dict = {
        "sp_id": sp_id,
        "reg_color": reg_color,
        "total": 0,
        "keep": [],
        "delete": [],
        "skipped": [],
    }

    # 활성(deleted_at=None) 옵션 전체 수집
    all_opts: list[SourceOption] = (
        session.query(SourceOption)
        .filter_by(source_product_id=sp_id, deleted_at=None)
        .all()
    )
    result["total"] = len(all_opts)

    # reg_color 없으면 no-op (보수적)
    if not reg_color:
        result["keep"] = [_so_dict(o) for o in all_opts]
        return result

    rc_norm = _cnorm_color(reg_color)

    # ── 1단계: 분류 (사이즈 그룹별) ─────────────────────────────────────────
    # 먼저 분류만 완료해 keep/delete/skipped 결정 → 2단계에서 DB 반영
    by_norm_size: dict[str, list[SourceOption]] = defaultdict(list)
    for o in all_opts:
        ns = _norm_size(o.size_text)
        by_norm_size[ns].append(o)

    # 분류 결과
    winners: list[tuple[SourceOption, str]] = []   # (winner_so, norm_size)
    to_delete: list[SourceOption] = []
    skipped: list[SourceOption] = []

    for ns, group in by_norm_size.items():
        # 등록색 일치 후보 (cnorm 포함·포함됨 모두 통과 — _scope_options_to_color 와 동일 정책)
        candidates = [
            o for o in group
            if _cnorm_color(o.color_text) == rc_norm
            or rc_norm in _cnorm_color(o.color_text)
            or _cnorm_color(o.color_text) in rc_norm
        ]
        # 타색 행 (등록색 아님)
        others = [o for o in group if o not in candidates]

        if not candidates:
            # 이 사이즈에 등록색 없음 → 보수적 유지 (0행 방지)
            skipped.extend(others)
            continue

        # 후보 중 canonical pick:
        # (non-None stock, stock 값, -id) 기준 — id 작은 것 우선(안정)
        def _pick_key(o: SourceOption):
            has_stock = 0 if o.current_stock is None else 1
            stock_val = o.current_stock if o.current_stock is not None else -1
            return (has_stock, stock_val, -o.id)

        candidates_sorted = sorted(candidates, key=_pick_key, reverse=True)
        winner = candidates_sorted[0]
        dup_candidates = candidates_sorted[1:]

        winners.append((winner, ns))
        to_delete.extend(dup_candidates)
        to_delete.extend(others)

    # ── 2단계: DB 반영 (not dry_run 일 때만) ────────────────────────────────
    if not dry_run:
        # 먼저 delete 행들 soft-delete (unique 제약 충돌 방지 — winner 정규화 전에)
        _now = _utcnow()
        for o in to_delete:
            o.deleted_at = _now
        # session.flush 로 delete 먼저 DB 에 반영
        session.flush()

        # 그 다음 winner 정규화 (deleted 행들이 이미 제거됐으므로 unique 충돌 없음)
        for winner, ns in winners:
            winner.color_text = reg_color
            if ns and winner.size_text != ns:
                winner.size_text = ns

    # ── 결과 dict 구성 ───────────────────────────────────────────────────────
    for winner, ns in winners:
        result["keep"].append({
            "id": winner.id,
            "color": reg_color,
            "size": ns if ns else winner.size_text,
            "stock": winner.current_stock,
        })

    for o in to_delete:
        result["delete"].append(_so_dict(o))

    for o in skipped:
        result["skipped"].append(_so_dict(o))

    return result


def _so_dict(o: SourceOption) -> dict:
    return {
        "id": o.id,
        "color": o.color_text,
        "size": o.size_text,
        "stock": o.current_stock,
    }
