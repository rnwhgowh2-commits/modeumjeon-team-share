# 소싱처 컬럼 = (소싱처 × URL) 단위 재정의 — 설계

> **상위 의존**: [[project_url_store_fragmentation]] · [[project_complete_b_cell_vs_fx_consistency]] · 크롤링-가이드.md
> **단일 진실 원천**: 본 문서 (소싱처 컬럼 표시 규칙 한정)

**작성일**: 2026-06-23
**상태**: 설계 승인 (사용자 "ㄱㄱ")

---

## 1. 목표 (한 문장)

매트릭스·매트릭스보기·크롤로그의 "소싱처 컬럼"을 **등록된 전체 소싱처 고정 목록**에서 → **이 모음전에 URL이 등록된 (소싱처 × URL) 조합**으로 재정의한다.

## 2. 해결하는 문제

1. **URL 없는 소싱처가 빈 컬럼으로 노출** — 롯데아이몰처럼 이 모음전에 URL을 안 건 소싱처도 컬럼이 생겨 전 셀이 '미크롤/마이크롤'로 떠 시각적 잡음. → **컬럼 자체를 숨긴다.**
2. **한 소싱처 다중 URL이 1개로 합쳐짐** — 롯데온에 '모음전 URL'+'단품 URL' 둘을 걸면 지금은 `_pickBestSrc`가 최저 매입가 1개만 골라 한 컬럼에 표시(완전한 B). 사용자는 **둘을 별개 소싱처처럼** 따로 보고 비교하고 싶다. → **URL마다 독립 컬럼**으로 분리.

## 3. 핵심 개념: "컬럼 단위" 변경

| 구분 | AS-IS | TO-BE |
|---|---|---|
| 컬럼 정의 | `SourceRegistry` 행 1개 = 컬럼 1개 (전체 7개 고정) | 이 모음전에 **URL이 등록된 (source_id × bundle_source_url_id)** 조합 1개 = 컬럼 1개 |
| URL 없는 소싱처 | 빈 컬럼(전 셀 미크롤) | **컬럼 없음** |
| 소싱처 1 URL | 컬럼 1개 `롯데온` | 컬럼 1개 `롯데온` (동일) |
| 소싱처 2+ URL | 컬럼 1개(최저가 합침) | 컬럼 N개 `롯데온(1) 모음전` `롯데온(2) 단품` |

- 분리된 각 컬럼은 **독립 소싱처처럼** 동작: 자기 `product_url`·`crawled_price`·`crawled_stock`·`last_status`·`source_product_id`로 fx(`compute_breakdown`)를 **독립 계산**.
- 데이터 근거(조사 완료): 다중 URL은 이미 `option['sources']`에 **같은 source_id·다른 product_url로 별개 객체**로 존재. URL 없는 소싱처는 `option['sources']`에 **아예 부재**(빈 값 아님). 따라서 "컬럼 목록"만 (소싱처×URL)로 파생하면 두 기능이 동시에 해결된다.

## 4. 컬럼 라벨 규칙

- 한 소싱처에 URL이 **1개**: `롯데온` (접미사 없음, 현행 유지)
- 한 소싱처에 URL이 **2개 이상**: `소싱처명(순번) URL라벨`
  - 순번 = 그 소싱처 내 URL을 `sort_order`(없으면 bsu.id) 오름차순으로 1,2,3…
  - URL라벨 = `BundleSourceUrl.label`(있으면) 아니면 `url_type`(단품/색상모음전/모델모음전)
  - 예: `롯데온(1) 모음전`, `롯데온(2) 단품`
- 분리 컬럼은 같은 소싱처끼리 **나란히 인접**(순번 순).

## 5. 변경 범위 (3영역)

### A. 백엔드 — `option-matrix` API (`webapp/routes/api_pricing.py` `_option_matrix_data`)
- 각 소싱처 항목(dict)에 **`bundle_source_url_id`** 추가 노출 (BundleSourceUrl.id). 신규 경로(BundleSourceUrl/OptionSourceUrlLink) append 지점(~586).
- 레거시 경로(OptionSourceUrl) 항목은 bsu_id가 없을 수 있음 → `None`. 프론트는 bsu_id 없으면 `product_url`을 분리 키로 폴백.
- `sources`(컬럼 목록) 자체는 **백엔드에서 트리밍하지 않음** — 프론트에서 파생(다른 소비자 영향 최소화). 단, 컬럼 파생에 필요한 `sort_order`(소싱처 정렬)는 이미 있음.
- **불변**: 가격/재고/매칭 로직·완전한 B의 fx 계산식 자체는 건드리지 않음. id 1개 노출만.

