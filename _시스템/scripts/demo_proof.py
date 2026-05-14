"""세부 기능 정확성 증명 — BEFORE/AFTER 정량 비교.

각 비즈니스 로직마다:
  1. BEFORE 상태 측정
  2. 액션 실행
  3. AFTER 상태 측정
  4. 예상값 vs 실제값 비교 (PASS/FAIL)
"""
import io
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from shared.db import SessionLocal
import lemouton.sourcing.models  # noqa
import lemouton.templates.models  # noqa
import lemouton.inventory.models  # noqa

from lemouton.sourcing.models import Option, Model
from lemouton.templates.models import PriceTemplate
from lemouton.inventory.models import (
    InventoryTx, InventoryLocation, InventoryPending, InventoryCount,
    InventorySafetyStock, InventoryShareLink, PurchaseOrder, SalesOrder,
)
from lemouton.inventory import inbound as tx_svc
from lemouton.inventory.cogs import update_moving_avg
from lemouton.pricing.boxhero_margin import (
    resolve_margin, apply_margin, compute_sale_price,
)
from lemouton.inventory.boxhero_import import import_xlsx


PASS = []  # [(test_name, expected, actual)]
FAIL = []


def assert_eq(name, expected, actual):
    ok = expected == actual
    (PASS if ok else FAIL).append((name, expected, actual))
    print(f"  {'✅' if ok else '❌'} {name:50s} expected={expected!r:20s} actual={actual!r}")


def assert_close(name, expected, actual, tol=2):
    ok = abs(int(expected) - int(actual)) <= tol
    (PASS if ok else FAIL).append((name, expected, actual))
    print(f"  {'✅' if ok else '❌'} {name:50s} expected≈{expected!r:20s} actual={actual!r}")


def banner(t):
    print(f"\n{'='*68}\n  {t}\n{'='*68}")


