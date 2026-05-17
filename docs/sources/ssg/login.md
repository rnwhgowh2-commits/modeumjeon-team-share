# SSG 로그인 셋업

## 🎯 로그인 필요한가?

**기본은 비로그인** — sale_price (bestAmt), 옵션, 재고 모두 비로그인 SSR HTML 에 노출.

다만 **SSG MONEY 적립률·카드혜택가** 같은 멤버십 한정 항목이 일부 노출 안 될 수 있음.

## 📦 인증 메커니즘

| 방식 | 위치 | 용도 |
|---|---|---|
| **비로그인 (default)** | — | 기본 운영 |
| **profile_dir** | `_시스템/data/profiles/ssg_ditodalal/` | 멤버십 한정 노출 시 |

## 👤 현재 등록된 SSG 계정

`_시스템/data/profiles/ssg_ditodalal` — Playwright 영구 프로필 1개.

`_시스템/data/auth/ssg_ditodalal.json` — storage_state JSON.

## 🛡️ Anti-bot

`curl_cffi chrome120` — 일반 `requests` 사용 시 차단 가능.

## ⚠️ 주의

- ❌ Playwright 프로필 / 쿠키 / 토큰 git commit 금지
- ⚠️ 사용자께서 `_시스템/scripts/_ssg_*.py` 9개 untracked 파일로 active work 중 — 본 방은 docs/code 만 다룸. 충돌 없음
