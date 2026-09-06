# 🗺️ 소싱처별 데이터 수집 지도 — 재고 3상태 · 가격(표면노출가·혜택)

> **목적**: 르무통 메이트(및 전 모음전) 소싱처별로 **재고(품절/실수량/수량미상)·표면노출가·혜택**을
> **어디(API/임베디드JSON/DOM)에서, 어떤 필드로** 수집하는지의 단일 참조표. 다른 세션 인수인계용.
> **작성 근거**: 라이브 실측(르무통·SSF claude-in-chrome 조사) + 크롤러 코드 + 크롤링 가이드.
> **작성일 기준**: 2026-06-25.

---

## 0. 공통 규칙 (전 소싱처)

- **재고 센티넬**: `0` = 품절 / `N` = 실수량 / `999` = 수량 미상("재고있음", 사이트가 정량 비공개) / `null` = 그 소싱처에 없는 조합.
- **가격 공식**: `표면노출가 − 혜택(선반영/차감/적립/결제/캐시백) = 최종매입가`. %혜택은 항상 베이스금액 기준.
- **혜택 조립·누적차감**: `webapp/routes/api_benefits.py` `compute_breakdown`. 공통 산출: `lemouton/pricing/unified.py` `compute_market_price`.
- **무결성 원칙(절대)**: 매칭/크롤 실패 시 **대표가(평균·최저) 폴백 금지** → "가격없음 + 크롤실패"로 표면화. 옛 재고/가격 stale 금지. 표면가 단일진실=`last_price`, 매입가=`compute_market_price`.
- **수집 경로 2종**: ① 서버사이드 크롤러(`crawlers/*.py`, 무로그인) ② 크롬확장 라이브크롤(로그인 브라우저 → `/api/sources/parse` → `/api/sources/crawl-result`). 로그인/ WAF 소싱처는 ②가 단일 경로.

---

## 1. 르무통 공홈 — `lemouton.co.kr` (Cafe24)

| 항목 | 출처 | 비고 |
|---|---|---|
| **데이터 소스** | 페이지 임베디드 JSON `var option_stock_data` (= 브라우저 전역 `EC_SHOP_FRONT_NEW_OPTION_DATA.aItemStockData`) | **별도 XHR API 없음** — 서버가 HTML에 JSON 객체로 심어 보냄. 무로그인 `requests.get`로도 동일 수신(회원가=비회원가). |
| **재고 3상태** | 조합별 `stock_number`(정수). `is_selling=F`→0. `is_display=F` 조합 제외 | **전부 실수량**(수량미상 없음). 미판매 조합은 키 자체가 없어 원천 배제(데카르트곱 날조 없음). |
| **표면노출가** | 조합별 `option_price` → 폴백 `strong.price-number` / `meta[product:sale_price:amount]` | |
| **혜택** | 기본할인 % (정가 vs 판매가). 공홈 회원적립은 미수집(영향 낮음) | |
| **상품명** | `meta[property=og:title]` **(1순위)** → h2 휴리스틱 폴백 | h2 첫 항목 내비 `메인메뉴` 오긁음 버그 → og:title로 근원 수정(2026-06-25). |
| **코드** | `crawlers/lemouton.py` `_parse_option_stock_data` | |

**실측 검증**: 크롤러 ↔ 로그인 브라우저 `aItemStockData` 100% 일치(블랙230=21·블랙270=54·다크네이비290=9·그레이290=3, 가격 116,900).

---

## 2. 스마트스토어 르무통 — `brand.naver.com` / `smartstore.naver.com`

