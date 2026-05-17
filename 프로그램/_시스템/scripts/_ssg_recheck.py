"""SSG 닥스 벨트 (itemId=1000631699134) 재크롤링 + 사이트 텍스트 디버깅.

목적:
  - 현재 ssg.py 가 추출하는 dyn keys 출력
  - body inner_text 에서 "상품쿠폰", "충전결제", "1.5%", "SSG MONEY" 패턴 노출 위치 grep
  - 추후 패치할 정규식의 ground-truth 확보
"""
from __future__ import annotations

import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

URL = "https://www.ssg.com/item/itemView.ssg?itemId=1000631699134&siteNo=6009&salestrNo=1004"

from lemouton.sourcing.crawlers.ssg import SsgCrawler  # noqa: E402
from curl_cffi import requests as cffi_requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402


def main():
    print('=== SSG 재크롤링 (CrawlResult) ===')
    cr = SsgCrawler().fetch(URL)
    print(f'product_name: {cr.product_name_raw}')
    print(f'brand: {cr.brand}')
    print(f'discount_info: {cr.discount_info}')
    print(f'옵션 개수: {len(cr.options)}')
    if cr.options:
        o = cr.options[0]
        print('첫 옵션 dict:')
        for k, v in o.items():
            print(f'  {k}: {v!r}')

    print()
    print('=== HTML body 디버깅 — 패턴 grep ===')
    resp = cffi_requests.get(URL, impersonate='chrome120', timeout=30,
                              headers={'Accept-Language': 'ko-KR,ko;q=0.9'})
    html = resp.text
    soup = BeautifulSoup(html, 'lxml')
    body_text = soup.get_text(' ', strip=True)
    body_text_compact = re.sub(r'\s+', ' ', body_text)

    keywords = [
        '상품쿠폰', '충전결제', 'SSG MONEY', 'SSGMONEY',
        '1.5%', '1.5 %', '12% 상품',
        '구매혜택', '쇼핑혜택', '3만원 이상',
        '카드혜택가', '5만원 이상',
    ]
    for kw in keywords:
        idx = 0
        hits = 0
        while True:
            i = body_text_compact.find(kw, idx)
            if i == -1:
                break
            ctx = body_text_compact[max(0, i-60):i+200]
            print(f'\n[{kw}] @ pos={i}')
            print(f'  ...{ctx}...')
            idx = i + 1
            hits += 1
            if hits >= 3:
                print(f'  (총 hit 3+ — break)')
                break
        if hits == 0:
            print(f'\n[{kw}] — body_text 에 없음')

    # HTML raw 에서도 "상품쿠폰" 노출 (스크립트 안일 수 있음)
    print()
    print('=== HTML raw 에서 상품쿠폰 grep (script 안 포함) ===')
    for m in re.finditer(r'상품\s*쿠폰', html):
        i = m.start()
        ctx = html[max(0, i-100):i+300]
        print(f'\n@ pos={i}: ...{ctx}...')
        # 너무 많으면 break
        # 첫 5개만
    # SSG MONEY 충전결제 패턴
    print()
    print('=== HTML raw 에서 충전결제 grep ===')
    for m in re.finditer(r'충전\s*결제', html):
        i = m.start()
        ctx = html[max(0, i-100):i+300]
        print(f'\n@ pos={i}: ...{ctx}...')

    # 1.5% 패턴
    print()
    print('=== HTML raw 에서 1\\.5\\s*% grep ===')
    for m in re.finditer(r'1\.5\s*%', html):
        i = m.start()
        ctx = html[max(0, i-100):i+200]
        print(f'\n@ pos={i}: ...{ctx}...')


if __name__ == '__main__':
    main()