### B. 프론트 — 매트릭스 + 매트릭스보기 (`webapp/templates/bundles/_matrix_v3.html`)
- **컬럼 파생 헬퍼** 신설 `deriveSourceColumns(DATA)`:
  - 입력: `DATA.options[].sources[]`.
  - (source_id, colKey) 조합 수집. `colKey = bundle_source_url_id ?? product_url`.
  - 각 source_id 별 colKey 목록을 `sort_order`(소싱처) → 그 안에서 URL `sort_order`/bsu.id 순 정렬.
  - 각 컬럼 객체: `{source_id, colKey, name(라벨), source_name, bsu_id, idx, total}` (total=그 소싱처 URL 수, 1이면 접미사 생략).
  - **URL 0개 소싱처는 자연히 제외**(어느 옵션 sources에도 없으므로) = Feature 1.
- **적용 지점 3곳** (전부 `DATA.sources` → `deriveSourceColumns(DATA)` 결과로 교체):
  1. 헤더 렌더 `renderSiteColsInThead` (~5588)
  2. 셀 행 렌더 `renderPriceMatrix`/`renderSiteCell` (~5735, 5761) — 셀 매칭을 `x.source_id===col.source_id && (x.bundle_source_url_id ?? x.product_url)===col.colKey` 로.
  3. '매트릭스 보기' 팝업 (~1254, 1274) — 동일 헬퍼 사용.
- **셀 픽 변경**: `_pickBestSrc(list)`의 list가 이제 (source, URL) 단위로 좁혀짐 → 사실상 1개. 완전한 B의 "소싱처 내 다중 URL 최저 합치기"는 분리로 대체되나, 같은 URL이 product/option 이중 등장하는 잔여 케이스 대비 `_pickBestSrc`는 유지(같은 colKey 내에서만 픽).
- 자동갱신(window.reloadMatrix/loadMatrix)·재고 3상태·기존 셀 상태(미크롤/완전한B 셀 강조) 표시는 **컬럼 키만 (source,URL)로 바뀔 뿐 그대로**.

### C. 크롤 로그 위젯 (`webapp/static/crawl_log.js` + enqueue 경로)
- 현재: 소싱처 카드를 `SOURCE_ORDER`(source_key 하드코딩)로 그룹.
- 변경: 카드 그룹 키를 `(source_key, URL)` 로 → `롯데온(1) 모음전` / `롯데온(2) 단품` 카드.
- enqueue 페이로드(`ext_bridge`/`toss.js`의 enqueueCrawl)에 **URL별 라벨·순번** 동봉 → 로그가 URL 단위로 카드 분리·라벨링.
- URL 없는 소싱처는 크롤 자체가 없어 카드 미생성(이미 충족) = Feature 1 로그분.
- 로그 라인(item-done)은 이미 URL 단위 → 카드 집계 키만 URL로 바꾸면 됨.

## 6. 영향·리스크 점검 (스펙 게이트)

1. **완전한 B / 업로드·최저가 선정 경로**: 완전한 B는 "매트릭스 셀에 어떤 URL 가격을 보일지"의 표시 로직. 분리로 표시는 둘 다 보이게 바뀜. **업로드/대표가 선정이 매트릭스 셀 픽에 의존하는지** 구현 1단계에서 grep 확인 — 의존 시 별도 처리, 비의존(별도 경로)이면 무영향.
2. **fx 독립 계산**: 각 컬럼 `source_product_id` 별 `compute_breakdown` → 이미 키별 계산이라 분리와 정합.
3. **레거시 OptionSourceUrl 항목**(bsu_id 없음): `product_url`을 colKey 폴백으로 → 분리/숨김 동일 동작. 단일 URL이면 접미사 없음.
4. **재고 3상태·자동갱신·매트릭스보기**: 컬럼 키 교체만, 셀 내부 로직 불변.
5. **금전 무결성**: 가격·혜택·매칭 계산식 **불변**. 본 작업은 "어떤 컬럼을 만들고 어떤 항목을 그 컬럼에 넣을지"(표시 라우팅)만 바꾼다.

## 7. 검증

- 단위/콘텐츠 테스트: `deriveSourceColumns` 순수 함수 테스트(0URL제외·1URL무접미사·2URL번호라벨·레거시폴백), 백엔드 bsu_id 노출 테스트.
- 라이브: 롯데온 2URL 모음전에서 `롯데온(1) 모음전`·`롯데온(2) 단품` 2컬럼이 매트릭스·매트릭스보기·로그에 뜨고 각 가격 독립, 롯데아이몰 컬럼 사라짐 — 실브라우저 시연(live-browser-verify).

## 8. 비범위 (YAGNI)

- 소싱처별 URL 등록 UI 변경 없음(이미 존재).
- 컬럼 수동 정렬/숨김 토글 없음(자동 파생만).
- 업로드 로직 재설계 없음(영향 점검만, 의존 시 최소 대응).
