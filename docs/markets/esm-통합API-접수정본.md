# ESM(옥션·G마켓) 통합 API — 접수 정본

> **계층**: 판매처 API 참조 정본 · **단일 진실 원천**: 본 문서 + `webapp/data/marketplace_api_map.json`
> **출처 3종** (2026-07-20 접수)
> 1. 권한신청서 엑셀 — **API 130개 전수 + 권한 신청 여부** (가장 정확)
> 2. `통합API_가이드_202407.pdf` (38p) — 상태 흐름 · 클레임 규칙 · 제약
> 3. 웹 문서 `https://etapi.gmarket.com` — **호출 제한·조회기간은 여기에만 있다**
>
> 마스터 ID: `rnwhgowh1` / `rnwhgowh2` / `rnwhgowh3` · 회사명 세소 · 요청일 2026-07-20

## 1. 우리 코드가 실제로 호출하는 것 — 8개

| 용도 | 엔드포인트 | 코드 |
|---|---|---|
| 주문조회 | `POST /shipping/v1/Order/RequestOrders` | esm/client.request_orders |
| 판매대금 정산조회 | `POST /account/v1/settle/getsettleorder` | esm/client.request_settlement |
| 사이트상품번호→goodsNo | `GET /item/v1/site-goods/{siteGoodsNo}/goods-no` | esm/products.resolve_goods_no |
| 상품 상세조회 | `GET /item/v1/goods/{goodsNo}` | esm/products.get_goods_detail |
| 옵션 조회 | `GET /item/v1/goods/{goodsNo}/recommended-options` | esm/products.get_recommended_options |
| 가격 수정 | `PUT /item/v1/goods/{goodsNo}/price` | esm/prices.update_price |
| 재고 수정 | `PUT /item/v1/goods/{goodsNo}/stock` | esm/inventory.update_stock |
| 배송비 정산조회 | `POST /account/v1/settle/getsettledeliveryfee` | 경로만 정의 · 호출 없음 |

## 2. 🔴 주문이 새는 구멍 — 미배선 조회 API 5개

`RequestOrders` 는 **클레임 주문을 반환하지 않는다**(공식문서 원문: 「클레임(취소, 반품, 교환, 미수령신고) 주문은 조회되지 않습니다」).
아래를 붙여야 다른 4개 마켓과 집계 기준이 같아진다. 그전까지 옥션·G마켓은 라이브 검증이 차단된다(`accounts._ESM_CLAIM_WIRED`).

| 지금 빠지는 주문 | 필요한 API |
|---|---|
| 입금확인중 (무통장 입금대기) | `POST /shipping/v1/Order/PreRequestOrders` |
| 취소요청 · 취소중 · 취소완료 · 취소철회 · CS직권취소 · 옥션송금후취소 | `POST /claim/v1/sa/Cancels` |
| 반품신청 · 반품처리중 · 반품완료 · 반품철회 | `POST /claim/v1/sa/Returns` |
| 교환요청 · 교환수거완료 · 교환보류 · 교환완료 · 교환철회 | `POST /claim/v1/sa/Exchanges` |
| 미수령신고 | `POST /shipping/v1/Delivery/ClaimList` |

## 3. 호출 제한 · 조회 기간 (웹 문서에만 있음)

- **주문조회는 5초당 1회.** 단 주문번호로 조회하면 제한 없음 — `etapi.gmarket.com/67`
- 실측(2026-07-20): 이 제한은 **판매자 계정별**이다. 다른 계정끼리는 1.5초 간격 연속 호출도 통과 → **계정 병렬 조회 가능**
- 조회 기간 상한: **G마켓 31일 / 옥션 180일** — `etapi.gmarket.com/67`
  (우리 코드 `esm/orders.py._MAX_WINDOW_DAYS` 는 둘 다 31일 → 옥션은 호출 수를 6분의 1로 줄일 여지)
- PDF에는 호출 제한·조회 기간 문구가 **없다**. 웹 문서가 유일한 출처.

## 4. 인증 (PDF p3~p4)

```
Header  {"typ":"JWT", "alg":"HS256", "kid":"<마스터ID>"}
Payload {"sub":"sell", "aud":"sa.esmplus.com", "iss":"<발행자 도메인>",
         "ssi":"A:<옥션 판매자ID>"}      // 옥션 단독
         "ssi":"G:<G마켓 판매자ID>"}     // G마켓 단독
         "ssi":"A:<옥션ID>, G:<G마켓ID>"} // 동시 토큰(한 토큰으로 양쪽)
전송     Authorization: Bearer {JWT}
```