| 항목 | 출처 | 비고 |
|---|---|---|
| **데이터 소스(정확)** | 로그인 브라우저(확장) first-party API `GET /n/v2/channels/{channelUid}/products/{channelProductNo}` | `channelProductNo` = `__PRELOADED_STATE__.simpleProductForDetailPage.A.id`. **per-SKU 재고**. |
| **WAF** | 비로그인 직접 GET 차단 → **확장(로그인 브라우저)만 통과**. `smartstore`→`brand.naver.com` 호스트 swap | claude-in-chrome 브라우저로는 `brand.naver.com` 접속도 안전정책 차단됨(확장 경로로만). |
| **재고 3상태** | per-SKU `sku_stock`/`stockQuantity`. 0=품절 / N=실수량 | ⚠️ 서버 inline `__PRELOADED_STATE__`는 **상품 합계만** 제공 → per-SKU는 n/v2 API 필수. `crawl-result`의 `_persist_option_stocks`가 `current_stock`에 영속해야 매트릭스 반영(2026-06-22 수정). |
| **표면노출가** | `simpleProductForDetailPage.A.benefitsView.discountedSalePrice`(표시 할인가) → 폴백 `salePrice`(정가) | |
| **혜택** | (정책 미정 — 추가 예정) | |
| **코드** | `crawlers/ss_lemouton.py` + `api_pricing.py` `_persist_option_stocks` | 🐛 과거: `productNo` 먼저 쓰면 204 빈응답→999 둔갑. **`A.id` 사용**. |

---

## 3. 무신사 — `musinsa.com`

| 항목 | 출처 | 비고 |
|---|---|---|
| **데이터 소스** | REST API (비로그인 공개), base `https://goods-detail.musinsa.com` | |
| · 메타/가격 | `GET /api2/goods/{goodsNo}` → `goodsPrice.salePrice`, `goodsNm`, `brandName`, `normalPrice` | |
| · 옵션 정의 | `GET /api2/goods/{goodsNo}/options` | |
| · **재고** | `POST /api2/goods/{goodsNo}/options/v2/prioritized-inventories` | |
| **재고 3상태** | `outOfStock=true`→0 / `remainQuantity=N`→N(잔여 N개·N개 남음) / `remainQuantity=None`(표시없음)→999(수량미상=충분) | **무신사는 충분재고 정량 비공개** → 999 정상. 한정수량만 N 노출. |
| **표면노출가** | `goodsPrice.salePrice` | 회원가 ❌(비로그인 노출 salePrice). 정가검산 폐기. |
| **혜택** | 등급적립·무신사머니·등급할인·쿠폰 (dynamic: `member_price`·`grade_reward_amount`·`money_reward_amount`·`grade_discount_amount`·`coupon_amount`·`money_active`) | ⚠️ 라이브 확장크롤이 혜택0 저장하는 결함 이력(별도 확인). |
| **코드** | `crawlers/musinsa.py:36-47, 489-499` | |

---

## 4. SSF샵 — `ssfshop.com` (삼성물산)

| 항목 | 출처 | 비고 |
|---|---|---|
| **데이터 소스(옵션·상태)** | 페이지 임베디드 HTML `#optionDiv1 li a[optcd]` (속성 `optcd`=사이즈, `statcd`=`SALE_PROGRS`/`SLDOUT`, `godno`, 부모 li `data`=아이템코드 `IT…`) | `curl_cffi`(chrome120 impersonate)로 Cloudflare 통과. |
| **진짜 재고 API** | `POST https://www.ssfshop.com/public/goods/selectGodItmOne` (사이즈 선택 시, per-item) → `godItm.totUsefulInvQty`/`safeInvQty`/`salePrearngeQty` | ⚠️ **정상재고 정확수량은 비공개(빈값)**. CSRF/세션 게이트로 서버사이드 직접 호출 어려움. **HTML 방식 대비 정확도 이득 없음**(라이브 실측 결론). |
| **재고 3상태** | `statcd=SLDOUT`→0 / li텍스트 `품절임박 (N)`→N(실수량) / 그 외→999(수량미상) | **SSF가 정상재고 수량 비공개** → 999 정상. 정규식 괄호공백 주의: `품절임박\s*\(\s*(\d+)\s*\)`. |
| **표면노출가** | `em.price`(없으면 `del` 정가) | |
| **혜택** | 기프트포인트(`기프트포인트…N원`), 멤버십포인트(`포인트 적립…멤버십포인트 N P`, sale_price로 나눠 rate 동적), 현대카드 2.73% auto | raw HTML 정규식. dynamic: `gift_point_amount`·`point_rate`. |
| **코드** | `crawlers/ssf.py` | 색상별 별도 GRG코드 URL → 페이지서 `/LEMOUTON/(GRG\d+)/` 자동발견해 통합. |

