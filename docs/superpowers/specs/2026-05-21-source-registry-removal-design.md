# 설계: 소싱처 사전 제거 — builtin 레지스트리로 통일

> 작성일: 2026-05-21
> 상태: 승인됨 (사용자 승인 2026-05-21)

## 배경·목적

소싱처 식별 데이터가 여러 곳에 중복돼 있다. 그중 `source_registry` 테이블
(= "소싱처 사전")은 `lemouton/sourcing/source_registry.py` 모듈의 builtin
`SOURCES` 5개를 DB로 한 번 더 복사한 5행짜리 중복이다. 사용자 결정: 소싱처
사전 개념을 전체 제거하고, 이미 존재하는 키 기반 builtin 레지스트리 하나로
통일한다.

## 끝 상태

- 소싱처 식별자 = `source_registry.py`의 문자열 키 (`lemouton` / `musinsa` /
  `ssf` / `lotteon` / `ss_lemouton`) 하나로 통일
- `source_registry` 테이블·`/source-registry` 페이지·사이드바 "소싱처 사전"
  메뉴 소멸
- 가격 매트릭스 화면·동작은 사용자 눈에 동일 (5개 소싱처 컬럼 그대로). 변하는
  것은 사이드바에서 "소싱처 사전" 메뉴가 사라지는 것뿐

## 현황 데이터 (2026-05-21 신규 DB 기준)

| 테이블 | 행 수 |
|--------|------|
| `source_registry` | 5 (= builtin 5개사) |
| `option_source_urls` | 38 |
| `option_price_config` | 0 |
| `sourcing_sources` (커스텀) | 0 |

## 스키마 변경 + 데이터 마이그레이션

`option_source_urls` 테이블:

- `source_id INTEGER` (FK→`source_registry.id`, ondelete CASCADE) →
  **`source_key VARCHAR(32) NOT NULL`** 로 교체
- `UniqueConstraint(canonical_sku, source_id)` →
  `UniqueConstraint(canonical_sku, source_key)`
- 인덱스 `ix_option_source_urls_v3_src` 를 `source_key` 기준으로 재생성

38행 이전 — `id → name → key` 매핑 (이름 기준 매핑으로 안전하게):

| id | name | → key |
|----|------|-------|
| 1 | 르무통 공홈 | `lemouton` |
| 2 | 스스 르무통 | `ss_lemouton` |
| 3 | 무신사 | `musinsa` |
| 4 | SSF | `ssf` |
| 5 | 롯데온 | `lotteon` |

매핑 근거: `scripts/migrate_pricing_v3.py` 의 `LEGACY_URL_MAP`.

마이그레이션 방식: 프로젝트에 Alembic이 아직 없으므로 기존
`scripts/migrate_*.py` 패턴을 따라 일회성 스크립트
`scripts/migrate_drop_source_registry.py` 를 작성한다. 스크립트는:

1. `source_registry` 의 실제 `id→name` 을 읽어 `name→key` 매핑 검증
   (예상 5개와 불일치 시 중단)
2. `option_source_urls` 에 `source_key` 컬럼 추가, 38행 채움
3. 행 수·매핑 정확성 검증 (이전 38행 == 이후 38행, 모든 source_key 유효)
4. `source_id` 컬럼·FK 제거, 제약·인덱스 재생성
5. `source_registry` 테이블 drop

Supabase(PostgreSQL)는 아직 미구축 — 그쪽 Alembic 마이그레이션은 인프라
셋업 시점에 별도 처리 (본 설계 범위 밖).

## 코드 변경 (call site repoint)

`SourceRegistry` 테이블 쿼리를 `source_registry.py` 의 `get_all_sources()`
모듈 호출로 교체하고, `OptionSourceUrl.source_id` 참조를 `source_key` 로 교체:

- `webapp/routes/api_pricing.py` — 매트릭스 빌드(`source_dict`), 소싱처
  생성/매핑 엔드포인트, CASCADE 로직
- `webapp/routes/bundles.py` (196-273) — `SourceRegistry` 조인 +
  `source_id == 3` 매직넘버 → `source_key == 'musinsa'`
- `webapp/routes/api.py` (48-141) — `src_by_name` 룩업을 키 기반으로
- `webapp/routes/home.py` (30), `webapp/routes/api_benefits.py` (377) —
  `OptionSourceUrl` 쿼리에서 `source_id` 참조 시 `source_key` 로
- `webapp/templates/bundles/_matrix_v3.html` — 매트릭스 JS 의 `source_id`
  → `source_key`, UI 문구 "소싱처 사전" → "소싱처" 로 정리
- `scripts/push_per_option_cheapest.py`, `scripts/run_full_pipeline.py` —
  `OptionSourceUrl` 쿼리 점검·수정
- `lemouton/sources/service.py` (360) — `OptionSourceUrl` 는 URL 기준
  조회라 `source_id` 무관, 점검만

## 제거 대상

- `webapp/routes/source_registry.py` — 라우트 파일 전체
- `webapp/templates/source_registry/list.html`
- 블루프린트 등록 — `webapp/routes/__init__.py` (23, 44)
- 사이드바 항목 — `webapp/routes/api_sidebar.py` (38) +
  `data/sidebar_layout.json`
- `SourceRegistry` 모델 클래스 — `lemouton/sourcing/models_pricing.py` (21)
- `scripts/migrate_pricing_v3.py` — `SourceRegistry` 의존부 obsolete 처리

## 기존 + 신규 적용 순서 (미러 룰)

1. 기존 시스템 먼저 코드 수정
   (`C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템`)
2. `python 프로그램/sync.py` 로 신규에 코드 반영
3. DB 마이그레이션은 각 시스템 DB 에 따로 실행 (sync.py 는 코드만 동기화,
   DB 스키마는 미동기화) — 기존 SQLite 1회 + 신규 SQLite 1회
4. 각 시스템 라이브 서버 재시작

## 검증

- 마이그레이션 전후 `option_source_urls` 38행 보존 + `source_key` 정확성
  (id↔key 1:1 대조)
- 가격 매트릭스 페이지: 5개 소싱처 컬럼·가격·재고 표시가 마이그레이션 전과
  동일 (브라우저 실검증)
- 모음전 번들 페이지·홈 화면 회귀 없음
- 사이드바에서 "소싱처 사전" 사라짐, 나머지 메뉴 정상
- 데이터 무결성: 가격·재고 값이 마이그레이션으로 어긋나지 않음 (무타협)

## 리스크·대응

- 가격 데이터 손상 = 금전적 손실. → 마이그레이션 스크립트가 전후 행 수·값을
  검증하고, 불일치 시 중단·롤백
- 기존 시스템은 운영 중 — DB 마이그레이션 전 DB 파일 백업 필수
- `source_id == 3` 같은 매직넘버 누락 시 무신사 매핑 깨짐 → call site
  전수 점검 (위 목록)
