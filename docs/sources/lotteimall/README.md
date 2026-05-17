# 🛏️ 롯데홈쇼핑 방 (lotteimall)

> 다섯 번째 소싱처 방. **3 도메인 통합** (lotteimall.com + lottehomeshopping.com + m.lottehomeshopping.com).

## ⚠️ 코드 위치 헷갈림 주의

- 코드 파일: `_시스템/lemouton/sourcing/crawlers/lotteon.py` ★ **이름이 lotteon 이지만** 도메인 라우팅으로 3 사이트 처리
- 본 방의 스코프: `_is_lotteon(url) == False` 분기 (lottehomeshopping/lotteimall SSR HTML)
- 별도 방: `docs/sources/lotteon/` — `_is_lotteon(url) == True` 분기 (lotteon.com Playwright + pbf API)

## 📂 파일

| 파일 | 역할 |
|---|---|
| **`profile.yaml`** | ⭐ V7 셀렉터·dataBenefit JSON·도메인 라우팅 |
| `selectors.yaml` | DOM 셀렉터 + dataBenefit 정규식 |
| `pricing_policy.yaml` | 2개 혜택 (카드 청구할인 변동 + L.POINT 2-tier) |
| `login.md` | 비로그인 기본 / LotteimallScraper 인증 |
| `env.example` | 환경변수 양식 |
| `changelog.md` | 변경기록 |
| `_demo_smoke.py` | 라이브 검증 |

## 🚀 빠른 진단

1. **`changelog.md` 확인**
2. **`_demo_smoke.py {URL}` 실행**
3. **에러 메시지로 갈래 잡기:**
   - `base_for_policy <= 0` (Fail-safe) → `.final span.num` / `.price > span.num` 셀렉터 변경
   - 옵션 0개 → `div.inp_option.inpOptList` 셀렉터 변경
   - 자동 카드 할인 누락 → `dataBenefit.cardDiscountList[]` JSON 구조 변경
   - L.POINT 누락 → `dataBenefit.lPointObj` JSON 구조 변경

## 🔗 관련 코드

| 위치 | 역할 |
|---|---|
| `_시스템/lemouton/sourcing/crawlers/lotteon.py` | 단일 파일 (3 도메인 라우팅) — 본 방은 SSR 분기만 |
| `_시스템/lemouton/auth/scrapers/lotteimall.py` | 로그인 자동화 (선택) |

## 📊 검증된 정확도 baseline

**라이브 검증 대기.** 핵심:
- max_price 가 카드 청구할인 반영된 값인지 (사이트 표시값과 비교)
- auto_card_discount.included_in_sale_price=True 가 실제로 max_price 안 반영됐는지

## ⚠️ 사용자 정책 핵심 (memory ⑤)

- **리뷰 적립 = 미포함** (다른 사이트와 다름)
- **카드 청구할인** = 사이트별 카드사·% 변동 (예: 국민카드 5%) — auto 차감 안 함, sale 가격에 이미 반영
- **구매 적립혜택** = L.POINT 2-tier (일반 / L.CLUB). 사용자 정책에 따라 어느 쪽 사용할지 결정
