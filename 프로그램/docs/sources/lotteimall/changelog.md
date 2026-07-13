# 롯데홈쇼핑 변경기록

---

## 2026-07-13 [재고 3상태 기준을 사이트 JS에 정렬 — '30상한' 오일반화 수정] by claude+rnwhgowh2

### 문제 (사용자 리포트)
- "롯데아이몰 재고 3상태 중 '재고 N개(한정)'를 구분 못한다."

### 근본 원인 (라이브 근거)
- 라이브 상품 페이지(goods 2559329941) JS 원문이 재고 라벨을 정하는 실제 기준:
  `if(optInvQty<=0) '(품절)'` · `else if(optInvQty>500) '(판매중)'` · `else if(optInvQty<5) '(N개 남음)'` · else 라벨없음(충분).
  → 사이트가 "N개 남음(한정)"으로 보는 경계는 **inv_qty<5** 뿐. 5~500은 그냥 '있음/충분'.
- 구 파서 `_lotteimall_disp_qty`는 경계를 **30**으로 잡음(2026-07-03 특정상품 97조합에서 최댓값이 우연히 30이었던 걸 상한으로 오일반화).
  결과: inv_qty 10 같은 '충분' 재고를 "10개 남음"으로 오표기 → 진짜 한정(2개)과 구분 불가.

### 수정
- `_lotteimall_disp_qty`: `<=0`→0(품절) / `0<inv<5`→실수량 N(한정) / `>=5`→999(충분, 프로젝트 표준 센티넬).
- 상수 `_LOTTEIMALL_SUFFICIENT_CAP=30`/`_DISP=50` 폐기 → `_LOTTEIMALL_LIMITED_THRESHOLD=5`.
- 라이브 실데이터 검증: 220·275mm=품절(0), 나머지(inv 5~30)=충분(999). 사이트와 일치.

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

### 라이브 검증 결과 (2026-05-17)
- URL: DB models — goods_no 2559417201 (르무통 클래식2, **비밀특가** 라벨)
- sale_price (base_for_policy) = **99,900원** — 5사이트 중 최저가
- 옵션 36개
- auto_card_discount = null (해당 상품 카드할인 미노출)
- point_rewards = 일반 99P + L.CLUB 499P + **리뷰적립 300/600원** (★ yaml 에 안 적힌 review_label/review_default/review_club 필드 발견 — 추후 yaml 보강 필요)
- ✅ dataBenefit JSON 파싱 정상

### 관련 메모리
- `project_benefit_spec.md` (⑤ 롯데홈쇼핑 항목)

---

(다음 변경 기록은 이 줄 위에 추가)
