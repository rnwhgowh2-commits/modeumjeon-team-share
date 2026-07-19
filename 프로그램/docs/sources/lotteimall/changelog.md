# 롯데홈쇼핑 변경기록

---

## 2026-07-18 [M1-6 카드 청구할인 배선 + 'key:' 합성 source_id 혜택 경로 복구] by claude+rnwhgowh2

### 문제 1 — 롯데아이몰·H몰 혜택이 하나도 안 붙었다
- 매트릭스는 레지스트리 미등록 소싱처의 `source_id` 를 정수가 아니라
  **`'key:lotteimall'` / `'key:hmall'` 문자열**로 쓴다(`api_pricing.py:728·1200`).
- `api_benefits.compute_breakdown` 의 `_SITE_BY_SRC` 조회가 `int(source_id)` 라
  ValueError → `_site_for=None` → 그 아래 **동적혜택 폴백 로더가 영영 안 돌았다**.
- 결과: 두 소싱처는 혜택 0건 → 최종매입가 = 표면가. 이미 작성돼 있던
  lotteimall `point_rewards`·hmall `hmall_point_amount` 처리 코드에 **도달조차 못 했다**.

### 문제 2 — M1-5 직후 카드분 8,180원 증발 (중간 상태)
- M1-5 가 표면가를 카드 미적용가로 올려놓고 카드할인 차감은 아직 안 붙인 상태였다.

### 수정
- `_resolve_site_key(source_id)` 신설 — `'key:<source_key>'` 접두를 떼면 그대로
  `SourceProduct.site` 다(저장 경로가 `upsert_source_product(site=bsu.source_key)`,
  `sources/service.py:449`). 정수 경로는 종전 `_SITE_BY_SRC` 그대로 = 무회귀.
- `lotteimall_card_discount` / `_label` → `'{label} 청구할인'` 정액 혜택으로 배선
  (`enabled=True`). **차감 지점은 이 한 곳뿐**(전수 grep 확인).

### 이중차감 안 나는 근거
- `auto_card_discount.included_in_sale_price` 는 M1-5 가 False → `api_pricing.py:626`
  의 "카드 OFF 시 가격 환원"(`price/(1-rate)`)이 no-op.
- 표면가에는 카드분이 안 빠져 있다(`benefitPrc + 카드금액`).
- 테스트가 차감 스텝 **1건 · deduct=8,180 · base_after=108,720** 을 직접 잠근다.

### 검증
- `tests/pricing/test_catalog_source_benefits.py` (10 케이스, 픽스처 전용·라이브 미접속)
  · 116,900 − 8,180 → base_after 108,720 / 헤드라인 108,700(백원 버림)
  · 100,540(이중차감)·116,900(미차감) 둘 다 명시적 실패 조건
  · H몰 기본 비활성 유지 · 정수 source_id 경로 무변경 회귀 가드
- 전체 스위트 결과 집합이 수정 전후 **byte-identical**(2,178 nodeid 동일, 실패 13건 동일).

### 알려진 한계
- '카드 미반영' 토글 미지원 — `CardDiscountUserPref.source_id` 가 Integer 라
  `'key:lotteimall'` 을 담을 수 없다. 토글을 열려면 그 컬럼 확장이 선행돼야 한다.
  (지금 `resolve_card_enabled` 를 물리면 항상 True 를 돌려주는 '작동하는 척하는 토글'.)

---

## 2026-07-18 [표면노출가 = 카드 미적용 할인가로 교정 (H몰 규약 정렬)] by claude+rnwhgowh2

### 문제
- 롯데아이몰 `crawled_price` 에 **최대할인가(카드 청구할인 포함)** 가 담겼다
  (`commonDiscountObj.benefitPrc`). 반면 현대H몰은 표면가 = `bbprc`(카드 미포함)이고
  카드할인은 `hmall_card_discount` 로 분리한다.
  → 두 소싱처가 같은 "표면노출가" 슬롯에 **다른 의미의 값**을 담아 매트릭스 비교 불성립.

### 사용자 확정 (2026-07-18)
- 롯데아이몰 표면노출가 = **카드 미적용 할인가**.
- 실측(르무통 메이트 메리노울 운동화): 정가 149,000 → 표면가 **116,900(22%)**
  → 삼성카드 7% 청구할인 −8,180 → 최대할인가 108,720.

### 수정
- `_resolve_surface_price(soup, html, card)` 신설 — 표면가 단일 진실 원천.
  · 카드 있음 → `benefitPrc + cardDiscountList[0].discountAmount`
    (항등식 근거: 108,720+8,180=116,900 / 문서화된 기존 실측 120,320+6,330=126,650)
  · 카드 없음 → `benefitPrc` → `.price>span.num` → `.final span.num`
  · 복원 불가(금액·benefitPrc 결측) → **RuntimeError** (폴백 금지)
- 카드 청구할인 분리 보관: `lotteimall_card_discount` · `lotteimall_card_label`
  (H몰 패턴). service.py `OPTION_DYNAMIC_KEYS` + benefit_parse.py 화이트리스트 등재.
- `auto_card_discount.included_in_sale_price` : True → **False**.
  ⚠️ 이게 True 로 남으면 `api_pricing.py:626` 의 "카드 OFF 시 환원"(price/(1-rate))이 걸려
  **이미 카드가 빠진 가격을 한 번 더 부풀린다**.
- 롯데온(lotteon.com) 경로는 **무변경** (같은 파일이지만 `_is_lotteon` 도메인 분기 별도).

### 남은 일
- **M1-6**: 분리 보관한 카드할인을 조건부 혜택(사용자 토글)으로 배선.
  그 전까지 카드할인은 매입가에서 차감되지 않는다(표면가만 정확해진 상태).

### 알려진 한계
- `cardDiscountList` 가 없고 `em.txt_em`/`benefitPrcLabelTxt` 만 있는 페이지는
  카드율은 알아도 **금액을 모른다** → 나눗셈 역산은 사이트의 10원 절사 때문에
  원 단위가 어긋나므로 역산하지 않고 **크롤 실패**로 드러낸다.

### 테스트
- `tests/sourcing/test_lotteimall_surface_price.py` (11 케이스, 픽스처 전용·라이브 미접속)

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
