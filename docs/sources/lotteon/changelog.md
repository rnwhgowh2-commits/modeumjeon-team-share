# 롯데ON 변경기록

---

## 2026-05-17 [방 최초 생성] by claude+rnwhgowh2

### 무엇
- `docs/sources/lotteon/` 폴더 신설 (여섯 번째 소싱처 방, 본 세션 마지막)
- 파일: profile.yaml · selectors.yaml · pricing_policy.yaml · login.md · env.example · README.md · changelog.md · _demo_smoke.py

### 코드 분석 결과 — Vue SPA + API 캡처
- 어댑터 파일: `_시스템/lemouton/sourcing/crawlers/lotteon.py` (롯데홈쇼핑과 공유)
- 본 방의 스코프: `_is_lotteon(url) == True` 분기 (`_fetch_lotteon`)
- 클래스: `LotteCrawler` (source_name='lotte' — 같은 source, 도메인으로만 분기)

### 핵심 특징 — 다른 사이트와 차별점
- **추출**: Vue SPA 라 SSR HTML 안 됨 → **Playwright + pbf.lotteon.com API 응답 캡처**
- 4개 API endpoint:
  - `/product/v2/detail/search/base/sitm/{sitmNo}` (기본 정보)
  - `/product/v2/detail/option/mapping/...` (옵션·재고)
  - `/product/v2/extlmsa/promotion/favorBox/benefits` (★ 쿠폰별 할인 그룹)
  - `/product/v2/extlmsa/promotion/qtyChangeFavorInfoList` (최종 가격)
- **할인 그룹 4종 분류**: IMMD / IMMD_AND_PRODUCT_COUPON / STORE_COUPON / ORDER (★ 사용자 명세)
- **혜택 1개만 (사용자 명세)**: 카드즉시할인 / 장바구니쿠폰 (groupId=ORDER, prKndCd=CRD_IMMD/CPN_BSK_CPN)
- **★ 조건부 적용**: minPdAmt/maxPdAmt 충족 시만 적용. 미충족 시 표시만 (사용자 정책)
- **리뷰 적립 없음** (memory ⑥ 명시)

### 전체 6개 사이트 통합 비교
| 항목 | 무신사 | 르무통 공홈 | 스스 르무통 | SSF | 롯데홈쇼핑 | 롯데ON |
|---|---|---|---|---|---|---|
| 추출 방식 | Playwright JS | requests+PW | brand.naver inline JSON | curl_cffi+BS4+regex | curl_cffi+BS4+JSON | **Playwright API capture** |
| 회원가 | 9가격항목 | 없음 | 없음 | 없음 | 없음 | 부분 (회원 등급) |
| 리뷰 적립 | 후기 500 | 5,000 | 변동 | 500 | ❌ 없음 | ❌ 없음 |
| 혜택 개수 | 9 | 3 | 3 | 5 | 2 | 1 (조건부) |
| 조건부 적용 | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ minPdAmt/maxPdAmt |

### 6 사이트 작업 총평
- **본 세션에서 5개 신규 방 생성** (르무통·스스·SSF·롯데홈쇼핑·롯데ON) — 무신사 방까지 합치면 6개 완결
- 각 방은 **무신사 방 패턴 복제** (profile/selectors/pricing/login/env/changelog/README + _demo_smoke)
- 라이브 검증은 **모두 대기 중** — 사용자께 URL 받으면 즉시 검증 가능

### Phase B 일반화 적합도 순위 (개인 평가)
1. **스스 르무통** — JSON path 매핑이라 yaml 표현 가장 깔끔
2. **롯데ON** — pbf API endpoint 추상화 가능
3. **롯데홈쇼핑** — dataBenefit JSON + DOM 셀렉터 혼합
4. **SSF** — DOM 셀렉터 + raw HTML 정규식 혼합
5. **르무통 공홈** — DOM 셀렉터 + Cafe24 동작 (정적 vs Playwright fallback)
6. **무신사** — JS 코드가 너무 복잡 (988줄). 셀렉터·timeout 만 부분 yaml 화 (이미 시연 완료)

### 라이브 검증 대기

### 관련 메모리
- `project_benefit_spec.md` (⑥ 롯데온 항목)

---

(다음 변경 기록은 이 줄 위에 추가)
