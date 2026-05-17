# 🛏️ SSF샵 방 (ssf)

> 네 번째 소싱처 방. 패션사이트. **multi-fetch 색상 발견** + **raw HTML 정규식** 패턴.

## 📂 파일

| 파일 | 역할 |
|---|---|
| **`profile.yaml`** | ⭐ 단일 진실 원천 — DOM 셀렉터·raw HTML regex·variant 발견 |
| `selectors.yaml` | V7 셀렉터 + 기프트/포인트 raw HTML 정규식 |
| `pricing_policy.yaml` | 5개 혜택 (리뷰 500 + 포인트 변동 + 기프트 변동 + 네페 + 현대카드) |
| `login.md` | 비로그인 기본 / 멤버십 한정 노출 시 profile_dir 검토 |
| `env.example` | 환경변수 양식 |
| `changelog.md` | 변경기록 |
| `_demo_smoke.py` | 라이브 검증 |

## 🚀 빠른 진단

1. **`changelog.md` 확인**
2. **`_demo_smoke.py {URL}` 실행**
3. **에러 메시지로 갈래 잡기:**
   - `sale_price <= 0` (Fail-safe) → `del` / `em.price` 셀렉터 변경
   - 옵션 0개 → `#optionDiv1 li a[optcd]` 셀렉터 변경
   - 모든 옵션 stock=999 → `statcd` / 품절임박 정규식 변경
   - 기프트포인트 0 → `GIFT_POINT_PATTERN` 정규식 변경 (dt/dd 구조 변경 가능성)
   - Cloudflare 차단 → `IMPERSONATE` 업그레이드 (chrome120 → chrome131)
   - 다중 색상 누락 → `variant_discovery.pattern` 의 `/LEMOUTON/(GRG\d+)/` 확장 (다른 브랜드)

## 🔗 관련 코드 (운영)

| 위치 | 역할 |
|---|---|
| `_시스템/lemouton/sourcing/crawlers/ssf.py` | 단일 파일 크롤러 (~460줄) |

## 📊 검증된 정확도 baseline

**라이브 검증 대기.** 핵심 검증 포인트:
- `point_rate` 가 사이트 표시 "멤버십포인트 X%" 와 일치
- `gift_point_amount` 가 사이트 "기프트포인트 최대 X원" 과 일치
- 다중 색상 GRG 자동 발견 모두 fetch 성공

## ⚠️ 관련 작업 (별도)

- `_시스템/scripts/_ssg_*.py` 9개는 SSG (별개 사이트) — 사용자 active work, 충돌 주의
- LEMOUTON 외 브랜드 SSF 상품 (다른 브랜드들) — variant_discovery.pattern 일반화 필요 시 별도 task
