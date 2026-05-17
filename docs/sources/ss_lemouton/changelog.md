# 스스 르무통 변경기록

> 사이트 개편·셀렉터/JSON path 변경·정책 룰 변경 시마다 최신 항목을 **위에서부터 append**.

---

## 2026-05-17 [방 최초 생성] by claude+rnwhgowh2

### 무엇
- `docs/sources/ss_lemouton/` 폴더 신설 (세 번째 소싱처 방)
- 파일: profile.yaml · selectors.yaml · pricing_policy.yaml · login.md · env.example · README.md · changelog.md · _demo_smoke.py

### 코드 분석 결과
- 어댑터: `_시스템/lemouton/sourcing/crawlers/ss_lemouton.py` (V7 미지원 신규)
- 사이트: `brand.naver.com/lemouton/products/{ID}` (smartstore.naver.com 자동 swap)
- 추출 방식: **inline JSON** (`window.__PRELOADED_STATE__` Next.js SSR)
- Anti-bot: `curl_cffi chrome120` (Naver Commerce WAF 우회)
- 회원가 표시: **없음** (`benefitsView.discountedSalePrice` 가 모든 사용자 동일)
- 리뷰적립: **동적 변동** (photo+afterPhoto+manager+managerAfter 합산 또는 텍스트 fallback)

### 무신사 vs 르무통 공홈 vs 스스 르무통 비교
| 항목 | 무신사 | 르무통 공홈 | 스스 르무통 |
|---|---|---|---|
| 추출 방식 | Playwright + JS extraction | requests + Playwright | inline JSON 파싱 |
| Anti-bot | curl_cffi (Cloudflare) | 없음 | curl_cffi (Naver WAF) |
| 회원가 영역 | 9가격항목 | 없음 | 없음 |
| 리뷰적립 | 후기 500 고정 (DB 자동) | 5,000 고정 (DB 자동) | 변동 (크롤링) |
| SKU 재고 | API 정확 | Cafe24 색상 클릭 토글 | 상품 전체만 (SKU 차등 불가) |

### Phase B 일반화 적합도
**스스 르무통이 가장 적합** — DOM 셀렉터 대신 JSON path 매핑이라 yaml 표현 깔끔. 향후 우선 yaml-driven 변환 후보.

### 라이브 검증 대기
- 사용자께 URL 받아서 `_demo_smoke.py` 실행 → accuracy_baseline 채우기
- 검증 포인트: review_point_max 가 사이트 "최대 리뷰적립" 표시값과 일치하는지 (memory `project_benefit_spec.md` 가이드)

### 관련 메모리
- `project_benefit_spec.md` (② 스스 르무통 항목)

---

(다음 변경 기록은 이 줄 위에 추가)
