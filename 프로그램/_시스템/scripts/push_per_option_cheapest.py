"""[run] 르무통 클래식 — 옵션별 cheapest 가격 적용 PUT 시연.

스마트스토어 옵션별 가격 = base salePrice + addPrice(delta).
옵션마다 가격이 다른 경우:
  base = min(옵션별 산출가)
  addPrice = 옵션별 산출가 - base  (>= 0)

산출 절차:
1. 각 옵션의 4 소싱처 cached price 중 가드레일 통과한 cheapest 1개 선택
2. cheapest 매입가 → ss_sale = round(매입가 / (1 - fee_rate - margin_rate))  (백원 단위)
3. base = min(ss_sale)
4. PUT: salePrice=base, optionCombinations[*].price = ss_sale - base, stockQuantity=정책 v2

검증: round-trip GET → 36/36 옵션 가격·재고 일치.
"""
from __future__ import annotations
import sys, json
from collections import defaultdict
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)
from shared.db import SessionLocal
import lemouton.sourcing.models  # noqa
import lemouton.templates.models  # noqa
import lemouton.uploader.models   # noqa
import lemouton.pricing.settings  # noqa
import lemouton.sourcing.models_pricing  # noqa
from lemouton.sourcing.models import Model, Option
from lemouton.sourcing.models_pricing import OptionSourceUrl
from lemouton.sources.models import SourceProduct
from lemouton.templates.models import PriceTemplate
from lemouton.uploader.adapters.smartstore import SmartStoreAdapter
from shared.platforms.smartstore.get_options import fetch_product_options

MODEL_CODE = "르무통 클래식"
ORIGIN_PRODUCT_NO = 13153051689
CAP = 10
ROUND_UNIT = 100  # 백원 단위 반올림
MARKUP_RATIO = 1.25  # 정가 = 목표 실판매가 × 1.25 (25% 인상 후킹용)


def round_to(n: int, unit: int) -> int:
    return int(round(n / unit) * unit)


