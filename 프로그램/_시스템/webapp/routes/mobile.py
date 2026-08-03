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
    InventoryLocation, InventoryTx, InventoryProduct,
)
from lemouton.sourcing.models import Option, Model

logger = logging.getLogger(__name__)

bp = Blueprint("mobile", __name__, url_prefix="/mobile")


# ─── 폰 전용으로 이미 만들어진 화면들 ───
#   '전체' 메뉴에서 두 가지로 쓴다: (1) 이 화면들을 메뉴에 싣는 원천, (2) '폰 전용' 배지 판정.
#
#   🔴 왜 따로 두나 — PC 상단 메뉴(sidebar_layout)에는 이 화면들이 **하나도 없다**.
#     폰에만 있는 화면이라 PC 메뉴에 넣을 자리가 없어서다(실측: 25줄 전부 PC 주소).
#     그래서 배지 집합만 두고 PC 메뉴 줄에만 배지를 붙이면, 맞는 줄이 영영 없어
#     **모든 줄이 조용히 'PC 화면'** 으로 뜬다.
#   ★ 3단계에서 PC 화면 하나를 폰 전용으로 바꿀 때는 여기 목록에 넣지 말고
#     그 화면의 **PC 주소**(예: '/orders/?tab=list')만 PHONE_NATIVE_URLS 에 더한다.
#     그 화면은 이미 PC 메뉴에 있으니, 목록에 또 넣으면 같은 줄이 두 번 뜬다.
PHONE_NATIVE: list[dict[str, Any]] = [
    {"emoji": "🏠", "name": "폰 홈", "url": "/mobile"},
    {"emoji": "📷", "name": "바코드 스캔", "url": "/mobile/scan"},
    {"emoji": "📥", "name": "연속 스캔 입고", "url": "/mobile/scan-batch?mode=in"},
    {"emoji": "📤", "name": "연속 스캔 출고", "url": "/mobile/scan-batch?mode=out"},
    {"emoji": "🏷", "name": "재고 목록", "url": "/mobile/inventory"},
    # 크롤 리모컨은 admin 전용이다(mobile_crawl._admin_only). member 에게 보여 주면
    # 눌러도 403 만 나오는 줄이 된다 — 이 설계가 가장 피하려는 결과다.
    {"emoji": "🛰", "name": "크롤 리모컨", "url": "/mobile/crawl/", "admin_only": True},
]

#: 배지 판정용 주소 집합.
#  같은 화면이 두 모양('/mobile' 과 '/mobile/')으로 불린다 — 라우트는 '/mobile/' 인데
#  위 목록과 _base.html 의 🏠 링크는 '/mobile' 을 쓴다. 배지는 **글자 그대로 맞춰야**
#  붙고 안 맞아도 에러가 안 나니(조용히 'PC 화면'), 두 모양을 다 넣어 둔다.
#  ⚠️ 정직하게 적어 둔다 — 지금 메뉴에 '/mobile/' 모양으로 나오는 줄은 없다. 그래서
#    이 한 줄을 지워도 오늘은 시험이 안 깨진다(변이로 확인). 앞으로 그 모양의 링크가
#    생겼을 때를 위한 대비다.
PHONE_NATIVE_URLS: set[str] = {it["url"] for it in PHONE_NATIVE} | {"/mobile/"}


#: '전체' 메뉴에 **일부러** 안 싣는 폰 라우트 — url_map 의 규칙 문자열 그대로 적는다.
#
#  🔴 왜 목록으로 두나 — 위 PHONE_NATIVE 만으로는 **한 방향밖에 못 지킨다**(적어 둔 주소가
#    진짜 있나). 반대쪽, 즉 '새로 만든 폰 화면이 메뉴에 실렸나'는 아무도 안 본다. 그러면
#    Task 6·7 에서 폰 화면을 만들고 PHONE_NATIVE 에 안 넣어도 아무것도 안 깨지고,
#    이 화면이 존재하는 이유였던 그 사고(만든 화면이 메뉴에 없어 두 달간 주소를 직접 침)가
#    폰 쪽에서 그대로 되살아난다.
#    → 시험(test_menu_single_source.py::test_모든_폰_화면은_메뉴에_실리거나_이유가_적혀있다)이
#      /mobile/* 페이지 라우트를 훑어, 여기에도 PHONE_NATIVE 에도 없으면 실패한다.
#      새 화면을 만들 때 '메뉴에 넣을까 / 일부러 뺄까'를 반드시 한 번 고르게 된다.
#
#  ★ 동적 주소(<sku> 같은)도 자동으로 봐주지 않는다 — 자동 예외는 한 부류를 통째로
#    조용히 빼는 것이라, 이 장치가 막으려는 사고와 정확히 같은 모양이 된다.
#    링크할 주소가 없는 화면이면 그 사실을 여기 한 줄로 적으면 된다.
MENU_EXEMPT_RULES: dict[str, str] = {
    "/mobile/menu": "이 메뉴 화면 자신 — 자기를 자기 목록에 넣지 않는다",
    "/mobile/install": "메뉴 맨 아래 고정줄(앱 설치 방법)에 이미 있다",
    "/mobile/sku/<path:sku>": "특정 SKU 상세 — 스캔·재고 목록에서 들어가는 곳이라 "
                              "링크할 고정 주소가 없다(진입점이 아니다)",
}


