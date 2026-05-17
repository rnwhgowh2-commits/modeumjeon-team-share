# 🛏️ SSG 방 (ssg)

> 일곱 번째 (마지막) 소싱처 방. **SSG MONEY 4 패턴 분기** — 가장 복잡한 정책 로직.

## 📂 파일

| 파일 | 역할 |
|---|---|
| **`profile.yaml`** | ⭐ SSG MONEY 4 패턴 + 카드혜택가 + 상품쿠폰 |
| `selectors.yaml` | 인라인 JS uitemObj 정규식 + DOM 셀렉터 + SSG MONEY 패턴 검출 |
| `pricing_policy.yaml` | 2개 혜택 (SSG MONEY 변동 + 카드혜택가 정액 조건부) |
| `login.md` | 비로그인 기본 / profile_dir 선택 |
| `env.example` | 환경변수 양식 |
| `changelog.md` | 변경기록 |
| `_demo_smoke.py` | 라이브 검증 |

## 🚀 빠른 진단

1. **`changelog.md` 확인**
2. **`_demo_smoke.py {URL}` 실행**
3. **에러 메시지로 갈래 잡기:**
   - `[SSG] 옵션 추출 실패` (Fail-safe) → uitemObj 정규식 패턴 변경 (인라인 JS 구조)
   - SSG MONEY 잘못 잡힘 → 4 패턴 검출 로직 점검 (profile.yaml.ssg_money_patterns)
   - 카드혜택가 누락 → `div.mndtl_card_price` 셀렉터 변경
   - 상품쿠폰 누락 → `dl.cdtl_cpn_wrap` 셀렉터 변경
   - 가격 0 → bestAmt/sellprc 인라인 JS 필드명 변경

## 🔗 관련 코드

| 위치 | 역할 |
|---|---|
| `_시스템/lemouton/sourcing/crawlers/ssg.py` | 단일 파일 (~650줄) — 인라인 JS + DOM 혼합 |

⚠️ **사용자 active work**: `_시스템/scripts/_ssg_*.py` 9개 (untracked) — 사용자 진행 중 디버그 스크립트. 본 방은 docs/sources 만 다룸 → 코드 안 건드림 → 충돌 없음

## ⚠️ 핵심 주의 — SSG MONEY 이중차감 방지

```python
if ssg_money_already_applied:    # 패턴 A·C
    base_차감 = 0                # ★ 추가 차감 금지
else:                            # 패턴 B·D
    base_차감 = sale_price × ssg_money_rate
```

**무신사 "쿠폰적용가" 라벨 룰과 유사한 패턴** — 사이트가 이미 적용한 할인을 또 빼면 이중차감 BUG.

## 📊 검증 baseline

라이브 검증 결과는 `changelog.md` 와 `profile.yaml.accuracy_baseline.verified_skus` 참조.