---

## 5. 롯데온 — `lotteon.com`

| 항목 | 출처 | 비고 |
|---|---|---|
| **데이터 소스** | `pbf.lotteon.com` API 응답(Playwright로 페이지 열고 가로채기) + DOM 폴백 | |
| · 옵션 mapping(색·사이즈·**재고**) | `GET https://pbf.lotteon.com/product/v2/detail/option/mapping/...` | **옵션매핑 경로만 200**, ISOLATED 컨텍스트서도 fetch됨 → 우선. |
| · DOM 폴백 품절 | `div.layer_option li.soldout p.txt_option` | |
| **재고 3상태** | API 옵션매핑=**실수량** / DOM 폴백: 품절→0, else 999(수량미상) | API 우선이면 실수량 확보. |
| **표면노출가** | `max_price`(최대할인가, `data-benefit`) 우선 → `.final span.num`(salePrice) → `.price>span.num` | |
| **혜택** | 롯데멤버 할인율(`lotte_member_discount_rate`), 찜쿠폰(`store_jjim_coupon_amount`), `lotteon_coupons`, L.POINT, 현대카드 2.73% fallback | |
| **코드** | `crawlers/lotteon.py:12-14, 37-64, 482, 1293` | URL: `/p/product/{LO…}?sitmNo={LO…_…}`. 🐛 대체상품 가드 숫자형URL 누출 이력. |

---

## 6. SSG — `ssg.com`

| 항목 | 출처 | 비고 |
|---|---|---|
| **데이터 소스** | 페이지 임베디드 인라인 JS `uitemObj` 블록(SSR `<script>`) | 서버사이드 `requests` 동작. **별도 XHR API 안 씀**(임베디드 JSON). |
| **재고 3상태** | per-option `usablInvQty`(정수). 0=품절 / N=실수량 | **거의 전부 실수량**(수량미상 거의 없음). `uitemId='00000'`(대표단품)은 건너뜀(단, 단일옵션 상품은 00000 사용). |
| **표면노출가** | `bestAmt`(우선) → `sellprc` | |
| **혜택** | SSG MONEY 적립(`ssg_money_rate`, "충전" 포함시 rate≥3%만 활성), `card_benefit_price`, `product_coupon_*`, 현대카드 fallback | ⚠️ 라이브 확장크롤(BG_PARSE)이 SSG MONEY 등 혜택 미갱신 결함 이력(price/stock만 저장). |
| **옵션명** | `optn1`/`type1`(색상), `optn2`/`type2`(사이즈) | |
| **코드** | `crawlers/ssg.py` `_parse_uitem_options:567-630` | |
| **⚠️ 조사 제약** | claude-in-chrome 브라우저 안전정책으로 **`ssg.com` 접속 차단** → 라이브 조사는 **서버 크롤러로만** 가능. | |

**실측 검증(서버 크롤)**: 10개 URL 194옵션 중 **189 실수량·5 품절·999둔갑 0·실패 0**, 가격 119,900.

---

## 7. 정확도 한계 요약 (사이트별 "공개 천장")

| 소싱처 | 정확수량 공개? | 비고 |
|---|---|---|
| 르무통·SSG | ✅ 전부 실수량 | 임베디드 JSON에 정량 포함 |
| 스마트스토어·롯데온 | ✅ 실수량 | per-SKU API / 옵션매핑 API |
| 무신사 | △ 한정수량만 N, 충분재고는 비공개(999) | 사이트 정책 |
| SSF | △ 품절임박 N만, 정상재고 비공개(999) | 사이트 정책. 진짜 API도 정량 비공개 |

> **핵심**: "API로 바꾸면 더 정확"이 항상 참은 아님 — **정확도 천장은 각 사이트가 공개하는 데이터가 결정**.
> 무신사·SSF는 정상재고 정량을 원래 비공개하므로 999(수량미상="재고있음")가 정답이며 가짜 숫자를 만들면 안 됨.
