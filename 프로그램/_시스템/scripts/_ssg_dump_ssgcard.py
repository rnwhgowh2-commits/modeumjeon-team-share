"""SSG 'ssgcard' / '쓱세일 청구할인' / '제휴할인' 영역 raw HTML 구조 dump."""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from lemouton.sourcing.crawlers.ssg import SsgCrawler
from bs4 import BeautifulSoup

URLS = [
    ('1000809938058 (나이키 리엑스)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000809938058&siteNo=6009&salestrNo=1004'),
    ('1000644956258 (나이키 카고팬츠)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000644956258&siteNo=6009&salestrNo=1004'),
    ('1000631699134 (벨트 — 비교용, 12% 상품쿠폰)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000631699134&siteNo=6009&salestrNo=1004'),
]

c = SsgCrawler()
for label, url in URLS:
    print('=' * 88)
    print(f'  {label}')
    print('=' * 88)
    html = c._fetch_html(url)
    # ssgcard_rate / ssgcard_discount 주변 dump
    for kw in ['ssgcard_rate', '쓱세일', '명품잡화쓱세일', '청구할인']:
        positions = [m.start() for m in re.finditer(re.escape(kw), html)]
        if positions:
            print(f'  "{kw}" ({len(positions)}회)')
            for pos in positions[:2]:
                ctx = html[max(0,pos-200):pos+400]
                ctx = re.sub(r'\s+', ' ', ctx)[:600]
                print(f'    ...{ctx}...')
    # ssgcard_item / ssg_card_list / 카드혜택 영역 selector 찾기
    soup = BeautifulSoup(html, 'lxml')
    for sel in ['div.ssgcard_item', 'a.ssgcard_item_link', '.ssgcard_info', '[data-react-unit-text*="청구할인"]']:
        nodes = soup.select(sel)
        if nodes:
            print(f'  selector "{sel}" → {len(nodes)} nodes')
            for n in nodes[:2]:
                t = re.sub(r'\s+', ' ', n.get_text(' ', strip=True))[:200]
                print(f'    text: {t}')
                # data-react-unit-text 속성도 확인
                if n.has_attr('data-react-unit-text'):
                    print(f'    react-text: {n["data-react-unit-text"][:200]}')
    print()
