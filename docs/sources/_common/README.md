# 공용 도구함 (`_common/`)

> 🧰 **현재 거의 비어있음. 의도된 상태입니다.**

## 📐 Rule of Three — 채우는 시점

이 폴더는 **여러 소싱처에서 똑같이 반복되는 패턴**이 발견됐을 때만 채웁니다.

**판단 기준:**
- ❌ "이거 다른 사이트에서도 쓸 것 같아" → `_common/` 에 두지 마세요
- ✅ "이미 2-3개 사이트에서 똑같이 쓰고 있음 (실측)" → 이제 promotion 가능

**왜 이 규칙이 중요한가:**
- 1개 사이트만 보고 만든 패턴은 그 사이트에만 맞음 → 다른 사이트에 강요 시 오히려 제약
- 미리 추측으로 만들면 잘못된 추상화가 모든 사이트로 전파됨 (premature abstraction)
- 진짜 공통 패턴은 2-3번 반복돼야 비로소 보임

## 🎯 향후 들어올 만한 항목 (예측 — 실제 promotion 시점에 검증)

| 카테고리 | 예시 |
|---|---|
| HTTP 클라이언트 | Cloudflare 우회 helper (curl_cffi wrapper) |
| 인증 | storage_state 로드·만료 감지 공통 패턴 |
| 파싱 | 가격 정규식 helper · 옵션 정규화 |
| 정책 | 결제수단 즉시할인 무시 / 적립금 사용 0 강제 (memory `project_benefit_spec.md` 공통 룰) |
| Fail-safe | member_price > base 같은 invariant 검증 (musinsa 패턴 일반화 가능성) |

→ 위 항목들 중 어느 것도 **지금은 만들지 않습니다.** 무신사·SSG·롯데온 3개 방 완성 후 진짜 공통 부분 추출.

## 📂 향후 구조 (예시)

```
_common/
├── README.md            ← (이 파일)
├── http/                ← (Rule of Three 후) 공통 HTTP 패턴
├── auth/                ← (Rule of Three 후) 인증·세션 공통
├── parsers/             ← (Rule of Three 후) 가격·옵션 파싱
└── policies/            ← (Rule of Three 후) 매입가 산식 공통 룰
```
