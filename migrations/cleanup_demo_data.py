"""시연 데이터 청소 — Supabase 의 InventoryTx + InventoryProduct 전체 삭제.

박스히어로 정식 import 직전. 기존 PC SQLite 는 건드리지 않음.

사용:
  python migrations/cleanup_demo_data.py --dry-run
  python migrations/cleanup_demo_data.py --execute
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

NEW_SYSTEM = Path(__file__).resolve().parent.parent / "_시스템"
sys.path.insert(0, str(NEW_SYSTEM))
os.chdir(NEW_SYSTEM)
from dotenv import load_dotenv
load_dotenv(NEW_SYSTEM / ".env", override=True)

from sqlalchemy import func
import lemouton.sourcing.models
import lemouton.sourcing.models_pricing
import lemouton.pricing.settings
import lemouton.uploader.models
import lemouton.templates.models
from lemouton.inventory.models import InventoryTx, InventoryProduct
from shared.db import SessionLocal


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()
    if not (args.dry_run or args.execute):
        print("--dry-run 또는 --execute 필요"); return 1

    with SessionLocal() as s:
        tx_count = s.query(func.count(InventoryTx.id)).scalar() or 0
        ip_count = s.query(func.count(InventoryProduct.id)).scalar() or 0
        print(f"삭제 대상: InventoryTx {tx_count}건 + InventoryProduct {ip_count}건")

        if args.dry_run:
            # by created_by 분포
            from sqlalchemy import distinct
            by_user = s.query(InventoryTx.created_by, func.count(InventoryTx.id))\
                       .group_by(InventoryTx.created_by).all()
            for u, c in sorted(by_user, key=lambda x: -x[1])[:15]:
                print(f"   {u!r}: {c}건")
            print("\n🔍 dry-run — 실제 삭제 안 함")
            return 0

        # 실제 삭제
        s.query(InventoryTx).delete(synchronize_session=False)
        s.query(InventoryProduct).delete(synchronize_session=False)
        s.commit()

        # 검증
        tx_after = s.query(func.count(InventoryTx.id)).scalar() or 0
        ip_after = s.query(func.count(InventoryProduct.id)).scalar() or 0
        print(f"\n✅ 청소 완료")
        print(f"   InventoryTx: {tx_count} → {tx_after}")
        print(f"   InventoryProduct: {ip_count} → {ip_after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
