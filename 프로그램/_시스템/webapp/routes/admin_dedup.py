"""POST /api/admin/musinsa-dan/dedup — 무신사 단품 SourceOption dedup 마이그레이션.

대상: musinsa 사이트 + BundleSourceUrl.url_type='단품' 인 SourceProduct.
동작:
  - dry_run=1 (기본): 분류만, DB 변경 없음 (안전 미리보기)
  - dry_run=0:         실제 soft-delete + 백업 파일 생성
  - bundle=<model_code>: 해당 모음전만 대상

응답:
  {ok, dry_run, backup_path, sp_count, total_keep, total_delete, per_sp:[...]}
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

from shared.db import SessionLocal

_log = logging.getLogger(__name__)

bp = Blueprint("admin_dedup", __name__, url_prefix="/api/admin/musinsa-dan")


@bp.before_request
def _admin_only():
    """admin 게이트 — 팀공유 모드 아닐 때도 통과 (기존 단일사용자 환경)."""
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


@bp.post("/dedup")
def dedup_musinsa_dan():
    """무신사 단품 SourceOption dedup 실행.

    Query params:
      dry_run  '1'(기본) = 미리보기, '0'/'false' = 실제 변경
      bundle   model_code 필터 (생략 시 전체 musinsa 단품 SP)
    """
    dry_run_str = request.args.get("dry_run", "1").strip().lower()
    dry_run = dry_run_str not in ("0", "false")
    bundle = (request.args.get("bundle") or "").strip() or None

    s = SessionLocal()
    try:
        # ── 대상 SP 선택 ────────────────────────────────────────────────────
        # musinsa + BundleSourceUrl.url_type='단품' 인 SP
        from lemouton.sources.models import SourceProduct, SourceOption
        from lemouton.sourcing.models import BundleSourceUrl
        from lemouton.sources.service import _resolve_reg_color
        from lemouton.sources.dedup_migration import dedup_dan_sp
        from sqlalchemy import distinct

        # 단품 BundleSourceUrl 의 URL → musinsa SourceProduct 찾기
        bsu_q = (s.query(BundleSourceUrl)
                 .filter(BundleSourceUrl.url_type == "단품")
                 .filter(BundleSourceUrl.source_key == "musinsa"))
        if bundle:
            bsu_q = bsu_q.filter(BundleSourceUrl.model_code == bundle)
        bsu_rows = bsu_q.all()

        if not bsu_rows:
            return jsonify(
                ok=True, dry_run=dry_run,
                backup_path=None, sp_count=0,
                total_keep=0, total_delete=0, total_skipped=0,
                per_sp=[],
                message="대상 단품 BundleSourceUrl 없음",
            )

        # URL → SourceProduct 매핑 (normalize_url 비교)
        from lemouton.sources.service import normalize_url

        # musinsa SP 전체 (삭제 안 된)
        all_musinsa_sps = (s.query(SourceProduct)
                           .filter_by(site="musinsa", deleted_at=None)
                           .all())
        sp_norm_map: dict[str, SourceProduct] = {}
        for sp in all_musinsa_sps:
            sp_norm_map[normalize_url(sp.url or "")] = sp

        # 단품 BSU URL 로 SP 탐색 (중복 제거)
        target_sp_ids: set[int] = set()
        target_sps: list[SourceProduct] = []
        for bsu in bsu_rows:
            norm = normalize_url(bsu.url or "")
            sp = sp_norm_map.get(norm)
            if sp and sp.id not in target_sp_ids:
                target_sp_ids.add(sp.id)
                target_sps.append(sp)

        if not target_sps:
            return jsonify(
                ok=True, dry_run=dry_run,
                backup_path=None, sp_count=0,
                total_keep=0, total_delete=0, total_skipped=0,
                per_sp=[],
                message="대상 musinsa SourceProduct 없음",
            )

        # ── 백업 (real run 일 때) ────────────────────────────────────────────
        backup_path: str | None = None
        if not dry_run:
            sp_ids = [sp.id for sp in target_sps]
            all_opts = (s.query(SourceOption)
                        .filter(SourceOption.source_product_id.in_(sp_ids))
                        .all())
            backup_data = [
                {
                    "id": o.id,
                    "source_product_id": o.source_product_id,
                    "color_text": o.color_text,
                    "size_text": o.size_text,
                    "current_stock": o.current_stock,
                    "current_price": o.current_price,
                    "deleted_at": o.deleted_at.isoformat() if o.deleted_at else None,
                }
                for o in all_opts
            ]
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            data_dir = Path(__file__).resolve().parent.parent.parent / "data"
            data_dir.mkdir(exist_ok=True)
            backup_file = data_dir / f"_backup_dedup_{ts}.json"
            backup_file.write_text(
                json.dumps(backup_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            backup_path = str(backup_file)
            _log.info("dedup 백업 저장: %s (%d 행)", backup_path, len(backup_data))

        # ── 각 SP dedup 실행 ─────────────────────────────────────────────────
        per_sp = []
        total_keep = 0
        total_delete = 0
        total_skipped = 0

        for sp in target_sps:
            reg = _resolve_reg_color(s, sp)
            res = dedup_dan_sp(s, sp, reg_color=reg, dry_run=dry_run)
            per_sp.append({
                "sp_id": res["sp_id"],
                "sp_url": sp.url,
                "reg_color": res["reg_color"],
                "total": res["total"],
                "keep": res["keep"],
                "delete": res["delete"],
                "skipped": res["skipped"],
            })
            total_keep += len(res["keep"])
            total_delete += len(res["delete"])
            total_skipped += len(res["skipped"])

        # ── commit (real run) ────────────────────────────────────────────────
        if not dry_run:
            s.commit()
            _log.info(
                "dedup 완료: SP %d개, keep %d / delete %d / skipped %d",
                len(target_sps), total_keep, total_delete, total_skipped,
            )

        return jsonify(
            ok=True,
            dry_run=dry_run,
            backup_path=backup_path,
            sp_count=len(target_sps),
            total_keep=total_keep,
            total_delete=total_delete,
            total_skipped=total_skipped,
            per_sp=per_sp,
        )

    except Exception as e:
        s.rollback()
        _log.exception("dedup_musinsa_dan 실패")
        return jsonify(ok=False, error=str(e)[:300]), 500
    finally:
        s.close()
