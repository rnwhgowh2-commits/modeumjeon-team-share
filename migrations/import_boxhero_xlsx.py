"""박스히어로 export 엑셀 → Supabase 전체 마이그레이션.

3단계 (각 단계 별도 함수로 분리, --step 인자로 선택):
  1. barcode-only:  SKU↔바코드 매핑만 (InventoryProduct.barcode 채우기). 옵션 추가 X.
  2. options:       박스히어로 SKU 를 Option 테이블에 신규 등록.
  3. stock:         박스히어로 수량을 InventoryTx 로 초기 입고.

사용:
  python migrations/import_boxhero_xlsx.py --step barcode-only --xlsx PATH --dry-run
  python migrations/import_boxhero_xlsx.py --step barcode-only --xlsx PATH
  python migrations/import_boxhero_xlsx.py --step options --xlsx PATH
  python migrations/import_boxhero_xlsx.py --step stock --xlsx PATH
"""
from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path
import datetime as dt

# UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 환경 셋업
THIS_DIR = Path(__file__).resolve().parent
NEW_SYSTEM = THIS_DIR.parent / "_시스템"
sys.path.insert(0, str(NEW_SYSTEM))
os.chdir(NEW_SYSTEM)

from dotenv import load_dotenv
load_dotenv(NEW_SYSTEM / ".env", override=True)

import openpyxl
from sqlalchemy import func

# 모델 import
import lemouton.sourcing.models
import lemouton.sourcing.models_pricing
import lemouton.pricing.settings
import lemouton.uploader.models
import lemouton.templates.models
from lemouton.inventory.models import (
    InventoryProduct, InventoryLocation, InventoryTx
)
from lemouton.sourcing.models import Option, Model

from shared.db import SessionLocal


COL = {
    "sku": 0, "barcode": 1, "name": 2, "purchase_price": 3, "sale_price": 4,
    "category": 5, "brand": 6, "model_name": 7, "size": 8, "memo": 9,
    "stock_safety_total": 10, "stock_safety_default": 11, "stock_safety_disabled": 12,
    "stock_safety_overall": 13, "created_at": 14, "quantity": 15,
    "quantity_gross": 16, "quantity_default": 17, "quantity_disabled": 18,
}


def banner(s):
    print(); print("─" * 70); print(s); print("─" * 70)


