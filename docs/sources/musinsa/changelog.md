# 무신사 변경기록

> 사이트 개편·셀렉터 변경·정책 룰 변경 시마다 최신 항목을 **위에서부터 append**.
> 형식: `## YYYY-MM-DD [변경 카테고리] by 작업자` + 변경 내용 + 영향 + 검증 결과.

---

## 2026-05-17 [라이브 검증 — 시연 모델 추가] by claude+rnwhgowh2

- URL: DB models — products/3728480 (르무통 클래식 2 다크네이비)
- benefit_price (회원가) = 113,265원 / member_price 109,300원 / sale 122,900원
- 옵션 1개 (단품 폴백 — Playwright dropdown 클릭 실패, 알려진 이슈)
- coupon = 0, grade_reward 0, money_reward 0 (혜택 미적용 상품)
- ✅ Fail-safe #9 통과 (109,300 ≤ 122,900)
- accuracy_baseline.verified_skus 에 추가 (총 4개 SKU 검증)

---

## 2026-05-17 [방 생성 · BUG fix · Fail-safe 추가] by claude+rnwhgowh2

### 1. 방 최초 생성
- `docs/sources/musinsa/` 폴더 신설 (첫 번째 소싱처 방, 다른 사이트 방의 표준 양식)
- 파일: profile.yaml · selectors.yaml · pricing_policy.yaml · login.md · env.example · README.md · changelog.md (본 파일) + `_demo_*.py` · `_debug_*.py` 진단/검증 스크립트
- 운영 코드 (`_시스템/lemouton/sourcing/crawlers/musinsa*.py`) 의 셀렉터·정책을 yaml/md 로 추출 (사람 친화 명세서)

### 2. 쿠폰 이중차감 BUG 수정 (musinsa_playwright.py)
- **증상**: 상품 4677240 (필름메이커 패딩) 매입가 152,286원 산출 → 사용자 기대 ~198,439원 (사이트 "나의 할인가" 215,320 베이스)
- **원인**: 사이트 PDP 가격 영역에 "쿠폰적용가" 라벨 노출 시 sale_price (220,320) 가 이미 특별쿠폰 -55,080 적용 후 가격인데, `base1 = sale - coupon` 산식이 또 -55,080 차감 → 165,240 → 매입가 152,286
- **사용자 확인**: 스크린샷으로 "쿠폰적용가" 라벨 직접 노출 확인 (2026-05-17)
- **수정 위치 (3곳)**:
  - `_EXTRACT_JS`: PriceTotal/DiscountWrap/CurrentPrice 의 textContent 에서 `/쿠폰\s*적용가/` 정규식 매칭 → `breakdown.is_already_coupon_applied` 플래그 set
  - `_crawl` base1 분기: `is_already_coupon_applied=True` → `base1 = sale - grade_discount` (쿠폰 차감 안 함), 아니면 기존 `base1 = sale - grade_discount - coupon`
  - `discount_info` 텍스트: "쿠폰 (이미 sale_price 에 반영, 추가 차감 안 함) -55,080원" 으로 명시
- **검증 결과**: 4677240 → benefit_price 152,286 → **203,048원** ✅ (사용자 기대 일치)

### 3. Fail-safe 가드 추가 (Verification #9)
- **추가 검증 룰**: `my_discount_price > base1` 이면 `RuntimeError` raise → DB 저장 차단
- **이유**: 사이트가 표시하는 "나의 할인가" (member_price 추출값) 가 우리 base1 보다 크면 base1 산정 오류 (이중차감·sale 추출 오류·정책 변경 등) — 단순 invariant 로 다양한 BUG 동시 탐지
- **위치**: `_crawl` 안 `tier1_confirmed = base1` 바로 다음 라인
- **효과**: 오늘의 BUG (199,900 > 165,240) 가 향후 비슷한 형태로 재발하면 즉시 차단 → 가격 오류 production 유입 방지

### 4. 회귀 테스트 결과 (3개 상품 모두 통과)
| 상품 | 라벨 | 매입가 | 회귀 |
|---|---|---|---|
| 4677240 (필름메이커 패딩) | 쿠폰적용가 ✅ | **152,286 → 203,048** (수정) | ✅ |
| 4046672 (르무통 운동화) | 없음 | 113,265 (불변) | ✅ |
| 4210142 (시티 레저 팬츠) | 없음 | 35,890 (불변) | ✅ |

### 5. 알려진 미해결 이슈 (별도 fix 예정)
- "적립금 사용" 체크박스 OFF 클릭 셀렉터 미적중 (`input[type="checkbox"]` 가 무신사 신 UI 의 커스텀 컴포넌트와 안 맞음)
- 일부 상품에서 `member_price` 추출 알고리즘 알려진 한계 (헤지스 등 특수 케이스)
- 4210142 등 헤드리스 모드에서 단품 폴백 (옵션 dropdown 클릭 실패, 옵션 1개로 반환)

### 관련 메모리
- `project_musinsa_coupon_applied_label.md` (이번 BUG 룰 영구 기록)
- `project_member_price_required.md` (회원가 필수 / 비로그인 의미 없음)
- `project_benefit_spec.md` (7개 소싱처 가격 정책 진실 원천)

---

(다음 변경 기록은 이 줄 위에 추가)
