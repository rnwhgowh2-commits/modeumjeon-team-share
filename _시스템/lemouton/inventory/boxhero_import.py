"""[I] boxhero_import.py — 박스히어로 1회 import (xlsx 또는 마지막 API).

ADR-005 (서비스 중단 → 단독 운영) 핵심 진입점.

흐름:
  1. xlsx 업로드 → boxhero_xlsx.parse_boxhero_xlsx() (기존 활용)
  2. fuzzy 자동 매핑 (sku_mapping.auto_map_all)
  3. 매핑 성공 옵션의 boxhero_avg_purchase_price + boxhero_stock_total 갱신
  4. 결과: 매핑 mapped/queued/unmapped + 평균매입가 갱신 N개

ai-workflow STEP 7 Sprint 1B Task 1.9
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from lemouton.sourcing.boxhero_xlsx import parse_boxhero_xlsx
from lemouton.sourcing.models import Option, Model
from lemouton.sourcing.master import upsert_model
from lemouton.inventory import sku_mapping
from lemouton.inventory.cogs import update_moving_avg


def _derive_model_code(brand: str | None, model_name: str | None, fallback_sku: str) -> str:
    """박스히어로 record → model_code 슬러그.
    brand+model_name 우선, 없으면 sku 단독 모델."""
    b = (brand or '').strip()
    m = (model_name or '').strip()
    if m:
        raw = f"{b}_{m}" if b else m
    else:
        raw = f"단독_{fallback_sku}"
    return raw.replace(' ', '_').replace('/', '_')[:64]


def _auto_create_master(session: Session, records: list[dict]) -> dict:
    """ADR-005 자동 생성: 박스히어로 record → Model + Option (1:1).

    페이지 헤더 '모음전 옵션 = 박스히어로 SKU 1:1' 의도와 일치.
    canonical_sku = 박스히어로 SKU 그대로, boxhero_sku = 자기 자신.
    """
    created_models = 0
    created_options = 0
    seen_models = set()

    for r in records:
        brand = (r.get('brand') or '').strip() or '미상'
        model_name = (r.get('model_name') or '').strip()
        color = (r.get('color_text') or '').strip() or '-'
        size = (r.get('size') or '').strip() or '-'
        canonical = r['sku']

        model_code = _derive_model_code(brand, model_name, canonical)

        if model_code not in seen_models:
            existed = session.query(Model).filter_by(model_code=model_code).first()
            upsert_model(
                session,
                model_code=model_code,
                model_name_raw=(r.get('name') or model_name or model_code)[:255],
                brand=brand[:100],
            )
            seen_models.add(model_code)
            if existed is None:
                created_models += 1

        existing = session.query(Option).filter_by(canonical_sku=canonical).first()
        if existing is None:
            opt = Option(
                canonical_sku=canonical,
                model_code=model_code,
                color_code=color[:32],
                color_display=color[:64],
                size_code=size[:32],
                size_display=size[:64],
                boxhero_sku=canonical,
            )
            session.add(opt)
            created_options += 1
        elif not existing.boxhero_sku:
            existing.boxhero_sku = canonical

    session.flush()
    return {'created_models': created_models, 'created_options': created_options}


def import_xlsx(xlsx_path: str, session: Session,
                threshold_auto: int = 80) -> dict:
    """박스히어로 xlsx 1회 import.

    Args:
        xlsx_path: 박스히어로 export xlsx 절대 경로.
        session: SQLAlchemy 세션.
        threshold_auto: 자동 매핑 임계 점수 (default 80).

    Returns:
        {
            'records_count': N,
            'mapped': [(option_sku, boxhero_sku, score), ...],
            'queued': [(option_sku, boxhero_sku, score), ...],
            'unmapped_options': [option_sku, ...],
            'already_mapped_options': [option_sku, ...],
            'stock_updated': N,         # 평균매입가 + 재고 갱신 건수
            'errors': [...],
        }
    """
    # 1. xlsx 파싱
    records = list(parse_boxhero_xlsx(xlsx_path))

    # 1.5. ADR-005 자동 생성 — 빈 DB 부트스트랩용 (옵션 0건이어도 안전)
    auto_master = _auto_create_master(session, records)

    # 2. fuzzy 자동 매핑 (Option.boxhero_sku 갱신)
    mapping_result = sku_mapping.auto_map_all(session, records, threshold_auto=threshold_auto)

    # 3. 매핑 성공 옵션의 평균매입가 + 재고 반영
    bh_by_sku = {r['sku']: r for r in records}
    stock_updated = 0
    errors = []
    for opt_sku, bh_sku, score in mapping_result['mapped']:
        bh = bh_by_sku.get(bh_sku)
        if not bh:
            continue
        opt = session.query(Option).filter(Option.canonical_sku == opt_sku).first()
        if not opt:
            errors.append(f"옵션 없음: {opt_sku}")
            continue
        try:
            qty = int(bh.get('quantity') or 0)
            price = int(bh.get('purchase_price') or 0)
            if qty > 0:
                # 재고 0 → 박스히어로 import 시 첫 입고 효과
                opt.boxhero_stock_total = 0
                opt.boxhero_avg_purchase_price = 0
                update_moving_avg(opt, qty_in=qty, price_in=price)
                stock_updated += 1
            else:
                opt.boxhero_stock_total = 0
                opt.boxhero_avg_updated_at = datetime.now(timezone.utc)
        except Exception as e:
            errors.append(f"{opt_sku}: {e}")

    # 이미 매핑돼 있던 옵션도 재고/평균 갱신 (boxhero_sku로 직접 찾기)
    for opt_sku in mapping_result['already_mapped']:
        opt = session.query(Option).filter(Option.canonical_sku == opt_sku).first()
        if not opt or not opt.boxhero_sku:
            continue
        bh = bh_by_sku.get(opt.boxhero_sku)
        if not bh:
            continue
        try:
            qty = int(bh.get('quantity') or 0)
            price = int(bh.get('purchase_price') or 0)
            opt.boxhero_stock_total = 0
            opt.boxhero_avg_purchase_price = 0
            if qty > 0:
                update_moving_avg(opt, qty_in=qty, price_in=price)
                stock_updated += 1
        except Exception as e:
            errors.append(f"{opt_sku}: {e}")

    return {
        'records_count': len(records),
        'mapped': mapping_result['mapped'],
        'queued': mapping_result['queued'],
        'unmapped_options': mapping_result['unmapped'],
        'already_mapped_options': mapping_result['already_mapped'],
        'stock_updated': stock_updated,
        'errors': errors,
        'auto_created_models': auto_master['created_models'],
        'auto_created_options': auto_master['created_options'],
    }


def verify_after_import(session: Session) -> dict:
    """import 후 1:1 수치 자동 비교 (Task 1.11 게이트용).

    Returns:
        {
            'mapped_count': 매핑된 옵션 수,
            'with_avg_price': 평균매입가 > 0 옵션 수,
            'with_stock': 재고 > 0 옵션 수,
            'total_stock': 전체 재고 합산,
        }
    """
    from sqlalchemy import func
    mapped = session.query(func.count(Option.canonical_sku)).filter(
        Option.boxhero_sku.isnot(None)).scalar() or 0
    with_avg = session.query(func.count(Option.canonical_sku)).filter(
        Option.boxhero_avg_purchase_price > 0).scalar() or 0
    with_stock = session.query(func.count(Option.canonical_sku)).filter(
        Option.boxhero_stock_total > 0).scalar() or 0
    total_stock = session.query(func.sum(Option.boxhero_stock_total)).scalar() or 0
    return {
        'mapped_count': mapped,
        'with_avg_price': with_avg,
        'with_stock': with_stock,
        'total_stock': int(total_stock),
    }
