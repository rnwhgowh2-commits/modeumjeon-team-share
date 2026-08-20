"""
모바일 PWA — 바코드 스캔 + 빠른 재고관리.

inventory 코드 0 수정 — 호출만.
ENVIRONMENT=team-share-dev 시 활성화 (login 게이트 기존 webapp.auth 가 처리).

라우트:
  GET  /mobile                 → 모바일 홈
  GET  /mobile/scan            → 바코드 스캔 UI
  GET  /mobile/sku/<sku>       → 옵션 상세 + 액션 선택
  GET  /mobile/inventory       → 재고 목록 (모바일)

  POST /mobile/api/lookup      → 바코드 → SKU 검색
  POST /mobile/api/action      → 입고/출고/조정 실행
  POST /mobile/api/transfer    → 위치 이동 (A4 — 폰의 유일한 쓰기, create_move 재사용)
  GET  /mobile/api/locations   → 위치 목록
  GET  /mobile/api/stock/<sku> → 현재 재고 (위치별, SSOT)
  GET  /mobile/api/product/<sku> → 제품 정보 + 색상×사이즈 표 (B1·C1·C4 상세 시트)
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func

from shared.db import SessionLocal
from lemouton.inventory.models import (
    InventoryLocation, InventoryTx, InventoryProduct,
)
from lemouton.sourcing.models import Option, Model

logger = logging.getLogger(__name__)

bp = Blueprint("mobile", __name__, url_prefix="/mobile")


# ─── 페이지 라우트 ───
@bp.route("/")
def home():
    # 🔴 이 import 는 **함수 안**에 둔다 — mobile_shell.menu() 와 같은 이유.
    #   시험이 flask_login.current_user 를 갈아끼워 admin/member 두 갈래를 보는데,
    #   상단 import 는 갈아끼우기 전의 프록시를 모듈에 붙잡아 둔다.
    from flask_login import current_user

    # 홈의 크롤 한 줄은 admin 전용(Task 7B) — /mobile/crawl/* 의 blueprint 게이트
    # (mobile_crawl._admin_only)와 같은 판정(is_admin)을 쓴다. member 에게 그리면
    # 매번 403 을 받아 고칠 수도 없는 「불러오지 못했습니다」 줄이 된다.
    return render_template("mobile/home.html",
                           is_admin=bool(getattr(current_user, "is_admin", False)))


@bp.route("/scan")
def scan_page():
    return render_template("mobile/scan.html")


@bp.route("/scan-batch")
def scan_batch_page():
    """연속 스캔 입고/출고 페이지 — 시안 A (상단 카메라 + 스크롤 list).

    Query: ?mode=in / ?mode=out
    """
    mode = (request.args.get("mode") or "in").lower()
    if mode not in ("in", "out"):
        mode = "in"
    return render_template("mobile/scan_batch.html", mode=mode)


@bp.route("/scan-ship")
def scan_ship_page():
    """포장 스캔 — 바코드를 찍어 「이 주문이 나갔다」를 확정한다.

    사입으로 표시된 줄만 재고가 깎인다(규칙 정본 = inventory/order_outbound.py).
    """
    return render_template("mobile/scan_ship.html")


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
      1.  InventoryProduct.barcode 완전 일치 (실 제품 EAN-13)
      1b. Option.barcode 완전 일치 (라벨 인쇄가 인코딩하는 값)
      2.  boxhero_sku 완전 일치 (대소문자 무시)
      3.  canonical_sku 완전 일치
      4~6. 위 항목들의 부분 일치 (ILIKE)

    Returns: {ok, option: {canonical_sku, model_code, color, size, stock, image_url, boxhero_sku, model_name}}
    """
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return _err("바코드/SKU 누락")

    with SessionLocal() as s:
        # 매핑 검색 순서 (실 운영 우선순위):
        # 1. InventoryProduct.barcode == 정확 매칭 (EAN-13 등 실 바코드)
        # 2. Option.boxhero_sku == (박스히어로 내부 코드, SKU-XXX)
        # 3. Option.canonical_sku == (내부 SKU 명)
        # 4~6. 위 3개 부분 매칭 (ILIKE)
        opt = None
        match_via = None

        # 1. 실 바코드 (EAN-13 등) — InventoryProduct 에서
        ip = (s.query(InventoryProduct)
              .filter(InventoryProduct.barcode == code)
              .first())
        if ip and ip.canonical_sku:
            opt = (s.query(Option)
                   .filter(Option.canonical_sku == ip.canonical_sku)
                   .first())
            if opt:
                match_via = "barcode"

        # 1b. Option.barcode 정확 — 라벨 인쇄(barcode_print.html)가 **최우선으로
        #     인코딩하는 값**인데 여기서 안 찾으면, 우리가 뽑은 라벨을 스캔해도
        #     전부 404 가 난다 (2026-08-05 라이브 실측: 인쇄 대상 890건 중
        #     표본 30/30 매칭 실패 — InventoryProduct.barcode 와 서로소 집합).
        if not opt:
            opt = (s.query(Option)
                   .filter(Option.barcode == code)
                   .first())
            if opt:
                match_via = "option_barcode"

        # 2. boxhero_sku 정확
        if not opt:
            opt = (s.query(Option)
                   .filter(func.lower(Option.boxhero_sku) == code.lower())
                   .first())
            if opt:
                match_via = "boxhero_sku"

        # 3. canonical_sku 정확
        if not opt:
            opt = (s.query(Option)
                   .filter(Option.canonical_sku == code)
                   .first())
            if opt:
                match_via = "canonical_sku"

        # 4. InventoryProduct.barcode 부분 매칭
        if not opt:
            ip = (s.query(InventoryProduct)
                  .filter(InventoryProduct.barcode.ilike(f"%{code}%"))
                  .first())
            if ip and ip.canonical_sku:
                opt = (s.query(Option)
                       .filter(Option.canonical_sku == ip.canonical_sku)
                       .first())
                if opt:
                    match_via = "barcode_partial"

        # 4b. Option.barcode 부분 매칭
        if not opt:
            opt = (s.query(Option)
                   .filter(Option.barcode.ilike(f"%{code}%"))
                   .first())
            if opt:
                match_via = "option_barcode_partial"

        # 5. boxhero_sku 부분
        if not opt:
            opt = (s.query(Option)
                   .filter(Option.boxhero_sku.ilike(f"%{code}%"))
                   .first())
            if opt:
                match_via = "boxhero_partial"

        # 6. canonical_sku 부분
        if not opt:
            opt = (s.query(Option)
                   .filter(Option.canonical_sku.ilike(f"%{code}%"))
                   .first())
            if opt:
                match_via = "canonical_partial"

        # 7. InventoryTx 에만 있는 SKU (Option 미등록)
        if not opt:
            tx_sku = (s.query(InventoryTx.option_canonical_sku)
                      .filter(InventoryTx.option_canonical_sku == code)
                      .filter(InventoryTx.status == 'completed')
                      .first())
            if tx_sku:
                # Option 없지만 InventoryTx 에 거래 있는 SKU → 처리 가능
                # 🔴 SSOT 부호 규약 — raw 합은 out/move 를 더해 버린다
                from shared.inventory_stock import get_stock_batch
                stock = int(get_stock_batch(s, [code]).get(code, 0))
                ip_info_orphan = (s.query(InventoryProduct)
                                  .filter(InventoryProduct.canonical_sku == code)
                                  .first())
                return _ok(option={
                    "canonical_sku": code,
                    "boxhero_sku": None,
                    "model_code": None,
                    "model_name": code.rsplit("-", 2)[0] if "-" in code else code,
                    "color_code": code.rsplit("-", 2)[1] if code.count("-") >= 2 else None,
                    "size_code": code.rsplit("-", 1)[-1] if "-" in code else None,
                    "image_url": None,
                    "stock": int(stock),
                    "avg_purchase_price": 0,
                    "boxhero_stock_total": 0,
                    "last_crawled_at": None,
                    "last_uploaded_at": None,
                    "last_tx_at": None,
                    "tx_count": 0,
                    "use_purchase_inventory": False,
                    "barcode": ip_info_orphan.barcode if ip_info_orphan else None,
                    "supplier": ip_info_orphan.supplier if ip_info_orphan else None,
                    "category": ip_info_orphan.category if ip_info_orphan else None,
                    "match_via": "inventory_tx_only",
                    "registered": False,  # Option 테이블 미등록
                    "warning": "이 SKU 는 모음전 옵션 미등록. 재고 거래만 존재.",
                })

            # 매칭 완전 실패
            ip_count = s.query(func.count(InventoryProduct.id)).filter(
                InventoryProduct.barcode.isnot(None),
                InventoryProduct.barcode != ''
            ).scalar() or 0
            opt_count = s.query(func.count(Option.canonical_sku)).scalar() or 0
            return _err(
                f"매칭 안 됨: {code} "
                f"(옵션 {opt_count}개 / 바코드 등록 {ip_count}개) "
                f"— 박스히어로 시스템에 이 바코드 등록 필요",
                404,
            )

        # 모델 정보
        model = s.query(Model).filter_by(model_code=opt.model_code).first()
        model_name = model.model_code if model else opt.model_code

        # 현재 재고 (모든 위치 합) — SSOT 부호 규약 (raw 합은 out/move 를 더해 버림.
        # 2026-08-05 라이브 실측: 입고2·출고2 상태에서 raw 합=4, SSOT=0)
        from shared.inventory_stock import get_stock_batch
        stock = int(get_stock_batch(s, [opt.canonical_sku]).get(opt.canonical_sku, 0))

        # 최근 트랜잭션 시간
        last_tx_at = (s.query(func.max(InventoryTx.created_at))
                      .filter(InventoryTx.option_canonical_sku == opt.canonical_sku)
                      .filter(InventoryTx.status == 'completed')
                      .scalar())

        # 트랜잭션 수
        tx_count = (s.query(func.count(InventoryTx.id))
                    .filter(InventoryTx.option_canonical_sku == opt.canonical_sku)
                    .filter(InventoryTx.status == 'completed')
                    .scalar()) or 0

        # InventoryProduct 매핑 정보 (바코드, 매입처 등)
        ip_info = (s.query(InventoryProduct)
                   .filter(InventoryProduct.canonical_sku == opt.canonical_sku)
                   .first())
        # 라이브 실측(2026-08-05): InventoryProduct.barcode 등록 0건 — 실 바코드는
        # Option.barcode 에 있다. IP 없으면 옵션 값으로 폴백해야 화면에 바코드가 뜬다.
        ip_barcode = (ip_info.barcode if ip_info and ip_info.barcode else None) or opt.barcode
        ip_supplier = ip_info.supplier if ip_info else None
        ip_category = ip_info.category if ip_info else None

        return _ok(option={
            "canonical_sku": opt.canonical_sku,
            "boxhero_sku": opt.boxhero_sku,
            "model_code": opt.model_code,
            "model_name": model_name,
            "color_code": opt.color_code,
            "size_code": opt.size_code,
            "image_url": opt.image_url,
            "stock": int(stock),
            # 추가 정보
            "avg_purchase_price": getattr(opt, "boxhero_avg_purchase_price", None) or 0,
            "boxhero_stock_total": getattr(opt, "boxhero_stock_total", None) or 0,
            "last_crawled_at": opt.last_crawled_at.isoformat() if getattr(opt, "last_crawled_at", None) else None,
            "last_uploaded_at": opt.last_uploaded_at.isoformat() if getattr(opt, "last_uploaded_at", None) else None,
            "last_tx_at": last_tx_at.isoformat() if last_tx_at else None,
            "tx_count": int(tx_count),
            "use_purchase_inventory": bool(getattr(opt, "use_purchase_inventory", False)),
            # InventoryProduct 정보
            "barcode": ip_barcode,
            "supplier": ip_supplier,
            "category": ip_category,
            "match_via": match_via,
        })