- 권한 없는 API 호출 시: `{"status":{"message":"The user does not have right access to the api","status_code":401}}`
- PDF 샘플의 `iss` 는 `www.cafe24.com`(셀링툴 업체 도메인 예시). 우리는 `www.esmplus.com` 사용 중이며 6개 계정 전부 연결 성공 — `iss` 는 엄격 검증되지 않는 것으로 보인다(추정, 근거 미확보).

## 5. 주문 상태 흐름 (PDF p26)

숫자 코드표는 PDF에 없고 한글 상태명으로만 기재돼 있다.

| 처리 | G마켓 | 옥션 | 주체 / API |
|---|---|---|---|
| 무통장구매 | 입금대기 | 입금확인중 | 구매자 / PreRequestOrders |
| 결제완료 | 결제완료 | 결제완료 | System / RequestOrders |
| 주문확인 | 배송준비중 | 배송준비중 | 판매자 / OrderCheck |
| 발송예정일(선택) | 배송지연 | 배송지연 | 판매자 / ShippingExpectedDate |
| 발송처리 | 배송시작 | 배송시작 | 판매자 / ShippingInfo |
| 송장 트래킹 | 배송중 | 배송중 | System |
| 배송완료 | 배송완료 | 배송완료 | System / AddShippingCompleteInfo |
| 구매결정 | 배송완료 | 거래완료 | 구매자 수취확인 또는 자동 |

## 6. ⚠️ 몰라서 사고 나는 제약 (PDF)

- 상품 등록 직후 수정 API 호출 불가 — 2~3분 뒤에 호출. 바로 부르면 「상품 정보가 부정확합니다」 에러 — *p19*
- 일괄수정 시 한쪽 사이트에만 상품이 있으면 **나머지 사이트에 새 상품이 생성**된다 — *p19*
- 장바구니(결제)번호 ≠ 주문번호. **상품 옵션 단위로 주문번호가 따로 부여**되므로 주문 처리·확인은 반드시 주문번호 단위로 — *p25*
- 옵션 수정은 To-Be 전체 스냅샷 방식 — 등록된 옵션을 **전부 포함**해 보내야 한다. 전 옵션 품절·미노출 처리는 불가(상품 판매중지로 처리) — *p15·p20*
- 판매기간은 수정 시 **덮어쓰기가 아니라 추가** (90+30 = 잔여 120일) — *p13*
- 가격은 1원 단위 불가 — 10원 ~ 10억원 미만. 판매자할인 정률은 1~70%, **G마켓 원단위 절상 / 옥션 원단위 절삭** — *p13*
- 검색용 상품명은 등록 후 수정 불가 (주문 없거나 등록 10일 이내만 예외) — *p13*
- 재고 최대 99,999 · 이미지 최소 600x600(권장 1000x1000) 최대 14장 — *p13*
- 결제완료 상태에서는 구매자가 주소를 바꿀 수 있다 — 조회 후 변경 여부 재확인 필요 — *p27*
- 발송예정일 등록은 **1회만** 가능. 발송마감일은 주문조회의 TransDueDate — *p28*
- 반품/교환 배송비는 **편도 기준**으로 입력 — *p18*
- G마켓 자동취소 = 발송마감일 익일부터 +19영업일 / 옥션 = 결제일 +90일 — *p29*
- G마켓은 구매결정 상태여도 배송완료 +7일까지 반품·교환 가능(전소법) — *p32·p35*
- 미수령신고 상태 주문은 **송금 대상에서 제외**된다 — *p36*
- URL 대소문자 혼용 주의 — 조회는 `/Cancels`(복수), 승인·판매취소는 `/Cancel/`(단수). 전환 API만 `{orderno}` 소문자 — *p24*

## 7. 전체 API 130개 (권한신청서 원본 그대로)

권한 ✅ = 신청함(126개) · ⛔ = 미신청(4개)

