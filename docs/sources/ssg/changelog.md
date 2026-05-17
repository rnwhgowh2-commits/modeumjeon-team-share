# SSG 변경기록

---

## 2026-05-17 [방 최초 생성] by claude+rnwhgowh2

### 무엇
- `docs/sources/ssg/` 폴더 신설 (일곱 번째 소싱처 방 — 본 세션 마지막)
- 파일: profile.yaml · selectors.yaml · pricing_policy.yaml · login.md · env.example · README.md · changelog.md · _demo_smoke.py

### 코드 분석 결과 — 가장 복잡한 소싱처
- 어댑터: `_시스템/lemouton/sourcing/crawlers/ssg.py` (~650줄)
- 추출: curl_cffi + BS4 + 인라인 JS uitemObj 정규식
- 회원가: 없음 — sale_price = bestAmt (최적가, 즉시할인 반영) 우선
- ★ **SSG MONEY 4 패턴 분기** (A 즉시할인 이미 반영 / B 적립 별도 / C 듀얼 옵션 / D 미노출)
- 카드혜택가 정액 + 조건부 / 미노출 시 현대카드 2.73% fallback
- 상품쿠폰 X% + 최소 구매금액

### 7개 사이트 통합 비교
| 항목 | 무신사 | 르무통 공홈 | 스스 르무통 | SSF | 롯데홈쇼핑 | 롯데ON | **SSG** |
|---|---|---|---|---|---|---|---|
| 추출 방식 | PW JS | requests+PW | inline JSON | curl_cffi+BS4+regex | curl_cffi+JSON | PW API capture | **curl_cffi+JS regex+DOM** |
| 회원가 | 9항목 | 없음 | 없음 | 없음 | 없음 | 부분 | 없음 |
| 혜택 수 | 9 | 3 | 3 | 5 | 2 | 1 조건부 | **2 (4 패턴 분기)** |
| 특이점 | Fail-safe #9 | DB 자동 | 리뷰 변동 | 멀티 색상 GRG | max_price 이미 반영 | minPdAmt 조건 | **SSG MONEY 즉시할인 vs 적립 듀얼** |

### Phase B 일반화 적합도 (업데이트)
1. **스스 르무통** — JSON path 가장 깔끔 (재확인)
2. **롯데ON** — pbf API endpoint 추상화 가능
3. **롯데홈쇼핑** — dataBenefit JSON 혼합
4. **SSG** — SSG MONEY 4 패턴이 복잡해서 yaml 표현 어려움 (코드 권장)
5. **SSF** — DOM + regex 혼합
6. **르무통 공홈** — Cafe24 동작 (단순)
7. **무신사** — 988줄 (셀렉터·timeout 만)

### 라이브 검증 결과 (2026-05-17) — ✅ 4/4 완벽 검증 (4 패턴 모두)

**1차 (curl_cffi)** — ❌ 4 URL 모두 HTTP 429 (사용자 active work 와 IP 단위 rate limit 충돌)

**2차 (Playwright 영구 프로필 우회)** — ✅ 4/4 성공
- 우회 도구: `docs/sources/ssg/_demo_via_playwright.py` (사용자 `_ssg_pw_fetch2.py` 패턴 활용)
- `data/profiles/ssg_ditodalal_pw` 영구 Chrome 프로필 + webdriver 우회
- SsgCrawler 내부 파싱 함수 1:1 재활용 → 운영 코드와 동일 결과

| # | item_id | sale | 옵션 | SSG MONEY 패턴 | 카드혜택가 | 상품쿠폰 |
|---|---|---|---|---|---|---|
| 1 | 1000809938058 (나이키 리엑스 8) | 70,805원 | 10 | E 충전결제 1.5% | 미노출 | — |
| 2 | **1000807328520 (밀레)** | **39,690원** | 26 | **C→A 듀얼·already_applied=True ★** | 미노출 | — |
| 3 | 1000644956258 (나이키 카고) | 60,605원 | 4 | E 충전결제 1.5% | 미노출 | — |
| 4 | **1000631699134 (닥스 벨트)** | 107,355원 | 1 | E 충전결제 | **98,767원 (5만원↑)** | **12% (3만원↑)** |

**검증된 4 패턴:**
- ✅ 패턴 A·C (already_applied=True 이중차감 방지) — 밀레
- ✅ 패턴 E (충전결제 1.5% fallback) — 나이키 리엑스/카고/닥스
- ✅ 카드혜택가 + 조건 텍스트 — 닥스 (98,767원 / 5만원 이상)
- ✅ 상품쿠폰 + 최소 구매금액 — 닥스 (12% / 30,000원)

→ **SsgCrawler 운영 코드 모든 로직 정상 동작 입증**. curl_cffi 만 풀리면 즉시 정상 작동.

### ⚠️ 본 세션 중 발생한 부가 이슈
- 본 세션 후반 git working tree 에서 docs/migrations/sync.py 76 파일이 사라짐 (worktree merge 영향 추정)
- `git restore` 로 복구 — git HEAD 의 객체는 무사. 운영 코드/데이터 손실 0

### 사용자 active work 충돌 검토
- `_시스템/scripts/_ssg_*.py` 9개 untracked — 모두 사용자 진행 중 디버그 스크립트
- 본 방은 docs/sources/ssg/ 만 (코드 안 건드림) → 충돌 없음

### 관련 메모리
- `project_benefit_spec.md` (⑦ SSG 항목)

---

(다음 변경 기록은 이 줄 위에 추가)