def _phone_native_rows(is_admin: bool) -> list[dict[str, Any]]:
    """메뉴에 실을 폰 전용 화면 — admin 전용 줄은 member 에게서 감춘다.

    /mobile/* 는 ENVIRONMENT=team-share-dev 에서만 등록된다(app.py:345). 즉 이 함수가
    도는 곳에선 mobile_crawl 의 admin 게이트도 **항상** 살아 있다 — 모드 분기를 둘 필요가 없다.
    """
    return [it for it in PHONE_NATIVE if is_admin or not it.get("admin_only")]


# ─── 페이지 라우트 ───
@bp.route("/")
def home():
    return render_template("mobile/home.html")


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


@bp.route("/sku/<path:sku>")
def sku_detail(sku: str):
    return render_template("mobile/action.html", sku=sku)


@bp.route("/inventory")
def inventory_list():
    return render_template("mobile/inventory.html")


@bp.route("/menu")
def menu():
    """'전체' — PC 상단 메뉴와 같은 원천(sidebar_layout)을 읽어 목록으로 편다.

    폰 전용 메뉴를 따로 정의하지 않는다. 새 화면을 만들 때 한쪽에만 넣고
    다른 쪽엔 빼먹는 사고를 구조적으로 막기 위해서다(이 프로젝트엔 그 실제 기록이 있다).
    """
    from flask_login import current_user

    from webapp.routes.api_sidebar import get_layout_for_template
    is_admin = bool(getattr(current_user, "is_admin", False))
    return render_template("mobile/menu.html",
                           layout=get_layout_for_template(),
                           phone_native=_phone_native_rows(is_admin),
                           phone_native_urls=PHONE_NATIVE_URLS)


@bp.route("/install")
def install():
    return render_template("mobile/install.html")


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
                stock = (s.query(func.sum(InventoryTx.qty))
                         .filter(InventoryTx.option_canonical_sku == code)
                         .filter(InventoryTx.status == 'completed')
                         .scalar()) or 0
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

        # 현재 재고 (모든 위치 합)
        stock = (s.query(func.sum(InventoryTx.qty))
                 .filter(InventoryTx.option_canonical_sku == opt.canonical_sku)
                 .filter(InventoryTx.status == 'completed')
                 .scalar()) or 0

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
        ip_barcode = ip_info.barcode if ip_info else None
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

        # 트랜잭션 qty 계산 — 데스크탑과 통일 (양수 저장, 부호는 SSOT 합산 시 처리)
        if action == "in":
            tx_qty = qty
            tx_memo = memo or f"[모바일 입고]"
        elif action == "out":
            tx_qty = qty  # 양수 저장 (데스크탑 outbound 와 통일). SSOT 가 -abs 처리
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
    """
    from shared.search import split_tokens, apply_and_filter
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
            return _ok(items=[
                {
                    "canonical_sku": opt.canonical_sku,
                    "boxhero_sku": opt.boxhero_sku,
                    "color_code": opt.color_code,
                    "size_code": opt.size_code,
                    "image_url": opt.image_url,
                    "stock": int(stock or 0),
                    "registered": True,
                }
                for opt, stock in rows
            ], total=len(rows), mode="option_registered")

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
        return _ok(items=[
            {
                "canonical_sku": sku,
                "boxhero_sku": opt.boxhero_sku if opt else None,
                "color_code": opt.color_code if opt else None,
                "size_code": opt.size_code if opt else None,
                "image_url": opt.image_url if opt else None,
                "stock": int(stock or 0),
                "registered": opt is not None,
            }
            for sku, stock, opt in rows
        ], total=len(rows), mode="inventory_all")


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