@bp.route("/api/stock/<path:sku>")
def api_stock(sku: str):
    """위치별 재고 분포 — SSOT(shared.inventory_stock) 부호 규약으로 계산.

    [중요] [2026-08-05] raw `sum(qty)` → SSOT 로 교체. 이 시스템의 저장 규약은
    「qty 양수 저장, 부호는 tx_type 이 결정」(in=+, out=-, move=출발지-·도착지+)라
    raw 합은 out/move 를 **더해 버린다** — 데스크탑 화면들과 다른 숫자를 말하는 모순.
    응답 모양(by_location/total)은 그대로라 action.html 등 기존 호출부는 무수정.
    """
    from shared.inventory_stock import get_stock_batch, get_stock_by_location_batch
    with SessionLocal() as s:
        locs = (
            s.query(InventoryLocation)
            .filter(InventoryLocation.deleted_at.is_(None))
            .order_by(InventoryLocation.sort_order, InventoryLocation.id)
            .all()
        )
        per_loc = get_stock_by_location_batch(s, [sku]).get(sku, {})
        out = [
            {"location_id": loc.id, "location_name": loc.name,
             "stock": int(per_loc.get(loc.id, 0))}
            for loc in locs
        ]
        # total 은 위치 무관 SSOT 합 (location_id 없는 옛 거래도 포함)
        total = int(get_stock_batch(s, [sku]).get(sku, 0))
        return _ok(by_location=out, total=total)