| 메뉴 | 구분 | API명 | 세부 | Method | URL | 권한 |
|---|---|---|---|---|---|---|
| 상품API | 카테고리/브랜드 조회 API | 지마켓/옥션 카테고리 조회 API | 대분류 전체 조회 API | GET | `https://sa2.esmplus.com/item/v1/categories/site-cats` | ✅ |
| 상품API | 카테고리/브랜드 조회 API | 지마켓/옥션 카테고리 조회 API | 하위 카테고리 개별 조회 API | GET | `https://sa2.esmplus.com/item/v1/categories/site-cats/{siteCatCode}` | ✅ |
| 상품API | 카테고리/브랜드 조회 API | ESM 카테고리 조회 API | 대분류 전체 조회 API | GET | `https://sa2.esmplus.com/item/v1/categories/sd-cats/0` | ✅ |
| 상품API | 카테고리/브랜드 조회 API | ESM 카테고리 조회 API | 하위 카테고리 개별 조회 API | GET | `https://sa2.esmplus.com/item/v1/categories/sd-cats/{sdCatCode}` | ✅ |
| 상품API | 카테고리/브랜드 조회 API | Site-ESM 카테고리매칭 조회 API | 전체 사이트 카테고리 조회 API | GET | `https://sa2.esmplus.com/item/v1/categories/sd-cats/{sdCatCode}/site-cats/full-depth` | ✅ |
| 상품API | 카테고리/브랜드 조회 API | Site-ESM 카테고리매칭 조회 API | 최하위 사이트 카테고리 조회 API | GET | `https://sa2.esmplus.com/item/v1/categories/sd-cats/{sdCatCode}/site-cats` | ✅ |
| 상품API | 카테고리/브랜드 조회 API | 브랜드코드 조회 API | 브랜드명으로 조회 API | GET | `https://sa2.esmplus.com/item/v1/catalogs/brands/{brandName}` | ✅ |
| 상품API | 카테고리/브랜드 조회 API | 브랜드코드 조회 API | 제조사명으로 조회 API | GET | `https://sa2.esmplus.com/item/v1/catalogs/makers/{makerName}` | ✅ |
| 상품API | 카테고리/브랜드 조회 API | 미니샵 카테고리 조회 API | 미니샵 카테고리 코드 전체 조회 API | GET | `https://sa2.esmplus.com/item/v1/categories/shop-cats` | ✅ |
| 상품API | 카테고리/브랜드 조회 API | 미니샵 카테고리 조회 API | 미니샵 카테고리 코드 조회 API | GET | `https://sa2.esmplus.com/item/v1/categories/shop-cats/{shopCatCode}` | ✅ |
| 상품API | 배송템플릿 관리 API | 판매자주소록 관리 API | 판매자주소록 등록 API | POST | `https://sa2.esmplus.com/item/v1/sellers/address` | ✅ |
| 상품API | 배송템플릿 관리 API | 판매자주소록 관리 API | 판매자주소록 수정 API | PUT | `https://sa2.esmplus.com/item/v1/sellers/address/{addrNo}` | ✅ |
| 상품API | 배송템플릿 관리 API | 판매자주소록 관리 API | 판매자주소록 조회 API | GET | `https://sa2.esmplus.com/item/v1/sellers/address/{addrNo}` | ✅ |
| 상품API | 배송템플릿 관리 API | 판매자주소록 관리 API | 판매자주소록 전체 조회 API | GET | `https://sa2.esmplus.com/item/v1/sellers/addresses` | ✅ |
| 상품API | 배송템플릿 관리 API | 출하지관리 API | 출하지 등록 API | POST | `https://sa2.esmplus.com/item/v1/shipping/places` | ✅ |
| 상품API | 배송템플릿 관리 API | 출하지관리 API | 출하지 수정 API | PUT | `https://sa2.esmplus.com/item/v1/shipping/places/{placeNo}` | ✅ |
| 상품API | 배송템플릿 관리 API | 출하지관리 API | 출하지 개별 조회 API | GET | `https://sa2.esmplus.com/item/v1/shipping/places/{placeNo}` | ✅ |
| 상품API | 배송템플릿 관리 API | 출하지관리 API | 출하지 전체 조회 API | GET | `https://sa2.esmplus.com/item/v1/shipping/places?pageSize={pageSize}&pageIndex={pageIndex}` | ✅ |
| 상품API | 배송템플릿 관리 API | 출하지관리 API | 출하지 주소별 조회 API | GET | `https://sa2.esmplus.com/item/v1/shipping/places?addrNo={addrNo}` | ✅ |
| 상품API | 배송템플릿 관리 API | 묶음배송비관리 API | 묶음배송비 정책 등록 API | POST | `https://sa2.esmplus.com/item/v1/shipping/policies` | ✅ |
| 상품API | 배송템플릿 관리 API | 묶음배송비관리 API | 묶음배송비 정책 수정 API | PUT | `https://sa2.esmplus.com/item/v1/shipping/policies/{policyNo}` | ✅ |
| 상품API | 배송템플릿 관리 API | 묶음배송비관리 API | 출하지기준 묶음배송비 정책 조회 API | GET | `https://sa2.esmplus.com/item/v1/shipping/places/{placeNo}/policies` | ✅ |
| 상품API | 배송템플릿 관리 API | 발송 정책 관리 API | 발송 정책 등록 API | POST | `https://sa2.esmplus.com/item/v1/shipping/dispatch-policies` | ✅ |
| 상품API | 배송템플릿 관리 API | 발송 정책 관리 API | 기본 발송 정책 설정 API | POST | `https://sa2.esmplus.com/item/v1/shipping/dispatch-policies/{dispatchPolicyNo}/default` | ✅ |
| 상품API | 배송템플릿 관리 API | 발송 정책 관리 API | 정책번호별 조회 API | GET | `https://sa2.esmplus.com/item/v1/shipping/dispatch-policies/{dispatchPolicyNo}` | ✅ |
| 상품API | 배송템플릿 관리 API | 발송 정책 관리 API | 발송정책 전체 조회 API | GET | `https://sa2.esmplus.com/item/v1/shipping/dispatch-policies` | ✅ |
| 상품API | 상품관리 API | 상품등록/수정/전환/조회 API | 상품 등록 API | POST | `https://sa2.esmplus.com/item/v1/goods` | ✅ |
| 상품API | 상품관리 API | 상품등록/수정/전환/조회 API | 상품 수정 API | PUT | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}` | ✅ |
| 상품API | 상품관리 API | 상품등록/수정/전환/조회 API | 상품 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}` | ✅ |
| 상품API | 상품관리 API | 상품등록/수정/전환/조회 API | 상품 전환 API | POST | `https://sa2.esmplus.com/item/v1/goods/convert-legacy-goods` | ✅ |
| 상품API | 상품관리 API | 상품번호 조회 API | 마스터 상품번호 기준 Site 상품번호 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/status` | ✅ |
| 상품API | 상품관리 API | 상품번호 조회 API | Site상품번호 기준 마스터상품번호 조회 API | GET | `https://sa2.esmplus.com/item/v1/site-goods/{siteGoodsNo}/goods-no` | ✅ |
| 상품API | 상품관리 API | 상품 목록 조회 API | - | GET | `https://sa2.esmplus.com/item/v1/goods/search` | ✅ |
| 상품API | 상품관리 API | 상품삭제 API | - | DELETE | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}` | ✅ |
| 상품API | 상품관리 API | 원산지 리스트 조회 API | - | GET | `https://sa2.esmplus.com/item/v1/origin/codes` | ✅ |
| 상품API | 상품관리 API | 고시 정보 조회 API | 고시 상품군 조회 | GET | `https://sa2.esmplus.com/item/v1/official-notice/groups` | ✅ |
| 상품API | 상품관리 API | 고시 정보 조회 API | 상품군별 리스트 조회 | GET | `https://sa2.esmplus.com/item/v1/official-notice/groups/{officialNoticeNo}/codes` | ✅ |
| 상품API | 상품관리 기능별 API | 가격/재고/판매상태 수정 API | 가격/재고/판매상태 수정 API | PUT | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/sell-status` | ✅ |
| 상품API | 상품관리 기능별 API | 가격/재고/판매상태 수정 API | 가격/재고/판매상태 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/sell-status` | ✅ |
| 상품API | 상품관리 기능별 API | 가격 수정 API | 수정 API | PUT | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/price` | ✅ |
| 상품API | 상품관리 기능별 API | 가격 수정 API | 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/price` | ✅ |
| 상품API | 상품관리 기능별 API | 재고 수정 API | - | PUT | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/stock` | ✅ |
| 상품API | 상품관리 기능별 API | 상품명 수정 API | - | PUT | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/goods-name` | ✅ |
| 상품API | 상품관리 기능별 API | 이미지 수정 API | - | POST | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/images` | ✅ |
| 상품API | 상품관리 기능별 API | 상세설명 수정 API | - | POST | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/descriptions` | ✅ |
| 상품API | 상품관리 기능별 API | 최소구매수량 API | 등록/수정 API | POST | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/minBuyableQuantity` | ✅ |
| 상품API | 상품관리 기능별 API | 최소구매수량 API | 해제 API | DELETE | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/minBuyableQuantity` | ✅ |
| 상품API | 상품관리 기능별 API | 최소구매수량 API | 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/minBuyableQuantity` | ✅ |
| 상품API | 옵션/추가구성 관리 API | 추천옵션 관리 API | 옵션 등록/수정 API | PUT | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/recommended-options` | ✅ |
| 상품API | 옵션/추가구성 관리 API | 추천옵션 관리 API | 등록한 옵션 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/recommended-options` | ✅ |
| 상품API | 옵션/추가구성 관리 API | 추천옵션 항목 조회 API | 카테고리별 추천옵션 코드 조회 API | GET | `https://sa2.esmplus.com/item/v1/options/recommended-opts?catCode={siteCatCode}` | ✅ |
| 상품API | 옵션/추가구성 관리 API | 추천옵션 항목 조회 API | 추천옵션별 선택항목 조회 API | GET | `https://sa2.esmplus.com/item/v1/options/recommended-opts/{recommendedOptNo}` | ✅ |
| 상품API | 옵션/추가구성 관리 API | 사이트 카테고리별 등록 옵션 정보 조회 API | - | GET | `https://sa2.esmplus.com/item/v1/goods/option-policies?siteId={siteId}&siteCatCode={siteCatCode}` | ✅ |
| 상품API | 옵션/추가구성 관리 API | 추가구성 항목 조회 API | - | GET | `https://sa2.esmplus.com/item/v1/addon-service/{sdCatCode}` | ✅ |
| 상품API | 고객혜택/광고 API | 판매자할인 관리 API | 판매자할인 등록/수정 API | POST | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/seller-discounts` | ✅ |
| 상품API | 고객혜택/광고 API | 판매자할인 관리 API | 판매자할인 해제 API | DELETE | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/seller-discounts` | ✅ |
| 상품API | 고객혜택/광고 API | 판매자할인 관리 API | 판매자할인 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/seller-discounts` | ✅ |
| 상품API | 고객혜택/광고 API | 판매자지급 스마일캐시 API | 등록 API | POST | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/cashback` | ✅ |
| 상품API | 고객혜택/광고 API | 판매자지급 스마일캐시 API | 수정 API | PUT | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/cashback` | ✅ |
| 상품API | 고객혜택/광고 API | 판매자지급 스마일캐시 API | 해제 API | DELETE | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/cashback` | ✅ |
| 상품API | 고객혜택/광고 API | 판매자지급 스마일캐시 API | 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/cashback` | ✅ |
| 상품API | 고객혜택/광고 API | 리스팅부가서비스 API | 등록/수정 API | PUT | `https://sa2.esmplus.com/item/v1/advertising/listing` | ✅ |
| 상품API | 고객혜택/광고 API | 후원/나눔쇼핑 API | 등록 API | POST | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/sponsorship` | ⛔ |
| 상품API | 고객혜택/광고 API | 후원/나눔쇼핑 API | 수정 API | PUT | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/sponsorship` | ⛔ |
| 상품API | 고객혜택/광고 API | 후원/나눔쇼핑 API | 해제 API | DELETE | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/sponsorship` | ⛔ |
| 상품API | 고객혜택/광고 API | 후원/나눔쇼핑 API | 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/sponsorship` | ⛔ |
| 상품API | 고객혜택/광고 API | 옥션 복수 할인 API | 등록/수정 API | POST | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/special-discount` | ✅ |
| 상품API | 고객혜택/광고 API | 옥션 복수 할인 API | 해제 API | DELETE | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/special-discount` | ✅ |
| 상품API | 고객혜택/광고 API | 옥션 복수 할인 API | 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/special-discount` | ✅ |
| 상품API | 고객혜택/광고 API | 지마켓 복수구매할인 API | 등록/수정 API | POST | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/multiple-purchase-discount` | ✅ |
| 상품API | 고객혜택/광고 API | 지마켓 복수구매할인 API | 해제 API | DELETE | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/multiple-purchase-discount` | ✅ |
| 상품API | 고객혜택/광고 API | 지마켓 복수구매할인 API | 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/multiple-purchase-discount` | ✅ |
| 상품API | 고객혜택/광고 API | 덤 API | 덤 등록 API | POST | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/bonus` | ✅ |
| 상품API | 고객혜택/광고 API | 덤 API | 덤 수정 API | PUT | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/bonus` | ✅ |
| 상품API | 고객혜택/광고 API | 덤 API | 덤 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/bonus` | ✅ |
| 상품API | 고객혜택/광고 API | 덤 API | 덤 삭제 API | DELETE | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/bonus` | ✅ |
| 상품API | 고객혜택/광고 API | 사은품 API | 사은품 등록 API | POST | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/free-gift` | ✅ |
| 상품API | 고객혜택/광고 API | 사은품 API | 사은품 수정 API | PUT | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/free-gift` | ✅ |
| 상품API | 고객혜택/광고 API | 사은품 API | 사은품 조회 API | GET | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/free-gift` | ✅ |
| 상품API | 고객혜택/광고 API | 사은품 API | 사은품 삭제 API | DELETE | `https://sa2.esmplus.com/item/v1/goods/{goodsNo}/customer-benefit/free-gift` | ✅ |
| 상품API | 그룹관리 API | 그룹생성/수정/삭제 API | 그룹 생성 API | POST | `https://sa2.esmplus.com/item/v1/groups` | ✅ |
| 상품API | 그룹관리 API | 그룹생성/수정/삭제 API | 그룹 수정 API | PUT | `https://sa2.esmplus.com/item/v1/groups/{groupNo}` | ✅ |
| 상품API | 그룹관리 API | 그룹생성/수정/삭제 API | 그룹상품 개별등록 API | PUT | `https://sa2.esmplus.com/item/v1/groups/{groupNo}/goods/{goodsNo}` | ✅ |
| 상품API | 그룹관리 API | 그룹생성/수정/삭제 API | 그룹상품 복수등록 API | PUT | `https://sa2.esmplus.com/item/v1/groups/{groupNo}/goods` | ✅ |
| 상품API | 그룹관리 API | 그룹생성/수정/삭제 API | 그룹 삭제 API | DELETE | `https://sa2.esmplus.com/item/v1/groups/{groupNo}` | ✅ |
| 상품API | 그룹관리 API | 그룹정보조회 API | 판매자 전체그룹 조회 API | GET | `https://sa2.esmplus.com/item/v1/groups` | ✅ |
| 상품API | 그룹관리 API | 그룹정보조회 API | 그룹별 조회 API | GET | `https://sa2.esmplus.com/item/v1/groups/{groupNo}` | ✅ |
| 상품API | 그룹관리 API | 그룹정보조회 API | 그룹상품조회 API | GET | `https://sa2.esmplus.com/item/v1/groups/{groupNo}/goods` | ✅ |
| 상품API | 이벤트 홍보 관리 API | 이벤트 홍보 등록/수정/삭제 API | 이벤트 홍보 등록 API | POST | `https://sa2.esmplus.com/item/v1/event-promotions` | ✅ |
| 상품API | 이벤트 홍보 관리 API | 이벤트 홍보 등록/수정/삭제 API | 이벤트 홍보 수정 API | PUT | `https://sa2.esmplus.com/item/v1/event-promotions/{promotionNo}` | ✅ |
| 상품API | 이벤트 홍보 관리 API | 이벤트 홍보 등록/수정/삭제 API | 이벤트 홍보 조회 API | GET | `https://sa2.esmplus.com/item/v1/event-promotions/{promotionNo}` | ✅ |
| 상품API | 이벤트 홍보 관리 API | 이벤트 홍보 등록/수정/삭제 API | 이벤트 홍보 삭제 API | DELETE | `https://sa2.esmplus.com/item/v1/event-promotions/{promotionNo}` | ✅ |
| 상품API | 이벤트 홍보 관리 API | 이벤트 홍보별 상품 등록/수정/삭제 API | 이벤트 홍보별 상품 등록/수정 API | POST | `https://sa2.esmplus.com/item/v1/event-promotions/{promotionNo}/goods` | ✅ |
| 상품API | 이벤트 홍보 관리 API | 이벤트 홍보별 상품 등록/수정/삭제 API | 이벤트 홍보별 상품 조회 API | GET | `https://sa2.esmplus.com/item/v1/event-promotions/{promotionNo}/goods` | ✅ |
| 상품API | 이벤트 홍보 관리 API | 이벤트 홍보별 상품 등록/수정/삭제 API | 이벤트 홍보별 상품 삭제 API | DELETE | `https://sa2.esmplus.com/item/v1/event-promotions/{promotionNo}/goods` | ✅ |
| 상품API | 이벤트 홍보 관리 API | 이벤트 홍보별 상품 등록/수정/삭제 API | 이벤트 홍보별 상품기준 조회 API | GET | `https://sa2.esmplus.com/item/v1/event-promotions/goods/{siteGoodsNo}` | ✅ |
| 주문/배송API | 주문 관리 API | 입금확인중 주문조회 API | - | POST | `https://sa2.esmplus.com/shipping/v1/Order/PreRequestOrders` | ✅ |
| 주문/배송API | 주문 관리 API | 주문조회 API | - | POST | `https://sa2.esmplus.com/shipping/v1/Order/RequestOrders` | ✅ |
| 주문/배송API | 주문 관리 API | 주문확인 API | - | POST | `https://sa2.esmplus.com/shipping/v1/Order/OrderCheck/{OrderNo}` | ✅ |
| 주문/배송API | 주문 관리 API | 주문상태조회 API | - | POST | `https://sa2.esmplus.com/shipping/v1/Delivery/GetDeliveryStatus` | ✅ |
| 주문/배송API | 배송 관리 API | 발송예정일 등록 API | - | POST | `https://sa2.esmplus.com/shipping/v1/Order/ShippingExpectedDate` | ✅ |
| 주문/배송API | 배송 관리 API | 발송처리 API | - | POST | `https://sa2.esmplus.com/shipping/v1/Delivery/ShippingInfo` | ✅ |
| 주문/배송API | 배송 관리 API | 배송 진행 정보 조회 API | - | POST | `https://sa2.esmplus.com/shipping/v1/Delivery/Progress` | ✅ |
| 클레임 API | 취소 관리 API | 취소조회 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/Cancels` | ✅ |
| 클레임 API | 취소 관리 API | 취소승인 API | - | PUT | `https://sa2.esmplus.com/claim/v1/sa/Cancel/{OrderNo}` | ✅ |
| 클레임 API | 취소 관리 API | 판매취소 API | 일반 API | POST | `https://sa2.esmplus.com/claim/v1/sa/Cancel/{OrderNo}/SoldOut` | ✅ |
| 클레임 API | 취소 관리 API | 옥션 거래완료 후 환불 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/Cancel/{orderNo}/AfterRemittanceBySeller` | ✅ |
| 클레임 API | 반품 관리 API | 반품조회 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/Returns` | ✅ |
| 클레임 API | 반품 관리 API | 반품승인 API | - | PUT | `https://sa2.esmplus.com/claim/v1/sa/return/{orderNo}` | ✅ |
| 클레임 API | 반품 관리 API | 판매자 직접 반품 신청 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/Return/{orderNo}/Request` | ✅ |
| 클레임 API | 반품 관리 API | 반품수거 송장등록 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/return/{orderNo}/pickup` | ✅ |
| 클레임 API | 반품 관리 API | 반품보류 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/return/{orderNo}/hold` | ✅ |
| 클레임 API | 반품 관리 API | 반품건 교환전환 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/return/{orderno}/exchange` | ✅ |
| 클레임 API | 교환 관리 API | 교환조회 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/Exchanges` | ✅ |
| 클레임 API | 교환 관리 API | 교환수거 송장등록 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/exchange/{orderNo}/pickup` | ✅ |
| 클레임 API | 교환 관리 API | 교환 수거 완료 처리 API | - | PUT | `https://sa2.esmplus.com/claim/v1/sa/exchange/{orderNo}/pickup` | ✅ |
| 클레임 API | 교환 관리 API | 교환재발송 송장등록 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/exchange/{orderNo}/resend` | ✅ |
| 클레임 API | 교환 관리 API | 교환재발송 배송완료 API | - | PUT | `https://sa2.esmplus.com/claim/v1/sa/exchange/{orderNo}/resend` | ✅ |
| 클레임 API | 교환 관리 API | 교환보류 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/exchange/{orderNo}/hold` | ✅ |
| 클레임 API | 교환 관리 API | 교환보류 해제 API | - | DELETE | `https://sa2.esmplus.com/claim/v1/sa/exchange/{orderNo}/hold` | ✅ |
| 클레임 API | 교환 관리 API | 교환건 반품전환 API | - | POST | `https://sa2.esmplus.com/claim/v1/sa/exchange/{orderno}/return` | ✅ |
| 클레임 API | 미수령 관리 API | 미수령신고 조회 API | - | POST | `https://sa2.esmplus.com/shipping/v1/Delivery/ClaimList` | ✅ |
| 클레임 API | 미수령 관리 API | 미수령신고 철회요청 API | - | POST | `https://sa2.esmplus.com/shipping/v1/Delivery/ClaimRelease` | ✅ |
| 정산조회 API | 판매대금 정산조회 API | - | - | POST | `https://sa2.esmplus.com/account/v1/settle/getsettleorder` | ✅ |
| 정산조회 API | 배송비 정산조회 API | - | - | POST | `https://sa2.esmplus.com/account/v1/settle/getsettledeliveryfee` | ✅ |
| CS API | ESM 공지사항 API | - | - | POST | `https://sa2.esmplus.com/item/v1/communications/notices` | ✅ |
| CS API | 긴급알리미 조회 API | - | - | POST | `https://sa2.esmplus.com/assist/v1/Selling/GetEmergencyInformList` | ✅ |
| CS API | 긴급알리미 답변 API | - | - | POST | `https://sa2.esmplus.com/assist/v1/Selling/AddEmergencyInformReply` | ✅ |
| CS API | 판매자문의 조회 API | - | - | POST | `https://sa2.esmplus.com/item/v1/communications/customer/bulletin-board` | ✅ |
| CS API | 판매자문의 답변 API | - | - | POST | `https://sa2.esmplus.com/item/v1/communications/customer/bulletin-board/qna` | ✅ |

