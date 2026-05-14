"""[v3] 소싱처 사전 + 옵션×소싱처 매핑 + 가격 설정 마이그레이션.

· 신규 테이블 자동 생성 (init_db 가 처리)
· 기존 Model.url_* 5 슬롯 데이터 → SourceRegistry + OptionSourceUrl 로 이전
· OptionPriceConfig 디폴트 행 (auto_enabled=True) 옵션마다 생성

사용:
  python scripts/migrate_pricing_v3.py            # 실행 (멱등)
  python scripts/migrate_pricing_v3.py --dry-run  # SQL 만 출력
  python scripts/migrate_pricing_v3.py --status   # 현재 상태 진단
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.db import SessionLocal, init_db
import lemouton.sourcing.models  # noqa: F401  # Model, Option 등록
import lemouton.sourcing.models_pricing  # noqa: F401
import lemouton.templates.models  # noqa: F401
from lemouton.sourcing.models import Model, Option
from lemouton.sourcing.models_pricing import (
    SourceRegistry, OptionSourceUrl, OptionPriceConfig,
)


# 기존 Model.url_* 5 슬롯의 라벨 → SourceRegistry 이름 매핑
LEGACY_URL_MAP = [
    ('url_lemouton',     '르무통 공홈',   'https://www.lemouton.co.kr'),
    ('url_ss_lemouton',  '스스 르무통',   'https://smartstore.naver.com/lemouton'),
    ('url_musinsa',      '무신사',         'https://musinsa.com'),
    ('url_ssf',          'SSF',            'https://ssfshop.com'),
    ('url_lotteon',      '롯데온',         'https://lotteon.com'),
]


def ensure_source_registry(s, dry_run: bool = False) -> dict[str, int]:
    """디폴트 5 소싱처를 SourceRegistry 에 등록 (없는 것만)."""
    existing = {r.name: r.id for r in s.query(SourceRegistry).all()}
    created = 0
    for order, (_attr, name, url) in enumerate(LEGACY_URL_MAP):
        if name in existing:
            continue
        if dry_run:
            print(f'  [DRY] INSERT SourceRegistry({name}, {url}, sort={order})')
        else:
            s.add(SourceRegistry(name=name, main_url=url, sort_order=order))
            created += 1
    if not dry_run and created:
        s.flush()
        existing = {r.name: r.id for r in s.query(SourceRegistry).all()}
    print(f'· SourceRegistry: {created} 신규 / 총 {len(existing)} 개')
    return existing


def migrate_option_links(s, src_map: dict[str, int], dry_run: bool = False) -> int:
    """기존 Model.url_* → 모음전의 모든 옵션에 OptionSourceUrl 로 복사.

    중복 제거: 같은 (canonical_sku, source_id) 가 이미 있으면 skip.
    """
    existing_pairs = {
        (l.canonical_sku, l.source_id)
        for l in s.query(OptionSourceUrl).all()
    }
    created = 0
    models = s.query(Model).all()
    for m in models:
        opts = s.query(Option).filter_by(model_code=m.model_code).all()
        if not opts:
            continue
        for attr, name, _url in LEGACY_URL_MAP:
            url_val = getattr(m, attr, None)
            if not url_val or not url_val.strip():
                continue
            sid = src_map.get(name)
            if sid is None:
                continue
            for o in opts:
                if (o.canonical_sku, sid) in existing_pairs:
                    continue
                if dry_run:
                    print(f'  [DRY] INSERT OptionSourceUrl({o.canonical_sku}, src={name}, {url_val[:40]}…)')
                else:
                    s.add(OptionSourceUrl(
                        canonical_sku=o.canonical_sku,
                        source_id=sid,
                        product_url=url_val,
                    ))
                    created += 1
                    existing_pairs.add((o.canonical_sku, sid))
    print(f'· OptionSourceUrl: {created} 신규')
    return created


def seed_price_config(s, dry_run: bool = False) -> int:
    """옵션마다 OptionPriceConfig 디폴트 행 (auto_enabled=True) 생성."""
    existing_skus = {c.canonical_sku for c in s.query(OptionPriceConfig).all()}
    created = 0
    opts = s.query(Option).all()
    for o in opts:
        if o.canonical_sku in existing_skus:
            continue
        if dry_run:
            print(f'  [DRY] INSERT OptionPriceConfig({o.canonical_sku}, auto=True)')
        else:
            s.add(OptionPriceConfig(canonical_sku=o.canonical_sku,
                                    auto_enabled=True))
            created += 1
    print(f'· OptionPriceConfig: {created} 신규 (auto_enabled=True 디폴트)')
    return created


def status(s) -> None:
    print(f'· SourceRegistry      : {s.query(SourceRegistry).count()} 행')
    print(f'· OptionSourceUrl    : {s.query(OptionSourceUrl).count()} 행')
    print(f'· OptionPriceConfig   : {s.query(OptionPriceConfig).count()} 행')
    print(f'· Model (참고)        : {s.query(Model).count()} 행')
    print(f'· Option (참고)       : {s.query(Option).count()} 행')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--status', action='store_true')
    args = ap.parse_args()

    print('[v3 마이그레이션] 시작')
    init_db()
    s = SessionLocal()
    try:
        if args.status:
            status(s)
            return
        src_map = ensure_source_registry(s, args.dry_run)
        if not args.dry_run:
            s.commit()
        migrate_option_links(s, src_map, args.dry_run)
        if not args.dry_run:
            s.commit()
        seed_price_config(s, args.dry_run)
        if not args.dry_run:
            s.commit()
        print('\n[완료]')
        status(s)
    finally:
        s.close()


if __name__ == '__main__':
    main()