def _size_sort_key(label: str):
    """사이즈 정렬 — 숫자면 수치로(235<240<1000), 아니면 글자로."""
    try:
        return (0, float(label), '')
    except (TypeError, ValueError):
        return (1, 0.0, str(label))


@bp.route("/api/product/<path:sku>")
def api_product(sku: str):
    """제품 정보(폰 상세 시트) — PC 「제품」(data_items) JSON rows 와 **같은 원천 필드**.

    [2026-08-05 B1·C1·C4] 카드 펼침 시트가 쓰는 한 방 API:
      - 제품 정보: brand·model_name·article_no(Model) / barcode·avg(Option) —
        PC data_items rows 의 'brand'·'name_raw'·'article_no'·'barcode'·'avg' 와
        같은 컬럼(drift 는 tests/mobile 값 대조 시험이 지킨다)
      - usage: OptionProductLink(product_canonical_sku==sku) 개수 — PC usage_map 과 동일.
        [중요] 「모음전 적용」은 스위치가 아니라 이 개수의 **읽기전용 배지**다(켜고 끄기 발명 금지).
      - matrix: 같은 model_code 활성 옵션 전체의 색상×사이즈 SSOT 재고 미니표.
        셀 = 재고 수(0 포함) / **조합 없음 = null** — 0 과 없음을 구분(모순 표기 금지).
    """
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.models import OptionProductLink

    with SessionLocal() as s:
        opt = s.query(Option).filter_by(canonical_sku=sku).first()
        if not opt:
            return _err(f"SKU 없음: {sku}", 404)

        model = (s.query(Model).filter_by(model_code=opt.model_code).first()
                 if opt.model_code else None)

        usage = (s.query(func.count(OptionProductLink.option_canonical_sku))
                 .filter(OptionProductLink.product_canonical_sku == sku)
                 .scalar()) or 0

        # ── C4 색상×사이즈 미니표 — 같은 model_code 활성 옵션 전체 ──
        matrix = None
        if opt.model_code:
            sibs = (s.query(Option)
                    .filter(Option.model_code == opt.model_code)
                    .filter(Option.is_active == True)  # noqa: E712
                    .all())
            if opt not in sibs:          # 본인이 비활성이어도 표에는 나온다
                sibs.append(opt)
            sib_stock = get_stock_batch(s, [o.canonical_sku for o in sibs])

            def _color(o):
                return (o.color_display or o.color_code or 'ONE').strip() or 'ONE'

            def _size(o):
                return (o.size_display or o.size_code or 'FREE').strip() or 'FREE'

            cells: dict[tuple[str, str], int] = {}
            for o in sibs:
                key = (_color(o), _size(o))
                cells[key] = cells.get(key, 0) + int(sib_stock.get(o.canonical_sku, 0))
            colors = sorted({c for c, _sz in cells}, key=str)
            sizes = sorted({sz for _c, sz in cells}, key=_size_sort_key)
            matrix = {
                "sizes": sizes,
                "rows": [
                    {"color": c,
                     # 조합 없음 = None (0 과 구분 — JSON null → 폰은 '—')
                     "cells": [cells.get((c, sz)) for sz in sizes]}
                    for c in colors
                ],
            }

        return _ok(product={
            "canonical_sku": opt.canonical_sku,
            "boxhero_sku": opt.boxhero_sku,
            "barcode": opt.barcode or "",
            "brand": (model.brand if model else "") or "",
            "model_code": opt.model_code or "",
            "model_name": ((model.model_name_display or model.model_name_raw)
                           if model else "") or "",
            "article_no": (getattr(model, "article_no", None) if model else "") or "",
            "color": (opt.color_display or opt.color_code or ""),
            "size": (opt.size_display or opt.size_code or ""),
            "avg_purchase_price": int(opt.boxhero_avg_purchase_price or 0),
            "image_url": opt.image_url,
            "usage": int(usage),
            "stock": int(get_stock_batch(s, [sku]).get(sku, 0)),
            "matrix": matrix,
        })


