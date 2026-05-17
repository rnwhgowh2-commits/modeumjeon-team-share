# 🛏️ 롯데ON 방 (lotteon)

> 여섯 번째 (마지막) 소싱처 방. **Vue SPA + pbf API 캡처** — 가장 복잡한 추출 패턴.

## ⚠️ 코드 위치 헷갈림 주의

- 코드 파일: `_시스템/lemouton/sourcing/crawlers/lotteon.py` ★ **롯데홈쇼핑과 같은 파일**
- 본 방의 스코프: `_is_lotteon(url) == True` 분기 (`_fetch_lotteon`)
- 별도 방: `docs/sources/lotteimall/` — `_is_lotteon(url) == False` (SSR HTML 분기)

## 📂 파일

| 파일 | 역할 |
|---|---|
| **`profile.yaml`** | ⭐ pbf API endpoints · discountGroups 4종 · 조건부 적용 룰 |
| `selectors.yaml` | API JSON path 매핑 (DOM 셀렉터는 schema.org JSON-LD 만) |
| `pricing_policy.yaml` | 1개 혜택 (카드즉시할인/장바구니쿠폰, 조건부) |
| `login.md` | LotteonScraper (실 토큰 fo_ac_tkn / fo_sso_tkn / fo_mno) |
| `env.example` | 환경변수 양식 |
| `changelog.md` | 변경기록 |
| `_demo_smoke.py` | 라이브 검증 |

## 🚀 빠른 진단

1. **`changelog.md` 확인**
2. **`_demo_smoke.py {URL}` 실행**
3. **에러 메시지로 갈래 잡기:**
   - `API 응답 캡처 실패` → pbf endpoint URL 패턴 변경 (예: v2 → v3)
   - `sale_price <= 0` (Fail-safe) → qtyChangeFavorInfoList JSON 구조 변경
   - 옵션 0개 → option/mapping API path 변경
   - 카드즉시할인 누락 → favorBox/benefits.discountGroups[] 의 ORDER 그룹 필터 변경

## 🔗 관련 코드

| 위치 | 역할 |
|---|---|
| `_시스템/lemouton/sourcing/crawlers/lotteon.py` | 단일 파일 (3 도메인) — 본 방은 _fetch_lotteon 분기 |
| `_시스템/lemouton/auth/scrapers/lotteon.py` | 로그인 자동화 (실 토큰 fo_*) |

## 📊 검증된 정확도 baseline

**라이브 검증 대기.** 핵심:
- pbf API 4개 모두 캡처 성공
- discountGroups 안 ORDER 그룹 카드즉시할인/장바구니쿠폰 정확 추출
- 조건부 (minPdAmt) 미충족 시 매입가 미적용

## ⚠️ 사용자 정책 핵심 (memory ⑥)

- **혜택 1개만 추출**: 카드즉시할인/장바구니쿠폰 (groupId=ORDER, prKndCd=CRD_IMMD or CPN_BSK_CPN)
- **조건 필수 명기**: minPdAmt/maxPdAmt 충족 시만 매입가 적용. 미충족 시 표시만
- **리뷰 적립 없음**
- 4개 그룹 중 IMMD/IMMD_AND_PRODUCT_COUPON/STORE_COUPON 은 매입가 미반영 (사용자 명세 외)
