# 🛏️ 무신사 방 (musinsa)

> 첫 번째 소싱처 방. 다른 사이트 방 만들 때 이 구조를 복제.

## 📂 파일

| 파일 | 역할 |
|---|---|
| **`profile.yaml`** | ⭐ 단일 진실 원천 — 인증·anti-bot·렌더링·API·회원가·Variant 발견 |
| `selectors.yaml` | 페이지 셀렉터 (코드에서 추출, 사람 친화 정리) |
| `pricing_policy.yaml` | 9개 가격 항목 · 누적식 5단계 산식 · 정책 룰 |
| `login.md` | 로그인 셋업 가이드 (수동 1회) |
| `env.example` | 환경변수 양식 |
| `changelog.md` | 변경기록 — 사이트 개편마다 append |
| `_demo_*.py` | 진단·회귀 검증 스크립트 (보존) |

## 🚀 빠른 진단 — "사이트 깨졌어!" 발생 시

1. **`changelog.md` 확인** — 최근 변경 이력 (다른 팀원이 발견한 게 있는지)
2. **`_demo_playwright_smoke.py {URL}` 실행** — 실제 크롤 결과 확인
3. **에러 메시지로 갈래 잡기:**
   - `wrap_found=False` → `[class*="MaxBenefitPrice"]` 셀렉터 변경 (selectors.yaml 참조)
   - `PointDetailWrap 미발견` → 펼침 클릭 selector 변경
   - `member_price > base1` (신규 가드) → base1 산정 오류 (쿠폰 이중차감·sale 추출 오류)
   - `핵심 섹션 미노출` → fail-safe 검증 항목 변경 (등급/후기/무신사머니)
   - `매입가 비율 비정상` → sale_price 산정 오류 또는 정책 변경
4. **`_debug_page_dump_v2.py` 로 page DOM 직접 확인** — BEFORE/AFTER 가격 변동 추적
5. **`_debug_extract_js_direct.py` 로 _EXTRACT_JS raw 결과 확인** — JS 가 무엇을 추출하는지

## 🔗 관련 코드 (운영)

| 위치 | 역할 |
|---|---|
| `_시스템/lemouton/sourcing/crawlers/musinsa.py` | 디스패처 + 비로그인 API fallback (988줄) |
| `_시스템/lemouton/sourcing/crawlers/musinsa_playwright.py` | ⭐ **회원가 운영 크롤러** (Playwright + 9가격항목) |
| `_시스템/config.py` (SOURCING_AUTH) | 운영 설정 (timeout · stock_cap · musinsa_rules) — 현재 코드가 읽는 진짜 source |

→ ⚠️ **현재(Phase A) 코드는 `profile.yaml` 안 읽음.** `config.py` 와 musinsa_playwright.py 안 하드코딩 사용. 추후 Phase B 일반화 시 yaml 로드 도입 예정.

## 📊 검증된 정확도 baseline

오늘(2026-05-17) 사용자 검증 완료:
- `4677240` (필름메이커 패딩) — 203,048원 ✅
- `4046672` (르무통 운동화) — 113,265원 ✅
- `4210142` (시티 레저 팬츠) — 35,890원 ✅

상세는 `profile.yaml` 의 `accuracy_baseline.verified_skus` + `changelog.md` 참조.