@bp.route("/api/transfer", methods=["POST"])
def api_transfer():
    """위치 이동 — 폰의 유일한 쓰기(A4). 데스크탑과 **같은 규약**으로 기록.

    부호 규약 (실코드 확인 결과 — 2026-08-05):
      데스크탑 이동은 lemouton/inventory/inbound.py:create_move 가 이미 있다 →
      **그 함수를 그대로 호출**한다(발명 0). 기록 = InventoryTx **1건**:
      tx_type='move', qty=양수, location_id=출발지, location_to_id=도착지,
      status='completed', source='local'. 합산은 SSOT(_stock_expr)가
      출발지 -abs / 도착지 +abs 처리(총합 영향 0).

    payload: {sku, from_location_id, to_location_id, qty, memo?}
    검증: 수량 양수만 / 같은 위치 거부 / 출발지 SSOT 재고 부족 시 거부(오버 이동 금지).
    응답: 양쪽 위치의 갱신 재고 + 총재고 (화면 즉시 갱신용).
    """
    from shared.inventory_stock import get_stock_batch
    from lemouton.inventory.inbound import create_move

    data = request.get_json(silent=True) or {}
    sku = (data.get("sku") or "").strip()
    try:
        from_id = int(data.get("from_location_id") or 0)
        to_id = int(data.get("to_location_id") or 0)
        qty = int(data.get("qty") or 0)
    except (TypeError, ValueError):
        return _err("from_location_id / to_location_id / qty 숫자 아님")
    memo = (data.get("memo") or "").strip() or None

    if not sku:
        return _err("sku 필수")
    if qty <= 0:
        return _err("이동 수량은 양수")
    if not from_id or not to_id:
        return _err("보내는 위치·받는 위치 필수")
    if from_id == to_id:
        return _err("같은 위치로는 이동 불가")

    from flask_login import current_user
    actor = (getattr(current_user, "email", None) if current_user.is_authenticated
             else "system")

    with SessionLocal() as s:
        opt = s.query(Option).filter_by(canonical_sku=sku).first()
        if not opt:
            return _err(f"SKU 없음: {sku}", 404)
        loc_from = s.query(InventoryLocation).filter_by(id=from_id).first()
        loc_to = s.query(InventoryLocation).filter_by(id=to_id).first()
        if not loc_from or loc_from.deleted_at:
            return _err("보내는 위치 없음", 404)
        if not loc_to or loc_to.deleted_at:
            return _err("받는 위치 없음", 404)

        # 오버 이동 금지 — 출발지 SSOT 재고로 판정
        from_stock = int(get_stock_batch(s, [sku], location_id=from_id).get(sku, 0))
        if from_stock < qty:
            return _err(f"재고 부족: {loc_from.name} 보유 {from_stock}, 요청 {qty}")

        tx = create_move(
            s,
            from_location_id=from_id,
            to_location_id=to_id,
            option_canonical_sku=sku,
            qty=qty,
            memo=memo or "[모바일 위치이동]",
            created_by=actor,
        )
        s.commit()  # 한 커밋 — create_move 는 flush 까지만

        new_from = int(get_stock_batch(s, [sku], location_id=from_id).get(sku, 0))
        new_to = int(get_stock_batch(s, [sku], location_id=to_id).get(sku, 0))
        total = int(get_stock_batch(s, [sku]).get(sku, 0))
        logger.info(f"[mobile] {actor} move sku={sku} qty={qty} "
                    f"{loc_from.name}→{loc_to.name}")
        return _ok(
            tx_id=tx.id,
            sku=sku,
            qty=qty,
            from_location={"id": from_id, "name": loc_from.name, "stock": new_from},
            to_location={"id": to_id, "name": loc_to.name, "stock": new_to},
            total_stock=total,
            actor=actor,
        )


