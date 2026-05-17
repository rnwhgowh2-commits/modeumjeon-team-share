# 무신사 로그인 셋업 가이드

## 🎯 왜 로그인 필요한가

운영 매입가 산정 = **회원가 (benefit_price)** 가 필수. 비로그인 API 의 sale_price 는 의미 없음 (memory 룰).
회원가는 LV별 등급할인·등급적립·무신사머니 적립 적용 → 로그인 세션 필수.

## 📦 인증 메커니즘

| 방식 | 위치 | 용도 |
|---|---|---|
| **storage_state JSON** (legacy) | `_시스템/data/auth/musinsa_{계정}.json` | `MusinsaPlaywrightCrawler(account_name="...")` 가 로드 |
| **Playwright user_data_dir** (신규) | `_시스템/data/profiles/musinsa_{계정}/` | `MusinsaPlaywrightCrawler(profile_dir="...")` — 영구 프로필 (자동 재로그인 시도) |

→ 현재 운영은 **storage_state 방식 (account_name)** 이 기본. profile_dir 은 일부 셀러 사이트에서 사용.

## 🔧 1회 수동 로그인 (storage_state 생성)

```bash
cd "C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템"
python -m scripts.musinsa_login
```

→ Chrome 창이 열림 → 무신사 로그인 (ID/PW or 카카오/네이버 SSO)
→ 5분 내 완료 시 자동으로 `data/auth/musinsa_{account}.json` 저장

**대표 크롤 계정** 은 DB `sourcing_accounts` 테이블의 `is_default_for_crawl=1` 로 지정 (`_get_default_musinsa_account()` 가 조회).

## 🔁 세션 만료 대응

**증상:**
- `_demo_playwright_smoke.py` 실행 시 `is_member_price=False` 지속
- `login_marker_present=False`
- `LoginExpiredError: 비로그인 페이지 감지`

**해결:**
1. 위의 `python -m scripts.musinsa_login` 재실행
2. 같은 account_name 으로 storage_state 갱신 → 기존 파일 덮어씀
3. `_demo_playwright_smoke.py` 로 다시 검증

**자동화 (향후):** `auth.state_age_days()` 로 N일 경과 시 알림 → 매니저 수동 재로그인.

## 👤 현재 등록된 무신사 계정 (2026-05-17)

`_시스템/data/profiles/` 에 12개 Playwright 프로필 존재:
- musinsa_rnwhgowh (+ 1, 2, 3, 4)
- musinsa_cdhking00
- musinsa_yangstrong
- musinsa_soyoon1627
- musinsa_whdtn111
- musinsa_topminn12
- musinsa_rossnehd
- musinsa_sukga01

`_시스템/data/auth/` storage_state JSON:
- musinsa_영빈.json (시연·테스트용)

→ 운영 매입가 크롤은 DB 의 `is_default_for_crawl=1` 계정 사용.

## ⚠️ 주의

- ❌ storage_state JSON / Playwright 프로필 **git commit 절대 금지** (쿠키·세션 토큰 노출)
- ❌ `data/auth/` 와 `data/profiles/` 는 `.gitignore` 에 포함되어 있어야 함
- ⚠️ 세션 파일 1개를 여러 PC에서 동시에 쓰면 무신사가 의심·차단 가능성
