"""[1회성] 기존 디스크 사진 → R2 이사.

- data/product_images/*  → R2 'product/<fname>' + Option.image_url 갱신
- data/attachments/*     → R2 'attachment/<fname>' (DB 참조는 첨부 JSON 안에 박혀
                           있어 자동 갱신 대상 아님 → 신규 첨부부터 R2, 구 첨부는
                           기존 디스크 라우트로 계속 서빙. 파일만 R2 백업 복사.)

원본 파일은 삭제하지 않는다. 실행 후 며칠 검증 뒤 사용자가 수동 정리.

실행(프로그램\\_시스템 안에서):  python scripts/migrate_images_to_r2.py --dry-run
                              python scripts/migrate_images_to_r2.py --commit
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from shared import storage
from shared.db import SessionLocal
from lemouton.sourcing.models import Option

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_DIR = ROOT / 'data' / 'product_images'
ATTACH_DIR = ROOT / 'data' / 'attachments'


def migrate_products(commit: bool) -> int:
    """product_images 파일을 R2로 올리고, 그 파일을 가리키던 image_url을 R2 URL로 갱신."""
    if not PRODUCT_DIR.exists():
        print('product_images 디렉터리 없음 — 건너뜀')
        return 0
    n = 0
    s = SessionLocal()
    try:
        for f in PRODUCT_DIR.iterdir():
            if not f.is_file():
                continue
            key = f'product/{f.name}'
            old_url = f'/inventory/data/product-image/{f.name}'
            new_url = storage.public_url(key)
            print(f'  {f.name}  ->  {new_url}')
            if commit:
                with f.open('rb') as fh:
                    storage.put_object(fh.read(), key, _content_type(f.name))
                opts = s.query(Option).filter(Option.image_url == old_url).all()
                for opt in opts:
                    opt.image_url = new_url
            n += 1
        if commit:
            s.commit()
    finally:
        s.close()
    return n


def migrate_attachments(commit: bool) -> int:
    """attachments 파일을 R2로 백업 복사(DB 참조 갱신은 안 함 — 신규부터 R2)."""
    if not ATTACH_DIR.exists():
        print('attachments 디렉터리 없음 — 건너뜀')
        return 0
    n = 0
    for f in ATTACH_DIR.iterdir():
        if not f.is_file():
            continue
        key = f'attachment/{f.name}'
        print(f'  {f.name}  ->  {storage.public_url(key)}')
        if commit:
            with f.open('rb') as fh:
                storage.put_object(fh.read(), key, _content_type(f.name))
        n += 1
    return n


def _content_type(name: str) -> str:
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    return storage._CONTENT_TYPES.get(ext, 'application/octet-stream')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--commit', action='store_true', help='실제 업로드/DB갱신 수행')
    ap.add_argument('--dry-run', action='store_true', help='미리보기만')
    args = ap.parse_args()
    commit = args.commit and not args.dry_run
    if not Config.R2_ENABLED:
        raise SystemExit('R2 미설정(.env) — R2_ACCOUNT_ID / R2_PUBLIC_BASE_URL 필요')
    mode = 'COMMIT' if commit else 'DRY-RUN'
    print(f'=== 이미지 R2 이사 [{mode}] ===')
    print('[상품 이미지]')
    p = migrate_products(commit)
    print('[첨부]')
    a = migrate_attachments(commit)
    print(f'완료 — 상품 {p}건, 첨부 {a}건 ({mode})')
    if not commit:
        print('실제 반영하려면 --commit 으로 다시 실행')


if __name__ == '__main__':
    main()
