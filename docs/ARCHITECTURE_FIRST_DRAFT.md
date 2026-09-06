# 대량등록 → samba-wave 아키텍처 1차 매핑

작업 위치: `C:/dev/_wt_sambawave` (worktree, branch `feature/samba-wave-integration`, base `main`)
> `main` 기준으로 만듦 — 지금 세션이 있던 `feature/design-unify` 는 main 보다 1,669 커밋 뒤처져 있고
> `webapp/routes/bulk/` 자체가 없어서(더 예전 지점에서 분기) 작업 기준이 될 수 없었음.

## 현재 상태 (탐색으로 확인)

- 대량등록은 사이드바 항목이 아니라 **최상위 모드 3개 중 하나** — `webapp/templates/partials/_modeswitch.html`
  이 모음전(`/`)·재고관리(`/inventory/`)·대량등록(`/bulk/`) 3개 링크를 가진 단일 원천.
- `/bulk` 블루프린트: `webapp/routes/bulk/`(8파일 1,194줄) + `webapp/templates/bulk/`(index+8 partial).
  9개 서브탭(수집·가공·전송·수기등록·상품관리·주문관리·CS관리·통계·설정) 중 주문관리·CS관리·통계는
  모음전 기존 화면 재사용(전용 코드 없음). 설계 정본: `docs/superpowers/specs/2026-07-17-신규상품등록-가공템플릿-design.md` §3-2.
- 판매처 계정 현재 방식: `shared/platforms/__init__.py` 의 `PLATFORM_CONFIG` 가 환경변수
  (예: `SMARTSTORE_MAIN_CLIENT_ID`)를 읽어 각 플랫폼 클라이언트(`shared/platforms/{coupang,eleven11,esm,lotteon,smartstore}/`)에
  넘김. OAuth 파생 토큰은 플랫폼별 파일 캐시(`token_store.py`, portalocker 락).
- samba-wave 판매처 계정: Postgres 단일 테이블 `samba_market_account`(tenant_id, market_type, api_key/secret,
  oauth_*, additional_fields JSON) + `backend/backend/domain/samba/account/credentials.py` 가 마켓별 표준 키로 변환.

## 매핑표

| 도메인 개념 | 폴더 경계 | 모듈/파일 | 변경 지점 |
|---|---|---|---|
| samba-wave 자체 | samba-wave 리포 (별도) | — | 코드 변경 없음. 자체 배포만 필요(`cloudbuild.yaml` 기존 보유) |
| 모드 전환 입구 | `webapp/templates/partials/_modeswitch.html` | `sb-modeswitch` | `href="/bulk/"` → samba-wave 배포 URL로 교체 (외부 링크) |
| 기존 /bulk 구현 | `webapp/routes/bulk/`, `webapp/templates/bulk/` | `bulk.bp` | 즉시 삭제 ❌ — 컷오버 확정 전까지 보존(안전망) |
| 판매처 계정 브리지 (신규) | `shared/market_accounts/` (신규 폴더) | `client.py` | `get_market_account(market_type: str) -> MarketAccountDTO` — samba-wave 계정 API 호출 + 로컬 캐시(기존 파일캐시 패턴 재사용) |
| 판매처 계정 기존 소스 | `shared/platforms/__init__.py` + 5개 플랫폼 클라이언트 | `PLATFORM_CONFIG` | `os.environ.get(...)` → `market_accounts_client.get_market_account(...)` 로 값 출처만 교체. 플랫폼 클라이언트(`smartstore/client.py` 등) 시그니처는 불변 |
| samba-wave 쪽 노출 API | samba-wave `backend/backend/domain/samba/account/` | `service.py`, `api/` | 모음전이 부를 조회 엔드포인트 존재 여부 미확인 — 다음 조사 대상 (없으면 samba-wave 쪽에도 신규 엔드포인트 필요) |

## 미해결 (STEP 2b 승인에서 확정)

1. 대량등록 기존 화면(1,194줄) 즉시 삭제 vs 컷오버 후 삭제 — 제안: 보존
2. samba-wave 실제 배포 URL — 아직 없음(현재 fork 의 "About" 링크는 upstream 데모로 추정) — 배포 후 확정
3. 판매처 계정 조회 API가 samba-wave 쪽에 이미 있는지 — 다음 조사 대상
