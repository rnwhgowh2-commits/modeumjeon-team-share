"""밀레 (1000807328520) — 8% 상품쿠폰 수동 입력 후 매트릭스 단계별 시뮬레이션.

cffi 로 sale_price + SSG MONEY 자동 추출. 상품쿠폰만 사용자 스크린샷 데이터 수동 박기:
  - product_coupon_rate: 0.08 (8%)
  - product_coupon_max_discount: 20000 (최대 2만원)
  - product_coupon_label: '[제휴할인] 백화점 8% 쿠폰 다운로드 1일이내 사용'
"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

URL = 'https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009'

# 이전 cffi 페치 결과 + 사용자 스크린샷 데이터 (현재 SSG rate limit 차단으로 재페치 불가)
opt = {
    'sale_price': 39690,
    'price': 39690,
    'color_text': '블랙(16)',
    'size_text': '76(29)',
    'stock': 18,
    # SSG MONEY (cffi 페치 자동 추출)
    'ssg_money_rate': 10.0,
    'ssg_money_amount': 4410,
    'ssg_money_already_applied': True,
    'ssg_money_text': '10% 적립 또는 10% 즉시할인',
    # 8% 상품쿠폰 (사용자 스크린샷 — 현재 cffi 비로그인 SSR 에 미노출)
    'product_coupon_rate': 0.08,
    'product_coupon_max_discount': 20000,
    'product_coupon_min_order': 0,
    'product_coupon_label': '[제휴할인] 백화점 8% 쿠폰 다운로드 1일이내 사용',
}

print(f'상품: (단독이월한정) 남성용 냉감등산카고팬츠 여름 카고 팬츠 MVTUP423 (출시가114000원)')
print(f'URL : {URL}')
print()
print('━' * 90)
print('  ⑦ SSG 밀레 카고팬츠 MVTUP423 (1000807328520) — 8% 상품쿠폰 수동 입력')
print('━' * 90)

sale_price = opt['sale_price']
print(f'  판매가 (정상 49,000 → 19%↓ / 최고 59,000) : {sale_price:,}원')
print(f'  ────────────────────────────────────────')

# 매트릭스 단계 시뮬레이션 (compute_breakdown 룰 그대로)
base = float(sale_price)
n = 0

# (1) 카드혜택가 (정액) — 없음
cbp = opt.get('card_benefit_price') or 0
if cbp:
    n += 1
    cbp_amt = base - cbp
    cond = opt.get('card_benefit_condition') or ''
    m = re.search(r'(\d+)\s*만\s*원\s*이상', cond)
    min_o = int(m.group(1)) * 10000 if m else 50000
    active = (base >= min_o)
    if active:
        print(f'  {n}. ✅ [정액] 카드혜택가 ({min_o:,}원 이상 충족): -{int(cbp_amt):,}원 → {int(base-cbp_amt):,}원')
        base -= cbp_amt
    else:
        print(f'  {n}. ❌ [정액] 카드혜택가 ({min_o:,}원 이상 필요 / 표시만): [-{int(cbp_amt):,}원]')

# (2) SSG MONEY (rate)
smr = opt.get('ssg_money_rate') or 0
sma = opt.get('ssg_money_already_applied')
smt = opt.get('ssg_money_text') or ''
if smr or sma:
    n += 1
    rate = float(smr) / 100 if float(smr) > 1 else float(smr)
    if sma:
        print(f'  {n}. ❌ [%적립] SSG MONEY ({smt}): already_applied=True / sale_price 반영됨 / 비활성')
    else:
        is_charge = '충전' in smt
        enabled = (not is_charge) or (rate >= 0.03)
        if enabled:
            deduct = int(base * rate)
            print(f'  {n}. ✅ [%적립] SSG MONEY ({"충전결제 " if is_charge else ""}{rate*100:g}%): {int(base):,} × {rate*100:g}% = {deduct:,}원 → {int(base-deduct):,}원')
            base -= deduct
        else:
            print(f'  {n}. ❌ [%적립] SSG MONEY (충전결제 {rate*100:g}%): 3% 미만 / 비활성 (현대카드 결제가 유리)')

# (3) 상품쿠폰 (rate, 자동 활성 — 사용자 명세 (1))
pcr = opt.get('product_coupon_rate') or 0
pca = opt.get('product_coupon_amount') or 0
pcmin = opt.get('product_coupon_min_order') or 0
pcmax = opt.get('product_coupon_max_discount') or 0
pclabel = opt.get('product_coupon_label') or ''
if pcr or pca:
    n += 1
    if pcr:
        rate = float(pcr) / 100 if float(pcr) > 1 else float(pcr)
        active = (base >= pcmin) if pcmin else True
        if active:
            deduct = int(base * rate)
            # 최대 할인 한도 적용
            if pcmax and deduct > pcmax:
                deduct_capped = pcmax
                print(f'  {n}. ✅ [%할인] 상품쿠폰 {rate*100:g}% — {pclabel}')
                print(f'         {int(base):,} × {rate*100:g}% = {deduct:,}원 → 최대 한도 {pcmax:,}원 적용 → -{deduct_capped:,}원 → {int(base-deduct_capped):,}원')
                base -= deduct_capped
            else:
                print(f'  {n}. ✅ [%할인] 상품쿠폰 {rate*100:g}% — {pclabel}')
                print(f'         {int(base):,} × {rate*100:g}% = -{deduct:,}원 → {int(base-deduct):,}원')
                base -= deduct
        else:
            print(f'  {n}. ❌ [%할인] 상품쿠폰 {rate*100:g}% ({pcmin:,}원 이상 필요 / 비활성)')
    elif pca:
        print(f'  {n}. ✅ [정액] 상품쿠폰 {int(pca):,}원 — {pclabel}: -{int(pca):,}원 → {int(base-pca):,}원')
        base -= pca

# (4) 현대카드 fallback (카드혜택가 비활성 시)
n += 1
fallback_active = not bool(cbp and base != sale_price)  # 카드혜택가 활성 안 됐으면 fallback ON
if fallback_active:
    deduct = int(base * 0.0273)
    print(f'  {n}. ✅ [%할인] 현대카드 캐시백 fallback 2.73%: {int(base):,} × 2.73% = -{deduct:,}원 → {int(base-deduct):,}원')
    base -= deduct
else:
    print(f'  {n}. ❌ [%할인] 현대카드 fallback (카드혜택가 활성으로 자동 비활성)')

print(f'  ────────────────────────────────────────')
print(f'  💰 매입가 : {int(base):,}원')
