"""[제품 공유 v1] 마이그레이션 — 기존 옵션 → 재고제품 + 연결 시딩.

설계: 바탕화면 '모음전 — 제품 공유 구조 설계안 v1.html'

무손실 원칙:
  - 기존 options / inventory_txs / models 테이블은 절대 변경하지 않음
  - 신규 테이블 option_product_links 생성 + 행 INSERT 만 수행
  - InventoryProduct(재고제품)는 누락된 옵션분만 신규 INSERT (기존 행은 보존)

멱등: 재실행해도 안전 — 이미 존재하는 재고제품/링크는 skip.

사용법 (cwd = 프로그램/_시스템):
  python scripts/migrate_product_share_v1.py --dry-run   # 미리보기 (커밋 안 함)
  python scripts/migrate_product_share_v1.py             # 실제 적용
  python scripts/migrate_product_share_v1.py --verify    # 적용 결과 검증만
"""
from __future__ import annotations

import argparse
import os
import sys

# 콘솔 UTF-8 (Windows cp949 대응)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 프로그램/_시스템 을 import path 에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db import SessionLocal, engine          # noqa: E402
from lemouton.sourcing.models import Option, Model   # noqa: E402
from lemouton.inventory.models import (              # noqa: E402
    InventoryProduct, OptionProductLink,
)


def _option_name(o: Option) -> str:
    """옵션 → 재고제품 표시명 (예: '미스티로즈-250')."""
    color = (o.color_display or o.color_code or "").strip()
    size = (o.size_display or o.size_code or "").strip()
    name = f"{color}-{size}".strip("-")
    return name or o.canonical_sku


def run(dry_run: bool = False, verify_only: bool = False) -> int:
    # ── 검증 전용 모드 ──
    if verify_only:
        s = SessionLocal()
        try:
            opt_count = s.query(Option).count()
            link_count = s.query(OptionProductLink).count()
            ip_count = s.query(InventoryProduct).count()
            print(f"[검증] 옵션 {opt_count} / 연결링크 {link_count} / 재고제품 {ip_count}")
            ok = link_count >= opt_count
            print("  → " + ("OK — 모든 옵션에 연결링크 존재" if ok
                             else f"X — 링크 누락 {opt_count - link_count}건"))
            return 0 if ok else 1
        finally:
            s.close()

    # ── 1) 신규 테이블 생성 (option_product_links 만, 이미 있으면 skip) ──
    OptionProductLink.__table__.create(engine, checkfirst=True)
    InventoryProduct.__table__.create(engine, checkfirst=True)  # 혹시 미생성 시 대비
    print("[1] 신규 테이블 확인/생성 완료 — option_product_links")

    # ── 2) 옵션 순회하며 재고제품 + 링크 시딩 ──
    s = SessionLocal()
    try:
        rows = (
            s.query(Option, Model)
            .outerjoin(Model, Option.model_code == Model.model_code)
            .all()
        )
        total = len(rows)
        existing_ip = {r[0] for r in s.query(InventoryProduct.canonical_sku).all()}
        existing_link = {
            r[0] for r in s.query(OptionProductLink.option_canonical_sku).all()
        }

        ip_new = ip_skip = link_new = link_skip = 0
        for opt, model in rows:
            sku = opt.canonical_sku
            if not sku:
                continue
            # 재고제품 — 없으면 신규 (있으면 사용자 데이터 보존, 건드리지 않음)
            if sku not in existing_ip:
                s.add(InventoryProduct(
                    canonical_sku=sku,
                    option_name=_option_name(opt),
                    model_code=opt.model_code,
                    color_code=opt.color_code,
                    size_code=opt.size_code,
                    brand=(model.brand if model else None),
                    category=(model.category if model else None),
                    barcode=opt.barcode,
                    status="completed",
                ))
                existing_ip.add(sku)
                ip_new += 1
            else:
                ip_skip += 1
            # 연결링크 — 초기 1:1 자기참조 (product_sku == option_sku)
            if sku not in existing_link:
                s.add(OptionProductLink(
                    option_canonical_sku=sku,
                    product_canonical_sku=sku,
                ))
                existing_link.add(sku)
                link_new += 1
            else:
                link_skip += 1

        print(f"[2] 옵션 {total}개 처리")
        print(f"    재고제품  신규 {ip_new} / 기존보존 {ip_skip}")
        print(f"    연결링크  신규 {link_new} / 기존보존 {link_skip}")

        if dry_run:
            s.rollback()
            print("[DRY-RUN] 커밋하지 않음 — 실제 적용하려면 --dry-run 없이 재실행")
            return 0

        s.commit()
        print("[3] 커밋 완료")

        # ── 4) 검증 — 옵션 수 = 링크 수 ──
        opt_count = s.query(Option).count()
        link_count = s.query(OptionProductLink).count()
        ok = link_count >= opt_count
        print(f"[검증] 옵션 {opt_count} / 연결링크 {link_count} → "
              + ("OK" if ok else f"X — 누락 {opt_count - link_count}건"))
        return 0 if ok else 1
    finally:
        s.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="제품 공유 v1 마이그레이션")
    ap.add_argument("--dry-run", action="store_true", help="미리보기 (커밋 안 함)")
    ap.add_argument("--verify", action="store_true", help="적용 결과 검증만")
    args = ap.parse_args()
    sys.exit(run(dry_run=args.dry_run, verify_only=args.verify))
