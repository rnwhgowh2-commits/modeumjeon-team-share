"""박스히어로 import → SSOT 재고 일치 검증 — end-to-end 실증.

목적: lemouton/inventory/boxhero_import.py 픽스 (InventoryTx SSOT 동시 갱신) 후
사용자의 실제 xlsx 가 /inventory/ 페이지에 동일 수치로 노출되는지 임시 DB 로 확인.

사용:
  cd 프로그램/_시스템
  python scripts/_verify_boxhero_import_ssot.py "<xlsx 경로>"

비교:
  - xlsx 자체 통계 (raw)
  - import_xlsx 결과
  - get_stock_summary (UI 가 보는 SSOT)  ← 핵심
  - verify_after_import (페이지 verify 패널)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Windows cp949 콘솔에서 UTF-8 강제 (이모지·한글 출력)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # _시스템
sys.path.insert(0, str(ROOT))

# 사용자 xlsx 경로 (인자 또는 디폴트)
USER_XLSX = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:\Users\seung\OneDrive\바탕 화면\Items_Export_99LAB_2026-05-17T23-11-20.xlsx"


def main() -> int:
    if not Path(USER_XLSX).exists():
        print(f"❌ xlsx 없음: {USER_XLSX}", file=sys.stderr)
        return 2

    # 1) 임시 SQLite (격리)
    tmp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp_db.close()
    os.environ['DATABASE_URL'] = f"sqlite:///{Path(tmp_db.name).as_posix()}"

    # 모든 모델 import → Base.metadata 채움 (app.py 와 동일 순서)
    from shared.db import Base, engine, SessionLocal, init_db
    _mods = [
        "lemouton.sourcing.models",
        "lemouton.sourcing.models_pricing",
        "lemouton.pricing.settings",
        "lemouton.uploader.models",
        "lemouton.templates.models",
        "lemouton.inventory.models",
        "lemouton.sources.models",
        "lemouton.sourcing.models_v2",
        "lemouton.multitenancy.models",
        "lemouton.audit.models",
    ]
    for _m in _mods:
        try:
            __import__(_m)
        except ImportError:
            pass
    try:
        import webapp.auth.models  # noqa: F401
    except ImportError:
        pass

    init_db()
    print(f"📦 임시 DB: {tmp_db.name}")

    # 2) xlsx raw 통계
    from lemouton.sourcing.boxhero_xlsx import parse_boxhero_xlsx
    records = list(parse_boxhero_xlsx(USER_XLSX))
    raw_total = len(records)
    raw_qty_skus = sum(1 for r in records if (r.get('quantity') or 0) > 0)
    raw_qty_sum = sum(int(r.get('quantity') or 0) for r in records)
    print()
    print("=== 1) xlsx 자체 ===")
    print(f"  rows:              {raw_total}")
    print(f"  qty > 0 SKU 수:    {raw_qty_skus}")
    print(f"  qty 총합:          {raw_qty_sum}")

    # 3) import 실행 (1차)
    from lemouton.inventory.boxhero_import import import_xlsx, verify_after_import
    s = SessionLocal()
    try:
        result = import_xlsx(USER_XLSX, s)
        s.commit()
        print()
        print("=== 2) import 결과 (1차) ===")
        print(f"  records_count:        {result['records_count']}")
        print(f"  auto_created_models:  {result.get('auto_created_models', 0)}")
        print(f"  auto_created_options: {result.get('auto_created_options', 0)}")
        print(f"  mapped:               {len(result['mapped'])}")
        print(f"  already_mapped:       {len(result['already_mapped_options'])}")
        print(f"  stock_updated:        {result['stock_updated']}")
        print(f"  errors:               {len(result['errors'])}")
        if result['errors']:
            for e in result['errors'][:5]:
                print(f"    - {e}")

        # 4) 바코드 + 제품명 검증 (라벨 인쇄용)
        from sqlalchemy import func
        from sqlalchemy.orm import joinedload
        from lemouton.sourcing.models import Option, Model
        raw_with_bc = sum(1 for r in records if (r.get('barcode') or '').strip())
        opts_with_bc = s.query(func.count(Option.canonical_sku)).filter(
            Option.barcode.isnot(None), Option.barcode != ''
        ).scalar() or 0
        opts_with_model = s.query(func.count(Option.canonical_sku)).filter(
            Option.model.has()
        ).scalar() or 0
        print()
        print("=== 라벨 인쇄용 데이터 ===")
        print(f"  Option.barcode 채워진 수:  {opts_with_bc}  (기대 {raw_with_bc})")
        print(f"  Option → Model 매핑된 수:   {opts_with_model}  (기대 {raw_total})")
        sample = (
            s.query(Option)
            .options(joinedload(Option.model))
            .filter(Option.barcode.isnot(None))
            .limit(3).all()
        )
        for o in sample:
            mname = (o.model.model_name_display or o.model.model_name_raw) if o.model else '—'
            print(f"  · {o.canonical_sku}  →  제품명='{mname}'  색상='{o.color_display}'  사이즈='{o.size_display}'  바코드={o.barcode}")

        # 5) SSOT (페이지가 읽는 통계)
        from shared.inventory_stock import get_stock_summary
        summary = get_stock_summary(s)
        print()
        print("=== 3) /inventory/ 페이지가 읽는 SSOT 통계 ★ ===")
        print(f"  total_skus:    {summary['total_skus']}  (기대 {raw_total})")
        print(f"  in_stock_skus: {summary['in_stock_skus']}  (기대 {raw_qty_skus})")
        print(f"  total_stock:   {summary['total_stock']}  (기대 {raw_qty_sum})")

        ok_skus = summary['total_skus'] == raw_total
        ok_in = summary['in_stock_skus'] == raw_qty_skus
        ok_stock = summary['total_stock'] == raw_qty_sum
        if ok_skus and ok_in and ok_stock:
            print("  ✅ SSOT = xlsx (3/3 일치)")
        else:
            print(f"  ❌ 불일치: skus={ok_skus} in_stock={ok_in} stock={ok_stock}")

        # 5) verify_after_import (페이지 verify 패널)
        v = verify_after_import(s)
        print()
        print("=== 4) verify_after_import (페이지 verify 패널) ===")
        for k, v_ in v.items():
            print(f"  {k}: {v_}")

        # 6) 멱등성 — 재 import 시 중복 누적 X
        print()
        print("=== 5) 재 import (멱등성 검증) ===")
        result2 = import_xlsx(USER_XLSX, s)
        s.commit()
        summary2 = get_stock_summary(s)
        print(f"  total_stock (재 import 후):  {summary2['total_stock']}  (기대 {raw_qty_sum}, 1차의 2배 아님)")
        print(f"  in_stock_skus:                {summary2['in_stock_skus']}")
        if summary2['total_stock'] == raw_qty_sum:
            print("  ✅ 멱등 OK — 재 import 해도 중복 누적 X")
        else:
            print(f"  ❌ 멱등 깨짐: {summary2['total_stock']} ≠ {raw_qty_sum}")

        return 0 if (ok_skus and ok_in and ok_stock and summary2['total_stock'] == raw_qty_sum) else 1
    finally:
        s.close()
        try:
            os.unlink(tmp_db.name)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
