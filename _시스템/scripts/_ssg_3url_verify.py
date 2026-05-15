"""SSG 3개 URL 100% 정확도 검증 (사용자 스크린샷과 1:1 비교)."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from lemouton.sourcing.crawlers.ssg import SsgCrawler
from shared.db import SessionLocal

URLS = [
    ('https://www.ssg.com/item/itemView.ssg?itemId=1000809938058&siteNo=6009&salestrNo=1004',
     '나이키 리엑스 8 IR5118-200 (스크린샷 1)',
     '예상: sale_price=70,805 / SSG MONEY 1.5% 충전결제 (비활성) / 카드혜택가 ❌ / 상품쿠폰 ❌'),
    ('https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009',
     '밀레 카고팬츠 MVTUP423 (스크린샷 3 / sp_id=14)',
     '예상: sale_price=39,690 / SSG MONEY 10% 적립 또는 즉시할인 (already_applied=True / 비활성)'),
    ('https://www.ssg.com/item/itemView.ssg?itemId=1000644956258&siteNo=6009&salestrNo=1004',
     '나이키 카고팬츠 HM6977-297 (스크린샷 2)',
     '예상: sale_price=60,605 / SSG MONEY 1.5% 충전결제 (비활성) / 카드혜택가 ❌ / 상품쿠폰 ❌'),
]

def fmt_won(v): return f"{int(v):,}원" if v else "—"

crawler = SsgCrawler()
session = SessionLocal()

for url, label, expected in URLS:
    print('=' * 88)
    print(f'  {label}')
    print(f'  URL: {url}')
    print(f'  {expected}')
    print('=' * 88)
    try:
        result = crawler.fetch(url)
        print(f'  product_name: {result.product_name_raw}')
        print(f'  옵션 수: {len(result.options)}')
        # 첫 옵션 dump
        if result.options:
            opt = result.options[0]
            print(f'  ── 첫 옵션 dyn 추출값 ──')
            for k in ('sale_price','price','color_text','size_text','stock',
                      'card_benefit_price','card_benefit_condition',
                      'ssg_money_rate','ssg_money_amount','ssg_money_already_applied','ssg_money_text',
                      'product_coupon_rate','product_coupon_amount','product_coupon_min_order','product_coupon_label'):
                v = opt.get(k)
                if v not in (None, 0, '', False):
                    print(f'    {k:35} = {v}')
            sale_price = opt.get('sale_price') or opt.get('price') or 0
            # compute_breakdown 시뮬레이션 — sku 매핑 우회: dyn dict 직접 적용
            # (실제 매트릭스는 OptionSourceUrl 통해 sku 매칭 필요. 여기선 동일 로직 시뮬)
            # → 임시로 effective list 직접 빌드 (compute_breakdown 의 dyn 분기 동일 로직)
            # SSG src_id=7. 임의 sku 사용 (DB lookup 실패 시 dyn 미반영) — 그래서
            # 여기선 직접 _DynBenefit 시뮬레이션 (ssg dyn 만 적용, 시드 fallback 무시)
            print(f'  ── 매트릭스 시뮬레이션 (SSG dyn 만 적용) ──')
            base = float(sale_price)
            print(f'    판매가 (베이스)              : {fmt_won(base)}')
            # 카드혜택가 (정액)
            cbp = opt.get('card_benefit_price') or 0
            cbp_active = False
            if cbp > 0:
                cbp_amt = base - cbp
                # 5만원 이상 자동 활성 (조건 텍스트 추출)
                cond = opt.get('card_benefit_condition') or ''
                import re as _re
                _min = 50000
                m = _re.search(r'(\d+)\s*만\s*원\s*이상', cond)
                if m:
                    _min = int(m.group(1)) * 10000
                cbp_active = (base >= _min)
                if cbp_active:
                    print(f'    카드혜택가 (조건 충족 / {_min:,}원 이상) -{int(cbp_amt):,}원')
                    base -= cbp_amt
                else:
                    print(f'    카드혜택가 (조건 미충족 / 표시만, {_min:,}원 이상 필요) [{int(cbp_amt):,}원]')
            else:
                print(f'    카드혜택가                    : 없음')
            # SSG MONEY (rate)
            smr = opt.get('ssg_money_rate') or 0
            sma = opt.get('ssg_money_already_applied')
            smt = opt.get('ssg_money_text') or ''
            if smr and not sma:
                rate = float(smr) / 100 if float(smr) > 1 else float(smr)
                is_charge = '충전' in smt
                enabled = (not is_charge) or (rate >= 0.03)
                tag = '충전결제' if is_charge else '기본'
                if enabled:
                    deduct = int(base * rate)
                    print(f'    SSG MONEY ({tag}, {rate*100:g}%) -{deduct:,}원  → {int(base-deduct):,}원')
                    base -= deduct
                else:
                    print(f'    SSG MONEY ({tag}, {rate*100:g}%) [비활성: 3% 미만 / 현대카드 결제가 유리]')
            elif sma:
                print(f'    SSG MONEY ({smt}) [already_applied=True / sale_price 반영됨 / 비활성]')
            else:
                print(f'    SSG MONEY                    : 없음')
            # 상품쿠폰
            pcr = opt.get('product_coupon_rate') or 0
            pca = opt.get('product_coupon_amount') or 0
            pcmin = opt.get('product_coupon_min_order') or 0
            pclabel = opt.get('product_coupon_label') or ''
            if pcr or pca:
                pc_active = (base >= pcmin) if pcmin else True
                if pcr:
                    rate = float(pcr) / 100 if float(pcr) > 1 else float(pcr)
                    if pc_active:
                        deduct = int(base * rate)
                        print(f'    상품쿠폰 {rate*100:g}% ({pcmin:,}원 이상) — {pclabel}: -{deduct:,}원 → {int(base-deduct):,}원')
                        base -= deduct
                    else:
                        print(f'    상품쿠폰 {rate*100:g}% [조건 미충족: {pcmin:,}원 이상 필요]')
                elif pca:
                    if pc_active:
                        print(f'    상품쿠폰 {int(pca):,}원: -{int(pca):,}원 → {int(base-pca):,}원')
                        base -= pca
            else:
                print(f'    상품쿠폰                     : 없음')
            # 현대카드 fallback (카드혜택가 미활성 시)
            if not cbp_active:
                deduct = int(base * 0.0273)
                print(f'    현대카드 fallback 2.73% : -{deduct:,}원  → {int(base-deduct):,}원')
                base -= deduct
            else:
                print(f'    현대카드 fallback (카드혜택가 활성으로 자동 비활성)')
            print(f'    💰 매입가                    : {fmt_won(base)}')
    except Exception as e:
        import traceback
        print(f'  ❌ ERROR: {e}')
        traceback.print_exc()
    print()

session.close()
