# 롯데ON 로그인 셋업

## 🎯 로그인 필요한가?

**권장 — 회원 등급에 따라 쿠폰·적립 정확도 차이.** 비로그인도 동작하지만 일부 혜택 미노출 가능.

## 📦 인증 메커니즘

| 방식 | 위치 | 용도 |
|---|---|---|
| **비로그인** | — | 기본 가격·옵션·일반 쿠폰 |
| **profile_dir / 로그인** | `_시스템/data/profiles/lotteon_{계정}/` | 회원 등급별 정확한 쿠폰·적립 |

## 👤 현재 등록된 lotteon 계정

`_시스템/data/profiles/` 안:
- `lotteon_ditodalal` — Playwright 영구 프로필

## 🔧 로그인 셋업 (LotteonScraper)

```python
from lemouton.auth.scrapers.lotteon import LotteonScraper
# 사이트 키: "lotteon"
```

**쿠키 (cookie_checker.py:41 참고):**
- ★ 2026-05-05 디스크 진단 결과: 실 로그인 토큰은 `fo_ac_tkn` / `fo_sso_tkn` / `fo_mno` (모두 session 만료)
- ❌ 기존 ["JSESSIONID","LCKR_SESSION","LO_LOGIN"] 은 lotteon 도메인에 존재 안 함 — false negative

## ⚠️ 주의

- ❌ Playwright 프로필 / 토큰 git commit 금지
- 회원가 표시 차이 작음 — 비로그인 fallback 도 운영 가능
- pbf.lotteon.com API 가 인증 토큰 검증할 가능성 — 로그인 세션 만료 시 빈 응답 가능 → Fail-safe 트리거
