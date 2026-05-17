"""[E] T17 — 데이터 마이그레이션 / 등록 ID 채움.

이전 세션에서 모음전 자동화 스크립트로 실 등록 테스트가 완료된 ID들을
적절한 Model 행에 채워 넣는다. 등록된 model_code를 인자로 지정.

사용:
  python scripts/migrate_existing_ids.py 메이트 \\
      --naver-id 13396056487 --coupang-id 16174944531

상태 확인 (인자 없이):
  python scripts/migrate_existing_ids.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.db import SessionLocal, init_db
from lemouton.sourcing.models import Model, Option, DiscoveryQueueItem
from lemouton.uploader.models import MarketRegistration


def show_status() -> None:
    s = SessionLocal()
    try:
        n_models = s.query(Model).count()
        n_options = s.query(Option).count()
        n_with_naver = s.query(Model).filter(Model.naver_product_id.isnot(None)).count()
        n_with_coupang = s.query(Model).filter(Model.coupang_product_id.isnot(None)).count()
        n_queue = s.query(DiscoveryQueueItem).filter_by(status='pending').count()
        n_failed = s.query(MarketRegistration).filter_by(status='failed').count()
        print(f"[현재 상태]")
        print(f"  모음전 (Model)       : {n_models}개")
        print(f"  옵션 (Option)        : {n_options}개")
        print(f"  Naver 등록 ID 채움   : {n_with_naver}개")
        print(f"  Coupang 등록 ID 채움 : {n_with_coupang}개")
        print(f"  미맵핑 큐 (pending)  : {n_queue}개")
        print(f"  업로드 실패 (DLQ)    : {n_failed}개")
        if n_models:
            print(f"\n[모음전 코드 목록]")
            for m in s.query(Model).order_by(Model.model_code).all():
                naver = m.naver_product_id or '-'
                coup = m.coupang_product_id or '-'
                print(f"  {m.model_code:8s}  naver={naver:14s}  coupang={coup:14s}")
    finally:
        s.close()


def patch_ids(model_code: str, naver_id: str | None, coupang_id: str | None) -> None:
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=model_code).first()
        if m is None:
            print(f"[ERROR] 모음전 '{model_code}' 없음 — 먼저 등록 필요", file=sys.stderr)
            sys.exit(1)
        if naver_id:
            m.naver_product_id = str(naver_id)
            print(f"  naver_product_id  = {naver_id}")
        if coupang_id:
            m.coupang_product_id = str(coupang_id)
            print(f"  coupang_product_id = {coupang_id}")
        s.commit()
        print(f"[OK] '{model_code}' 갱신 완료.")
    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser(description='르무통 등록 ID 마이그레이션')
    parser.add_argument('model_code', nargs='?', help='업데이트할 모음전 코드 (예: 메이트)')
    parser.add_argument('--naver-id', help='SS originProductNo')
    parser.add_argument('--coupang-id', help='Coupang sellerProductId')
    args = parser.parse_args()

    init_db()  # 새 컬럼 누락 시 생성

    if not args.model_code:
        show_status()
        return
    if not (args.naver_id or args.coupang_id):
        print("[INFO] --naver-id 또는 --coupang-id 중 하나는 필요해요.")
        show_status()
        return
    patch_ids(args.model_code, args.naver_id, args.coupang_id)


if __name__ == '__main__':
    main()
