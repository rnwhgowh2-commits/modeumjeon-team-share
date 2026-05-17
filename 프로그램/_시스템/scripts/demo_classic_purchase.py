"""르무통 클래식 모음전 — 가상 사입재고 입고 + 사입재고 활성화 토글 ON.

흐름:
  1. 클래식 36 옵션 중 12개 픽업
  2. 입고 Tx 생성 (가상 구매 — 위치=기본, 수량+매입가 부여)
  3. 옵션 단위 사입 마진 별도 설정 (option layer)
  4. use_purchase_inventory=True (활성화 토글 ON) — 매트릭스에서 자체 판매가 적용
"""
import sys
from datetime import datetime, timezone

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.db import SessionLocal, init_db
import lemouton.sourcing.models  # noqa
import lemouton.templates.models  # noqa
import lemouton.inventory.models  # noqa

# 마이그레이션 실행 (use_purchase_inventory 컬럼 추가)
init_db()

from lemouton.sourcing.models import Option, Model
from lemouton.templates.models import PriceTemplate
from lemouton.inventory import inbound as tx_svc
from lemouton.pricing.boxhero_margin import compute_sale_price


# 클래식 모델 옵션에 부여할 가상 사입재고 — 12개 옵션
PURCHASE_DATA = [
    # (color, size, 박스히어로 SKU, 입고 수량, 매입가, 사입 마진 mode, 사입 마진 value)
    ('블랙',     220, 'BH-CLASSIC-BK-220', 30, 78_000, 'rate',   3000),
    ('블랙',     225, 'BH-CLASSIC-BK-225', 45, 78_000, 'rate',   3000),
    ('블랙',     230, 'BH-CLASSIC-BK-230', 60, 80_000, 'rate',   2800),
    ('블랙',     235, 'BH-CLASSIC-BK-235', 50, 80_000, 'amount', 28_000),
    ('블랙',     240, 'BH-CLASSIC-BK-240', 35, 82_000, 'rate',   2500),
    ('블랙',     245, 'BH-CLASSIC-BK-245', 20, 82_000, 'amount', 30_000),
    ('화이트',   220, 'BH-CLASSIC-WH-220', 25, 80_000, 'rate',   3200),
    ('화이트',   225, 'BH-CLASSIC-WH-225', 40, 80_000, 'rate',   3200),
    ('화이트',   230, 'BH-CLASSIC-WH-230', 55, 82_000, 'rate',   3000),
    ('화이트',   235, 'BH-CLASSIC-WH-235', 38, 82_000, 'amount', 32_000),
    ('화이트',   240, 'BH-CLASSIC-WH-240', 22, 84_000, 'rate',   2700),
    ('화이트',   245, 'BH-CLASSIC-WH-245', 15, 84_000, 'amount', 35_000),
]


def main():
    s = SessionLocal()
    try:
        # 클래식 모델 찾기
        model = s.query(Model).filter(Model.model_name_raw.like('%클래식%')).first()
        if not model:
            print("❌ 클래식 모음전 없음")
            return
        print(f"\n🎯 대상: {model.model_code} — {model.model_name_raw}")

        applied = 0
        skipped = []
        print(f"\n{'='*72}")
        print(f"  STEP 1: 가상 사입재고 입고 (입고 Tx + 옵션 마진 + 활성화 토글 ON)")
        print(f"{'='*72}")

        for color, size, bh_sku, qty, price, margin_mode, margin_val in PURCHASE_DATA:
            # 옵션 찾기 — color + size 매칭
            opt = (s.query(Option)
                   .filter(Option.model_code == model.model_code,
                           Option.color_code.like(f'%{color}%') | Option.color_display.like(f'%{color}%'),
                           Option.size_code == str(size))
                   .first())
            if not opt:
                skipped.append((f'{color}-{size}', '매칭 없음'))
                continue

            # 박스히어로 매핑 + 옵션 단위 마진 + 활성화 토글
            opt.boxhero_sku = bh_sku
            opt.option_boxhero_margin_mode = margin_mode
            opt.option_boxhero_margin_value = margin_val
            opt.use_purchase_inventory = True  # ★ 사입재고 활성화 ON
            s.flush()

            # 입고 Tx 생성 (가상 구매)
            tx = tx_svc.create_inbound(
                s, location_id=1, option_canonical_sku=opt.canonical_sku,
                qty=qty, unit_purchase_price=price,
                partner_label='클래식 가상 사입',
                memo=f'사입재고 시연 — {color} {size}',
                created_by='시연',
            )
            applied += 1

            # 산식 계산
            tpl_id = opt.price_template_id_override or model.price_template_id
            tpl = s.query(PriceTemplate).filter(PriceTemplate.id == tpl_id).first() if tpl_id else None
            calc_self = compute_sale_price(opt, model, tpl, 'self')
            calc_ext = compute_sale_price(opt, model, tpl, 'external')
            margin_label = (f"rate {margin_val/100:.1f}%" if margin_mode == 'rate'
                            else f"+{margin_val:,}원")
            print(f"  ✅ {opt.canonical_sku:32s} 입고 +{qty:2d} @{price:>6,} | "
                  f"마진 {margin_label:14s} → 자체 {calc_self['sale_price']:>7,}원 / "
                  f"외부 {calc_ext['sale_price']:>7,}원 | 토글 ON")

        s.commit()

        if skipped:
            print(f"\n  스킵: {skipped}")

        # ============ 통계 ============
        print(f"\n{'='*72}")
        print(f"  STEP 2: 종합")
        print(f"{'='*72}")
        active = s.query(Option).filter(Option.use_purchase_inventory == True).count()
        with_purchase = s.query(Option).filter(Option.boxhero_avg_purchase_price > 0).count()
        total = s.query(Option).count()
        print(f"  옵션 총합:                {total}")
        print(f"  사입재고 보유:             {with_purchase}")
        print(f"  ★ 사입재고 활성화 토글 ON: {active}")
        print(f"  적용 라인:                {applied}")

        # 클래식 36 옵션 요약
        print(f"\n  르무통 클래식 36 옵션 — 활성화 ON:")
        active_opts = (s.query(Option).filter(Option.model_code == model.model_code,
                                              Option.use_purchase_inventory == True)
                       .order_by(Option.canonical_sku).all())
        for opt in active_opts:
            print(f"    · {opt.canonical_sku:32s} 재고 {opt.boxhero_stock_total:3d} "
                  f"매입 {opt.boxhero_avg_purchase_price:>7,} BH={opt.boxhero_sku}")
    finally:
        s.close()


if __name__ == '__main__':
    main()
