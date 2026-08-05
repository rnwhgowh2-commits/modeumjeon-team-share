# -*- coding: utf-8 -*-
"""쿠팡 상품 상세 응답 모양 실측 (읽기 전용) — 「배송비·가격이 빈 60개」의 원인 규명.

왜: 세소쿠팡 63개 중 60개가 판매가·노출가·배송비 NULL(상세 실패 로그는 0건).
extract_vendor_items 주석에 「실 GET 은 최상위 vendorItemId/salePrice, 구버전은
marketplaceItemData 중첩」 두 모양이 기록돼 있다 — 빈 상품이 구형 모양인지,
아니면 items 자체가 없는지 **실응답으로만** 판정한다(추측 배선 금지).

부르는 것: GET 상품 상세(get_product)만. 생성/수정/삭제 절대 없음.
env: ONLY_MARKET 무시. 대상은 아래 고정 표본(빈 것 3 + 채워진 것 1 대조).
"""
import json
import sys

sys.path.insert(0, '/app')

#: (account_key, seller_product_id, 메모)
SAMPLES = [
    ('세소쿠팡', 15782833359, 'NULL·판매중지·르무통 메이트'),
    ('세소쿠팡', 15787543294, 'NULL·판매중 ·잔스포츠 드로우색'),
    ('세소쿠팡', 15788212253, 'NULL·판매중 ·잔스포츠 슈퍼브레이크'),
    ('브랜드마켓쿠팡', 16141239772, '채워짐 대조군·르무통 스니커즈'),
]


def main() -> int:
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    from lemouton.uploader.market_fetch import _coupang_client
    from shared.platforms.coupang.products import get_product

    s = SessionLocal()
    try:
        accs = {a.account_key: a for a in
                s.query(UploadAccount).filter_by(market='coupang',
                                                 is_active=True).all()}
    finally:
        s.close()

    ok = 0
    for acct, pid, memo in SAMPLES:
        print('=' * 70)
        print(f'[{acct}] {pid} ({memo})')
        a = accs.get(acct)
        if not a:
            print('  ✕ 계정 없음'); continue
        try:
            client = _coupang_client(a.env_prefix)
            d = get_product(pid, client=client)
        except Exception as e:                          # noqa: BLE001
            print(f'  ✕ 조회 실패: {str(e)[:200]}'); continue
        print('  상세 최상위 키:', sorted(d.keys())[:25] if isinstance(d, dict) else type(d).__name__)
        print('  statusName:', d.get('statusName'), '/ deliveryCharge:',
              d.get('deliveryCharge'), '/ deliveryChargeType:', d.get('deliveryChargeType'))
        ship = d.get('marketplaceShippingAndReturnInfo')
        if ship is not None:
            import json as _j
            print('  marketplaceShippingAndReturnInfo:', _j.dumps(ship, ensure_ascii=False)[:500])
        items = d.get('items') or []
        print(f'  items: {len(items)}건')
        for it in items[:2]:
            keys = sorted(it.keys()) if isinstance(it, dict) else it
            print('   아이템 키:', json.dumps(keys, ensure_ascii=False)[:250])
            mp = it.get('marketplaceItemData') or {}
            print('   최상위 salePrice:', it.get('salePrice'),
                  '/ 최상위 vendorItemId:', it.get('vendorItemId'))
            print('   중첩 mp.vendorItemId:', mp.get('vendorItemId'),
                  '/ mp.priceData.salePrice:',
                  (mp.get('priceData') or {}).get('salePrice'))
        ok += 1
    print('\n■ 끝 —', f'{ok}/{len(SAMPLES)} 조회 성공')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
