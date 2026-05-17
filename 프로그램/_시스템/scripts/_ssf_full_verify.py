"""SSF 두 URL 전수 검증 — 재크롤링 + DB 갱신 + compute_breakdown.

Step:
  1. SourceProduct (id=3 LEMOUTON, id=9 BEANPOLE) refetch via fetch_one_source
  2. DB 의 last_price / dynamic_benefits_json / OptionSourceUrl.price_cached 갱신 확인
  3. compute_breakdown 호출 → steps 출력
  4. 사이트 노출 vs 우리 매트릭스 1:1 비교표
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
from shared.db import SessionLocal
from lemouton.sources.models import SourceProduct, SourceOption
from lemouton.sources.service import fetch_one_source
from lemouton.sourcing.crawlers.ssf import SsfCrawler
from lemouton.sourcing.models_pricing import OptionSourceUrl
from webapp.routes.api_benefits import compute_breakdown

CRAWLERS = {'ssf': SsfCrawler()}

TARGETS = [
    {
        'label': 'LEMOUTON 클래식2',
        'sp_id': 3,
        'sku': '르무통 클래식-그레이-235',  # OptionSourceUrl 매핑된 SKU 사용
        'expected_sale_price': 109900,
        'expected_dyn': {
            'point_amount': 549,  # 사이트 표시 멤버십포인트
            'first_purchase_coupon': None,  # 노출 없음
            'gift_point': None,
        },
    },
    {
        'label': 'BEANPOLE 티셔츠',
        'sp_id': 9,
        'sku': '르무통 클래식-그레이-230',
        'expected_sale_price': 56050,
        'expected_dyn': {
            'point_amount': 2802,
            'first_purchase_coupon': 0.20,
            'gift_point': 5600,
        },
    },
]

s = SessionLocal()
try:
    for tgt in TARGETS:
        print("=" * 78)
        print(f"[{tgt['label']}] sp.id={tgt['sp_id']} sku={tgt['sku']}")
        print("=" * 78)
        # Step 1 — refetch via service (저장 로직 통과)
        result = fetch_one_source(s, source_product_id=tgt['sp_id'], crawlers=CRAWLERS)
        s.commit()
        print(f"refetch status: {result['status']}")
        if result.get('error'):
            print(f"  error: {result['error']}")

        # Step 2 — DB 상태 확인
        sp = s.get(SourceProduct, tgt['sp_id'])
        print(f"sp.last_price       = {sp.last_price}  (expected {tgt['expected_sale_price']})")
        print(f"sp.dynamic_benefits = {sp.dynamic_benefits_json}")

        # OptionSourceUrl.price_cached 도 갱신됐는지
        osu = s.query(OptionSourceUrl).filter_by(canonical_sku=tgt['sku'], source_id=4).first()
        if osu:
            print(f"OptionSourceUrl.price_cached = {osu.price_cached}")
        else:
            print(f"OptionSourceUrl 매핑 없음 (sku={tgt['sku']}, source_id=4)")

        # Step 3 — compute_breakdown
        print()
        print(f"[compute_breakdown] sale_price={tgt['expected_sale_price']} sku={tgt['sku']} source_id=4")
        bd = compute_breakdown(
            s, sku=tgt['sku'], source_id=4,
            sale_price=tgt['expected_sale_price'],
        )
        print(f"  final_price = {bd['final_price']}")
        print(f"  steps:")
        for st in bd['steps']:
            print(f"    [{st['type']:6s}] {st['name']:40s}  -{st['deduct']:>7,}원  → base_after={st['base_after']:,}")
        print(f"  items_used (참고 — disabled 포함):")
        for it in bd['items_used']:
            mark = '✓' if it['enabled'] else '✗'
            extra = ' (카드토글 OFF)' if it.get('disabled_by_card_off') else ''
            print(f"    {mark} [{it['type']:6s}] {it['name']:40s}  value={it['value']}{extra}")
        print()
finally:
    s.close()

print("=" * 78)
print("검증 완료")
print("=" * 78)