## 8. 라이브 실측으로 확정된 함정 (2026-07-20~21)

문서에 없거나 문서와 다른 것만. 전부 실제 계정·실제 주문으로 재현·수정 완료.

| # | 함정 | 실증 | 대응(코드) |
|---|---|---|---|
| 1 | **취소조회만 G마켓 SiteType=3** (반품·교환·입금확인중은 2) | 2로 보내면 에러 없이 0건 | `esm/claims._SITE` |
| 2 | 클레임 기간 "7일 이하"인데 **정확히 7일도 거부**(2000) | 라이브 2000 응답 | 6일 분할 |
| 3 | **EndDate 는 그날 00:00 로 해석** — 오늘 낮 처리 건이 빠짐 | 07-21 15:01 취소가 EndDate=07-21 조회 0건 | EndDate 하루 올림 |
| 4 | 목록조회는 **신청일(Type2)+완료일(Type3) 병행** 필요 | 완료일만 최근인 건이 신청일 조회에서 샘 | `_CLAIM_TYPES=(2,3)` |
| 5 | 입금확인중(PreRequestOrders)은 주문조회와 **5초/1회 버킷 공유** | 연속 호출 시 3000 | `is_order=True` |
| 6 | 클레임 응답에 **페이징·TotalCount 없음** → 잘려도 모름 | wrapper = ResultCode·Message·BizRuleCode 뿐 | 50건↑이면 기간 반분 재조회 |
| 7 | 클레임 응답에 **상품명·단가·수량 없음**, GoodsNo=0 | 프로브 실측 | SiteGoodsNo→상품API로 이름만(가격은 현재가라 금지) |
| 8 | 클레임 주문은 **RequestOrders 로 상세 재조회 불가**(3가지 요청 모양 모두 0건) | 주문일+기간/번호만/결제일+기간 전부 0건 | 상품API 경로 사용 |
| 9 | 상품번호 변환(resolve) 실패 시 **입력을 그대로 반환하는 폴백** → 404 로 위장 | F575628540 사례 | 같은 값이면 '변환 안 됨' 판정 |
| 10 | 삭제된 상품은 매핑 API 가 400 + `{"message":"삭제된 상품 입니다."}` — **본문에 이유가 있다** | raise_for_status 가 본문을 버리고 있었음 | 본문 message 를 표면화 |
| 11 | 주문내역 기준일 = **고객 발주일(OrderDate)** — 클레임도 주문일로 필터(사장님 확정) | 주문 07-09·취소 최근 건이 섞였었음 | `_esm_daystr` 필터 |
| 12 | 5초/1회 제한은 **판매자 계정별** — 계정 간 병렬 안전 | 타계정 1.5초 연속 3건 성공 | 계정 병렬 3 |

- 검증(verify-live) 1회 ≈ 30~40초. **연타 시 게이트웨이 502** — 계정 간 1분 간격.
- 0건 계정 승인 = `confirm_zero`(마켓 화면에서 "정말 0건" 확인 후). 다른 결함은 이 플래그로 우회 불가.
