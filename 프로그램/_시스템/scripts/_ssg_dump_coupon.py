"""3개 SSG URL raw HTML 에서 '상품쿠폰' 주변 dump → 어느 URL 에 8% 쿠폰 있는지 확인."""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from lemouton.sourcing.crawlers.ssg import SsgCrawler
from bs4 import BeautifulSoup

URLS = [
    ('1000809938058', 'https://www.ssg.com/item/itemView.ssg?itemId=1000809938058&siteNo=6009&salestrNo=1004'),
    ('1000807328520', 'https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009'),
    ('1000644956258', 'https://www.ssg.com/item/itemView.ssg?itemId=1000644956258&siteNo=6009&salestrNo=1004'),
]

c = SsgCrawler()
for label, url in URLS:
    print('=' * 88)
    print(f'  {label}')
    print('=' * 88)
    try:
        html = c._fetch_html(url)
        # "상품쿠폰" 키워드 모든 위치 dump (주변 200자)
        positions = [m.start() for m in re.finditer(r'상품\s*쿠폰', html)]
        print(f'  "상품쿠폰" 출현 횟수: {len(positions)}')
        for i, pos in enumerate(positions[:3]):
            ctx = html[max(0,pos-150):pos+250]
            ctx = re.sub(r'\s+', ' ', ctx)
            print(f'  [{i+1}] ...{ctx}...')
        # "8%" / "%상품쿠폰" 패턴 검색
        m8 = re.search(r'(\d+)\s*%[^<]{0,5}상품\s*쿠폰', html)
        if m8:
            print(f'  ⭐ X%상품쿠폰 매칭: {m8.group()}')
        # cdtl_cpn_wrap 클래스 dl 추출
        soup = BeautifulSoup(html, 'lxml')
        wraps = soup.select('dl.cdtl_cpn_wrap')
        print(f'  dl.cdtl_cpn_wrap 개수: {len(wraps)}')
        for i, w in enumerate(wraps):
            text = re.sub(r'\s+', ' ', w.get_text(' ', strip=True))[:300]
            print(f'    [{i+1}] {text}')
        # 다른 셀렉터: cdtl_benefit_coupon
        bcps = soup.select('a.cdtl_benefit_coupon, .cdtl_benefit_coupon')
        print(f'  .cdtl_benefit_coupon 개수: {len(bcps)}')
        for i, b in enumerate(bcps[:3]):
            text = re.sub(r'\s+', ' ', b.get_text(' ', strip=True))[:300]
            print(f'    [{i+1}] {text}')
    except Exception as e:
        import traceback
        print(f'  ❌ ERROR: {e}')
        traceback.print_exc()
    print()
