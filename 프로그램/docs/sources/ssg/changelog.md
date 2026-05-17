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

### 라이브 검증 결과 (2026-05-17) — ⚠️ HTTP 429 Rate Limit
- URL: itemId=1000631699134 (DB option_source_urls)
- ❌ **HTTP 429 (Too Many Requests)** — SSG 의 anti-bot rate limit 발동
- 추정 원인: 사용자가 `_시스템/scripts/_ssg_*.py` 9개로 active 디버깅 중 → IP 단위 누적 호출 한도 초과
- 대응: 시간차 두고 재시도 필요 (15분~1시간 wait 후). 또는 다른 IP/세션 사용
- Fail-safe 동작 정상 (RuntimeError 대신 HTTPError raise — curl_cffi 가 응답 코드로 차단)
- 코드 로직 자체는 정상 — Rate Limit 만 풀리면 정상 동작 예상

### 사용자 active work 충돌 검토
- `_시스템/scripts/_ssg_*.py` 9개 untracked — 모두 사용자 진행 중 디버그 스크립트
- 본 방은 docs/sources/ssg/ 만 (코드 안 건드림) → 충돌 없음

### 관련 메모리
- `project_benefit_spec.md` (⑦ SSG 항목)

---

(다음 변경 기록은 이 줄 위에 추가)
