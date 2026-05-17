# 롯데홈쇼핑 변경기록

---

## 2026-05-17 [방 최초 생성] by claude+rnwhgowh2

### 무엇
- `docs/sources/lotteimall/` 폴더 신설 (다섯 번째 소싱처 방)
- 파일: profile.yaml · selectors.yaml · pricing_policy.yaml · login.md · env.example · README.md · changelog.md · _demo_smoke.py

### 코드 분석 결과 — ⚠️ 특수한 케이스
- 어댑터 파일: `_시스템/lemouton/sourcing/crawlers/lotteon.py` ★ 파일명이 lotteon 이지만 도메인 라우팅으로 3 사이트 처리
- 본 방의 스코프: **lotteimall.com + lottehomeshopping.com + m.lottehomeshopping.com** (V7 호환 SSR HTML)
- 별도 방: docs/sources/lotteon/ — lotteon.com 전용 (Playwright + pbf API, 2026-05-14 신규)
- 클래스: `LotteCrawler` (source_name='lotte' 단일)

### 핵심 특징
- **추출**: SSR HTML + dataBenefit inline JSON 정규식
- **회원가**: 없음 (비회원과 동일 표시)
- **베이스 가격**: max_price (롯데홈쇼핑 최대할인가 — 카드 청구할인 이미 반영) 우선, sale_price fallback
- **혜택 2개만**: 카드 청구 할인 (% , 이미 max_price 에 반영) + 구매 적립 L.POINT (% 적립금, 2-tier)
- **리뷰 적립 없음** (memory ⑤ 명시 — 제외)

### 무신사 vs 르무통 vs SSF vs 롯데홈쇼핑 비교
| 항목 | 무신사 | 르무통 공홈 | SSF | 롯데홈쇼핑 |
|---|---|---|---|---|
| 회원가 | 9가격항목 | 없음 | 없음 | 없음 |
| 리뷰적립 | 후기 500 | 5,000 고정 | 500 | ❌ 없음 |
| 카드 | 무신사머니 자동 차감 | 현대카드 2.73% (별도 차감) | 현대카드 2.73% (별도) | 변동, 이미 max_price 반영 |
| 적립 | LV별 % | 네페 1% | 포인트 변동 | L.POINT 2-tier |
| 도메인 | 1개 | 1개 | 1개 | 3개 (라우팅) |

### 알려진 주의
- 파일명 lotteon.py 헷갈리지 말 것 — 본 방은 lotteimall/lottehomeshopping 만 다룸. lotteon.com 은 별도 방
- auto_card_discount.included_in_sale_price=True → DB compute_breakdown 에서 별도 차감 안 함 (이중차감 방지)
- L.CLUB 회원 적립 (club_point) 사용 여부는 사용자 정책에 따름

### 라이브 검증 대기

### 관련 메모리
- `project_benefit_spec.md` (⑤ 롯데홈쇼핑 항목)

---

(다음 변경 기록은 이 줄 위에 추가)
