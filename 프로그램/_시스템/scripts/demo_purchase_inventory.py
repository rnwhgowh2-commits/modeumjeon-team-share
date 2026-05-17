"""모음전 옵션에 '사입용 재고' 반영 — 가격 별도 마진.

사입용 = 박스히어로 자체 사입 (boxhero_stock_total + boxhero_avg_purchase_price).
가격 별도 = 옵션 단위 사입 마진 오버라이드 (option_boxhero_margin_mode/value).
"""
import sys
from datetime import datetime, timezone

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.db import SessionLocal
import lemouton.sourcing.models  # noqa
import lemouton.templates.models  # noqa
import lemouton.inventory.models  # noqa

from lemouton.sourcing.models import Option, Model
from lemouton.templates.models import PriceTemplate
from lemouton.pricing.boxhero_margin import compute_sale_price


# (모음전 SKU, 박스히어로 SKU, 사입 재고, 평균 매입가, 사입 마진 mode, 사입 마진 value)
PURCHASE_DATA = [
    # 메이트 그레이 — rate 30% (기본 +5%)
    ('르무통 메이트-그레이-240', 'BH-MATE-GR-240', 15,  87_000, 'rate',   3000),
    ('르무통 메이트-그레이-245', 'BH-MATE-GR-245', 20,  87_000, 'amount', 30_000),
    ('르무통 메이트-그레이-250', 'BH-MATE-GR-250', 12,  89_000, 'rate',   2800),
    ('르무통 메이트-그레이-255', 'BH-MATE-GR-255',  8,  89_000, 'rate',   2500),
    ('르무통 메이트-그레이-260', 'BH-MATE-GR-260',  5,  91_000, 'amount', 25_000),
    ('르무통 메이트-그레이-265', 'BH-MATE-GR-265',  3,  91_000, 'rate',   3500),
    # 메이트 다크네이비
    ('르무통 메이트-다크네이비-240', 'BH-MATE-NV-240', 18,  92_000, 'rate',   3200),
    ('르무통 메이트-다크네이비-245', 'BH-MATE-NV-245', 25,  92_000, 'amount', 35_000),
]


def main():
    s = SessionLocal()
    try:
        print("="*70)
        print("  사입용 재고 반영 (가격 별도 마진)")
        print("="*70)

        applied = 0
        skipped = []
        for sku, bh_sku, stock, avg, margin_mode, margin_val in PURCHASE_DATA:
            opt = s.query(Option).filter(Option.canonical_sku == sku).first()
            if not opt:
                skipped.append((sku, '옵션 없음'))
                continue

            # 박스히어로 매핑 + 사입 재고 + 평균 매입가
            opt.boxhero_sku = bh_sku
            opt.boxhero_stock_total = stock
            opt.boxhero_avg_purchase_price = avg
            opt.boxhero_avg_updated_at = datetime.now(timezone.utc)

            # 옵션 단위 사입 마진 (option layer) — 가격 별도
            opt.option_boxhero_margin_mode = margin_mode
            opt.option_boxhero_margin_value = margin_val

            applied += 1

            # 산식 미리 계산
            model = s.query(Model).filter(Model.model_code == opt.model_code).first()
            tpl_id = opt.price_template_id_override or (model.price_template_id if model else None)
            tpl = s.query(PriceTemplate).filter(PriceTemplate.id == tpl_id).first() if tpl_id else None
            calc = compute_sale_price(opt, model, tpl, 'self')
            if margin_mode == 'rate':
                margin_label = f"rate {margin_val/100:.2f}%"
            else:
                margin_label = f"amount +{margin_val:,}원"
            print(f"  {sku:30s} → BH={bh_sku:18s} 재고 {stock:3d} / 매입 {avg:>7,} / "
                  f"마진 {margin_label:18s} → 자체판매가 {calc['sale_price']:>7,}원 (마진 +{calc['margin_amount']:,})")

        s.commit()
        print()
        print(f"  적용 완료: {applied} 옵션")
        if skipped:
            print(f"  스킵: {skipped}")

        # 통계
        total_options = s.query(Option).count()
        with_purchase = s.query(Option).filter(Option.boxhero_avg_purchase_price > 0).count()
        with_option_margin = s.query(Option).filter(Option.option_boxhero_margin_mode.isnot(None)).count()
        print()
        print(f"  종합: 총 옵션 {total_options}, 사입재고 보유 {with_purchase}, "
              f"옵션-단위 사입 마진 {with_option_margin}")
    finally:
        s.close()


if __name__ == '__main__':
    main()
