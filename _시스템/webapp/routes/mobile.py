"""
모바일 PWA — 바코드 스캔 + 빠른 재고관리.

신규 폴더 전용 (.sync-ignore 보호). 기존 inventory 코드 0 수정 — 호출만.
ENVIRONMENT=team-share-dev 시 활성화 (login 게이트 기존 webapp.auth 가 처리).

라우트:
  GET  /mobile                 → 모바일 홈
  GET  /mobile/scan            → 바코드 스캔 UI
  GET  /mobile/sku/<sku>       → 옵션 상세 + 액션 선택
  GET  /mobile/inventory       → 재고 목록 (모바일)

  POST /mobile/api/lookup      → 바코드 → SKU 검색
  POST /mobile/api/action      → 입고/출고/조정 실행
  GET  /mobile/api/locations   → 위치 목록
  GET  /mobile/api/stock/<sku> → 현재 재고 (위치별)
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func

from shared.db import SessionLocal
from lemouton.inventory.models import (
    InventoryLocation, InventoryTx,
)
from lemouton.sourcing.models import Option, Model

logger = logging.getLogger(__name__)

bp = Blueprint("mobile", __name__, url_prefix="/mobile")


# ─── 페이지 라우트 ───
@bp.route("/")
def home():
    return render_template("mobile/home.html")


@bp.route("/scan")
def scan_page():
    return render_template("mobile/scan.html")


@bp.route("/sku/<path:sku>")
def sku_detail(sku: str):
    return render_template("mobile/action.html", sku=sku)


@bp.route("/inventory")
def inventory_list():
    return render_template("mobile/inventory.html")


# ─── API 라우트 ───
def _err(msg: str, code: int = 400):
    return jsonify(ok=False, error=msg), code


def _ok(**kw):
    return jsonify(ok=True, **kw)


@bp.route("/api/locations")
def api_locations():
    """위치 목록 (드롭다운 / 버튼)."""
    with SessionLocal() as s:
        rows = (
            s.query(InventoryLocation)
            .filter(InventoryLocation.deleted_at.is_(None))
            .order_by(InventoryLocation.is_default.desc(),
                      InventoryLocation.sort_order,
                      InventoryLocation.id)
            .all()
        )
        return _ok(locations=[
            {"id": r.id, "name": r.name, "is_default": bool(r.is_default)}
            for r in rows
        ])


@bp.route("/api/lookup", methods=["POST"])
def api_lookup():
    """바코드 → 옵션 매칭.

    검색 순서:
      1. boxhero_sku 완전 일치 (대소문자 무시)
      2. canonical_sku 완전 일치
      3. boxhero_sku 부분 일치 (LIKE)
      4. canonical_sku 부분 일치

    Returns: {ok, option: {canonical_sku, model_code, color, size, stock, image_url, boxhero_sku, model_name}}
    """
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return _err("바코드/SKU 누락")

    with SessionLocal() as s:
        # 1. boxhero_sku 정확 매칭
        opt = (s.query(Option)
               .filter(func.lower(Option.boxhero_sku) == code.lower())
               .first())
        if not opt:
            # 2. canonical_sku 정확
            opt = (s.query(Option)
                   .filter(Option.canonical_sku == code)
                   .first())
        if not opt:
            # 3. boxhero_sku 부분
            opt = (s.query(Option)
                   .filter(Option.boxhero_sku.ilike(f"%{code}%"))
                   .first())
        if not opt:
            # 4. canonical_sku 부분
            opt = (s.query(Option)
                   .filter(Option.canonical_sku.ilike(f"%{code}%"))
                   .first())

        if not opt:
            return _err(f"SKU 못 찾음: {code}", 404)

        # 모델 정보
        model = s.query(Model).filter_by(model_code=opt.model_code).first()
        model_name = model.model_code if model else opt.model_code

        # 현재 재고 (모든 위치 합)
        stock = (s.query(func.sum(InventoryTx.qty))
                 .filter(InventoryTx.option_canonical_sku == opt.canonical_sku)
                 .filter(InventoryTx.status == 'completed')
                 .scalar()) or 0

        return _ok(option={
            "canonical_sku": opt.canonical_sku,
            "boxhero_sku": opt.boxhero_sku,
            "model_code": opt.model_code,
            "model_name": model_name,
            "color_code": opt.color_code,
            "size_code": opt.size_code,
            "image_url": opt.image_url,
            "stock": int(stock),
        })


@bp.route("/api/stock/<path:sku>")
def api_stock(sku: str):
    """위치별 재고 분포."""
    with SessionLocal() as s:
        rows = (
            s.query(
                InventoryLocation.id,
                InventoryLocation.name,
                func.coalesce(func.sum(InventoryTx.qty), 0).label("stock"),
            )
            .outerjoin(
                InventoryTx,
                (InventoryTx.location_id == InventoryLocation.id)
                & (InventoryTx.option_canonical_sku == sku)
                & (InventoryTx.status == 'completed'),
            )
            .filter(InventoryLocation.deleted_at.is_(None))
            .group_by(InventoryLocation.id, InventoryLocation.name)
            .order_by(InventoryLocation.sort_order, InventoryLocation.id)
            .all()
        )
        out = [
            {"location_id": lid, "location_name": name, "stock": int(stock)}
            for lid, name, stock in rows
        ]
        total = sum(r["stock"] for r in out)
        return _ok(by_location=out, total=total)


@bp.route("/api/action", methods=["POST"])
def api_action():
    """입고/출고/조정 트랜잭션 1건 기록.

    payload: {
      sku: str (canonical_sku),
      action: 'in' | 'out' | 'adjust',
      location_id: int,
      qty: int,                # in/out: +qty / adjust: 새 절대값
      memo: str (optional),
    }

    조정 (adjust):
      - 현재 해당 위치 재고를 qty 로 맞춤
      - delta = qty - 현재재고 → 그 delta 를 새 trans 로 기록
    """
    data = request.get_json(silent=True) or {}
    sku = (data.get("sku") or "").strip()
    action = (data.get("action") or "").strip().lower()
    try:
        location_id = int(data.get("location_id") or 0)
        qty = int(data.get("qty") or 0)
    except (TypeError, ValueError):
        return _err("location_id / qty 숫자 아님")
    memo = (data.get("memo") or "").strip() or None

    if action not in ("in", "out", "adjust"):
        return _err("action 은 in / out / adjust 만")
    if not sku:
        return _err("sku 필수")
    if not location_id:
        return _err("location_id 필수")
    if action in ("in", "out") and qty <= 0:
        return _err("qty 는 양수")
    if action == "adjust" and qty < 0:
        return _err("조정 qty 는 0 이상")

    from flask_login import current_user
    actor = (getattr(current_user, "email", None) if current_user.is_authenticated
             else "system")

    with SessionLocal() as s:
        # 옵션 존재 확인
        opt = s.query(Option).filter_by(canonical_sku=sku).first()
        if not opt:
            return _err(f"SKU 없음: {sku}", 404)

        # 위치 확인
        loc = s.query(InventoryLocation).filter_by(id=location_id).first()
        if not loc or loc.deleted_at:
            return _err("위치 없음", 404)

        # 트랜잭션 qty 계산
        if action == "in":
            tx_qty = qty
            tx_memo = memo or f"[모바일 입고]"
        elif action == "out":
            tx_qty = -qty
            tx_memo = memo or f"[모바일 출고]"
        else:  # adjust
            # 해당 위치의 현재 재고
            current = (s.query(func.coalesce(func.sum(InventoryTx.qty), 0))
                       .filter(InventoryTx.option_canonical_sku == sku)
                       .filter(InventoryTx.location_id == location_id)
                       .filter(InventoryTx.status == 'completed')
                       .scalar() or 0)
            tx_qty = int(qty) - int(current)
            if tx_qty == 0:
                return _ok(message="변경 없음 (현재 재고와 동일)", tx_id=None)
            tx_memo = memo or f"[모바일 조정] {current} → {qty}"

        tx = InventoryTx(
            tx_type=action,
            location_id=location_id,
            option_canonical_sku=sku,
            qty=tx_qty,
            memo=tx_memo,
            created_by=actor,
            source='local',
            status='completed',
            created_at=dt.datetime.utcnow(),
        )
        s.add(tx)
        s.commit()

        # 갱신된 재고
        new_total = (s.query(func.sum(InventoryTx.qty))
                     .filter(InventoryTx.option_canonical_sku == sku)
                     .filter(InventoryTx.status == 'completed')
                     .scalar()) or 0

        logger.info(f"[mobile] {actor} {action} sku={sku} qty={tx_qty} loc={loc.name}")
        return _ok(
            tx_id=tx.id,
            action=action,
            applied_qty=tx_qty,
            new_total_stock=int(new_total),
            location_name=loc.name,
            actor=actor,
        )


@bp.route("/api/recent", methods=["GET"])
def api_recent():
    """최근 트랜잭션 (홈에서 활동 피드)."""
    with SessionLocal() as s:
        rows = (
            s.query(InventoryTx, InventoryLocation.name)
            .outerjoin(InventoryLocation, InventoryLocation.id == InventoryTx.location_id)
            .filter(InventoryTx.status == 'completed')
            .filter(InventoryTx.source == 'local')
            .order_by(InventoryTx.created_at.desc())
            .limit(20)
            .all()
        )
        out = []
        for tx, loc_name in rows:
            out.append({
                "id": tx.id,
                "tx_type": tx.tx_type,
                "sku": tx.option_canonical_sku,
                "qty": tx.qty,
                "location": loc_name or "?",
                "memo": tx.memo,
                "actor": tx.created_by or "?",
                "at": tx.created_at.isoformat() if tx.created_at else None,
            })
        return _ok(items=out)