@bp.route("/api/action", methods=["POST"])
def api_action():
    """입고/출고/조정 트랜잭션 1건 기록.

    payload: {
      sku: str (canonical_sku),
      action: 'in' | 'out' | 'adjust',
      location_id: int,
      qty: int,                # in/out: +qty / adjust: 세어 본 결과 수량
      memo: str (optional),
    }

    조정 (adjust):
      - 받는 값은 「실사해 보니 qty 개」(결과 수량) — 작업자가 뺄셈하지 않는다
      - 원장에는 **그 차이(qty − 현재재고)** 를 남긴다
        (규칙 원천 = shared/inventory_stock.py `fold_tx_rows` — `adjust → total += q`)
      - 응답의 applied_qty 도 그 차이다
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

        # 트랜잭션 qty 계산 — 데스크탑과 통일 (양수 저장, 부호는 SSOT 합산 시 처리)
        if action == "in":
            tx_qty = qty
            tx_memo = memo or f"[모바일 입고]"
        elif action == "out":
            tx_qty = qty  # 양수 저장 (데스크탑 outbound 와 통일). SSOT 가 -abs 처리
            tx_memo = memo or f"[모바일 출고]"
        else:  # adjust
            # 🔴 조정은 **차이값(증감분)으로 저장한다** — 사장님 확정(2026-08-13).
            #   쓰는 곳 셋이 **모두 같은 뜻**이어야 한다(그래야 읽는 쪽이 옳을 수 있다):
            #     · lemouton/inventory/inbound.create_adjustment  → qty=delta
            #     · webapp/routes/api_inventory_link              → qty=diff
            #     · 여기(모바일)                                   → qty−현재재고  ← 이 줄
            #   읽는 쪽 정본 = `shared.inventory_stock.fold_tx_rows` (`adjust → total += q`).
            #   받는 값은 그대로 「세어 보니 N개」다 — 작업자에게 뺄셈을 시키지 않는다.
            #
            #   ⚠️ 2026-08-13 이 한 줄이 하루에 **세 번** 뒤집혔다(재고 4 → 6 → 4).
            #     전부 「에러 없이 숫자만 틀리는」 사고였다.
            #   🔴 고치려거든 위 **세 곳을 한꺼번에** 보라. 한 곳만 바꾸면 같은 표의 같은
            #     종류 행이 두 가지 뜻을 갖고, 그 순간 어느 읽는 쪽도 옳을 수 없다.
            #     `tests/inventory/test_adjust_writer_consistency.py` 가 세 곳을 같이 잡는다.
            from shared.inventory_stock import get_stock_batch
            current = int(get_stock_batch(s, [sku], location_id=location_id).get(sku, 0))
            delta = int(qty) - current
            if delta == 0:
                return _ok(message="변경 없음 (현재 재고와 동일)", tx_id=None)
            tx_qty = int(qty) - current          # 저장 = 차이값(정본과 같은 뜻)
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

        # 갱신된 재고 — SSOT 부호 규약 (2026-08-05 라이브 실측: raw 합은
        # 출고를 더해 new_total_stock=4 를 돌려줬다. 실제 재고는 0)
        from shared.inventory_stock import get_stock_batch
        new_total = int(get_stock_batch(s, [sku]).get(sku, 0))

        logger.info(f"[mobile] {actor} {action} sku={sku} qty={tx_qty} loc={loc.name}")
        return _ok(
            tx_id=tx.id,
            action=action,
            # 조정도 저장값이 곧 변화량이다(델타 규약) — 갈라 쓸 이유가 없다.
            # 화면엔 **변화량**을 보여준다(「4개 늘었다」). 조정만 저장값(절대값)과
            #  뜻이 달라 여기서 가른다 — 입고·출고는 저장값이 곧 변화량이다.
            applied_qty=(delta if action == "adjust" else tx_qty),
            new_total_stock=int(new_total),
            location_name=loc.name,
            actor=actor,
        )


@bp.route("/api/action-batch", methods=["POST"])
def api_action_batch():
    """연속 스캔 batch 저장 — N개 SKU 한꺼번에 입고/출고.

    payload: {
      action: 'in' | 'out',
      location_id: int,
      items: [{sku: str, qty: int}, ...],
      memo: str (optional),
    }
    Response: {ok, saved: [tx_id], failed: [{sku, error}]}
    """
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    try:
        location_id = int(data.get("location_id") or 0)
    except (TypeError, ValueError):
        return _err("location_id 숫자 아님")
    items = data.get("items") or []
    memo = (data.get("memo") or "").strip() or None

    if action not in ("in", "out"):
        return _err("action 은 in / out 만")
    if not location_id:
        return _err("location_id 필수")
    if not items:
        return _err("items 빈 배열")

    from flask_login import current_user
    actor = (getattr(current_user, "email", None) if current_user.is_authenticated
             else "system")

    saved, failed = [], []
    with SessionLocal() as s:
        loc = s.query(InventoryLocation).filter_by(id=location_id).first()
        if not loc or loc.deleted_at:
            return _err("위치 없음", 404)
        for it in items:
            sku = (it.get("sku") or "").strip()
            try:
                qty = int(it.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0
            if not sku or qty <= 0:
                failed.append({"sku": sku, "error": "sku 또는 qty 무효"})
                continue
            opt = s.query(Option).filter_by(canonical_sku=sku).first()
            if not opt:
                failed.append({"sku": sku, "error": "SKU 미등록"})
                continue
            # 양수 저장 (출고 부호는 SSOT 가 abs() 처리)
            tx_memo = memo or (f"[모바일 일괄 {('입고' if action=='in' else '출고')}]")
            tx = InventoryTx(
                tx_type=action,
                location_id=location_id,
                option_canonical_sku=sku,
                qty=qty,
                memo=tx_memo,
                created_by=actor,
                source='local',
                status='completed',
                created_at=dt.datetime.utcnow(),
            )
            s.add(tx)
            s.flush()
            saved.append({"tx_id": tx.id, "sku": sku, "qty": qty})
        s.commit()
        logger.info(f"[mobile-batch] {actor} {action} saved={len(saved)} failed={len(failed)}")
    return _ok(saved=saved, failed=failed, total_saved=len(saved), total_failed=len(failed))


@bp.route("/api/options", methods=["GET"])
def api_options():
    """모바일 재고 목록 — InventoryTx 기준 SKU 합집합 (Option 미등록도 표시).

    데스크탑 /inventory/ 는 Option 테이블 기반이지만, 모바일은 재고 작업 도구라
    "거래 있는 모든 SKU" 를 보여주는 게 더 직관적.

    Query params:
      q: 검색어 (canonical_sku / color / size / boxhero_sku / barcode 부분 일치)
      limit: 기본 200
      registered_only: '1' 시 Option 테이블 등록된 것만

    [2026-08-05] kpi: PC 「제품」(data_items) 3칸과 같은 정의(shared.inventory_stock.master_kpi)
    를 항상 싣는다. 각 줄의 stock 도 SSOT 로 재계산(raw 합은 out/move 부호를 무시).
    """
    from shared.search import split_tokens, apply_and_filter
    from shared.inventory_stock import get_stock_batch, master_kpi
    q = (request.args.get("q") or "").strip()
    search_tokens = split_tokens(q)
    registered_only = request.args.get("registered_only") == "1"
    try:
        limit = min(int(request.args.get("limit") or 200), 500)
    except ValueError:
        limit = 200

    with SessionLocal() as s:
        # 옵션별 총 재고 (InventoryTx 기준 — 모든 SKU)
        stock_q = (
            s.query(
                InventoryTx.option_canonical_sku.label("sku"),
                func.coalesce(func.sum(InventoryTx.qty), 0).label("stock"),
            )
            .filter(InventoryTx.status == 'completed')
            .filter(InventoryTx.option_canonical_sku.isnot(None))
            .group_by(InventoryTx.option_canonical_sku)
            .subquery()
        )

        # Option + stock 합집합 (Option 없어도 stock 있으면 포함)
        # SQLAlchemy 의 outer join 으로 InventoryTx 의 SKU 가 base 가 되게
        if registered_only:
            # Option 기반 (데스크탑 호환 모드)
            query = (
                s.query(Option, stock_q.c.stock)
                .outerjoin(stock_q, stock_q.c.sku == Option.canonical_sku)
            )
            # ★ 박스히어로식 다중 키워드 AND 교집합
            query = apply_and_filter(
                query, search_tokens,
                Option.canonical_sku, Option.color_code, Option.size_code, Option.boxhero_sku,
                op='ilike',
            )
            query = query.order_by(
                func.coalesce(stock_q.c.stock, 0).desc(),
                Option.canonical_sku,
            ).limit(limit)
            rows = query.all()
            # SSOT 재계산 — raw 합(stock_q)은 정렬·선별용, 표시값은 부호 규약 반영
            ssot = get_stock_batch(s, [opt.canonical_sku for opt, _ in rows])
            items = [
                {
                    "canonical_sku": opt.canonical_sku,
                    "boxhero_sku": opt.boxhero_sku,
                    "color_code": opt.color_code,
                    "size_code": opt.size_code,
                    "image_url": opt.image_url,
                    "stock": int(ssot.get(opt.canonical_sku, 0)),
                    "registered": True,
                }
                for opt, _stock in rows
            ]
            items.sort(key=lambda it: (-it["stock"], it["canonical_sku"]))
            return _ok(items=items, total=len(items), mode="option_registered",
                       kpi=master_kpi(s))

        # 기본 모드: InventoryTx 의 모든 SKU + Option 정보 join
        # SQL: SELECT sku, stock, opt.* FROM stock LEFT JOIN options ON stock.sku == options.canonical_sku
        query = (
            s.query(stock_q.c.sku, stock_q.c.stock, Option)
            .outerjoin(Option, Option.canonical_sku == stock_q.c.sku)
        )
        # ★ 박스히어로식 다중 키워드 AND 교집합
        query = apply_and_filter(
            query, search_tokens,
            stock_q.c.sku, Option.color_code, Option.size_code, Option.boxhero_sku,
            op='ilike',
        )
        query = query.order_by(stock_q.c.stock.desc(), stock_q.c.sku).limit(limit)

        rows = query.all()
        # SSOT 재계산 — raw 합(stock_q)은 정렬·선별용, 표시값은 부호 규약 반영
        ssot = get_stock_batch(s, [sku for sku, _stock, _opt in rows])
        items = [
            {
                "canonical_sku": sku,
                "boxhero_sku": opt.boxhero_sku if opt else None,
                "color_code": opt.color_code if opt else None,
                "size_code": opt.size_code if opt else None,
                "image_url": opt.image_url if opt else None,
                "stock": int(ssot.get(sku, 0)),
                "registered": opt is not None,
            }
            for sku, _stock, opt in rows
        ]
        items.sort(key=lambda it: (-it["stock"], it["canonical_sku"]))
        return _ok(items=items, total=len(items), mode="inventory_all",
                   kpi=master_kpi(s))


# ══════════════════════════════════════════════════════════════════════════
#  포장 스캔 출고 — 바코드를 찍어 「이 주문 줄이 나갔다」를 확정한다.
#   사장님 확정(2026-08-06): 재고 차감은 표시가 아니라 **바코드 찍을 때**,
#   **사입으로 표시된 줄만**. 무재고 줄은 소싱처에서 사서 보내므로 안 깎는다.
#   규칙 정본 = lemouton/inventory/order_outbound.py
# ══════════════════════════════════════════════════════════════════════════

@bp.route("/api/scan-orders", methods=["POST"])
def api_scan_orders():
    """바코드 → 그 옵션으로 최근 들어온 주문 줄 목록 (포장 대상 고르기).

    payload: {code | sku, days?}  → {ok, sku, orders: [...]}
    """
    from lemouton.inventory import order_outbound as _oo

    data = request.get_json(silent=True) or {}
    sku = (data.get("sku") or "").strip()
    if not sku:
        # 바코드로 들어오면 lookup 과 같은 규칙으로 옵션을 먼저 찾는다
        code = (data.get("code") or "").strip()
        if not code:
            return _err("바코드(code) 또는 sku 가 필요해요.")
        with SessionLocal() as s:
            opt = (s.query(Option).filter(Option.barcode == code).first()
                   or s.query(Option).filter(
                       func.lower(Option.boxhero_sku) == code.lower()).first()
                   or s.query(Option).filter(Option.canonical_sku == code).first())
            if not opt:
                return _err(f"매칭 안 됨: {code}", 404)
            sku = opt.canonical_sku
    try:
        days = int(data.get("days") or 30)
    except (TypeError, ValueError):
        days = 30
    with SessionLocal() as s:
        return _ok(sku=sku, orders=_oo.pending_lines_for_sku(s, sku, days=days))


@bp.route("/api/scan-ship", methods=["POST"])
def api_scan_ship():
    """포장 스캔 1건 처리.

    payload: {line_uid, sku, location_id, qty?, sale_price?}
    응답: {ok, result, supply_mode, deducted_qty, stock_after, warning}
      · result = deducted(사입 — 깎음) | no_deduct(무재고 — 안 깎음) | already(두 번 찍음)
      · [중요] warning 은 재고가 모자란데 그대로 기록했다는 뜻이다(막지 않는다 — 사장님 확정).
        화면은 이 문구를 반드시 띄워야 한다. 조용히 넘기면 장부가 실물과 어긋난 채 굳는다.
    """
    from lemouton.inventory import order_outbound as _oo

    data = request.get_json(silent=True) or {}
    try:
        location_id = int(data.get("location_id") or 0)
    except (TypeError, ValueError):
        return _err("location_id 숫자 아님")
    if not location_id:
        return _err("location_id 필수")

    from flask_login import current_user
    actor = (getattr(current_user, "email", None) if current_user.is_authenticated
             else "system")

    with SessionLocal() as s:
        loc = s.query(InventoryLocation).filter_by(id=location_id).first()
        if not loc or loc.deleted_at:
            return _err("위치 없음", 404)
        try:
            res = _oo.ship_order_line(
                s, line_uid=data.get("line_uid"), canonical_sku=data.get("sku"),
                location_id=location_id, qty=data.get("qty") or 1, actor=actor,
                unit_sale_price=data.get("sale_price") or 0)
        except ValueError as e:
            return _err(str(e))
        return _ok(**res)


@bp.route("/api/scan-ship/status", methods=["POST"])
def api_scan_ship_status():
    """여러 주문 줄의 처리 상태 한 번에 — 화면이 「이미 찍음」을 회색으로 그린다.

    payload: {line_uids: [...]} → {ok, shipped: [...], modes: {uid: mode}}
    """
    from lemouton.inventory import order_outbound as _oo
    from lemouton.markets import supply_mode as _sm

    data = request.get_json(silent=True) or {}
    uids = data.get("line_uids") or []
    if not isinstance(uids, list):
        return _err("line_uids 는 배열이어야 해요.")
    if not uids:
        return _ok(shipped=[], modes={})
    with SessionLocal() as s:
        return _ok(shipped=sorted(_oo.already_shipped_uids(s, uids)),
                   modes=_sm.get_many_with_default(s, uids))


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
