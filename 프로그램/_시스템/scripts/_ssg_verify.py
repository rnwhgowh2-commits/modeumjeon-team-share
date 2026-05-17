"""SSG 닥스 벨트 (source_product 10) 재크롤링 → DB 갱신 → compute_breakdown 검증.

단계:
  1. SsgCrawler 로 재크롤링 → save_crawl_result 로 DB 갱신
  2. SourceProduct.dynamic_benefits_json 출력
  3. compute_breakdown(sku, source_id=7, sale_price=last_price) 호출 → steps 출력
  4. 사이트 vs 우리 1:1 비교표
  5. 매입가 (사이트 노출 항목 모두 활성 시)
"""
from __future__ import annotations

import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from shared.db import SessionLocal  # noqa: E402
from lemouton.sources.models import SourceProduct, SourceOption  # noqa: E402
from lemouton.sources.service import save_crawl_result  # noqa: E402
from lemouton.sourcing.crawlers.ssg import SsgCrawler  # noqa: E402
from webapp.routes.api_benefits import compute_breakdown  # noqa: E402


SOURCE_PRODUCT_ID = 10
SSG_SOURCE_ID = 7  # source_benefit_templates.source_id


def main():
    s = SessionLocal()
    try:
        sp = s.get(SourceProduct, SOURCE_PRODUCT_ID)
        print(f'=== SourceProduct id={SOURCE_PRODUCT_ID} ===')
        print(f'  url: {sp.url}')

        # Step 1: 재크롤링
        print('\n=== Step 1: 재크롤링 ===')
        cr = SsgCrawler().fetch(sp.url)
        print(f'  product_name: {cr.product_name_raw}')
        print(f'  brand: {cr.brand}')
        print(f'  discount_info: {cr.discount_info}')
        print(f'  옵션 dict (첫 옵션):')
        for k, v in cr.options[0].items():
            print(f'    {k}: {v!r}')

        # Step 2: DB 갱신
        print('\n=== Step 2: DB 갱신 (save_crawl_result) ===')
        save_crawl_result(s, source_product=sp, crawl_result=cr)
        s.commit()

        # 갱신된 dynamic_benefits_json 확인
        s.expire_all()
        sp = s.get(SourceProduct, SOURCE_PRODUCT_ID)
        print(f'  last_price: {sp.last_price}')
        print(f'  dynamic_benefits_json:')
        dyn = json.loads(sp.dynamic_benefits_json) if sp.dynamic_benefits_json else {}
        for k, v in dyn.items():
            print(f'    {k}: {v!r}')

        # 옵션 lookup 위해 OptionSourceUrl 확인 (sku 매핑)
        from lemouton.sourcing.models_pricing import OptionSourceUrl
        osu_rows = (s.query(OptionSourceUrl)
                    .filter_by(source_id=SSG_SOURCE_ID)
                    .all())
        print(f'\n=== OptionSourceUrl (source_id={SSG_SOURCE_ID}) — sku list ===')
        target_sku = None
        for osu in osu_rows:
            same_url = osu.product_url and (osu.product_url.split('?')[0] == sp.url.split('?')[0])
            mark = ' ★' if same_url else ''
            print(f'  sku={osu.canonical_sku} url={osu.product_url}{mark}')
            if same_url and target_sku is None:
                target_sku = osu.canonical_sku
        if target_sku is None:
            # fallback — 사용자 명세
            target_sku = '르무통 클래식-그레이-230'
            print(f'  (URL 매칭 실패 — fallback sku 사용: {target_sku})')

        # Step 3: compute_breakdown
        print(f'\n=== Step 3: compute_breakdown(sku={target_sku!r}, source_id={SSG_SOURCE_ID}, sale_price={sp.last_price}) ===')
        result = compute_breakdown(s, sku=target_sku, source_id=SSG_SOURCE_ID,
                                    sale_price=float(sp.last_price))
        print(f'  sale_price: {result["sale_price"]:,.0f}')
        print(f'  final_price: {result["final_price"]:,}')
        print(f'\n  items_used (effective list):')
        for it in result['items_used']:
            on = '[ON]' if it['enabled'] else '[OFF]'
            print(f'    {on} kind={it["kind"]} name={it["name"]!r} type={it["type"]} value={it["value"]}')
        print(f'\n  steps (누적 차감):')
        base_prev = result['sale_price']
        for st in result['steps']:
            print(f'    - {st["name"]!r} ({st["type"]} {st["value"]}) → -{st["deduct"]:,}원 → {st["base_after"]:,}원')

        # Step 4: 사이트 vs 우리 1:1 비교
        print('\n=== Step 4: 사이트 vs 우리 1:1 비교표 ===')
        site_items = [
            ('카드혜택가 (5만원 이상 → 98,767원)', 'amount', 107355 - 98767, 'ON (조건 충족)'),
            ('상품쿠폰 12% (3만원 이상)', 'rate', 0.12, 'ON (조건 충족)'),
            ('SSG MONEY 1.5% (충전결제)', 'rate', 0.015, 'ON (별도 적립)'),
            ('현대카드 fallback 2.73%', 'rate', 0.0273, 'OFF (카드혜택가 활성)'),
        ]
        print('\n  [사이트 노출 / 정확 기대값]')
        for nm, tp, val, status in site_items:
            print(f'    {status}  {nm}  ({tp}, value={val})')
        print('\n  [우리 effective list]')
        for it in result['items_used']:
            on = 'ON ' if it['enabled'] else 'OFF'
            print(f'    {on}  {it["name"]}  ({it["type"]}, value={it["value"]})')

    finally:
        s.close()


if __name__ == '__main__':
    main()
