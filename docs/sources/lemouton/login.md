# 르무통 공홈 로그인 셋업

## 🎯 로그인 필요한가?

**기본은 비로그인 크롤** — `lemouton.co.kr` 은 회원가 영역을 explicit 표시하지 않으므로 sale_price 가 모든 사용자 동일.

다만 `profile_dir` 모드를 지원하므로 **대표 크롤 계정 셋업 시** 로그인 상태로 크롤 가능 (재고 상태가 회원 한정으로 다를 가능성 대응).

## 📦 인증 메커니즘

| 방식 | 위치 | 용도 |
|---|---|---|
| **비로그인** (default) | — | 기본 크롤. sale_price 만 추출 |
| **profile_dir** | `_시스템/data/profiles/lemouton_{계정}/` | 회원 한정 정보 (필요 시) |

## 🔧 (선택) 로그인 셋업

로그인 크롤이 필요하면 사용자 GUI 로 수동 로그인 → `data/profiles/lemouton_{계정}/` 영구 프로필 생성.

```bash
cd "C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템"
# 향후: python -m scripts.lemouton_login (현재 없음 — 무신사 패턴 따라 생성 가능)
```

→ Playwright launch_persistent_context 가 자동 재로그인 시도.

## 👤 현재 등록된 르무통 계정

`_시스템/data/profiles/` 안 르무통 관련 프로필: **없음** (기본은 비로그인 운영).

## ⚠️ 주의

- ❌ Cafe24 세션 쿠키 git commit 금지 (`.gitignore` 에 `data/profiles/` 포함)
- ⚠️ 자사몰이라 anti-bot 위험 낮음 — 평소 비로그인이 권장
