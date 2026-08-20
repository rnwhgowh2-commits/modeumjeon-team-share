# 계층형 계수 — 소싱처 > 브랜드 > 모음전 > URL (범위별 규칙) 설계

> **작성일**: 2026-07-05
> **상태**: 설계 확정 (구현 전)
> **관계**: 자동화 실행 엔진(연속 배수 큐) 워크스트림의 계수(crawl_weight) 확장. 상위 = [design.md](2026-07-04-자동화-연속배수큐-실행엔진-design.md) §5.2 · CLAUDE.md 데이터 정합성 3원칙.

---

## 1. 목적 (한 줄)

크롤 계수(얼마나 자주 긁을지 ×N배)를 **URL 하나씩**이 아니라 **소싱처 > 브랜드 > 모음전 상품 > URL** 계층으로 걸 수 있게 한다. 상위에 걸면 그 아래 전체에 적용되고, 하위에 직접 걸면 그게 우선. "URL만 보면 뭔지 몰라 설정이 어렵다"를 해결.

## 2. 확정된 규칙 (사용자 결정)

- **4단계**: 소싱처 → 브랜드 → 모음전 상품 → URL (아래로 갈수록 세부).
- **가장 세부 우선(most-specific-wins)**: URL 규칙 > 모음전 규칙 > 브랜드 규칙 > 소싱처 규칙 > 기본값.
- **기본값 = ×1** (아무 데도 안 걸면 ×1).
- **공유 URL 예외**: 한 URL이 여러 모음전에 걸쳐 있고 그 모음전들의 계수가 다르며 URL 자체 규칙이 없으면 → **가장 높은 계수(가장 자주)** 채택(놓치는 것보다 안전). URL에 직접 걸면 그게 우선.
- 계수 범위 = 1~5.

## 3. 데이터 — 「계수 규칙」 단일 테이블

```
CrawlWeightRule
  id           INT PK
  scope_type   VARCHAR(8)   -- 'source' | 'brand' | 'model' | 'url'
  scope_key    VARCHAR(...) -- source: 소싱처키(site) / brand: 브랜드명 / model: model_code / url: 정규화 URL
  weight       INT          -- 1~5
  UNIQUE(scope_type, scope_key)
```

- **4단계 계수의 단일 저장소.** 규칙이 없으면 상속, 최종엔 기본 ×1.
- 브랜드는 별도 테이블이 없고 `Model.brand`(글자)지만, `scope_type='brand'` 규칙으로 자연스럽게 담긴다.
- **기존 `SourceProduct.crawl_weight`(P1) 는 URL 규칙으로 흡수·마이그레이션** → 계수 정본을 이 테이블로 일원화. (마이그레이션 시 `crawl_weight != 1` 인 URL만 `scope_type='url'` 규칙으로 이전. 이후 `crawl_weight` 컬럼은 미사용/제거 후보.)

## 4. 해석 로직 — `resolve_crawl_weight(session, source_product) -> int`

한 URL(SourceProduct)의 최종 계수를 구한다. 순서:

1. **URL 규칙**: `(scope_type='url', scope_key=normalize_url(sp.url))` 있으면 그 값.
2. **모음전 규칙**: 그 URL이 걸린 모음전들의 `model_code` (= `BundleSourceUrl.url` 정규화 매칭) → `(scope_type='model', scope_key=model_code)` 규칙들. 있으면 **여럿이면 최고값**.
3. **브랜드 규칙**: 그 모음전들의 `Model.brand` → `(scope_type='brand', scope_key=brand)` 규칙들. 있으면 **최고값**.
4. **소싱처 규칙**: `(scope_type='source', scope_key=sp.site)` 있으면 그 값.
5. 없으면 **기본 ×1**.

- **URL 정규화**: `normalize_url`(파이프라인 정본, tracking 제거)로 `SourceProduct.url` ↔ `BundleSourceUrl.url` 양쪽 정규화해 매칭(조용한 누락 방지 — [design.md](2026-07-04-자동화-연속배수큐-실행엔진-design.md) 정규화 규칙과 동일).
- 연결: `SourceProduct.url` → (정규화) → `BundleSourceUrl.model_code` → `Model.brand`. (deleted_at 활성만)
- 성능: 규칙 수는 적으므로(수십~수백) 규칙 dict 한 번 로드 + URL별 매핑 조회. 대량 시 캐시(후속).

## 5. 엔진 연결 (P2에 최소 변경)

- P2 `due_products`(연속 배수 큐 선정)가 지금은 `sp.crawl_weight`를 직접 읽는다 → **`resolve_crawl_weight(session, sp)` 호출로 교체.** 나머지 큐·무변동 완화 로직은 동일(effective_interval = 기준 ÷ 해석된계수 × 완화).
- 즉 계층형은 "URL의 계수를 어떻게 구하나"만 바꾸고, 큐 동작은 그대로.

## 6. 설정 API + 화면 방향

- `set_crawl_weight_rule(session, scope_type, scope_key, weight | None)`: weight 1~5 클램프 upsert. **None/해제 = 규칙 삭제(상속으로 복귀).**
- 라우트: `GET`(브라우징 트리 + 각 노드 유효 계수·직접/상속 표시), `POST`(규칙 설정/해제).
- **화면 = 소싱처 > 브랜드 > 모음전 > URL 드릴다운.** 각 노드에 **유효 계수 + 「− ×N +」 스텝퍼 + "직접 설정 / 상속" 표시 + 「기본으로(해제)」**. 구체 시안 = 앞서 만든 「소싱처-URL 2단계」 10종을 계층 확장해 design-mockup 게이트로 확정(구현 플랜의 프론트 태스크).

## 7. 테스트 (TDD, 서버측)

- resolve 우선순위: URL > 모음전 > 브랜드 > 소싱처 > 기본1 (각 단계만 걸었을 때 정확)
- 공유 URL 최고값 tiebreak (URL 규칙 없고 모음전 2개 다른 계수 → 최고)
- 정규화 매칭(등록 URL에 tracking 붙어도 매칭)
- set/해제(규칙 삭제 시 상속 복귀), 1~5 클램프
- P2 통합: due_products가 계층 계수 반영(소싱처에 ×2 걸면 그 소싱처 URL 유효간격 절반)

## 8. 비목표 (YAGNI)

- 계수 규칙 이력/감사 로그 — 이번 범위 아님.
- 대량 캐시 최적화 — 필요 시 후속(지금 규모 단순 조회로 충분).
- 브랜드를 별도 엔티티 테이블로 승격 — 안 함(글자 scope_key로 충분).

## 9. 열린 항목

- 마이그레이션: 기존 `crawl_weight != 1` URL 수 확인 후 URL 규칙 이전 방식 확정.
- 드릴다운 화면의 구체 레이아웃 = design-mockup(10종 기반).
