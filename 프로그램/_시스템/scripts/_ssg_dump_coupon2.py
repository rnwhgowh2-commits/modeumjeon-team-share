"""3개 SSG URL raw HTML 에서 '쿠폰'/'제휴할인'/'8%' 등 키워드 dump."""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from lemouton.sourcing.crawlers.ssg import SsgCrawler

URLS = [
    ('1000809938058 (나이키 리엑스)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000809938058&siteNo=6009&salestrNo=1004'),
    ('1000807328520 (밀레)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009'),
    ('1000644956258 (나이키 카고팬츠)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000644956258&siteNo=6009&salestrNo=1004'),
]

c = SsgCrawler()
for label, url in URLS:
    print('=' * 88)
    print(f'  {label}')
    print(f'  {url}')
    print('=' * 88)
    try:
        html = c._fetch_html(url)
        print(f'  HTML 길이: {len(html):,} bytes')
        for kw in ['쿠폰', '제휴할인', '8%', '최대 2만원', '다운로드', '백화점']:
            positions = [m.start() for m in re.finditer(re.escape(kw), html)]
            print(f'  "{kw}" 출현: {len(positions)}회')
            for pos in positions[:2]:
                ctx = html[max(0,pos-100):pos+200]
                ctx = re.sub(r'\s+', ' ', ctx)[:300]
                print(f'    ...{ctx}...')
    except Exception as e:
        print(f'  ❌ ERROR: {e}')
    print()
