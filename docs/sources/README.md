# 소싱처 방 시스템 (docs/sources/)

> 🚨 **DEV 전용 (운영 미적용)** — 이 폴더의 yaml/md 파일은 **사람이 읽는 명세서**입니다. 운영 크롤러·웹앱·스케줄러는 이 폴더를 import 하거나 읽지 않습니다. 추후 일반화(Phase B) 시 운영 코드가 yaml 로드하도록 리팩토링 예정. **이 폴더 안 내용 수정해도 운영 동작 자동 변경 안 됨.** 운영 변경은 `_시스템/` 의 해당 어댑터 코드 수정 + sync 필요.

## 🎯 목적

각 소싱처별 개발환경·셀렉터·인증·가격 정책·변경 이력을 **한 폴더에 집중**해서:
- 사이트 개편 시 어디 봐야 하는지 즉시 파악
- 새 팀원이 코드 안 읽고도 사이트 이해
- 향후 packages 추출 / yaml-driven 자동화 발판

## 📂 구조

```
docs/sources/
├── README.md             ← (이 파일)
├── _schema.yaml          ← 모든 소싱처 yaml 공통 스키마
├── _common/              ← 🧰 공용 도구함 (현재 거의 비움)
│   └── README.md
└── {site}/               ← 🛏️ 각 소싱처별 "방"
    ├── README.md         ← 방 입구 + 빠른 진단
    ├── profile.yaml      ← 인증·anti-bot·렌더링·API (단일 진실 원천)
    ├── selectors.yaml    ← 페이지 셀렉터
    ├── pricing_policy.yaml  ← 가격 산식·정책 룰
    ├── login.md          ← 로그인 셋업 가이드
    ├── env.example       ← 환경변수 양식
    ├── changelog.md      ← 변경기록 (사이트 개편마다 append)
    └── _debug_*.py       ← 진단·회귀 검증 스크립트 (보존)
```

현재 존재하는 방: `musinsa/` (2026-05-17 최초)

향후 예정: lemouton · ss_lemouton · ssf · ssg · lotteon

## 📐 핵심 원칙 — Rule of Three

**`_common/` 에 무엇을 둘지의 룰:**
- 처음에는 **모든 코드/셀렉터를 `{site}/` 안에만** 두기
- **같은 패턴이 2-3개 사이트에서 반복되는 게 확인된 후에만** `_common/` 으로 promotion
- 절대 미리 추측으로 `_common/` 만들지 않기 (premature abstraction 방지)

## 👥 팀 협업 흐름

이 폴더는 GitHub repo [modeumjeon-team-share](https://github.com/rnwhgowh2-commits/modeumjeon-team-share) 로 팀 공유됩니다.

```
[팀원 A] git pull → docs/sources/{site}/selectors.yaml 수정
                  → docs/sources/{site}/changelog.md 에 "{날짜} {변경 내용} / by A" 추가
                  → git commit + push
[팀원 B] git pull → 자동 반영
```

## 🚀 신규 소싱처 방 만들 때

1. `docs/sources/{site}/` 디렉터리 생성
2. `_schema.yaml` 참고해 7개 파일 생성 (profile/selectors/pricing_policy/login/env.example/changelog/README)
3. 운영 어댑터 코드 (`_시스템/lemouton/sourcing/crawlers/{site}.py`) 의 셀렉터·정책을 yaml 로 추출
4. `_demo_*.py` 작성 → live 상품 1~3개로 정확도 검증
5. `accuracy_baseline.verified_skus` 에 검증 완료 product_id 누적
6. git commit + push

## 🔗 관련 메모리

- [회원가 크롤링 필수 (비로그인 API 의미 없음)](../../../../../.claude/projects/.../project_member_price_required.md)
- [무신사 "쿠폰적용가" 라벨 룰](../../../../../.claude/projects/.../project_musinsa_coupon_applied_label.md)
- [소싱처별 혜택 계산 명세](../../../../../.claude/projects/.../project_benefit_spec.md)
