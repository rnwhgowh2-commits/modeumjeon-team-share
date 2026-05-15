"""롯데홈쇼핑 (lotteimall) 사이트 1:1 검증 스크립트.

URL: https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559417201
DB: source_products.id=7, sku='르무통 클래식-그레이-235'

수행:
  1. 크롤러 직접 호출 → CrawlResult 출력
  2. save_crawl_result 통해 DB 갱신
  3. compute_breakdown 호출 → steps 출력
  4. 사이트 노출값과 1:1 비교

실행: PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/_lotte_recheck.py
"""
from __future__ import annotations

import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 전체 모델 import (FK 메타 해석)
import shared.db  # noqa: F401
import lemouton.sources.models  # noqa: F401
import lemouton.sourcing.models  # noqa: F401
import lemouton.sourcing.models_pricing  # noqa: F401
import lemouton.templates.models  # noqa: F401

URL = 'https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559417201'
SP_ID = 7
SKU = '르무통 클래식-그레이-235'
SOURCE_ID = 6  # 롯데홈쇼핑 (정정 후)

# ─── 1. 크롤러 직접 호출 ───────────────────────────────────
print('=' * 70)
print('[1] 크롤러 직접 호출')
print('=' * 70)

from lemouton.sourcing.crawlers.lotteon import LotteCrawler

crawler = LotteCrawler(timeout=30)
cr = crawler.fetch(URL)
print(f'product_name_raw: {cr.product_name_raw}')
print(f'discount_info: {cr.discount_info}')
print(f'options count: {len(cr.options)}')
print()
print('first 2 options:')
for o in cr.options[:2]:
    print('  -', json.dumps({
        'option_id': o.get('option_id'),
        'color_text': o.get('color_text'),
        'size_text': o.get('size_text'),
        'price': o.get('price'),
        'sale_price': o.get('sale_price'),
        'auto_card_discount': o.get('auto_card_discount'),
        'point_rewards': o.get('point_rewards'),
        'stock': o.get('stock'),
    }, ensure_ascii=False, indent=2))

# ─── 2. save_crawl_result 통해 DB 갱신 ─────────────────────
print()
print('=' * 70)
print('[2] save_crawl_result 통해 DB 갱신')
print('=' * 70)

from shared.db import SessionLocal
from lemouton.sources.models import SourceProduct
from lemouton.sources.service import save_crawl_result

s = SessionLocal()
try:
    sp = s.get(SourceProduct, SP_ID)
    if sp is None:
        print(f'ERROR: SourceProduct id={SP_ID} 없음')
        sys.exit(1)
    print(f'기존 sp.last_price: {sp.last_price}')
    print(f'기존 sp.dynamic_benefits_json: {sp.dynamic_benefits_json}')
    counts = save_crawl_result(s, source_product=sp, crawl_result=cr)
    s.commit()
    print(f'저장 결과: {counts}')
    s.refresh(sp)
    print(f'갱신 sp.last_price: {sp.last_price}')
    print(f'갱신 sp.dynamic_benefits_json: {sp.dynamic_benefits_json}')
    print(f'갱신 sp.auto_card_discount_json: {sp.auto_card_discount_json}')
finally:
    s.close()

# ─── 3. compute_breakdown 호출 ─────────────────────────────
print()
print('=' * 70)
print('[3] compute_breakdown 호출 — steps 출력')
print('=' * 70)

from webapp.routes.api_benefits import compute_breakdown

s = SessionLocal()
try:
    out = compute_breakdown(s, sku=SKU, source_id=SOURCE_ID, sale_price=120320)
    print(f'sale_price: {out["sale_price"]}')
    print(f'final_price (매입가): {out["final_price"]}')
    print()
    print('items_used:')
    for it in out['items_used']:
        print(f'  - kind={it["kind"]} name={it["name"]} type={it["type"]} value={it["value"]} enabled={it["enabled"]}')
    print()
    print('steps (실제 차감 과정):')
    for st in out['steps']:
        print(f'  {st["name"]}  ({st["type"]} {st["value"]}) → -{st["deduct"]:,}원 → 잔여 {st["base_after"]:,}원')
finally:
    s.close()

# ─── 4. 사이트 1:1 비교표 ──────────────────────────────────
print()
print('=' * 70)
print('[4] 사이트 vs 우리 DB 1:1 비교')
print('=' * 70)

site_data = {
    '정상가': 149000,
    '15% 할인 후 (일반 판매가)': 126650,
    '롯데홈쇼핑 최대할인가 (sale_price)': 120320,
    '쿠폰할인': 22350,
    '현대카드 5% 청구할인': 6330,
    '구매적립 L.POINT (일반)': 126,
    '구매적립 L.POINT (L.CLUB)': 633,
    '리뷰작성 적립금 (일반)': 300,
    '리뷰작성 적립금 (L.CLUB)': 600,
}

s = SessionLocal()
try:
    sp = s.get(SourceProduct, SP_ID)
    db_dyn = json.loads(sp.dynamic_benefits_json) if sp.dynamic_benefits_json else {}
    db_acd = json.loads(sp.auto_card_discount_json) if sp.auto_card_discount_json else {}
    pr = db_dyn.get('point_rewards') or {}
    print()
    print(f'{"항목":<40} | {"사이트":>10} | {"DB":>10} | 일치')
    print('-' * 80)
    rows = [
        ('sale_price (last_price)', site_data['롯데홈쇼핑 최대할인가 (sale_price)'], sp.last_price),
        ('현대카드 5% 청구할인 금액', site_data['현대카드 5% 청구할인'], db_acd.get('amount', 0)),
        ('구매적립 L.POINT 일반', site_data['구매적립 L.POINT (일반)'], pr.get('default_point', 0)),
        ('구매적립 L.POINT L.CLUB', site_data['구매적립 L.POINT (L.CLUB)'], pr.get('club_point', 0)),
        ('리뷰적립 일반 (원)', site_data['리뷰작성 적립금 (일반)'], pr.get('review_default', 0)),
        ('리뷰적립 L.CLUB (원)', site_data['리뷰작성 적립금 (L.CLUB)'], pr.get('review_club', 0)),
    ]
    for name, site_v, db_v in rows:
        match = '✓' if site_v == db_v else '✗'
        print(f'{name:<40} | {site_v:>10,} | {db_v:>10,} | {match}')
finally:
    s.close()

print()
print('완료.')
