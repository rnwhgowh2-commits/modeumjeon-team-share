# 🛏️ 스스 르무통 방 (ss_lemouton)

> 세 번째 소싱처 방. 네이버 브랜드스토어 (brand.naver.com/lemouton).
> **JSON-based 추출** — DOM 셀렉터 대신 `window.__PRELOADED_STATE__` 파싱.

## 📂 파일

| 파일 | 역할 |
|---|---|
| **`profile.yaml`** | ⭐ 단일 진실 원천 — JSON path 매핑·anti-bot·추출 방식 |
| `selectors.yaml` | DOM 셀렉터 X / JSON path 명세 |
| `pricing_policy.yaml` | 3개 혜택 (리뷰적립 변동 + 네페 1% + 현대카드 2.73%) |
| `login.md` | 비로그인 + curl_cffi WAF 우회 |
| `env.example` | 환경변수 (대부분 옵셔널) |
| `changelog.md` | 변경기록 |
| `_demo_smoke.py` | 라이브 검증 |

## 🚀 빠른 진단

1. **`changelog.md` 확인**
2. **`_demo_smoke.py {URL}` 실행** — 라이브 결과
3. **에러 메시지로 갈래 잡기:**
   - 빈 결과 (options=[]) → `__PRELOADED_STATE__` 파싱 실패 → Next.js 구조 변경. `selectors.yaml.state_extraction` 패턴 재확인
   - `[ss_lemouton] 가격 추출 실패` (Fail-safe) → `benefitsView.discountedSalePrice` JSON path 변경
   - 429 / 비로그인 페이지 → WAF 변경 → curl_cffi impersonate target 변경 (chrome120 → chrome131 등)
   - URL 이 smartstore 인데 swap 안 됨 → `_normalize_url` 호스트 매칭 변경

## 🔗 관련 코드 (운영)

| 위치 | 역할 |
|---|---|
| `_시스템/lemouton/sourcing/crawlers/ss_lemouton.py` | 단일 파일 크롤러 (~380줄) |
| `_시스템/lemouton/sourcing/crawlers/base.py` | AbstractCrawler · CrawlResult |

## 📊 검증된 정확도 baseline

**라이브 검증 대기.** 핵심 검증 포인트:
- `review_point_max` 가 사이트 "최대 리뷰적립" 표시값과 일치 (2026-05-15 사용자 정정 산식)
- `sale_price` 가 `benefitsView.discountedSalePrice` 와 일치

## ⚠️ 르무통 공홈과 차이 (헷갈리지 말 것)

| 항목 | 르무통 공홈 (lemouton) | 스스 르무통 (ss_lemouton) |
|---|---|---|
| 사이트 | lemouton.co.kr | brand.naver.com/lemouton |
| 플랫폼 | Cafe24 자사몰 | 네이버 브랜드스토어 |
| 리뷰적립 | 5,000 고정 (DB 자동) | 변동 (크롤링 추출 필요) |
| 옵션 추출 | DOM 셀렉터 + Playwright 클릭 | JSON path |
| 같은 브랜드 ('르무통') | 다른 채널 — 데이터 별도 |

→ 두 사이트 결과 차이가 본질 (가격·재고·옵션 모두 별개). 매트릭스에서도 source 분리.
