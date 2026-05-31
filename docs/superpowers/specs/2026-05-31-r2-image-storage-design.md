# R2 이미지 저장 인프라 — 설계 문서

> 작성일: 2026-05-31
> 단계: 인프라 토대 (저장만, 가공은 미래 확장 자리만 마련)
> 관련 코드: `shared/`, `webapp/routes/inventory/data.py`, `webapp/routes/inventory/notifications.py`

---

## 1. 배경 / 문제

현재 사진 업로드 기능은 이미 존재하며, 파일을 **서버 자체 디스크 폴더**에 저장한다.

| 기능 | 현재 저장 위치 | DB 기록 값 |
|------|---------------|-----------|
| 상품 이미지 (`data.py:57`) | `data/product_images/<sku>.<ext>` | `Option.image_url` = `/inventory/data/product-image/<fname>` |
| 첨부 파일 (`notifications.py:67`) | `data/attachments/<random>.<ext>` | `/inventory/api/attachment/<fname>` |

이 폴더는 Fly Volume `modeumjeon_data`(1GB)에 마운트되어 있어(`fly.toml:38`) 재배포해도 보존된다. 그러나:

1. **용량 1GB를 설정 파일(`bundles.json` 등)과 공유** — 사진이 쌓이면 설정 저장까지 동반 실패 위험.
2. **볼륨이 머신 1대에 묶임** — 현재 `min_machines_running=1` 강제, 확장 불가(`fly.toml:18`).
3. **볼륨 증설은 GB당 과금** — 사진 수만 장이면 부담.

## 2. 목표 / 비목표

**목표 (이번 단계):**
- 사진 저장소를 서버 디스크 → Cloudflare R2 로 이전.
- 업로드 / 표시 / 삭제 자동화.
- **가공(리사이즈·워터마크 등)이 나중에 깨끗하게 끼워질 수 있는 토대(seam)** 마련.

**비목표 (이번엔 안 함):**
- 실제 이미지 가공 기능 (가공 "자리"만 비워둠).
- 사진별 메타데이터 대장(asset table) / 중복 제거 — 미래 단계.
- 접근 제어(비공개) — 이번엔 전부 공개(Public).

## 3. 결정 사항 (확정)

- **방식**: 단일 스토리지 어댑터 모듈("창고 직원"). DB 대장 방식은 미래로 보류.
- **보안**: 전부 공개 버킷(Public). 민감 첨부 분리는 미래 과제.
- **마이그레이션**: 신규 업로드부터 R2 → 기존 사진은 별도 스크립트로 안전 이사(원본 보존).

## 4. 아키텍처 — 스토리지 어댑터

신규 파일 `shared/storage.py`. 공개 계약(인터페이스):

```python
def put_object(data: bytes, key: str, content_type: str, *, processors=None) -> str:
    """processors(bytes->bytes 목록)를 순서대로 통과시킨 뒤 R2에 업로드, 공개 URL 반환."""

def put_upload(file_storage, key: str, *, processors=None) -> str:
    """Flask FileStorage 편의 래퍼 — put_object 호출."""

def delete_object(key: str) -> None:
    """R2에서 key 삭제."""

def public_url(key: str) -> str:
    """key의 공개 URL을 계산(네트워크 호출 없음)."""
```

**구현 메모:**
- `boto3` (S3 호환) 사용. R2 endpoint = `https://<account_id>.r2.cloudflarestorage.com`.
- 설정은 환경변수(금고)에서: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`.
- `requirements`에 `boto3` 추가.

**가공 seam (★ 토대의 핵심):**
`put_object` 내부 동작 순서 = `데이터 → processors 순차 적용 → R2 업로드 → 공개 URL 반환`.
지금 `processors` 기본값은 빈 목록(그냥 통과). 미래에 `resize_to(1000)`, `add_watermark(...)` 같은 `bytes->bytes` 함수를 목록에 추가하면 끝. 호출부 코드는 불변.

**key 네이밍 규칙:**
- 상품 이미지: `product/<sku>.<ext>`
- 첨부 파일: `attachment/<random>.<ext>`

## 5. 데이터 흐름

**업로드 (변경):**
```
지금:  브라우저 → Flask → 서버디스크 저장 → DB에 '/inventory/...' 경로
변경:  브라우저 → Flask → storage.put_upload(...) → R2 업로드 → DB에 R2 공개 URL
```
변경 지점: `data.py:57`, `notifications.py:67` 의 `file.save(...)` → `storage.put_upload(...)` 교체. DB에 저장하는 URL을 R2 공개 URL로.

**표시:** `<img src="https://...r2.dev/product/<sku>.jpg">` — 브라우저가 R2에서 직접 로드(앱 서버 미경유, egress 무료).

**삭제:** 사진 삭제 시 `storage.delete_object(key)` 호출 → R2에서 실제 삭제.

## 6. 기존 사진 마이그레이션 (2단계, 되돌림 가능)

- **1단계 (즉시):** 신규 업로드만 R2. 기존 사진/DB 주소는 그대로 → 옛 주소가 서버 디스크를 가리켜 정상 표시. 무중단·무손상.
- **2단계 (확인 후):** 1회성 스크립트 — `data/product_images/`·`data/attachments/` 로컬 파일을 R2로 복사, DB의 옛 URL을 R2 URL로 갱신. **원본 파일 미삭제(보존)**. 며칠 검증 후 볼륨 정리.
- 기존 서빙 라우트(`/inventory/data/product-image/<fname>`, `/inventory/api/attachment/<fname>`)는 폴백으로 유지.

## 7. 수동 세팅 (사용자가 클라우드플레어에서 1회)

1. 클라우드플레어 가입(무료)
2. R2 버킷 생성 (예: `modeumjeon-images`) — 카드 등록 1회 필요(10GB 무료)
3. 버킷 Public 활성화 → 공개 주소(`https://pub-xxxx.r2.dev`) 확보
4. R2 API 토큰(읽기·쓰기) 발급 → Access Key ID / Secret Access Key 확보
5. 값 5개를 Fly secrets + 로컬 `.env`에 주입 (코드에 직접 박지 않음)

## 8. 비용

R2 무료 한도: 저장 10GB + 월 읽기 1천만 / 쓰기 100만 + egress 영구 무료.
사진 200KB 기준 10GB ≈ 5만 장 무료. 초과 시 1GB월 ≈ 20원.

## 9. 검증

- 로컬: 테스트 이미지 업로드 → 클라우드플레어 대시보드에서 R2 객체 확인 → `<img>` 로드 확인.
- 삭제 시 R2 객체 실제 삭제 확인.
- 마무리: `/live-browser-verify` → `/ui-verify` 전수 검증.

## 10. 향후 확장 (이 토대 위에 얹힐 것)

- 가공 부품: 리사이즈/썸네일, 워터마크·로고, 배경 제거, 상세페이지 합성 (processors 목록에 추가).
- 비공개 버킷 + 서명 URL (민감 첨부 분리).
- 사진별 메타 대장(asset table) + 중복 제거.