def main():
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=MODEL_CODE).first()
        pt = s.query(PriceTemplate).filter_by(id=m.price_template_id).first()
        gl, gu = int(pt.guardrail_lower), int(pt.guardrail_upper)
        fee = float(pt.ss_fee_rate)
        margin = float(pt.ss_margin_rate)

        opts_db = (s.query(Option).filter_by(model_code=MODEL_CODE)
                   .order_by(Option.color_code, Option.size_code).all())

        # 옵션별 cheapest 산출
        per_opt = []
        for o in opts_db:
            urls = (s.query(OptionSourceUrl)
                    .filter_by(canonical_sku=o.canonical_sku).all())
            cands = []
            for u in urls:
                p = u.price_cached
                if p is None and u.product_url:
                    sp = (s.query(SourceProduct)
                          .filter_by(url=u.product_url).first())
                    if sp:
                        p = sp.last_price
                if p is None: continue
                if not (gl <= int(p) <= gu): continue
                cands.append({'src_id': u.source_id, 'price': int(p)})
            cheapest = min(cands, key=lambda x: x['price']) if cands else None
            if cheapest:
                ss_sale_raw = cheapest['price'] / (1 - fee - margin)
                ss_sale = round_to(int(ss_sale_raw), ROUND_UNIT)
            else:
                ss_sale = None
            per_opt.append({
                'sku': o.canonical_sku, 'oid': int(o.naver_option_id or 0),
                'color': o.color_code, 'size': o.size_code,
                'cheapest_price': cheapest['price'] if cheapest else None,
                'ss_sale': ss_sale,
            })

        # 옵션별 목표 실판매가 = ss_sale (마진 보장 산출가)
        valid = [p for p in per_opt if p['ss_sale'] is not None]
        target_min = min(p['ss_sale'] for p in valid) if valid else 128900
        target_max = max(p['ss_sale'] for p in valid) if valid else 128900

        # 후킹용 정가 = 옵션별 목표가 × 1.25 (정가 인상)
        # base salePrice = min(정가), 옵션별 addPrice = 옵션 정가 - base
        # 즉시할인 = 정가 - 목표가 (옵션 평균치 기준 절대값 1개)
        for p in valid:
            p['list_price'] = round_to(int(p['ss_sale'] * MARKUP_RATIO), ROUND_UNIT)
        base = min(p['list_price'] for p in valid) if valid else int(target_min * MARKUP_RATIO)
        # 단일 즉시할인 = base - target_min  (모든 옵션 같은 cheapest 이면 깔끔)
        # 옵션별 cheapest 가 다양하면: 실가는 옵션별로 다름 = (base + addPrice) - 즉시할인
        discount_amount = base - target_min

        print(f"\n[B] 옵션별 cheapest + 25% 인상 정가 산출 (model={MODEL_CODE})")
        print(f"  가드레일: {gl:,}~{gu:,} / 수수료 {fee*100:.2f}% + 마진 {margin*100:.2f}%")
        print(f"  목표 실판매가 (ss_sale): {target_min:,}~{target_max:,}원")
        print(f"  정가 = 목표가 × {MARKUP_RATIO} = {int(target_min*MARKUP_RATIO):,}~{int(target_max*MARKUP_RATIO):,}원")
        print(f"  → base salePrice: {base:,}원 / 즉시할인: -{discount_amount:,}원 (WON)")
        print(f"  → 노출 실가 ({base:,} - {discount_amount:,}): {base-discount_amount:,}원")
        if base > 0:
            print(f"  → 할인율: {discount_amount/base*100:.1f}%")
        # 색상별 분포
        by_color = defaultdict(list)
        for p in per_opt:
            by_color[p['color']].append(p)
        print(f"  {'색상':<10} | cheapest 분포 (매입원가) → ss_sale 분포")
        print("  " + "-" * 70)
        for c, lst in by_color.items():
            cps = [p['cheapest_price'] for p in lst if p['cheapest_price']]
            sss = [p['ss_sale'] for p in lst if p['ss_sale']]
            if cps:
                print(f"  {c:<10} | 매입 {min(cps):,}~{max(cps):,} → ss_sale {min(sss):,}~{max(sss):,} (옵션 {len(lst)})")

        # stock 정책 (기존 풀 파이프라인 결과 그대로 — 라이브 GET 으로 확보)
        live = fetch_product_options(ORIGIN_PRODUCT_NO)
        live_stock = {o.option_id: o.stock for o in live.options}

        # PUT 페이로드 — addPrice = 옵션 정가 - base
        # stock 은 raw 그대로 (1개도 1개로 노출 — lost sale 방지)
        option_updates = {}
        addprice_dist = defaultdict(int)
        for p in per_opt:
            oid = p['oid']
            if not oid: continue
            list_p = p.get('list_price') or base
            add = list_p - base
            stock = live_stock.get(oid, 0)
            option_updates[oid] = {'stockQuantity': stock, 'price': add}
            addprice_dist[add] += 1

        print()
        print(f"[D] 옵션별 addPrice 분포 (옵션 가격 다양성 확인):")
        for delta in sorted(addprice_dist.keys()):
            print(f"  +{delta:>5,}원 delta : {addprice_dist[delta]}개 옵션")

        # PUT (즉시할인 포함)
        adapter = SmartStoreAdapter()
        result = adapter.batch_update(
            market_product_id=ORIGIN_PRODUCT_NO,
            sale_price=base,
            option_updates=option_updates,
            immediate_discount={'value': discount_amount, 'unitType': 'WON'} if discount_amount > 0 else {'value': 0},
        )
        print()
        print(f"[E] PUT 결과: success={result.success} http={result.http_status}")
        if not result.success:
            print(f"  error: {result.error}")
            return

        # round-trip — salePrice + addPrice + 즉시할인 + 실가 모두 검증
        from shared.platforms.smartstore.client import SmartStoreClient
        c2 = SmartStoreClient()
        d = c2.request('GET', f'/external/v2/products/origin-products/{ORIGIN_PRODUCT_NO}')
        op = d.get('originProduct') or {}
        live_sale = int(op.get('salePrice') or 0)
        cb = op.get('customerBenefit') or {}
        idp = cb.get('immediateDiscountPolicy') or {}
        dm = idp.get('discountMethod') or {}
        live_disc_value = int(dm.get('value') or 0)
        live_disc_unit = dm.get('unitType') or 'WON'

        live2 = fetch_product_options(ORIGIN_PRODUCT_NO)
        ok_price = ok_stock = 0
        for o in live2.options:
            wanted = option_updates.get(o.option_id)
            if not wanted: continue
            if o.add_price == wanted['price']: ok_price += 1
            if o.stock == wanted['stockQuantity']: ok_stock += 1
        print(f"\n[F] round-trip 검증 (라이브 GET):")
        print(f"  salePrice (정가):    {live_sale:,}원 (요청 {base:,}) {'✅' if live_sale==base else '❌'}")
        print(f"  immediateDiscount:   {live_disc_value:,}{live_disc_unit} (요청 {discount_amount:,}WON) {'✅' if live_disc_value==discount_amount else '❌'}")
        print(f"  옵션별 addPrice:     {ok_price}/{len(option_updates)} 일치")
        print(f"  옵션별 stock:        {ok_stock}/{len(option_updates)} 일치")
        # 노출 실가 sample
        print(f"\n  📌 고객 노출 가격 sample (옵션 5건):")
        for o in live2.options[:5]:
            list_price = live_sale + o.add_price
            real_price = list_price - live_disc_value
            disc_pct = live_disc_value / list_price * 100 if list_price else 0
            print(f"    {o.name1}/{o.name2}: ~~{list_price:,}원~~ → "
                  f"\033[31m{real_price:,}원\033[0m  "
                  f"({disc_pct:.0f}% 할인 -{live_disc_value:,}원)")

    finally:
        s.close()


if __name__ == "__main__":
    main()
