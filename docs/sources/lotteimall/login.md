# 롯데홈쇼핑 로그인 셋업

## 🎯 로그인 필요한가?

**기본은 비로그인** — sale_price·max_price·옵션·자동 카드 할인 모두 비로그인 SSR HTML 에 노출.

다만 **L.CLUB 회원 적립** (`club_point`) 같은 멤버십 한정 노출 정확도를 위해 로그인 모드 검토 가능.

## 📦 인증 메커니즘

| 방식 | 위치 | 용도 |
|---|---|---|
| **비로그인 (default)** | — | 기본 운영 |
| **로그인** | `_시스템/data/profiles/lotteimall_{계정}/` | L.CLUB / 멤버십 한정 |

## 👤 현재 등록된 lotteimall 계정

`_시스템/data/profiles/` 안:
- `lotteimall_rnwhgowh2_gmail_com` — Playwright 영구 프로필

## 🔧 로그인 셋업 (LotteimallScraper)

별도 인증 스크래퍼 존재: `_시스템/lemouton/auth/scrapers/lotteimall.py`

```python
from lemouton.auth.scrapers.lotteimall import LotteimallScraper
# 사이트 키: "lotteimall"
# 로그인 URL: https://www.lotteimall.com/member/login/forward.LCLoginMem.lotte
```

쿠키 키 (cookie_checker.py:40):
- JSESSIONID
- LMC_TOKEN
- LM_LOGIN

## ⚠️ 주의

- 도메인 3개 (lotteimall.com · lottehomeshopping.com · m.lottehomeshopping.com) 모두 같은 로그인 세션 공유? — 별도 검증 필요
- ❌ Playwright 프로필 / 쿠키 git commit 금지
