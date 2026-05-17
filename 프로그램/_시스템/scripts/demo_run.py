"""시연 자동화 - import 매핑 거래 4종 발주/판매/반품 알림/링크 결과 보고.

박스히어로 서비스 중단 후 단독 운영 (ADR-005) 검증용 라이브 시연.
"""
import io
import sys
import json
import secrets
from pathlib import Path
from datetime import datetime, timezone

# 콘솔 UTF-8 강제 (Windows cp949 회피)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.db import SessionLocal
# Eager-load all models so SQLAlchemy metadata is fully resolved
import lemouton.sourcing.models  # noqa: F401
import lemouton.templates.models  # noqa: F401
import lemouton.inventory.models  # noqa: F401
from lemouton.inventory.boxhero_import import import_xlsx, verify_after_import
from lemouton.inventory.locations import list_active, seed_defaults, create as create_location
from lemouton.inventory import inbound as tx_svc
from lemouton.sourcing.models import Option, Model
from lemouton.inventory.models import (
    PurchaseOrder, SalesOrder, ReturnOrder, InventoryCount,
    InventoryShareLink, InventorySafetyStock, InventoryTx,
)


def banner(t):
    print(f"\n{'='*60}\n  {t}\n{'='*60}")


def demo():
    XLSX = Path(__file__).parent.parent / 'data' / 'TEST_boxhero_demo.xlsx'
    s = SessionLocal()
    try:
        # ========== 1. import ==========
        banner("STEP 1 . 박스히어로 xlsx import")
        result = import_xlsx(str(XLSX), s, threshold_auto=80)
        s.commit()
        print(f"  records:        {result['records_count']}")
        print(f"  자동 매핑:      {len(result['mapped'])}")
        print(f"  검토 큐:        {len(result['queued'])}")
        print(f"  이미 매핑:      {len(result['already_mapped_options'])}")
        print(f"  재고 갱신:      {result['stock_updated']}")
        print(f"  오류:           {len(result['errors'])}")
        if result['mapped'][:3]:
            print(f"  매핑 샘플 3건:")
            for opt, bh, score in result['mapped'][:3]:
                print(f"    {opt}  <-  {bh} (score={score})")

        verify = verify_after_import(s)
        print(f"  검증 - 매핑 {verify['mapped_count']} / 재고 보유 {verify['with_stock']} / 평균가 {verify['with_avg_price']} / 총재고 {verify['total_stock']}")

        # 매핑된 옵션 1개 픽업 (이후 단계에서 SKU로 사용)
        sample_opt = s.query(Option).filter(
            Option.boxhero_sku.isnot(None),
            Option.boxhero_stock_total > 0,
        ).first()
        if not sample_opt:
            print("!️ 매핑.재고 옵션 없음 - 시연 중단")
            return
        SAMPLE_SKU = sample_opt.canonical_sku
        print(f"  -> 시연 샘플 SKU: {SAMPLE_SKU}  (재고 {sample_opt.boxhero_stock_total}, 평균가 {sample_opt.boxhero_avg_purchase_price})")

        # ========== 2. 위치 ==========
        banner("STEP 2 . 위치 시드 (창고/매장)")
        seed_defaults(s)
        s.commit()
        locs = list_active(s)
        for loc in locs:
            print(f"  . {loc.name} (id={loc.id}, default={loc.is_default})")
        loc_main = locs[0]

        # ========== 3. 거래 4종 ==========
        banner("STEP 3 . 거래 4종 시연")
        # 입고 +5
        tx1 = tx_svc.create_inbound(s, location_id=loc_main.id,
                                    option_canonical_sku=SAMPLE_SKU, qty=5,
                                    unit_purchase_price=88000,
                                    partner_label='시연 입고', memo='시연 #1 입고',
                                    created_by='데모')
        s.commit()
        print(f"  ✅ 입고 #{tx1.id}  +5개 @88000")

        # 출고 -2
        tx2 = tx_svc.create_outbound(s, location_id=loc_main.id,
                                     option_canonical_sku=SAMPLE_SKU, qty=2,
                                     unit_sale_price=125000,
                                     partner_label='시연 고객', memo='시연 #2 출고',
                                     created_by='데모')
        s.commit()
        print(f"  ✅ 출고 #{tx2.id}  -2개 @125000  (COGS snapshot @{tx2.unit_purchase_price_at_tx})")

        # 조정 absolute
        s.refresh(sample_opt)
        cur_stock = sample_opt.boxhero_stock_total
        new_stock = cur_stock + 3  # +3 만큼 조정
        tx3 = tx_svc.create_adjustment(s, location_id=loc_main.id,
                                       option_canonical_sku=SAMPLE_SKU,
                                       new_qty=new_stock,
                                       memo='시연 #3 조정',
                                       created_by='데모')
        s.commit()
        print(f"  ✅ 조정 #{tx3.id}  ={new_stock}개 (기존 {cur_stock} -> {new_stock})")

        # 이동 (다른 위치 있으면)
        if len(locs) >= 2:
            loc_to = locs[1]
            tx4 = tx_svc.create_move(s, from_location_id=loc_main.id,
                                     to_location_id=loc_to.id,
                                     option_canonical_sku=SAMPLE_SKU, qty=1,
                                     memo='시연 #4 이동',
                                     created_by='데모')
            s.commit()
            print(f"  ✅ 이동 #{tx4.id}  {loc_main.name} -> {loc_to.name}  -1개")

        # ========== 4. 발주 -> 검사 ==========
        banner("STEP 4 . 발주 + 검사 처리")
        po = PurchaseOrder(
            partner_label='시연 공급처',
            items_json=json.dumps([
                {'sku': SAMPLE_SKU, 'qty': 10, 'unit_price': 86000},
            ], ensure_ascii=False),
            status='pending',
            memo='시연 PO',
            created_by='데모',
        )
        s.add(po)
        s.commit()
        print(f"  ✅ 발주 PO #{po.id} 생성 (10개 @86000)")

        # 검사 처리 - 9개만 받음 (1개 미입고 -> partial)
        tx_svc.create_inbound(s, location_id=loc_main.id,
                              option_canonical_sku=SAMPLE_SKU, qty=9,
                              unit_purchase_price=86000,
                              partner_label=po.partner_label,
                              memo=f'PO #{po.id} 검사 (예상 10 -> 실제 9, 차이 !)',
                              created_by='검사')
        po.status = 'partial'
        s.commit()
        print(f"  ✅ 검사 처리 - PO #{po.id}: 예상 10 / 실제 9 -> status=partial")

        # ========== 5. 판매 + 반품 ==========
        banner("STEP 5 . 판매 + 반품")
        so = SalesOrder(
            partner_label='시연 매장',
            items_json=json.dumps([{'sku': SAMPLE_SKU, 'qty': 3, 'unit_price': 130000}], ensure_ascii=False),
            status='pending', memo='시연 SO', created_by='데모',
        )
        s.add(so)
        s.commit()
        print(f"  ✅ 판매 SO #{so.id} 생성 (3개 @130000)")

        ro = ReturnOrder(
            sales_order_id=so.id,
            items_json=json.dumps([{'sku': SAMPLE_SKU, 'qty': 1}], ensure_ascii=False),
            status='pending', created_by='데모',
        )
        s.add(ro)
        s.commit()
        print(f"  ✅ 반품 RO #{ro.id} 생성 (SO #{so.id} 중 1개 반품)")

        # ========== 6. 재고조사 ==========
        banner("STEP 6 . 재고조사")
        c = InventoryCount(
            name='시연 정기실사',
            target_locations_json=json.dumps([loc_main.id]),
            status='in_progress',
        )
        s.add(c)
        s.commit()
        print(f"  ✅ 재고조사 #{c.id} 시작 -> 마감")
        c.status = 'closed'
        c.closed_at = datetime.now(timezone.utc)
        s.commit()
        print(f"  ✅ 재고조사 #{c.id} closed_at={c.closed_at.strftime('%H:%M:%S')}")

        # ========== 7. 안전재고 알림 ==========
        banner("STEP 7 . 안전재고 알림")
        alert = InventorySafetyStock(
            option_canonical_sku=SAMPLE_SKU,
            location_id=None,  # 전체
            threshold=100,  # 일부러 높게 -> 알림 발생 유도
        )
        s.add(alert)
        s.commit()
        s.refresh(sample_opt)
        gap = 100 - (sample_opt.boxhero_stock_total or 0)
        print(f"  ✅ 임계값 {SAMPLE_SKU} ≥ 100 (현재 {sample_opt.boxhero_stock_total}, gap={gap})")

        # ========== 8. 공유링크 ==========
        banner("STEP 8 . 재고 공유 링크")
        link = InventoryShareLink(
            name='시연 공개 링크', token=secrets.token_urlsafe(24),
            created_by='데모',
        )
        s.add(link)
        s.commit()
        print(f"  ✅ 링크 #{link.id} 토큰={link.token[:16]}...")
        print(f"     URL: /inventory/share/public/{link.token}")

        # ========== 9. R2 옵션 매트릭스 - 사입 마진 ==========
        banner("STEP 9 . R2 *** 사입 마진 옵션 오버라이드")
        sample_opt.option_boxhero_margin_mode = 'rate'
        sample_opt.option_boxhero_margin_value = 3500  # 35.00%
        sample_opt.option_external_margin_mode = 'amount'
        sample_opt.option_external_margin_value = 25000
        s.commit()
        print(f"  ✅ {SAMPLE_SKU} 자체=35.00% / 외부=+25,000원 (option layer)")

        # ========== 종합 ==========
        banner("STEP 10 . 종합 통계")
        from sqlalchemy import func
        stats = {
            'options_total': s.query(Option).count(),
            'mapped': s.query(Option).filter(Option.boxhero_sku.isnot(None)).count(),
            'with_stock': s.query(Option).filter(Option.boxhero_stock_total > 0).count(),
            'tx_in': s.query(InventoryTx).filter(InventoryTx.tx_type == 'in').count(),
            'tx_out': s.query(InventoryTx).filter(InventoryTx.tx_type == 'out').count(),
            'tx_adjust': s.query(InventoryTx).filter(InventoryTx.tx_type == 'adjust').count(),
            'tx_move': s.query(InventoryTx).filter(InventoryTx.tx_type == 'move').count(),
            'po_count': s.query(PurchaseOrder).count(),
            'so_count': s.query(SalesOrder).count(),
            'ro_count': s.query(ReturnOrder).count(),
            'count_count': s.query(InventoryCount).count(),
            'alert_count': s.query(InventorySafetyStock).count(),
            'link_count': s.query(InventoryShareLink).count(),
        }
        for k, v in stats.items():
            print(f"  {k:20s}  {v}")

        return {'sample_sku': SAMPLE_SKU, 'po_id': po.id, 'so_id': so.id,
                'ro_id': ro.id, 'count_id': c.id, 'alert_id': alert.id,
                'link_token': link.token, 'stats': stats}
    finally:
        s.close()


if __name__ == '__main__':
    demo()
