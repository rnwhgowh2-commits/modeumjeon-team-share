"""SSG cffi 페치 — ckwhere=ssg_naver + Naver Referer 헤더 박아서 8% 쿠폰 노출 시도."""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from curl_cffi import requests as cffi_requests

NAVER_PARAMS = '&ckwhere=ssg_naver&appPopYn=n&utm_medium=PCS&utm_source=naver&utm_campaign=naver_pcs'

URLS = [
    ('1000809938058 (나이키 리엑스)', f'https://www.ssg.com/item/itemView.ssg?itemId=1000809938058&siteNo=6009&salestrNo=1004{NAVER_PARAMS}'),
    ('1000807328520 (밀레)',         f'https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009{NAVER_PARAMS}'),
    ('1000644956258 (나이키 카고)',  f'https://www.ssg.com/item/itemView.ssg?itemId=1000644956258&siteNo=6009&salestrNo=1004{NAVER_PARAMS}'),
]

for label, url in URLS:
    print('=' * 90)
    print(f'  {label}')
    print('=' * 90)
    try:
        resp = cffi_requests.get(
            url,
            impersonate='chrome120',
            timeout=30,
            headers={
                'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Referer': 'https://search.shopping.naver.com/',
            },
        )
        print(f'  status: {resp.status_code}  size: {len(resp.text):,}')
        html = resp.text
        # 차단 체크
        if '연속적인 접근' in html:
            print('  ❌ reCAPTCHA 차단')
            continue
        # 핵심 키워드
        for kw in ['상품쿠폰', '8% 상품쿠폰', '제휴할인', '다운로드 1일이내', '최대 2만원', '백화점 8%']:
            cnt = len(list(re.finditer(re.escape(kw), html)))
            print(f'  "{kw}": {cnt}회')
            if cnt > 0:
                m = re.search(re.escape(kw), html)
                if m:
                    ctx = html[max(0,m.start()-100):m.start()+300]
                    ctx = re.sub(r'\s+', ' ', ctx)[:400]
                    print(f'    ...{ctx}...')
    except Exception as e:
        print(f'  ❌ ERROR: {e}')
    print()