def parse_xlsx(path: str) -> list[dict]:
    """엑셀 → 정규화 dict 목록."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    out = []
    for row in list(ws.iter_rows(values_only=True))[1:]:
        if not row or row[COL["sku"]] is None:
            continue
        out.append({
            "sku": str(row[COL["sku"]]).strip(),
            "barcode": str(row[COL["barcode"]] or "").strip(),
            "name": str(row[COL["name"]] or "").strip(),
            "purchase_price": int(row[COL["purchase_price"]] or 0),
            "sale_price": int(row[COL["sale_price"]] or 0),
            "category": (str(row[COL["category"]]).strip() if row[COL["category"]] else None),
            "brand": (str(row[COL["brand"]]).strip() if row[COL["brand"]] else None),
            "model_name": (str(row[COL["model_name"]]).strip() if row[COL["model_name"]] else None),
            "size": (str(row[COL["size"]]).strip() if row[COL["size"]] else None),
            "memo": (str(row[COL["memo"]]).strip() if row[COL["memo"]] else None),
            "quantity": int(row[COL["quantity"]] or 0),
            "quantity_gross": int(row[COL["quantity_gross"]] or 0),
            "quantity_default": int(row[COL["quantity_default"]] or 0),
            "quantity_disabled": int(row[COL["quantity_disabled"]] or 0),
        })
    return out


def _extract_color(name: str, brand: str | None, model_name: str | None) -> str:
    """제품명에서 브랜드+모델명 떼고 나머지를 색상으로."""
    text = (name or "").strip()
    if brand and text.startswith(brand):
        text = text[len(brand):].strip()
    if model_name and text.startswith(model_name):
        text = text[len(model_name):].strip()
    return text or "기본"


def make_canonical_sku(rec: dict) -> str:
    """canonical_sku 생성: '{브랜드} {모델명}-{색상}-{사이즈}' 또는 박스히어로 제품명."""
    brand = rec.get("brand") or ""
    model_name = rec.get("model_name") or ""
    size = rec.get("size") or ""
    color = _extract_color(rec["name"], brand, model_name)
    if brand and model_name:
        return f"{brand} {model_name}-{color}-{size}".strip("-")
    # 폴백: 박스히어로 제품명 + 사이즈
    base = rec["name"]
    if size and not base.endswith(size):
        return f"{base}-{size}"
    return base


# ───────────────────────────────────────────────────────────
# 1단계: 바코드 매핑만 (안전, 옵션 추가 X)
# ───────────────────────────────────────────────────────────
def step_barcode_only(records: list[dict], dry_run: bool) -> dict:
    """SKU↔바코드 매핑을 InventoryProduct.barcode 에 저장.

    매핑 대상:
      - Option 에 boxhero_sku == box SKU 가 이미 매핑된 옵션
      - 그 옵션의 canonical_sku 에 대해 InventoryProduct row 생성/갱신
      - barcode 필드 채움
    """
    banner("[1단계] 바코드 매핑 import (InventoryProduct.barcode)")
    counts = {"matched": 0, "new_ip": 0, "updated_ip": 0, "no_opt": 0, "no_barcode": 0, "errors": 0}

    with SessionLocal() as s:
        # Option 의 boxhero_sku → canonical_sku 매핑
        opt_by_bsku = {}
        for opt in s.query(Option).filter(Option.boxhero_sku.isnot(None)).all():
            if opt.boxhero_sku:
                opt_by_bsku[opt.boxhero_sku.lower()] = opt

        print(f"[옵션 매핑] Option 에 boxhero_sku 등록된 수: {len(opt_by_bsku)}")
        print(f"[박스히어로] 엑셀 row 수: {len(records)}")

        for rec in records:
            bsku = rec["sku"]
            barcode = rec["barcode"]
            if not barcode:
                counts["no_barcode"] += 1
                continue

            opt = opt_by_bsku.get(bsku.lower())
            if not opt:
                counts["no_opt"] += 1
                continue

            counts["matched"] += 1
            csku = opt.canonical_sku

            # InventoryProduct 조회/생성
            ip = s.query(InventoryProduct).filter_by(canonical_sku=csku).first()
            if ip:
                if ip.barcode != barcode:
                    if not dry_run:
                        ip.barcode = barcode
                        ip.updated_at = dt.datetime.utcnow()
                    counts["updated_ip"] += 1
            else:
                if not dry_run:
                    ip = InventoryProduct(
                        canonical_sku=csku,
                        option_name=f"{opt.color_code or ''}-{opt.size_code or ''}".strip("-"),
                        model_code=opt.model_code,
                        color_code=opt.color_code,
                        size_code=opt.size_code,
                        brand=rec.get("brand"),
                        category=rec.get("category"),
                        barcode=barcode,
                        purchase_price=rec.get("purchase_price"),
                        sale_price=rec.get("sale_price"),
                        status="completed",
                    )
                    s.add(ip)
                counts["new_ip"] += 1

        if not dry_run:
            try:
                s.commit()
                print("✅ commit 완료")
            except Exception as e:
                s.rollback()
                counts["errors"] += 1
                print(f"❌ commit 실패: {e}")
        else:
            s.rollback()
            print("🔍 dry-run: rollback")

    print(f"\n결과: 매칭 {counts['matched']} / 신규 IP {counts['new_ip']} / "
          f"갱신 IP {counts['updated_ip']} / 옵션없음 {counts['no_opt']} / "
          f"바코드없음 {counts['no_barcode']} / 에러 {counts['errors']}")
    return counts


# ───────────────────────────────────────────────────────────
# 2단계: 신규 옵션 등록 (Option 테이블 + InventoryProduct + 바코드)
# ───────────────────────────────────────────────────────────
def step_options(records: list[dict], dry_run: bool) -> dict:
    """박스히어로 SKU 를 Option 테이블에 신규 등록 (이미 있는 거 스킵).

    각 신규 옵션마다:
      - Option row 추가 (canonical_sku, model_code, color_code, size_code, boxhero_sku)
      - InventoryProduct row 추가 (canonical_sku, barcode 등)
      - Model 도 누락이면 신규 등록
    """
    banner("[2단계] 신규 옵션 일괄 등록")
    counts = {"existing_opt": 0, "new_opt": 0, "new_model": 0, "new_ip": 0, "skipped": 0, "errors": 0}

    with SessionLocal() as s:
        # 기존 boxhero_sku → option 매핑
        existing_bsku = set()
        for opt in s.query(Option.boxhero_sku).filter(Option.boxhero_sku.isnot(None)).all():
            existing_bsku.add(opt.boxhero_sku.lower())

        # 기존 model_code 매핑
        existing_models = {m.model_code for m in s.query(Model).all()}

        # 기존 canonical_sku 매핑 (Option + InventoryProduct 양쪽 — UNIQUE 회피)
        existing_csku = set()
        for row in s.query(Option.canonical_sku).all():
            existing_csku.add(row[0])
        for row in s.query(InventoryProduct.canonical_sku).all():
            existing_csku.add(row[0])

        # raw SQL 일괄 INSERT 용 (Option 만, IP 는 1단계 재실행에서 처리)
        rows_to_insert: list[dict] = []
        models_to_insert: list[dict] = []

        for rec in records:
            bsku = rec["sku"]
            if bsku.lower() in existing_bsku:
                counts["existing_opt"] += 1
                continue

            brand = rec.get("brand") or "기타"
            model_name = rec.get("model_name") or rec["name"]
            color = _extract_color(rec["name"], brand, rec.get("model_name"))
            size = rec.get("size") or ""
            csku_base = make_canonical_sku(rec)
            # 신규 옵션은 항상 박스히어로 SKU suffix 로 unique 보장
            # (기존 36 옵션은 suffix 없이 그대로 유지)
            csku = f"{csku_base} [{bsku}]"
            # 혹시 모를 충돌 (이미 같은 csku 가 있으면 다른 형태)
            n = 1
            while csku in existing_csku:
                n += 1
                csku = f"{csku_base} [{bsku}#{n}]"
                if n > 5:
                    csku = bsku  # 최후 폴백
                    break
            existing_csku.add(csku)

            # Model 등록 (필요 시) — raw SQL 이라 모든 NOT NULL 필드 명시
            model_code = f"{brand} {model_name}".strip() if rec.get("model_name") else model_name
            if model_code not in existing_models:
                if not dry_run:
                    models_to_insert.append({
                        "model_code": model_code,
                        "model_name_raw": model_name or model_code,
                        "brand": brand,
                        "auto_enabled": True,  # NOT NULL default
                    })
                existing_models.add(model_code)
                counts["new_model"] += 1

            # Option 만 등록 — raw SQL + ON CONFLICT
            # NOT NULL: canonical_sku (PK), model_code (FK), color_code, size_code,
            #          use_purchase_inventory (default 0), purchase_priority (default 'auto')
            if not dry_run:
                rows_to_insert.append({
                    "canonical_sku": csku,
                    "model_code": model_code,
                    "color_code": color or "기본",
                    "size_code": size or "단일",
                    "boxhero_sku": bsku,
                    "boxhero_stock_total": rec.get("quantity") or 0,
                    "boxhero_avg_purchase_price": rec.get("purchase_price") or 0,
                    "boxhero_avg_updated_at": dt.datetime.utcnow(),
                    "use_purchase_inventory": False,
                    "purchase_priority": "auto",
                })
                counts["new_opt"] += 1
                existing_bsku.add(bsku.lower())
            else:
                counts["new_opt"] += 1

        if not dry_run:
            # ORM + 한 row 씩 새 session + 에러 row 만 스킵
            from shared.db import SessionLocal as _SL
            from sqlalchemy.exc import IntegrityError

            # batch 내 중복 dedup
            seen_mc = set()
            models_dedup = []
            for m in models_to_insert:
                if m["model_code"] not in seen_mc:
                    seen_mc.add(m["model_code"])
                    models_dedup.append(m)

            seen_csku = set()
            opts_dedup = []
            for r in rows_to_insert:
                if r["canonical_sku"] not in seen_csku:
                    seen_csku.add(r["canonical_sku"])
                    opts_dedup.append(r)

            print(f"  dedup: Model {len(models_dedup)} / Option {len(opts_dedup)}")

            # 1) Model 일괄 (ORM, batch commit)
            m_added = 0
            with _SL() as s2:
                for m_row in models_dedup:
                    try:
                        s2.add(Model(**m_row))
                        s2.flush()
                        m_added += 1
                    except IntegrityError:
                        s2.rollback()
                try:
                    s2.commit()
                except Exception as e:
                    s2.rollback()
                    print(f"  ⚠️ model commit 실패 → row-by-row 재시도")
                    m_added = 0
                    for m_row in models_dedup:
                        try:
                            with _SL() as s3:
                                s3.add(Model(**m_row))
                                s3.commit()
                            m_added += 1
                        except Exception:
                            pass

            # 2) Option — row 별 새 session
            o_added = 0
            o_err = 0
            for o_row in opts_dedup:
                try:
                    with _SL() as s3:
                        s3.add(Option(**o_row))
                        s3.commit()
                    o_added += 1
                except IntegrityError as e:
                    o_err += 1
                except Exception as e:
                    o_err += 1
                    if o_err < 5:
                        print(f"  [SKIP] {o_row.get('canonical_sku')}: {str(e)[:120]}")

            counts["new_model"] = m_added
            counts["new_opt"] = o_added
            counts["errors"] = o_err
            print(f"✅ Model {m_added} / Option {o_added} added (에러 row 스킵 {o_err})")
        else:
            s.rollback()
            print("🔍 dry-run: rollback")

    print(f"\n결과: 신규 옵션 {counts['new_opt']} / 신규 Model {counts['new_model']} / "
          f"신규 IP {counts['new_ip']} / 기존 {counts['existing_opt']} / "
          f"스킵(중복 csku) {counts['skipped']} / 에러 {counts['errors']}")
    return counts


# ───────────────────────────────────────────────────────────
# 3단계: 재고 초기화 (InventoryTx 입고 일괄)
# ───────────────────────────────────────────────────────────
def step_stock(records: list[dict], dry_run: bool) -> dict:
    """박스히어로 수량을 InventoryTx 로 위치별 입고 등록.

    위치 매핑:
      - quantity_default → '기본 위치 수정'
      - quantity_gross   → '그로스'
      - quantity_disabled → '판매불가'
    """
    banner("[3단계] 재고 초기화 (InventoryTx 위치별 입고)")
    counts = {"locations_resolved": 0, "tx_added": 0, "no_opt": 0, "errors": 0}

    with SessionLocal() as s:
        # 위치 매핑
        loc_by_name = {l.name: l for l in s.query(InventoryLocation).filter(
            InventoryLocation.deleted_at.is_(None)
        ).all()}
        print(f"위치: {list(loc_by_name.keys())}")

        # 위치 이름 매핑 — 박스히어로 → 시스템
        loc_default = loc_by_name.get("기본 위치 수정") or loc_by_name.get("기본 위치")
        loc_gross = loc_by_name.get("그로스") or loc_by_name.get("그로스 ")
        loc_disabled = loc_by_name.get("판매불가")

        if not loc_default:
            print("⚠️ '기본 위치' 위치 없음 — 첫 번째 위치 사용")
            loc_default = list(loc_by_name.values())[0] if loc_by_name else None

        # boxhero_sku → Option 매핑
        opt_by_bsku = {}
        for opt in s.query(Option).filter(Option.boxhero_sku.isnot(None)).all():
            if opt.boxhero_sku:
                opt_by_bsku[opt.boxhero_sku.lower()] = opt

        for rec in records:
            bsku = rec["sku"]
            opt = opt_by_bsku.get(bsku.lower())
            if not opt:
                counts["no_opt"] += 1
                continue

            # 각 위치별 수량 처리
            for loc_obj, qty_field in [
                (loc_default, "quantity_default"),
                (loc_gross, "quantity_gross"),
                (loc_disabled, "quantity_disabled"),
            ]:
                if not loc_obj:
                    continue
                qty = rec.get(qty_field) or 0
                if qty <= 0:
                    continue

                if not dry_run:
                    try:
                        tx = InventoryTx(
                            tx_type="in",
                            location_id=loc_obj.id,
                            option_canonical_sku=opt.canonical_sku,
                            qty=qty,
                            memo=f"[박스히어로 import] 초기 입고 ({loc_obj.name})",
                            created_by="boxhero_import",
                            source="import",
                            status="completed",
                            created_at=dt.datetime.utcnow(),
                        )
                        s.add(tx)
                        counts["tx_added"] += 1
                    except Exception as e:
                        counts["errors"] += 1
                        print(f"  [ERROR] {opt.canonical_sku}: {e}")
                else:
                    counts["tx_added"] += 1

        if not dry_run:
            try:
                s.commit()
                print("✅ commit 완료")
            except Exception as e:
                s.rollback()
                counts["errors"] += 1
                print(f"❌ commit 실패: {e}")
        else:
            s.rollback()
            print("🔍 dry-run: rollback")

    print(f"\n결과: 트랜잭션 {counts['tx_added']} 추가 / 옵션없음 {counts['no_opt']} / 에러 {counts['errors']}")
    return counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--xlsx", required=True, help="박스히어로 export xlsx 경로")
    p.add_argument("--step", required=True, choices=["barcode-only", "options", "stock", "all"],
                   help="실행할 단계")
    p.add_argument("--dry-run", action="store_true", help="실제 적용 X (rollback)")
    args = p.parse_args()

    if not Path(args.xlsx).exists():
        print(f"❌ 파일 없음: {args.xlsx}", file=sys.stderr)
        return 1

    records = parse_xlsx(args.xlsx)
    banner(f"엑셀 파싱 — {len(records)} row")

    if args.step == "barcode-only" or args.step == "all":
        step_barcode_only(records, args.dry_run)
    if args.step == "options" or args.step == "all":
        step_options(records, args.dry_run)
    if args.step == "stock" or args.step == "all":
        step_stock(records, args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
