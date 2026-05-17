# 르무통 공홈 변경기록

> 사이트 개편·셀렉터 변경·정책 룰 변경 시마다 최신 항목을 **위에서부터 append**.

---

## 2026-05-17 [방 최초 생성] by claude+rnwhgowh2

### 무엇
- `docs/sources/lemouton/` 폴더 신설 (두 번째 소싱처 방, 무신사 방 패턴 복제)
- 파일: profile.yaml · selectors.yaml · pricing_policy.yaml · login.md · env.example · README.md · changelog.md · _demo_smoke.py

### 코드 분석 결과
- 어댑터: `_시스템/lemouton/sourcing/crawlers/lemouton.py` (정적 HTML, V7 1:1 포팅) + `lemouton_playwright.py` (색상별 사이즈 정확도)
- 플랫폼: **Cafe24** (자사몰)
- 인증: 기본 비로그인 (profile_dir 모드도 지원)
- Anti-bot: 없음
- 회원가 표시: **없음** (모든 사용자 동일 가격) — 무신사와 큰 차이
- 매입가 산정: DB `compute_breakdown` 가 sale_price 에 혜택 차감 (리뷰적립 5,000 + 네페 1% + 현대카드 2.73%)

### 무신사 vs 르무통 공홈 차이
| 항목 | 무신사 | 르무통 공홈 |
|---|---|---|
| 플랫폼 | 자체 React SPA | Cafe24 |
| Anti-bot | Cloudflare → curl_cffi | 없음 |
| 회원가 영역 | 9가격항목, 사이트가 표시 | 없음 (DB 계산) |
| 크롤러 복잡도 | 988줄 (Playwright + JS extraction) | 350줄 (requests + Playwright fallback) |
| Fail-safe | 5단계 + LV sanity + Phase 8.8.3 + #9 invariant | 1개 (sale_price > 0) |
| 옵션 처리 | dropdown 클릭으로 enumerate | 색상 클릭 → 사이즈 토글 (Cafe24 .ec-product-soldout 동적 토글) |

### 라이브 검증 결과 (2026-05-17)
- URL: DB models 테이블 — product_no=219 (르무통 클래식2 메리노울 운동화)
- sale_price = **116,900원** (기본할인 22%)
- 옵션 40개 (8색 × 5사이즈) — Playwright 색상 클릭 → 사이즈 토글 정상 동작
- auto_card_discount = 현대카드 2.73% 정상 부착
- ✅ 정상 동작 — accuracy_baseline.verified_skus 에 누적

### 관련 메모리
- `project_benefit_spec.md` (① 르무통 공홈 항목)

---

(다음 변경 기록은 이 줄 위에 추가)
