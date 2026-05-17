# 🛏️ 르무통 공홈 방 (lemouton)

> 두 번째 소싱처 방. 자사몰 (Cafe24) — 무신사보다 훨씬 단순한 구조.

## 📂 파일

| 파일 | 역할 |
|---|---|
| **`profile.yaml`** | ⭐ 단일 진실 원천 — Cafe24 셀렉터·Playwright 모드·자동 카드 |
| `selectors.yaml` | V7 셀렉터 (price-number, ec-product-button 등) 상세 |
| `pricing_policy.yaml` | 3개 혜택 (리뷰적립 5,000 + 네페 1% + 현대카드 2.73%) |
| `login.md` | 비로그인 기본 — profile_dir 옵션 안내 |
| `env.example` | 환경변수 양식 (대부분 옵셔널) |
| `changelog.md` | 변경기록 |
| `_demo_smoke.py` | 라이브 검증 스크립트 |

## 🚀 빠른 진단

1. **`changelog.md` 확인** — 최근 변경 이력
2. **`_demo_smoke.py {URL}` 실행** — 실제 크롤 결과
3. **에러 메시지로 갈래 잡기:**
   - `sale_price <= 0` (Fail-safe) → 가격 셀렉터 변경 (selectors.yaml.price 참조)
   - `옵션 버튼 로드 타임아웃` → `ul.ec-product-button` 셀렉터 변경
   - `색상 클릭 후 사이즈 안 토글` → Playwright wait 시간 조정 (`color_click_wait_ms`)
   - 옵션 모두 "재고 있음" 으로 잘못 표시 → 정적 HTML 모드만 됨, Playwright fallback 실패

## 🔗 관련 코드 (운영)

| 위치 | 역할 |
|---|---|
| `_시스템/lemouton/sourcing/crawlers/lemouton.py` | Dispatcher + 정적 HTML 파서 (350줄) |
| `_시스템/lemouton/sourcing/crawlers/lemouton_playwright.py` | Playwright 색상 클릭 → 사이즈 토글 (정확도 핵심) |
| `_시스템/lemouton/sourcing/crawlers/base.py` | AbstractCrawler · CrawlResult 인터페이스 |

## 📊 검증된 정확도 baseline

**라이브 검증 대기.** 사용자께 URL 1-2개 받아서 `_demo_smoke.py` 실행 → 결과를 `profile.yaml` 의 `accuracy_baseline.verified_skus` 에 누적.

## ⚠️ 무신사 패턴 적용 시 주의

무신사는 사이트가 "회원가" 와 "나의 할인가" 를 직접 표시 → `member_price > base1` 가드 가능.
**르무통은 회원가 영역 자체가 없음** → 같은 가드 적용 불가. 대신 다른 invariant 필요 (예: sale_price 가 어제와 비교해 ±50% 이상 변동 시 의심) — 향후 검토.