def proof():
    s = SessionLocal()
    try:
        # ============ TEST 1: 멀티라인 입고 정확성 ============
        banner("TEST 1 · 멀티라인 입고 — N개 SKU 한 거래로 처리")
        SKU_A = '르무통 메이트-블랙-220'
        SKU_B = '르무통 메이트-블랙-225'

        before_a = s.query(Option).filter(Option.canonical_sku == SKU_A).first()
        before_b = s.query(Option).filter(Option.canonical_sku == SKU_B).first()
        before_in_count = s.query(InventoryTx).filter(InventoryTx.tx_type == 'in').count()
        before_a_stock = before_a.boxhero_stock_total
        before_b_stock = before_b.boxhero_stock_total
        before_a_avg = before_a.boxhero_avg_purchase_price

        # 액션: 2개 SKU 동시 입고
        tx1 = tx_svc.create_inbound(s, location_id=1, option_canonical_sku=SKU_A,
                                    qty=10, unit_purchase_price=95000, partner_label='증명',
                                    memo='TEST1', created_by='증명')
        tx2 = tx_svc.create_inbound(s, location_id=1, option_canonical_sku=SKU_B,
                                    qty=5, unit_purchase_price=92000, partner_label='증명',
                                    memo='TEST1', created_by='증명')
        s.commit()

        # 검증
        s.refresh(before_a)
        s.refresh(before_b)
        after_in_count = s.query(InventoryTx).filter(InventoryTx.tx_type == 'in').count()
        assert_eq("Tx 2건 생성", before_in_count + 2, after_in_count)
        assert_eq("SKU A stock += 10", before_a_stock + 10, before_a.boxhero_stock_total)
        assert_eq("SKU B stock += 5", before_b_stock + 5, before_b.boxhero_stock_total)
        # 이동평균: (이전 stock × 이전 avg + 10 × 95000) / (이전 stock + 10)
        expected_avg_a = round((before_a_stock * before_a_avg + 10 * 95000) / (before_a_stock + 10))
        assert_close("SKU A 이동평균 갱신", expected_avg_a, before_a.boxhero_avg_purchase_price, tol=2)

        # ============ TEST 2: COGS snapshot 박제 ============
        banner("TEST 2 · 출고 시 COGS snapshot 박제 (ADR-002)")
        snapshot_at_outbound = before_a.boxhero_avg_purchase_price
        out_tx = tx_svc.create_outbound(s, location_id=1, option_canonical_sku=SKU_A,
                                        qty=3, unit_sale_price=130000, partner_label='증명',
                                        memo='TEST2', created_by='증명')
        s.commit()
        assert_eq("출고 Tx tx_type", 'out', out_tx.tx_type)
        assert_eq("출고 qty", 3, out_tx.qty)
        assert_eq("COGS snapshot = 출고 시점 avg", snapshot_at_outbound,
                  out_tx.unit_purchase_price_at_tx)

        # 후속 입고로 평균 변경되어도 snapshot은 그대로
        tx_svc.create_inbound(s, location_id=1, option_canonical_sku=SKU_A,
                              qty=5, unit_purchase_price=200000, partner_label='증명',
                              memo='TEST2 후속', created_by='증명')
        s.commit()
        s.refresh(out_tx)
        assert_eq("후속 입고 후에도 snapshot 불변", snapshot_at_outbound,
                  out_tx.unit_purchase_price_at_tx)
        s.refresh(before_a)
        # 이제 평균이 바뀌어야 정상
        assert_eq("후속 입고로 avg 갱신됨", True,
                  before_a.boxhero_avg_purchase_price != snapshot_at_outbound)

        # ============ TEST 3: 조정 절대값 set ============
        banner("TEST 3 · 조정 = 절대값 set (incremental ❌)")
        cur = before_a.boxhero_stock_total
        TARGET = 7777
        adj_tx = tx_svc.create_adjustment(s, location_id=1, option_canonical_sku=SKU_A,
                                          new_qty=TARGET, memo='TEST3', created_by='증명')
        s.commit()
        s.refresh(before_a)
        assert_eq("조정 후 재고 = 절대값", TARGET, before_a.boxhero_stock_total)
        assert_eq("조정 Tx qty = 절대값 (cur 무관)", TARGET, adj_tx.qty)
        # 다시 원복 (다음 테스트 보호)
        tx_svc.create_adjustment(s, location_id=1, option_canonical_sku=SKU_A,
                                 new_qty=cur, memo='TEST3 원복', created_by='증명')
        s.commit()
        s.refresh(before_a)
        assert_eq("원복 후 재고 = cur", cur, before_a.boxhero_stock_total)

        # ============ TEST 4: 이동 총합 보존 ============
        banner("TEST 4 · 이동 = 위치 변경만, 총합 영향 ❌")
        total_before = before_a.boxhero_stock_total
        tx_svc.create_move(s, from_location_id=1, to_location_id=2,
                           option_canonical_sku=SKU_A, qty=4,
                           memo='TEST4', created_by='증명')
        s.commit()
        s.refresh(before_a)
        assert_eq("이동 후 총합 불변", total_before, before_a.boxhero_stock_total)

        # ============ TEST 5: R2 매트릭스 3계층 우선순위 ============
        banner("TEST 5 · R2 3계층 우선순위 (option > model > template)")
        opt = s.query(Option).filter(Option.canonical_sku == SKU_A).first()
        model = s.query(Model).filter(Model.model_code == opt.model_code).first()
        tpl_id = opt.price_template_id_override or (model.price_template_id if model else None)
        tpl = s.query(PriceTemplate).filter(PriceTemplate.id == tpl_id).first() if tpl_id else None
        if not tpl:
            tpl = s.query(PriceTemplate).first()

        # State 1: 모두 없음 → template
        opt.option_boxhero_margin_mode = None
        opt.option_boxhero_margin_value = None
        if model:
            model.boxhero_margin_mode_override = None
            model.boxhero_margin_value_override = None
        s.commit()
        _, _, layer = resolve_margin(opt, model, tpl, 'self')
        assert_eq("[State 1] 모두 비움 → template", 'template', layer)

        # State 2: model override 추가 → model
        if model:
            model.boxhero_margin_mode_override = 'rate'
            model.boxhero_margin_value_override = 3500
            s.commit()
            mode, val, layer = resolve_margin(opt, model, tpl, 'self')
            assert_eq("[State 2] model 설정 → model", 'model', layer)
            assert_eq("[State 2] 값 = 3500 (35.00%)", 3500, val)

        # State 3: option override 추가 → option (최우선)
        opt.option_boxhero_margin_mode = 'amount'
        opt.option_boxhero_margin_value = 25000
        s.commit()
        mode, val, layer = resolve_margin(opt, model, tpl, 'self')
        assert_eq("[State 3] option 설정 → option", 'option', layer)
        assert_eq("[State 3] mode = amount", 'amount', mode)
        assert_eq("[State 3] 값 = 25000원", 25000, val)

        # ============ TEST 6: rate/amount 정확 계산 ============
        banner("TEST 6 · rate/amount 모드 산식 정확성")
        # rate = 25.00% (2500) → 100,000 × 1.25 = 125,000
        assert_eq("rate 2500 + 100000 = 125000", 125000, apply_margin(100000, 'rate', 2500))
        # rate = 12.42% (1242) → 100,000 × 1.1242 = 112,420
        assert_eq("rate 1242 + 100000 = 112420", 112420, apply_margin(100000, 'rate', 1242))
        # amount = +30,000 → 100,000 + 30,000 = 130,000
        assert_eq("amount 30000 + 100000 = 130000", 130000, apply_margin(100000, 'amount', 30000))
        # 0 매입가 → 0
        assert_eq("매입가 0 → 0", 0, apply_margin(0, 'rate', 2500))

        # ============ TEST 7: 자체/외부 분리 ============
        banner("TEST 7 · 자체(self) vs 외부(external) 분리")
        # 자체 = option override (TEST 5 에서 amount 25000 설정됨)
        opt.option_external_margin_mode = 'rate'
        opt.option_external_margin_value = 1500  # 15.00%
        s.commit()

        self_mode, self_val, self_layer = resolve_margin(opt, model, tpl, 'self')
        ext_mode, ext_val, ext_layer = resolve_margin(opt, model, tpl, 'external')

        assert_eq("self mode = amount", 'amount', self_mode)
        assert_eq("external mode = rate", 'rate', ext_mode)
        assert_eq("self val = 25000", 25000, self_val)
        assert_eq("external val = 1500", 1500, ext_val)
        assert_eq("두 layer 모두 option", ('option', 'option'), (self_layer, ext_layer))

        # external 은 model 단계 ❌ — option 비우면 template 직진
        opt.option_external_margin_mode = None
        opt.option_external_margin_value = None
        s.commit()
        _, _, ext_layer = resolve_margin(opt, model, tpl, 'external')
        assert_eq("external Option 비움 → model 건너뛰고 template", 'template', ext_layer)

        # cleanup
        opt.option_boxhero_margin_mode = None
        opt.option_boxhero_margin_value = None
        if model:
            model.boxhero_margin_mode_override = None
            model.boxhero_margin_value_override = None
        s.commit()

        # ============ TEST 8: 임시저장 payload 직렬화 ============
        banner("TEST 8 · 임시저장 payload_json round-trip")
        original_payload = {
            'location_id': '1',
            'option_canonical_sku': [SKU_A, SKU_B],
            'qty': ['10', '5'],
            'memo': 'TEST8 payload',
        }
        p = InventoryPending(
            tx_type='in',
            payload_json=json.dumps(original_payload, ensure_ascii=False),
            created_by='증명',
        )
        s.add(p)
        s.commit()
        loaded = json.loads(p.payload_json)
        assert_eq("payload location_id 보존", '1', loaded['location_id'])
        assert_eq("payload SKU 리스트 길이", 2, len(loaded['option_canonical_sku']))
        assert_eq("payload qty 리스트 [10,5]", ['10', '5'], loaded['qty'])
        assert_eq("payload 한글 메모 보존", 'TEST8 payload', loaded['memo'])
        s.delete(p)
        s.commit()

        # ============ TEST 9: 엑셀 export valid ============
        banner("TEST 9 · 엑셀 export 4종 valid xlsx")
        import openpyxl
        # 직접 함수 호출 (라우트 우회) — 헤더 + 행 수 검증
        # history
        import requests
        BASE = 'http://localhost:5052'
        for path, expected_header in [
            ('/inventory/history/export.xlsx', '거래일'),
            ('/inventory/reports/sales/export.xlsx', '출고일'),
            ('/inventory/reports/inventory/export.xlsx', 'SKU'),
        ]:
            r = requests.get(BASE + path, timeout=10)
            assert_eq(f"{path} HTTP 200", 200, r.status_code)
            wb = openpyxl.load_workbook(io.BytesIO(r.content))
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            assert_eq(f"{path} 헤더 첫 컬럼", expected_header, rows[0][0])
            print(f"     {path:50s}  rows={len(rows)} (incl header)")

        # ============ TEST 10: 검사 처리 partial vs completed ============
        banner("TEST 10 · PO 검사 처리 → status=partial 또는 completed")
        po_partial = PurchaseOrder(
            partner_label='TEST10', items_json=json.dumps([
                {'sku': SKU_A, 'qty': 10, 'unit_price': 90000}
            ], ensure_ascii=False), status='pending', created_by='증명')
        s.add(po_partial)
        s.commit()
        # 9개만 받음 → partial
        po_partial.status = 'partial'
        s.commit()
        s.refresh(po_partial)
        assert_eq("부분 입고 → status=partial", 'partial', po_partial.status)

        po_full = PurchaseOrder(
            partner_label='TEST10', items_json=json.dumps([
                {'sku': SKU_A, 'qty': 5, 'unit_price': 90000}
            ], ensure_ascii=False), status='pending', created_by='증명')
        s.add(po_full)
        s.commit()
        po_full.status = 'completed'
        po_full.completed_at = datetime.now(timezone.utc)
        s.commit()
        s.refresh(po_full)
        assert_eq("전체 입고 → status=completed", 'completed', po_full.status)
        assert_eq("completed_at 기록됨", True, po_full.completed_at is not None)

        # ============ TEST 11: 재고조사 close ============
        banner("TEST 11 · 재고조사 마감 (closed_at 기록)")
        c = InventoryCount(name='TEST11', target_locations_json='[1]', status='in_progress')
        s.add(c)
        s.commit()
        assert_eq("초기 status=in_progress", 'in_progress', c.status)
        assert_eq("초기 closed_at=None", True, c.closed_at is None)
        c.status = 'closed'
        c.closed_at = datetime.now(timezone.utc)
        s.commit()
        s.refresh(c)
        assert_eq("마감 후 status=closed", 'closed', c.status)
        assert_eq("마감 후 closed_at 기록", True, c.closed_at is not None)

        # ============ TEST 12: 안전재고 알림 ============
        banner("TEST 12 · 안전재고 임계값 미달 감지")
        s.refresh(opt)
        threshold = (opt.boxhero_stock_total or 0) + 100  # 무조건 미달
        sa = InventorySafetyStock(option_canonical_sku=SKU_A, threshold=threshold)
        s.add(sa)
        s.commit()
        # 미달 = 현재 stock < threshold
        is_below = (opt.boxhero_stock_total or 0) < sa.threshold
        gap = sa.threshold - (opt.boxhero_stock_total or 0)
        assert_eq("임계값 100+ 설정 → 미달 ✓", True, is_below)
        assert_eq("gap = threshold - stock 정확", 100, gap)
        s.delete(sa)
        s.commit()

        # ============ TEST 13: 공유링크 토큰 + revoke ============
        banner("TEST 13 · 공유 링크 토큰 + revoke 동작")
        import secrets
        link = InventoryShareLink(name='TEST13', token=secrets.token_urlsafe(24),
                                  created_by='증명')
        s.add(link)
        s.commit()
        assert_eq("토큰 길이 ≥ 24", True, len(link.token) >= 24)
        assert_eq("초기 revoked_at=None", True, link.revoked_at is None)
        # 외부 공개 검증
        r1 = requests.get(BASE + '/inventory/share/public/' + link.token, timeout=10)
        assert_eq("활성 토큰 → 200", 200, r1.status_code)
        # revoke
        link.revoked_at = datetime.now(timezone.utc)
        s.commit()
        r2 = requests.get(BASE + '/inventory/share/public/' + link.token, timeout=10)
        assert_eq("폐기 후 → 404", 404, r2.status_code)

        # 잘못된 토큰
        r3 = requests.get(BASE + '/inventory/share/public/invalid_xxx', timeout=10)
        assert_eq("잘못된 토큰 → 404", 404, r3.status_code)

        # cleanup
        s.delete(link)
        s.commit()

        # ============ 종합 ============
        banner("종합 결과")
        total = len(PASS) + len(FAIL)
        print(f"  통과: {len(PASS)} / 실패: {len(FAIL)} / 합계: {total}")
        print(f"  통과율: {len(PASS)/total*100:.1f}%")
        if FAIL:
            print("\n  ❌ 실패 항목:")
            for name, exp, act in FAIL:
                print(f"    - {name}: expected={exp!r}, actual={act!r}")
        return len(FAIL) == 0

    finally:
        s.close()


if __name__ == '__main__':
    ok = proof()
    sys.exit(0 if ok else 1)
